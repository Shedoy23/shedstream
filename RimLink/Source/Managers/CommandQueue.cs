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
        private readonly HashSet<string> _executedIds = new HashSet<string>();
        private const int MaxQueueSize = RimLinkConstants.MaxCommandQueueSize;

        public void Enqueue(Dictionary<string, object> cmd)
        {
            lock (_lock)
            {
                if (_queue.Count >= MaxQueueSize)
                {
                    Log.Warning($"[RimLink] Очередь команд переполнена ({MaxQueueSize}), команда отброшена");
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
                try { RimLinkMod.API?.AckCommand(ackId, ok, msg ?? ""); }
                catch (Exception ex) { Log.Warning($"[RimLink] AckCommand bg: {ex.Message}"); }
            });
        }

        private void Execute(Dictionary<string, object> cmd)
        {
            if (!cmd.TryGetValue("type", out var typeObj))
            {
                Log.Warning("[RimLink] Команда без поля 'type'");
                return;
            }

            string type = typeObj.ToString();
            string commandId = cmd.TryGetValue("id", out var idObj) ? idObj.ToString() : "";

            // Дедупликация: не выполнять команду с тем же ID дважды
            if (!string.IsNullOrEmpty(commandId))
            {
                lock (_lock)
                {
                    if (_executedIds.Contains(commandId))
                    {
                        Log.Warning($"[RimLink] Команда {commandId} ({type}) уже выполнялась — пропускаем");
                        AckCommandAsync(commandId, true, "duplicate");
                        return;
                    }
                    _executedIds.Add(commandId);
                    // Чистим старые ID чтобы Set не рос бесконечно
                    if (_executedIds.Count > 500)
                        _executedIds.Clear();
                }
            }

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
                AckCommandAsync(commandId, false, $"bad_payload: {e.Message}");
                return;
            }

            if (command == null)
            {
                Log.Warning($"[RimLink] Неизвестный тип команды: {type}");
                AckCommandAsync(commandId, false, $"Unknown command: {type}");
                return;
            }

            try
            {
                // 2026-07-19: Execute теперь bool — false = no-op (эффекта не
                // было) → success=false → бэкенд вернёт зрителю очки.
                bool ok = command.Execute();
                if (!ok)
                    Log.Warning($"[RimLink] Команда {type} без эффекта — шлём success=false (рефанд)");
                AckCommandAsync(commandId, ok, ok ? "" : "no_effect");
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] Команда {type} завершилась ошибкой: {e.Message}");
                AckCommandAsync(commandId, false, e.Message);
            }
        }
    }
}
