using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading.Tasks;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Sprint 4.5 — runtime state для active powers с длительностью (rage,
    /// retribution_toggle). Singleton, ConcurrentDictionary т.к. читается из
    /// Harmony patch'а во время Mission.RegisterBlow и пишется из main-thread
    /// dispatcher (ActivatePowerHandler).
    ///
    /// Expiry source: Mission.Current.CurrentTime — паузо-чувствительный
    /// (стопится во время Esc-menu), что критично — buff не должен утекать
    /// во время паузы.
    ///
    /// Cleanup: PowersMissionBehavior.OnMissionTick дёргает RemoveExpired()
    /// каждые ~2 сек. Tolerance ±2 сек acceptable для 30-60 сек buff'ов.
    ///
    /// Структура: username (lowercase) → { powerKey → BuffEntry }.
    /// Один зритель может одновременно держать rage + retribution.
    /// </summary>
    public static class ActiveBuffState
    {
        public class BuffEntry
        {
            public string PowerKey;   // "rage" / "retribution_toggle"
            public float ExpiresAt;   // mission.CurrentTime в момент expiry
            public double Value;      // damage multi (1.5) или reflect % (50)

            // 2026-05-29 Stage 1 (BLT-RC22 pattern) — persistent particle handle.
            // Lifecycle: created on Activate (via PowerVisualFx.AttachBuffPfx),
            // Stop()'d on RemoveExpired или explicit clear. Если null — no
            // persistent visual (e.g. instant powers heal_burst).
            //
            // Изменён struct → class чтобы хранить mutable reference type.
            // ConcurrentDictionary всё ещё работает (reference assignments
            // atomic), но nested mutation pattern теперь cleaner.
            public BannerlordLink.Util.AgentPfx Pfx;
        }

        // username → powerKey → entry
        private static readonly ConcurrentDictionary<string,
            ConcurrentDictionary<string, BuffEntry>> _buffs =
            new ConcurrentDictionary<string, ConcurrentDictionary<string, BuffEntry>>(
                StringComparer.OrdinalIgnoreCase);

        public static void Activate(string username, string powerKey, float duration, double value)
        {
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(powerKey)) return;
            if (Mission.Current == null) return;

            float now = Mission.Current.CurrentTime;
            var entry = new BuffEntry
            {
                PowerKey = powerKey,
                ExpiresAt = now + duration,
                Value = value,
            };
            var perUser = _buffs.GetOrAdd(username,
                _ => new ConcurrentDictionary<string, BuffEntry>(StringComparer.OrdinalIgnoreCase));
            perUser[powerKey] = entry;

            BannerlordLinkModule.Log(
                $"[BuffState] @{username} {powerKey} activated value={value:F2} duration={duration}s");

            // Sprint 4.6: fire-and-forget push на backend → frontend HUD timer.
            // Не ждём ACK — buff state локально уже set, push best-effort.
            PostBuffEventAsync("buff.activated", username, powerKey, duration, value);
        }

        /// <summary>Resolve active buff value, или null если нет / expired.</summary>
        public static double? GetValue(string username, string powerKey)
        {
            if (string.IsNullOrEmpty(username) || Mission.Current == null) return null;
            if (!_buffs.TryGetValue(username, out var perUser)) return null;
            if (!perUser.TryGetValue(powerKey, out var entry)) return null;
            if (Mission.Current.CurrentTime >= entry.ExpiresAt) return null;
            return entry.Value;
        }

        /// <summary>2026-05-29 Stage 1 — attach persistent particle handle к
        /// уже-активному buff entry. Caller (PowerVisualFx.PlayActivation)
        /// создаёт AgentPfx и передаёт сюда. RemoveExpired автоматически
        /// Stop()'нет на expire.
        ///
        /// No-op если buff entry not found (e.g. Activate ещё не вызван или
        /// уже истёк). Safe для defensive call.</summary>
        public static void AttachPfx(string username, string powerKey, BannerlordLink.Util.AgentPfx pfx)
        {
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(powerKey)) return;
            if (pfx == null) return;
            if (!_buffs.TryGetValue(username, out var perUser)) return;
            if (!perUser.TryGetValue(powerKey, out var entry)) return;

            // Замена предыдущего pfx (если был) — старый Stop() чтобы не leak.
            if (entry.Pfx != null && entry.Pfx != pfx)
            {
                try { entry.Pfx.Stop(); } catch { /* swallow */ }
            }
            entry.Pfx = pfx;
        }

        /// <summary>Drop expired buffs. Called from MissionLogic slow tick.
        /// Sprint 5.33 — returns list of expired (username, powerKey, value)
        /// чтобы caller мог react (e.g. reset speed for berserker_charge,
        /// stop DoT visual particle).</summary>
        public static List<(string username, string powerKey, double value)> RemoveExpired()
        {
            var expiredList = new List<(string, string, double)>();
            if (Mission.Current == null) return expiredList;
            float now = Mission.Current.CurrentTime;

            foreach (var userKvp in _buffs)
            {
                var expired = new List<string>();
                foreach (var bk in userKvp.Value)
                {
                    if (now >= bk.Value.ExpiresAt) expired.Add(bk.Key);
                }
                foreach (var k in expired)
                {
                    if (userKvp.Value.TryRemove(k, out var entry))
                    {
                        expiredList.Add((userKvp.Key, k, entry.Value));
                        BannerlordLinkModule.Log(
                            $"[BuffState] @{userKvp.Key} {k} expired (value={entry.Value:F2})");

                        // 2026-05-29 Stage 1 — Stop persistent particle на expire.
                        // AgentPfx.Stop() idempotent + auto-unregister из
                        // HeroPfxBehaviour. Без этого particle бы leaked до
                        // OnEndMission cleanup.
                        if (entry.Pfx != null)
                        {
                            try { entry.Pfx.Stop(); }
                            catch (Exception ex)
                            {
                                BannerlordLinkModule.Log(
                                    $"[BuffState] @{userKvp.Key} {k} pfx.Stop error: {ex.Message}");
                            }
                            entry.Pfx = null;
                        }

                        PostBuffEventAsync("buff.expired", userKvp.Key, k, 0f, 0.0);
                    }
                }
            }
            return expiredList;
        }

        /// <summary>Sprint 5.33 (BLT-parity FX) — DoT tick support. Returns
        /// snapshot всех active "poison_dot" buffs (keyed by "dot_target_{agentIdx}")
        /// для caller'а — он apply'ит per-tick damage в Mission tick.</summary>
        public static List<(int agentIndex, double damagePerSec, float remainingSec)> SnapshotDotTargets()
        {
            var list = new List<(int, double, float)>();
            if (Mission.Current == null) return list;
            float now = Mission.Current.CurrentTime;
            foreach (var userKvp in _buffs)
            {
                // DoT keyed by "dot_target_{idx}" — extract index из username.
                if (!userKvp.Key.StartsWith("dot_target_",
                    StringComparison.OrdinalIgnoreCase)) continue;
                string idxStr = userKvp.Key.Substring("dot_target_".Length);
                if (!int.TryParse(idxStr, out int agentIdx)) continue;

                foreach (var bk in userKvp.Value)
                {
                    if (bk.Key != "poison_dot") continue;
                    if (now >= bk.Value.ExpiresAt) continue;
                    float remaining = bk.Value.ExpiresAt - now;
                    list.Add((agentIdx, bk.Value.Value, remaining));
                }
            }
            return list;
        }

        /// <summary>Drop ALL buffs (mission ended).
        /// 2026-05-29 Stage 1 — также Stop()'ит все persistent particles
        /// (auto-defensive — HeroPfxBehaviour.OnEndMission делает то же,
        /// но мы дублируем чтобы не зависеть от behavior ordering).</summary>
        public static void Clear()
        {
            foreach (var userKvp in _buffs)
            {
                foreach (var bk in userKvp.Value)
                {
                    if (bk.Value.Pfx != null)
                    {
                        try { bk.Value.Pfx.Stop(); } catch { /* swallow */ }
                    }
                }
            }
            _buffs.Clear();
        }

        /// <summary>Sprint 5.30 #41 — snapshot active buffs как list of
        /// (username, powerKey) для periodic visual tick в PowersMissionBehavior.
        /// Не возвращает expired/value — только enumeration. ExpiresAt comparado
        /// с Mission.Current.CurrentTime (тот же scale что в Activate/GetValue).</summary>
        public static System.Collections.Generic.List<(string username, string powerKey)>
            SnapshotActive()
        {
            var list = new System.Collections.Generic.List<(string, string)>();
            if (Mission.Current == null) return list;
            float now = Mission.Current.CurrentTime;
            foreach (var userKvp in _buffs)
            {
                foreach (var buffKvp in userKvp.Value)
                {
                    if (now < buffKvp.Value.ExpiresAt)
                        list.Add((userKvp.Key, buffKvp.Key));
                }
            }
            return list;
        }

        // Fire-and-forget event push. Backend хранит in-memory dict для
        // /api/bannerlord/my-buffs (frontend HUD). Manifest extensions.events
        // декларирует buff.activated / buff.expired (Sprint 4.6).
        private static void PostBuffEventAsync(string eventType, string username,
            string powerKey, float duration, double value)
        {
            var backend = BannerlordLinkModule.Backend;
            if (backend == null) return;

            // 2026-05-29 P1.4 (Stage 0 Phase 1) — ранее использовался ручной
            // string.Format с :F1/:F3 для float/double. Newtonsoft JToken.Parse
            // на стороне BackendClient давился на "position 72" с "F" character —
            // 100% воспроизводимый bug. См. Расширение/docs/REFACTOR_PLAN_BLT_RC22.md
            // и логи crash 5/6 (бесконечные "bad dataJson, skipping" warnings).
            //
            // Fix: JsonConvert.SerializeObject anonymous object — Newtonsoft
            // serializer гарантирует корректный JSON (численные literals + escape
            // strings). Эквивалентный pattern используется в BackendClient.cs:137
            // для envelope wrapper.
            string json = Newtonsoft.Json.JsonConvert.SerializeObject(new
            {
                username = username,
                power_key = powerKey,
                duration_s = duration,
                value = value,
            });

            Task.Run(async () =>
            {
                try { await backend.PostEventAsync("bannerlord", eventType, json); }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[BuffState] push {eventType} failed: {ex.Message}");
                }
            });
        }
    }
}
