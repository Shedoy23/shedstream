using System;
using System.Linq;
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
                        // Backoff: 5s × min(fails, 6) → max 30s.
                        // Sprint 5.33 IMPROV-2 (friend feedback) — adaptive:
                        // в Mission (battle/siege/town walk) viewer ждёт action effects
                        // → recovery критичнее, сжимаем backoff в 2×. На world map
                        // viewer'ам можно подождать; original schedule.
                        int delay = Math.Min(consecutiveFails, 6) * 5;
                        bool inMission = false;
                        try { inMission = TaleWorlds.MountAndBlade.Mission.Current != null; } catch { }
                        if (inMission) delay = Math.Max(2, delay / 2);
                        _log($"poll failed (consecutive={consecutiveFails}, mission={inMission}), retry in {delay}s");
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

        // Sprint 5.31 #45e (audit MED-7) — idempotency ring против двойного
        // применения. Если backend dispatched-sweeper re-queue'ит action
        // (потому что ACK потерян), мод видит тот же action_id второй раз
        // и BLT-style apply: гольд debit'ится в игре дважды для viewer'а.
        // Ring: первые N запомненных action_id (или TTL 10 мин) — repeat'ы
        // skip'аются с ACK-success (чтобы backend пометил applied).
        private static readonly System.Collections.Concurrent.ConcurrentDictionary<string, DateTime>
            _processedActionIds = new System.Collections.Concurrent.ConcurrentDictionary<string, DateTime>();
        private const int PROCESSED_IDS_TTL_MIN = 10;
        private const int PROCESSED_IDS_MAX = 2000;   // memory cap

        private static bool MarkProcessedOnce(string actionId)
        {
            if (string.IsNullOrEmpty(actionId)) return true;
            var now = DateTime.UtcNow;
            // Lazy cleanup при превышении cap.
            if (_processedActionIds.Count >= PROCESSED_IDS_MAX)
            {
                var cutoff = now.AddMinutes(-PROCESSED_IDS_TTL_MIN);
                foreach (var kv in _processedActionIds)
                {
                    if (kv.Value < cutoff)
                        _processedActionIds.TryRemove(kv.Key, out _);
                }
            }
            // TryAdd — атомарный insert-if-absent. Returns true если успешно
            // вставили (= это первый раз); false если уже был.
            return _processedActionIds.TryAdd(actionId, now);
        }

        private async Task ProcessActionAsync(JObject action)
        {
            string actionId = action["action_id"]?.ToString() ?? "";
            string actionType = action["type"]?.ToString() ?? "";

            // Sprint 5.31 #45e (audit MED-7) — dedup re-delivered actions.
            if (!MarkProcessedOnce(actionId))
            {
                _log($"action[{actionId}] type={actionType} ALREADY PROCESSED — " +
                     "ACK success without re-apply (backend sweeper re-queue?)");
                try
                {
                    string dedupAckBody = Newtonsoft.Json.JsonConvert.SerializeObject(new
                    {
                        action_id = actionId,
                        success = true,
                        error = (string)null,
                        note = "mod-side dedup: already applied",
                    });
                    await _backend.PostJsonAsync($"/v1/module/{_moduleId}/ack", dedupAckBody);
                }
                catch (Exception ex)
                {
                    _log($"  ↳ dedup ACK failed: {ex.Message}");
                }
                return;
            }

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

            // Sprint 5.29 / BLT-parity #3: inject action_id в data чтобы
            // handlers могли push'ить action.failed event на refuse paths
            // (через Util.ActionFeedback.PostFailed). Underscore prefix —
            // соглашение «internal field, не из user payload'a».
            data["_action_id"] = actionId;

            // Sprint 5.30 #42: cache reward_boost для downstream gameplay
            // rewards (KillReward, Tournament). Backend пушит data.reward_boost
            // basado на JWT role + Helix sub detection. Если viewer ещё не
            // купил action — cache empty, default 1.0 в RewardBoostCache.Get.
            try
            {
                var targetField = data["target"]?.ToString() ?? data["initiated_by"]?.ToString();
                var boostField = data["reward_boost"];
                if (!string.IsNullOrEmpty(targetField) && boostField != null)
                {
                    double boost = (double)boostField;
                    BannerlordLink.Net.RewardBoostCache.Set(targetField, boost);
                }
            }
            catch (Exception ex)
            {
                // Sprint 5.31 #45c — раньше silent swallow. Если backend пушит
                // malformed reward_boost, sub'ы тихо теряли бонус.
                _log($"[reward_boost] parse failed action[{actionId}]: {ex.Message}");
            }

            _log($"action[{actionId}] type={actionType}");

            // Sprint 5.32 VERBOSE — детальный pre-dispatch log с params.
            // Catch-all для **всех** action handlers — видно ровно что пришло
            // от backend (initiated_by/target/price/specific keys).
            BannerlordLink.BannerlordLinkModule.LogVerbose(() =>
            {
                try
                {
                    string initBy = data["initiated_by"]?.ToString() ?? "?";
                    string target = data["target"]?.ToString() ?? "?";
                    string price = data["price"]?.ToString() ?? "0";
                    string perk = data["_perk_label"]?.ToString() ?? "viewer";
                    string clientId = (data["client_action_id"]?.ToString() ?? "").Substring(
                        0, Math.Min(12, (data["client_action_id"]?.ToString() ?? "").Length));
                    return $"[ACTION-IN V] {actionType} init=@{initBy} target=@{target} " +
                           $"price={price}⦷ perk={perk} client_id={clientId} " +
                           $"data_keys=[{string.Join(",", data.Properties().Select(p => p.Name))}]";
                }
                catch (Exception ex) { return $"[ACTION-IN V] {actionType} log-format crash: {ex.Message}"; }
            });

            bool success;
            string error;
            var swStart = System.Diagnostics.Stopwatch.StartNew();
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
                    BannerlordLink.BannerlordLinkModule.LogVerbose(() =>
                        $"[ACTION-OUT V] {actionType} → success={success} " +
                        $"error={error ?? "(none)"} elapsed={swStart.ElapsedMilliseconds}ms");
                }
            }
            catch (OperationCanceledException)
            {
                // Sprint 5.31 #45d (audit HIGH-4) — на shutdown _cts.Cancel()
                // бросает OCE из in-flight handler'а. Если поймать как regular
                // exception и ACK'нуть failed → backend оф'рефандит viewer'у
                // крустики за action, который не упал, а игра просто закрылась.
                // Re-throw чтобы LoopAsync exit'нул без ACK'а.
                _log("  ↳ handler cancelled (mod shutdown) — skipping ACK");
                throw;
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
