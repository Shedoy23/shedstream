using System;
using System.Threading;
using System.Threading.Tasks;
using BannerlordLink.Actions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Long-poll loop для action queue.
    ///
    /// Алгоритм:
    ///   1. GET /v1/module/bannerlord/actions?since=<cursor>
    ///      Backend long-poll'ит до 25 сек если queue пуст.
    ///   2. Response: {actions:[{id, action_id, type, data, created_at}], cursor}
    ///      Если actions[] не пуст — dispatch к ActionRegistry → handler.
    ///   3. POST /v1/module/bannerlord/ack {action_id, success, error?}
    ///      Backend помечает action как `acked` / `failed`.
    ///   4. Update cursor → next iteration.
    ///
    /// Threading: Task.Run loop, CancellationToken от Module.OnSubModuleUnloaded.
    /// Action.ExecuteAsync БЛОКИРУЕТ poller — multiple actions выполняются
    /// последовательно (защита от race в game thread). Reality check для Sprint 3+:
    /// long actions (summon hero) уйдут в MainThread.queue игры.
    ///
    /// Failure modes:
    ///   - 401 invalid token → log + stop loop (config issue, не self-heal)
    ///   - 502/504/timeout → sleep 5 сек, retry (backend down / restart)
    ///   - JSON parse error → log + skip (corrupt response)
    ///   - Handler exception → ACK with success=false + error msg
    /// </summary>
    public class ActionPoller
    {
        private readonly BackendClient _backend;
        private readonly string _moduleId;
        private readonly Action<string> _log;

        private CancellationTokenSource _cts;
        private Task _loopTask;
        private long _cursor = 0;

        public ActionPoller(BackendClient backend, string moduleId, Action<string> log)
        {
            _backend = backend;
            _moduleId = moduleId;
            _log = log;
        }

        public void Start()
        {
            if (_loopTask != null) return;
            _cts = new CancellationTokenSource();
            _loopTask = Task.Run(() => LoopAsync(_cts.Token));
            _log($"ActionPoller started (module={_moduleId})");
        }

        public void Stop()
        {
            try { _cts?.Cancel(); } catch { }
            _cts = null;
            _loopTask = null;
        }

        private async Task LoopAsync(CancellationToken ct)
        {
            int consecutiveFails = 0;
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    string path = $"/v1/module/{_moduleId}/actions?since={_cursor}";
                    string body = await _backend.GetAsync(path);
                    if (body == null)
                    {
                        consecutiveFails++;
                        // Backoff: 5s × min(fails, 6) → max 30s
                        int delay = Math.Min(consecutiveFails, 6) * 5;
                        _log($"poll failed (consecutive={consecutiveFails}), retry in {delay}s");
                        await Task.Delay(TimeSpan.FromSeconds(delay), ct);
                        continue;
                    }
                    consecutiveFails = 0;

                    JObject parsed;
                    try
                    {
                        parsed = JObject.Parse(body);
                    }
                    catch (Exception ex)
                    {
                        _log($"poll JSON parse error: {ex.Message}");
                        await Task.Delay(TimeSpan.FromSeconds(2), ct);
                        continue;
                    }

                    var actions = parsed["actions"] as JArray;
                    long cursor = (long?)parsed["cursor"] ?? _cursor;
                    if (actions != null && actions.Count > 0)
                    {
                        _log($"poll got {actions.Count} action(s), processing...");
                        foreach (JObject action in actions)
                        {
                            await ProcessActionAsync(action);
                        }
                    }
                    if (cursor > _cursor) _cursor = cursor;
                    // Backend long-poll уже включил wait inside (25s). Если actions
                    // были — сразу зовём next iteration. Если пусто — backend уже
                    // ждал, можем ре-запросить immediately.
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    _log($"poll loop error: {ex.GetType().Name}: {ex.Message}");
                    try { await Task.Delay(TimeSpan.FromSeconds(5), ct); }
                    catch (OperationCanceledException) { break; }
                }
            }
            _log("ActionPoller loop exited");
        }

        private async Task ProcessActionAsync(JObject action)
        {
            string actionId = action["action_id"]?.ToString() ?? "";
            string actionType = action["type"]?.ToString() ?? "";
            JToken dataRaw = action["data"];

            // data в backend хранится как text (JSON-сериализованный). Сервер
            // может вернуть либо string, либо уже распарсенный object.
            JObject data;
            if (dataRaw == null) data = new JObject();
            else if (dataRaw.Type == JTokenType.String)
            {
                try { data = JObject.Parse((string)dataRaw); }
                catch { data = new JObject(); }
            }
            else if (dataRaw is JObject dObj) data = dObj;
            else data = new JObject();

            _log($"action[{actionId}] type={actionType}");

            bool success;
            string error;
            try
            {
                var handler = ActionRegistry.Get(actionType);
                if (handler == null)
                {
                    success = false;
                    error = $"no handler for type={actionType}";
                    _log($"  ↳ {error}");
                }
                else
                {
                    var result = await handler.ExecuteAsync(data);
                    success = result.success;
                    error = result.error;
                }
            }
            catch (Exception ex)
            {
                success = false;
                error = $"{ex.GetType().Name}: {ex.Message}";
                _log($"  ↳ handler crashed: {error}");
            }

            // ACK назад
            string ackBody = JsonConvert.SerializeObject(new
            {
                action_id = actionId,
                success = success,
                error = error,
            });
            await _backend.PostJsonAsync($"/v1/module/{_moduleId}/ack", ackBody);
        }
    }
}
