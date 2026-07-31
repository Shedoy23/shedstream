using System;
using System.Collections.Generic;
using System.Threading;
using Verse;
using RimLink.Actions;

namespace RimLink.Managers
{
    /// <summary>
    /// Буфер команд от сервера. Команды добавляются из фонового потока,
    /// выполняются строго в главном потоке через FlushAll().
    /// </summary>
    public class CommandQueue
    {
        private readonly Queue<Dictionary<string, object>> _queue = new Queue<Dictionary<string, object>>();
        private readonly object _lock = new object();
        private readonly ManualResetEventSlim _processedEvent = new ManualResetEventSlim(true);
        private readonly Dictionary<string, CommandOutcome> _executedResults =
            new Dictionary<string, CommandOutcome>();
        private readonly Queue<string> _executedOrder = new Queue<string>();
        private const int MaxQueueSize = RimLinkConstants.MaxCommandQueueSize;
        private const int MaxExecutedIds = 1000;

        // Бэкенд возвращает деньги за доставленную команду, если за 10 минут
        // не получил ACK. Повторяем почти всё это окно, чтобы короткий обрыв
        // сети не превращал уже случившийся игровой эффект в бесплатный.
        private static readonly int[] AckRetryDelaysMs =
        {
            0, 500, 1000, 2000, 5000, 10000, 30000, 60000, 120000, 240000
        };

        private sealed class CommandOutcome
        {
            public readonly bool Success;
            public readonly string Message;

            public CommandOutcome(bool success, string message)
            {
                Success = success;
                Message = message ?? "";
            }
        }

        public void Enqueue(Dictionary<string, object> cmd)
        {
            lock (_lock)
            {
                if (_queue.Count >= MaxQueueSize)
                {
                    Log.Warning($"[RimLink] Очередь команд переполнена ({MaxQueueSize}), команда отброшена");
                    if (cmd != null && cmd.TryGetValue("id", out var idObj))
                    {
                        string overflowId = idObj?.ToString() ?? "";
                        if (!string.IsNullOrEmpty(overflowId))
                            AckCommandAsync(overflowId, false, "queue_full");
                    }
                    return;
                }
                _queue.Enqueue(cmd);
                _processedEvent.Reset();
            }
        }

        /// <summary>Выполняет все накопленные команды. Вызывать ТОЛЬКО из главного потока.</summary>
        public void FlushAll()
        {
            List<Dictionary<string, object>> batch;
            lock (_lock)
            {
                if (_queue.Count == 0) return;
                batch = new List<Dictionary<string, object>>(_queue.Count);
                while (_queue.Count > 0)
                    batch.Add(_queue.Dequeue());
            }

            foreach (var cmd in batch)
            {
                try
                {
                    Execute(cmd);
                }
                catch (Exception e)
                {
                    Log.Error($"[RimLink] Ошибка выполнения команды: {e.Message}");
                }
            }

            _processedEvent.Set();

            var count = batch.Count;
            System.Threading.Tasks.Task.Run(() =>
            {
                try { RimLinkMod.API?.OnCommandsProcessed(count); }
                catch (Exception ex) { Log.Warning($"[RimLink] OnCommandsProcessed: {ex.Message}"); }
            });
        }

        /// <summary>Количество команд в очереди.</summary>
        public int Count
        {
            get { lock (_lock) return _queue.Count; }
        }

        /// <summary>Очищает ресурсы.</summary>
        public void Dispose()
        {
            _processedEvent.Dispose();
        }

        /// <summary>
        /// Отправляет подтверждение выполнения команды в фоновом потоке.
        /// </summary>
        private static void AckCommandAsync(string commandId, bool success, string message = null)
        {
            var ackId = commandId;
            var msg = message;
            var ok = success;
            System.Threading.Tasks.Task.Run(() =>
            {
                string lastError = null;
                for (int attempt = 0; attempt < AckRetryDelaysMs.Length; attempt++)
                {
                    int delay = AckRetryDelaysMs[attempt];
                    if (delay > 0)
                        Thread.Sleep(delay);

                    try
                    {
                        var api = RimLinkMod.API;
                        if (api != null && api.AckCommand(ackId, ok, msg ?? "", out lastError))
                            return;
                        if (api == null)
                            lastError = "API is not initialized";
                    }
                    catch (Exception ex)
                    {
                        lastError = ex.Message;
                    }
                }

                Log.Warning($"[RimLink] ACK {ackId} не доставлен после "
                            + $"{AckRetryDelaysMs.Length} попыток: {lastError ?? "unknown error"}");
            });
        }

        private void RememberOutcome(string commandId, bool success, string message)
        {
            lock (_lock)
            {
                _executedResults[commandId] = new CommandOutcome(success, message);
                _executedOrder.Enqueue(commandId);
                while (_executedOrder.Count > MaxExecutedIds)
                {
                    string oldest = _executedOrder.Dequeue();
                    _executedResults.Remove(oldest);
                }
            }
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

            // Повтор должен получить ТОТ ЖЕ вердикт, что и первая попытка.
            // Старый HashSet отвечал success=true даже после no_effect/error,
            // из-за чего гонка двух ACK могла съесть положенный refund.
            lock (_lock)
            {
                if (_executedResults.TryGetValue(commandId, out var previous))
                {
                    Log.Warning($"[RimLink] Команда {commandId} уже выполнялась — повторяем прежний ACK");
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

            // 2026-07-19: конструкторы команд читают поля payload'а напрямую —
            // битый payload кидал ДО try ниже → ack не уходил вообще (команда
            // висла на бэке без вердикта). Теперь честный success=false.
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
                // 2026-07-19: Execute теперь bool — false = no-op (эффекта не
                // было) → success=false → бэкенд вернёт зрителю очки.
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
