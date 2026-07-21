using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Net;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Real handler для `power.activate` — triggered active ability для hero
    /// в текущей Mission.
    ///
    /// data: { target, power_key, [duration_s], [value] }
    /// Поддерживаемые power_keys:
    ///   heal_burst         — +50 HP к active agent (Sprint 4.3)
    ///   shield_break_burst — AoE: break shields всех врагов в радиусе (4.5)
    ///   rage               — timed outgoing damage multi, 30s default (4.5)
    ///   retribution_toggle — 2026-07-21: ПЕРЕИСПОЛЬЗОВАН под «Невидимость» ассасина
    ///                        (был timed reflect). Ключ сохранён, т.к. фронт заморожен
    ///                        на ревью Twitch. См. docs/SPEC_ASSASSIN_INVIS.md.
    ///
    /// Timed powers держат state в ActiveBuffState (читается из DamageHookPatch).
    /// PowersMissionBehavior.OnMissionTick чистит expired каждые 2 сек.
    ///
    /// Все active powers требуют hero spawned как agent в Mission.Current.
    /// Иначе skipped с log "no active agent".
    /// </summary>
    public class ActivatePowerHandler : IActionHandler
    {
        public string ActionType => "power.activate";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string powerKey = (data["power_key"]?.ToString() ?? "heal_burst").Trim().ToLowerInvariant();

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            // Optional overrides — backend может передать кастомные value/duration.
            // Иначе берём дефолты из PowerCache (class+level value) и hard-coded duration.
            float? durationOverride = (float?)data["duration_s"];
            double? valueOverride = (double?)data["value"];
            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);

            MainThreadDispatcher.Enqueue(() =>
                Activate(username, powerKey, durationOverride, valueOverride, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Activate(
            string username, string powerKey,
            float? durationOverride, double? valueOverride, string actionId)
        {
            try
            {
                if (Mission.Current == null)
                {
                    BannerlordLinkModule.Log(
                        $"[power.activate] REFUSE @{username}: no active Mission");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "no_active_mission");
                    return;
                }

                // 2026-06-05 — активки ЗАПРЕЩЕНЫ в живом бою арены/турнира: это
                // честный бой, способности зрителя его ломают. Mode==Battle
                // отличает сам бой от меню/зоны посещения арены (см. MissionContext).
                if (BannerlordLink.Util.MissionContext.IsArenaOrTournamentFight())
                {
                    BannerlordLinkModule.Log(
                        $"[power.activate] REFUSE @{username}: powers disabled in arena/tournament");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "arena_or_tournament");
                    return;
                }

                // Find agent in current mission. Match по extracted username
                // ([BLink] prefix stripped + lowercase).
                Agent agent = null;
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || !a.IsHuman || !a.IsActive()) continue;
                    var hero = (a.Character as TaleWorlds.CampaignSystem.CharacterObject)?.HeroObject;
                    if (hero?.Name == null) continue;
                    string extracted = BannerlordLink.Util.HeroNaming.ExtractUsername(hero.Name.ToString());
                    if (string.Equals(extracted, username, StringComparison.OrdinalIgnoreCase))
                    {
                        agent = a;
                        break;
                    }
                }

                if (agent == null)
                {
                    BannerlordLinkModule.Log(
                        $"[power.activate] REFUSE @{username}: hero не spawned как agent в Mission");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_spawned");
                    return;
                }

                switch (powerKey)
                {
                    case "heal_burst":
                        ApplyHealBurst(agent, username);
                        break;
                    case "shield_break_burst":
                        ApplyShieldBreakBurst(agent, username, durationOverride, valueOverride);
                        break;
                    case "rage":
                        ActivateRage(username, durationOverride, valueOverride, agent);
                        break;
                    case "retribution_toggle":
                        // 2026-07-21 — ключ переиспользован под «Невидимость» (фронт заморожен).
                        ActivateStealth(username, durationOverride, valueOverride, agent);
                        break;
                    // Sprint 5.33 (BLT-parity FX) — 3 new character effects.
                    case "poison_dot":
                        ApplyPoisonDot(agent, username, durationOverride, valueOverride);
                        break;
                    case "disarm_burst":
                        ApplyDisarmBurst(agent, username);
                        break;
                    case "berserker_charge":
                        ApplyBerserkerCharge(agent, username, durationOverride, valueOverride);
                        break;
                    // 2026-05-29 (BLT-parity combat powers) — active variants.
                    case "lifesteal_burst":
                        ActivateLifestealBurst(username, durationOverride, valueOverride, agent);
                        break;
                    case "ironskin_toggle":
                        ActivateIronskin(username, durationOverride, valueOverride, agent);
                        break;
                    case "explosive_arrows":
                        ActivateExplosiveArrows(username, durationOverride, valueOverride, agent);
                        break;
                    // 2026-06-17 (#15) — рассечение: мили splash-AoE как активка.
                    case "cleave":
                        ActivateCleave(username, durationOverride, valueOverride, agent);
                        break;
                    default:
                        BannerlordLinkModule.Log(
                            $"[power.activate] REFUSE @{username}: unknown power '{powerKey}'");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "unknown_power:" + powerKey);
                        break;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[power.activate] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        private static void ApplyHealBurst(Agent agent, string username)
        {
            const float BURST_AMOUNT = 50f;
            float before = agent.Health;
            float max = agent.HealthLimit;
            agent.Health = Math.Min(max, agent.Health + BURST_AMOUNT);
            BannerlordLinkModule.Log(
                $"[power.heal_burst] @{username}: HP {before:F0} → {agent.Health:F0} / {max:F0}");
            // Sprint 5.30 #41 — visible cue
            BannerlordLink.Util.PowerVisualFx.PlayActivation(agent, "heal_burst", username);
        }

        // shield_break_burst — 2026-07-20 РЕДИЗАЙН (решение владельца): было мгновенное
        // AoE «сломать щиты в радиусе R». Проблема: ломало только тем, у кого щит ЕСТЬ,
        // мгновенно и без связи с действием игрока → чаще всего «broke 0», зритель платил
        // и видел ноль («не работает»).
        // Стало — БАФФ на 45с: пока активен, ТВОЙ удар ломает щит тому, кого ты бьёшь
        // (та же схема, что cleave/explosive_arrows; исполняется в DamageHookPatch).
        // Эффект привязан к попаданию → видно глазами, и «пшика» не бывает.
        private static void ApplyShieldBreakBurst(Agent caster, string username,
            float? durationOverride, double? valueOverride)
        {
            float duration = durationOverride ?? 45f;
            // value больше не радиус — держим как «силу» для FX/логов (совместимо со
            // старым посевом: 6..12 просто станет числом в попапе).
            double v = valueOverride
                ?? PowerCache.GetPowerValue(username, "shield_break_burst")
                ?? 1.0;

            ActiveBuffState.Activate(username, "shield_break_burst", duration, v);
            BannerlordLinkModule.Log(
                $"[power.shield_break_burst] @{username}: удары ломают щиты {duration}s");
            BannerlordLink.Util.PowerVisualFx.PlayActivation(caster, "shield_break_burst", username);
        }

        // Search through weapon slots, find a shield, zero its hitpoints +
        // визуально дёрнуть native shield-break particle effect (4.6).
        // Particle через Mission.Scene.CreateBurstParticle — pure TaleWorlds API.
        // Sound пропускаем (4.6 scope: только particle).
        internal static bool TryBreakShield(Agent agent)
        {
            try
            {
                for (int i = 0; i < (int)EquipmentIndex.NumAllWeaponSlots; i++)
                {
                    var idx = (EquipmentIndex)i;
                    var weapon = agent.Equipment[idx];
                    if (weapon.IsEmpty) continue;

                    // 2026-06-01 — надёжная детекция щита по ItemType. Раньше шли
                    // только через CurrentUsageItem.WeaponClass — у несвыбранного
                    // щита usage мог быть null → power «не срабатывал».
                    bool isShield = weapon.Item != null
                        && weapon.Item.ItemType == ItemObject.ItemTypeEnum.Shield;
                    if (!isShield)
                    {
                        var usage = weapon.CurrentUsageItem;
                        isShield = usage != null
                            && (usage.WeaponClass == WeaponClass.LargeShield
                                || usage.WeaponClass == WeaponClass.SmallShield);
                    }
                    if (!isShield) continue;

                    // 2026-07-20 (#post-стрим) — ChangeWeaponHitPoints(0) ломает щит во
                    // ВРЕМЯ удара. В новом дизайне (shield_break = бафф, TryBreakShield
                    // зовётся из DamageHookPatch НА КАЖДОМ мили-попадании) контекст удара
                    // всегда есть → щит ломается штатно, DropItem не нужен.
                    // УБРАН форсированный DropItem: он спамил движковый ассерт
                    // "drop_item: weapon.is_valid_item()!" (12× за стрим) — выбить только
                    // что обнулённый/невалидный щит нельзя, а guard `Item != null` слабее
                    // нативного is_valid_item(). Обнуление HP безопасно и идемпотентно
                    // (повторный удар по уже сломанному щиту — no-op, без ассерта).
                    agent.ChangeWeaponHitPoints(idx, 0);
                    TryTriggerShieldBreakFx(agent);
                    return true;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[shield_break] {ex.Message}");
            }
            return false;
        }

        // Native game-asset particle + sound у off-hand bone.
        // Frame = agent global frame * skeleton bone-local frame. AgentVisuals
        // может быть null если agent disposed — wrap try/catch и no-op fallback.
        // Sprint 4.9: sound через Mission.MakeSound (TaleWorlds public API).
        private static void TryTriggerShieldBreakFx(Agent agent)
        {
            try
            {
                if (agent?.AgentVisuals == null || Mission.Current?.Scene == null) return;
                var skel = agent.AgentVisuals.GetSkeleton();
                if (skel == null) return;
                sbyte bone = agent.Monster?.OffHandItemBoneIndex ?? (sbyte)-1;
                if (bone < 0) return;

                MatrixFrame frame = agent.AgentVisuals.GetGlobalFrame()
                                  * skel.GetBoneEntitialFrame(bone);
                int psysId = ParticleSystemManager.GetRuntimeIdByName("psys_game_shield_break");
                if (psysId >= 0)
                {
                    Mission.Current.Scene.CreateBurstParticle(psysId, frame);
                }

                // Sound — отдельный try/catch чтобы particle всегда срабатывал
                // даже если sound API дропнет (API нестабилен между 1.3.x patch'ами).
                try
                {
                    int soundId = SoundEvent.GetEventIdFromString(
                        "event:/mission/combat/shield/broken");
                    if (soundId >= 0)
                    {
                        // Positional args (BLT pattern, OneShotEffect.cs:54):
                        // soundEventId, position, soundEventPlayInArea, isReverbAffected,
                        // relatedAgentIndex, parentObjectIndex
                        Mission.Current.MakeSound(soundId, frame.origin, false, true, agent.Index, -1);
                    }
                }
                catch (Exception sx)
                {
                    BannerlordLinkModule.Log($"[shield_break sound] {sx.Message}");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[shield_break fx] {ex.Message}");
            }
        }

        private static void ActivateRage(string username, float? durationOverride,
            double? valueOverride, Agent agent)
        {
            float duration = durationOverride ?? 45f;   // 2026-06-01 — унификация активок: 45с
            double multi = valueOverride
                ?? PowerCache.GetPowerValue(username, "rage")
                ?? 1.5;
            if (multi <= 1.0) multi = 1.5;  // защита от backend mis-config
            ActiveBuffState.Activate(username, "rage", duration, multi);
            BannerlordLinkModule.Log(
                $"[power.rage] @{username}: ×{multi:F2} dmg for {duration}s");
            // Sprint 5.30 #41 — popup + sound + burst particle
            BannerlordLink.Util.PowerVisualFx.PlayActivation(
                agent, "rage", username, $"{multi:F1}");
        }

        /// <summary>2026-07-21 — «Невидимость» ассасина (docs/SPEC_ASSASSIN_INVIS.md).
        /// Ключ силы остался `retribution_toggle`: ярлык под него во фронте УЖЕ есть,
        /// а фронт заморожен на ревью Twitch (новый ключ = кнопки у зрителя просто нет).
        /// Отражение урона по этому ключу снято (см. DamageHookPatch.ApplyReflect) —
        /// пассивный damage_reflect_pct не тронут.
        ///
        /// value = окно раскрытия после удара в секундах (падает с уровнем: прокачка =
        /// быстрее растворяешься обратно). Длительность — общие 45с.</summary>
        private static void ActivateStealth(string username, float? durationOverride,
            double? valueOverride, Agent agent)
        {
            float duration = durationOverride ?? 45f;   // 2026-06-01 — унификация активок: 45с
            double revealSec = valueOverride
                ?? PowerCache.GetPowerValue(username, "retribution_toggle")
                ?? 3.0;
            ActiveBuffState.Activate(username, "retribution_toggle", duration, revealSec);
            // Сбрасываем захваты СРАЗУ, не дожидаясь тика (0.5с): активку жмут, когда
            // уже прилетает — задержка ощущалась бы как «не сработало».
            int dropped = BannerlordLink.Behaviors.PowersMissionBehavior.ScrubEnemyTargets(agent);
            BannerlordLinkModule.Log(
                $"[power.stealth] @{username}: невидимость {duration}s, окно раскрытия " +
                $"{revealSec:F1}s, сброшено захватов сразу: {dropped}");
            // Sprint 5.30 #41
            BannerlordLink.Util.PowerVisualFx.PlayActivation(
                agent, "retribution_toggle", username, (int)revealSec);
        }

        // ── Sprint 5.33 (BLT-parity FX) — 3 new character effects ────────────

        /// <summary>Poison DoT — random enemy в радиусе получает damage per second.
        /// Stores active state в `ActiveBuffState` keyed by victim agent index.
        /// DamageHookPatch / Mission tick реально применит ticks. MVP — мы делаем
        /// ОДНОРАЗОВЫЙ damage с popup; full periodic tick — followup.
        ///
        /// Value = damage per tick. Duration = 10s. Tick interval = 1s (handled
        /// by PowersMissionBehavior.OnMissionTick через ActiveBuffState).</summary>
        private static void ApplyPoisonDot(Agent caster, string username,
            float? durationOverride, double? valueOverride)
        {
            float duration = durationOverride ?? 45f;   // 2026-06-01 — унификация активок: 45с
            double dps = valueOverride
                ?? PowerCache.GetPowerValue(username, "poison_dot")
                ?? 5.0;

            // 2026-07-20 РЕДИЗАЙН (решение владельца): было «повесить DoT на СЛУЧАЙНОГО
            // врага в 15м» — зритель не видел, кого отравил, а без врагов рядом активка
            // молча уходила в ноль. Стало — БАФФ на 45с: «выстрелил, попал → отравил».
            // Сам DoT вешает DamageHookPatch на ТОГО, в кого ты попал (мили или стрела);
            // тикает та же машинерия dot_target_{index} в PowersMissionBehavior.
            ActiveBuffState.Activate(username, "poison_dot", duration, dps);
            BannerlordLinkModule.Log(
                $"[power.poison_dot] @{username}: попадания отравляют "
                + $"({(int)dps} dmg/s) {duration}s");
            BannerlordLink.Util.PowerVisualFx.PlayActivation(caster, "poison_dot", username, (int)dps);
        }

        // 2026-06-10 — реально-роняемые типы предметов (защита от
        // "drop_item: weapon.is_valid_item()!" на баннерах / невалидных слотах).
        private static bool IsDroppableWeapon(ItemObject.ItemTypeEnum t) =>
            t == ItemObject.ItemTypeEnum.OneHandedWeapon
            || t == ItemObject.ItemTypeEnum.TwoHandedWeapon
            || t == ItemObject.ItemTypeEnum.Polearm
            || t == ItemObject.ItemTypeEnum.Bow
            || t == ItemObject.ItemTypeEnum.Crossbow
            || t == ItemObject.ItemTypeEnum.Thrown
            || t == ItemObject.ItemTypeEnum.Shield;

        /// <summary>Disarm burst — random enemy роняет wielded weapon.
        /// Engine API: Agent.DropItem(EquipmentIndex). Instant, no duration.</summary>
        private static void ApplyDisarmBurst(Agent caster, string username)
        {
            Agent target = FindRandomEnemyNearby(caster, 15f);
            if (target == null)
            {
                BannerlordLinkModule.Log(
                    $"[power.disarm_burst] @{username}: no enemy in 15m range");
                return;
            }
            try
            {
                // GetWieldedItemIndex API нет в нашей версии engine — loop через
                // 4 weapon slots, drop first non-empty melee/ranged item.
                EquipmentIndex dropSlot = EquipmentIndex.None;
                for (int i = 0; i < 4; i++)
                {
                    var slot = (EquipmentIndex)i;
                    var w = target.Equipment[slot];
                    // 2026-06-10 — роняем ТОЛЬКО реальное оружие. Раньше брали
                    // первый непустой слот → мог попасть баннер/невалидный предмет
                    // → движок: "SCRIPT ERROR drop_item: weapon.is_valid_item()!".
                    if (w.IsEmpty || w.Item == null) continue;
                    if (!IsDroppableWeapon(w.Item.ItemType)) continue;
                    dropSlot = slot;
                    break;
                }
                if (dropSlot == EquipmentIndex.None)
                {
                    BannerlordLinkModule.Log(
                        $"[power.disarm_burst] @{username} enemy idx={target.Index} " +
                        $"has no weapons to drop");
                    return;
                }
                target.DropItem(dropSlot);
                BannerlordLinkModule.Log(
                    $"[power.disarm_burst] @{username} → enemy idx={target.Index} " +
                    $"dropped weapon slot={dropSlot}");
                BannerlordLink.Util.PowerVisualFx.PlayActivation(target, "disarm_burst", username);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[power.disarm_burst] @{username} crash: {ex.Message}");
            }
        }

        /// <summary>Единая точка применения множителя скорости к агенту.
        /// AgentDrivenProperties — это то, из чего движок реально считает бег
        /// (в отличие от SetMaximumSpeedLimit, который лишь ставит потолок).
        /// UpdateAgentProperties() обязателен — без него движок не подхватит.
        /// mult = 1.0 → снять бафф.</summary>
        internal static void ApplySpeedMultiplier(Agent agent, float mult)
        {
            if (agent == null || !agent.IsActive()) return;
            try
            {
                // 1) Сброс к БАЗОВЫМ значениям модели. Обязателен: множитель применяем
                //    поверх базы, иначе при переприменении каждый тик он бы копился
                //    (×1.5 → ×2.25 → ×3.4…).
                agent.UpdateAgentProperties();
                var p = agent.AgentDrivenProperties;
                if (p == null) return;

                // 2) Множитель поверх базы.
                //    ⚠ UpdateAgentProperties() после этого звать НЕЛЬЗЯ — она пересчитает
                //    свойства из модели и ЗАТРЁТ правку. Именно это убивало прошлый фикс
                //    (2026-07-20): значение ставилось и тут же стиралось.
                if (agent.HasMount)
                {
                    // Конный: скорость определяет ЛОШАДЬ — MountSpeed (абсолютная величина).
                    // MaxSpeedMultiplier всадника на бег коня не влияет вообще, поэтому
                    // у кавалериста рывок не давал НИЧЕГО (репорт из боя).
                    p.MountSpeed *= mult;
                    p.MountDashAccelerationMultiplier *= mult;
                }
                else
                {
                    p.MaxSpeedMultiplier *= mult;
                    p.CombatMaxSpeedMultiplier *= mult;
                }
            }
            catch { }
        }

        /// <summary>Berserker charge — self movement speed bonus.
        /// Value = % bonus (e.g. 50 → 1.5× speed). Duration default 8s.
        /// Agent.SetMaximumSpeedLimit — engine API.</summary>
        private static void ApplyBerserkerCharge(Agent caster, string username,
            float? durationOverride, double? valueOverride)
        {
            float duration = durationOverride ?? 45f;   // 2026-06-01 — унификация активок: 45с
            double bonusPct = valueOverride
                ?? PowerCache.GetPowerValue(username, "berserker_charge")
                ?? 50.0;
            float mult = 1f + (float)(bonusPct / 100.0);

            // Register в buff state — PowersMissionBehavior tick применит / снимет.
            ActiveBuffState.Activate(username, "berserker_charge", duration, mult);

            // Apply immediate speed bonus.
            try
            {
                // 2026-07-20 FIX — раньше звали SetMaximumSpeedLimit(mult, true). Декомпайл
                // движка: это ПОТОЛОК скорости, а не ускорение — агент бежит со скоростью из
                // AgentDrivenProperties и до потолка обычно не достаёт, поэтому подъём потолка
                // не давал НИЧЕГО (репорт владельца «рывок не работает»). Реальный рычаг —
                // AgentDrivenProperties.MaxSpeedMultiplier / CombatMaxSpeedMultiplier.
                // Движок пересчитывает драйв-свойства → значение переприменяется каждый тик в
                // PowersMissionBehavior.ApplySpeedBuffTick (как сделано для ai_combat_pct).
                ApplySpeedMultiplier(caster, mult);
                BannerlordLinkModule.Log(
                    $"[power.berserker_charge] @{username} speed ×{mult:F2} for {duration}s");
                BannerlordLink.Util.PowerVisualFx.PlayActivation(
                    caster, "berserker_charge", username, $"+{(int)bonusPct}%");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[power.berserker_charge] speed limit warn: {ex.Message}");
            }
        }

        // 2026-05-29 (BLT-parity AbsorbHealthPower active) — вампиризм-всплеск.
        // Value = % урона → хил на время буффа; читается в DamageHook.ApplyLifesteal.
        private static void ActivateLifestealBurst(string username, float? durationOverride,
            double? valueOverride, Agent agent)
        {
            float duration = durationOverride ?? 45f;   // 2026-06-01 — унификация активок: 45с
            double pct = valueOverride
                ?? PowerCache.GetPowerValue(username, "lifesteal_burst")
                ?? 40.0;
            ActiveBuffState.Activate(username, "lifesteal_burst", duration, pct);
            BannerlordLinkModule.Log(
                $"[power.lifesteal_burst] @{username}: +{pct:F0}% lifesteal for {duration}s");
            BannerlordLink.Util.PowerVisualFx.PlayActivation(agent, "lifesteal_burst", username, (int)pct);
        }

        // 2026-05-29 (BLT-parity TakeDamagePower active) — железная кожа-тоггл.
        // Value = % снижения входящего урона; читается в DamageHook.ApplyDamageReduction.
        private static void ActivateIronskin(string username, float? durationOverride,
            double? valueOverride, Agent agent)
        {
            float duration = durationOverride ?? 45f;   // 2026-06-01 — унификация активок: 45с
            double pct = valueOverride
                ?? PowerCache.GetPowerValue(username, "ironskin_toggle")
                ?? 40.0;
            ActiveBuffState.Activate(username, "ironskin_toggle", duration, pct);
            BannerlordLinkModule.Log(
                $"[power.ironskin_toggle] @{username}: -{pct:F0}% incoming for {duration}s");
            BannerlordLink.Util.PowerVisualFx.PlayActivation(agent, "ironskin_toggle", username, (int)pct);
        }

        // 2026-05-29 (BLT-parity AoE) — взрывные стрелы: buff, во время которого
        // missile-хиты дают AoE по площади (см. DamageHook.ApplyExplosiveArrows).
        // Value = урон в центре взрыва. Self-buff (цель не нужна).
        private static void ActivateExplosiveArrows(string username, float? durationOverride,
            double? valueOverride, Agent agent)
        {
            float duration = durationOverride ?? 45f;   // 2026-06-01 — унификация активок: 45с
            double dmg = valueOverride
                ?? PowerCache.GetPowerValue(username, "explosive_arrows")
                ?? 40.0;
            ActiveBuffState.Activate(username, "explosive_arrows", duration, dmg);
            BannerlordLinkModule.Log(
                $"[power.explosive_arrows] @{username}: AoE arrows ({dmg:F0} center) for {duration}s");
            BannerlordLink.Util.PowerVisualFx.PlayActivation(agent, "explosive_arrows", username, (int)dmg);
        }

        // 2026-06-17 (#15) — рассечение как АКТИВКА (мили-зеркало explosive_arrows):
        // buff, во время которого МИЛИ-хиты дают splash-AoE по соседям (см.
        // DamageHook.ApplyMeleeCleave). Value = доля урона в splash. Self-buff.
        private static void ActivateCleave(string username, float? durationOverride,
            double? valueOverride, Agent agent)
        {
            float duration = durationOverride ?? 45f;   // унификация активок: 45с
            double frac = valueOverride
                ?? PowerCache.GetPowerValue(username, "cleave")
                ?? 0.5;
            ActiveBuffState.Activate(username, "cleave", duration, frac);
            BannerlordLinkModule.Log(
                $"[power.cleave] @{username}: splash {frac * 100:F0}% по соседям for {duration}s");
            BannerlordLink.Util.PowerVisualFx.PlayActivation(agent, "cleave", username, (int)(frac * 100));
        }

        /// <summary>Helper — find random active enemy human within radius.
        /// Used by poison_dot + disarm_burst target resolution.</summary>
        private static Agent FindRandomEnemyNearby(Agent caster, float radius)
        {
            try
            {
                var candidates = new System.Collections.Generic.List<Agent>();
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || a == caster || !a.IsActive() || !a.IsHuman) continue;
                    if (!a.IsEnemyOf(caster)) continue;
                    float dist = a.Position.Distance(caster.Position);
                    if (dist > radius) continue;
                    candidates.Add(a);
                }
                if (candidates.Count == 0) return null;
                return candidates[TaleWorlds.Core.MBRandom.RandomInt(candidates.Count)];
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[FindRandomEnemyNearby] warn: {ex.Message}");
                return null;
            }
        }
    }
}
