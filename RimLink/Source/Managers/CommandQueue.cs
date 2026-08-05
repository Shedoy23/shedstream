using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Verse;
using RimLink.Actions;

namespace RimLink.Managers
{
    /// <summary>
    /// Буфер команд от сервера. Команды добавляются из фонового потока,
    /// выполняются строго в главном потоке через FlushBudget().
    /// Результаты сохраняются на диск до отправки ACK, чтобы рестарт игры
    /// не превращал уже применённый эффект в бесплатный.
    /// </summary>
    public class CommandQueue : IDisposable
    {
        private readonly Queue<Dictionary<string, object>> _queue =
            new Queue<Dictionary<string, object>>();
        private readonly object _lock = new object();
        private readonly Dictionary<string, CommandOutcome> _executedResults =
            new Dictionary<string, CommandOutcome>(StringComparer.Ordinal);
        private readonly Queue<string> _executedOrder = new Queue<string>();
        private readonly HashSet<string> _acksInFlight =
            new HashSet<string>(StringComparer.Ordinal);
        private readonly string _journalPath;
        private volatile bool _disposed;

        private const int MaxQueueSize = RimLinkConstants.MaxCommandQueueSize;
        private const int MaxExecutedIds = 1000;
        private const string JournalFileName = "RimLink-command-outcomes-v1.txt";

        // WebClient синхронный, поэтому одновременно допускаем не больше четырёх
        // реальных HTTP-вызовов. Ожидание ретрая использует Task.Delay и не держит
        // поток ThreadPool заблокированным.
        private static readonly SemaphoreSlim AckConcurrency = new SemaphoreSlim(4, 4);

        // Бэкенд возвращает деньги за доставленную команду, если за 10 минут
        // не получил ACK. Повторяем почти всё это окно.
        private static readonly int[] AckRetryDelaysMs =
        {
            0, 500, 1000, 2000, 5000, 10000, 30000, 60000, 120000, 240000
        };

        private sealed class CommandOutcome
        {
            public readonly bool Success;
            public readonly string Message;
            public bool AckPending;

            public CommandOutcome(bool success, string message, bool ackPending = true)
            {
                Success = success;
                Message = message ?? "";
                AckPending = ackPending;
            }
        }

        public CommandQueue()
        {
            _journalPath = Path.Combine(GenFilePaths.ConfigFolderPath, JournalFileName);
            LoadOutcomeJournal();
            RetryPendingAcks();
        }

        public void Enqueue(Dictionary<string, object> cmd)
        {
            string overflowId = null;
            lock (_lock)
            {
                if (_queue.Count >= MaxQueueSize)
                {
                    Log.Warning($"[RimLink] Очередь команд переполнена ({MaxQueueSize}), команда отброшена");
                    if (cmd != null && cmd.TryGetValue("id", out var idObj))
                        overflowId = idObj?.ToString() ?? "";
                }
                else
                {
                    _queue.Enqueue(cmd);
                }
            }

            if (!string.IsNullOrEmpty(overflowId))
            {
                RememberOutcome(overflowId, false, "queue_full");
                AckCommandAsync(overflowId, false, "queue_full");
            }
        }

        /// <summary>
        /// Выполняет ограниченное число команд и не начинает следующую после
        /// исчерпания временного бюджета. Вызывать только из главного потока.
        /// </summary>
        public int FlushBudget(int maxCommands, int maxMilliseconds)
        {
            if (maxCommands <= 0) return 0;

            int processed = 0;
            var stopwatch = Stopwatch.StartNew();
            while (processed < maxCommands)
            {
                Dictionary<string, object> cmd;
                lock (_lock)
                {
                    if (_queue.Count == 0) break;
                    cmd = _queue.Dequeue();
                }

                try
                {
                    Execute(cmd);
                }
                catch (Exception e)
                {
                    Log.Error($"[RimLink] Ошибка выполнения команды: {e.Message}");
                }

                processed++;
                if (maxMilliseconds > 0 && stopwatch.ElapsedMilliseconds >= maxMilliseconds)
                    break;
            }

            if (processed > 0)
            {
                int count = processed;
                Task.Run(() =>
                {
                    try { RimLinkMod.API?.OnCommandsProcessed(count); }
                    catch (Exception ex) { Log.Warning($"[RimLink] OnCommandsProcessed: {ex.Message}"); }
                });
            }

            return processed;
        }

        public int Count
        {
            get { lock (_lock) return _queue.Count; }
        }

        /// <summary>Удаляет ещё не выполненные команды при смене сохранения.</summary>
        public void ClearPending()
        {
            lock (_lock) _queue.Clear();
        }

        public void Dispose()
        {
            _disposed = true;
            PersistOutcomeJournal();
        }

        private void RetryPendingAcks()
        {
            List<KeyValuePair<string, CommandOutcome>> pending;
            lock (_lock)
            {
                pending = _executedResults
                    .Where(kv => kv.Value.AckPending)
                    .ToList();
            }

            foreach (var kv in pending)
                AckCommandAsync(kv.Key, kv.Value.Success, kv.Value.Message);
        }

        private void AckCommandAsync(string commandId, bool success, string message = null)
        {
            if (string.IsNullOrEmpty(commandId)) return;

            lock (_lock)
            {
                if (!_acksInFlight.Add(commandId)) return;
            }

            var ackId = commandId;
            var msg = message ?? "";
            var ok = success;

            Task.Run(async () =>
            {
                string lastError = null;
                try
                {
                    for (int attempt = 0; attempt < AckRetryDelaysMs.Length; attempt++)
                    {
                        int delay = AckRetryDelaysMs[attempt];
                        if (delay > 0)
                            await Task.Delay(delay).ConfigureAwait(false);

                        await AckConcurrency.WaitAsync().ConfigureAwait(false);
                        try
                        {
                            var api = RimLinkMod.API;
                            if (api != null && api.AckCommand(ackId, ok, msg, out lastError))
                            {
                                MarkAckDelivered(ackId);
                                return;
                            }
                            if (api == null)
                                lastError = "API is not initialized";
                        }
                        catch (Exception ex)
                        {
                            lastError = ex.Message;
                        }
                        finally
                        {
                            AckConcurrency.Release();
                        }
                    }

                    Log.Warning($"[RimLink] ACK {ackId} не доставлен после "
                                + $"{AckRetryDelaysMs.Length} попыток: {lastError ?? "unknown error"}");
                }
                finally
                {
                    lock (_lock) _acksInFlight.Remove(ackId);
                }
            });
        }

        private void RememberOutcome(string commandId, bool success, string message)
        {
            lock (_lock)
            {
                if (!_executedResults.ContainsKey(commandId))
                    _executedOrder.Enqueue(commandId);
                _executedResults[commandId] = new CommandOutcome(success, message);
                TrimOutcomesLocked();
                PersistOutcomeJournalLocked();
            }
        }

        private void MarkAckDelivered(string commandId)
        {
            lock (_lock)
            {
                if (_executedResults.TryGetValue(commandId, out var outcome))
                {
                    outcome.AckPending = false;
                    PersistOutcomeJournalLocked();
                }
            }
        }

        private void TrimOutcomesLocked()
        {
            while (_executedOrder.Count > MaxExecutedIds)
            {
                string oldest = _executedOrder.Dequeue();
                // Не выбрасываем недоставленный результат: он важнее лимита и
                // должен пережить рестарт. ACK-доставленные записи можно удалить.
                if (_executedResults.TryGetValue(oldest, out var value) && value.AckPending)
                {
                    _executedOrder.Enqueue(oldest);
                    if (_executedOrder.All(id =>
                        _executedResults.TryGetValue(id, out var item) && item.AckPending))
                        break;
                    continue;
                }
                _executedResults.Remove(oldest);
            }
        }

        private void LoadOutcomeJournal()
        {
            try
            {
                if (!File.Exists(_journalPath)) return;

                foreach (string line in File.ReadAllLines(_journalPath))
                {
                    string[] parts = line.Split('|');
                    if (parts.Length != 4) continue;

                    string id = Decode(parts[0]);
                    if (string.IsNullOrEmpty(id)) continue;
                    bool success = parts[1] == "1";
                    bool pending = parts[2] == "1";
                    string message = Decode(parts[3]);

                    if (!_executedResults.ContainsKey(id))
                        _executedOrder.Enqueue(id);
                    _executedResults[id] = new CommandOutcome(success, message, pending);
                }

                lock (_lock) TrimOutcomesLocked();
                if (_executedResults.Count > 0)
                    Log.Message($"[RimLink] Загружен журнал команд: {_executedResults.Count}");
            }
            catch (Exception ex)
            {
                Log.Warning($"[RimLink] Не удалось прочитать журнал команд: {ex.Message}");
            }
        }

        private void PersistOutcomeJournal()
        {
            lock (_lock) PersistOutcomeJournalLocked();
        }

        private void PersistOutcomeJournalLocked()
        {
            if (_disposed && _executedResults.Count == 0) return;

            try
            {
                string directory = Path.GetDirectoryName(_journalPath);
                if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);

                var lines = new List<string>(_executedOrder.Count);
                foreach (string id in _executedOrder)
                {
                    if (!_executedResults.TryGetValue(id, out var outcome)) continue;
                    lines.Add(string.Join("|",
                        Encode(id),
                        outcome.Success ? "1" : "0",
                        outcome.AckPending ? "1" : "0",
                        Encode(outcome.Message)));
                }

                string tempPath = _journalPath + ".tmp";
                File.WriteAllLines(tempPath, lines.ToArray(), Encoding.UTF8);
                if (File.Exists(_journalPath))
                {
                    try { File.Replace(tempPath, _journalPath, null); }
                    catch
                    {
                        File.Delete(_journalPath);
                        File.Move(tempPath, _journalPath);
                    }
                }
                else
                {
                    File.Move(tempPath, _journalPath);
                }
            }
            catch (Exception ex)
            {
                Log.Warning($"[RimLink] Не удалось сохранить журнал команд: {ex.Message}");
            }
        }

        private static string Encode(string value)
        {
            return Convert.ToBase64String(Encoding.UTF8.GetBytes(value ?? ""));
        }

        private static string Decode(string value)
        {
            try { return Encoding.UTF8.GetString(Convert.FromBase64String(value ?? "")); }
            catch { return ""; }
        }

        private void Execute(Dictionary<string, object> cmd)
        {
            string commandId = cmd != null && cmd.TryGetValue("id", out var idObj)
                ? idObj?.ToString() ?? ""
                : "";

            if (string.IsNullOrEmpty(commandId))
            {
                Log.Warning("[RimLink] Команда без поля 'id' отклонена: её нельзя безопасно подтвердить");
                return;
            }

            lock (_lock)
            {
                if (_executedResults.TryGetValue(commandId, out var previous))
                {
                    Log.Warning($"[RimLink] Команда {commandId} уже выполнялась — повторяем прежний ACK");
                    if (previous.AckPending)
                        AckCommandAsync(commandId, previous.Success, previous.Message);
                    return;
                }
            }

            if (!cmd.TryGetValue("type", out var typeObj))
            {
                Log.Warning("[RimLink] Команда без поля 'type'");
                RememberOutcome(commandId, false, "missing_type");
                AckCommandAsync(commandId, false, "missing_type");
                return;
            }

            string type = typeObj.ToString();
            Log.Message($"[RimLink] Выполняем команду: {type}");

            ICommand command;
            try
            {
                command = CommandFactory.Create(type, cmd);
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] Команда {type}: битый payload: {e.Message}");
                string message = $"bad_payload: {e.Message}";
                RememberOutcome(commandId, false, message);
                AckCommandAsync(commandId, false, message);
                return;
            }

            if (command == null)
            {
                Log.Warning($"[RimLink] Неизвестный тип команды: {type}");
                string message = $"Unknown command: {type}";
                RememberOutcome(commandId, false, message);
                AckCommandAsync(commandId, false, message);
                return;
            }

            try
            {
                bool ok = command.Execute();
                if (!ok)
                    Log.Warning($"[RimLink] Команда {type} без эффекта — шлём success=false (рефанд)");
                string message = ok ? "" : "no_effect";
                RememberOutcome(commandId, ok, message);
                AckCommandAsync(commandId, ok, message);
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] Команда {type} завершилась ошибкой: {e.Message}");
                RememberOutcome(commandId, false, e.Message);
                AckCommandAsync(commandId, false, e.Message);
            }
        }
    }
}
