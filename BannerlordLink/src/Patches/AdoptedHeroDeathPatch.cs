using System;
using BannerlordLink.Util;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-05-29 Stage 3 (BLT-RC22 pattern) — permadeath prevention для adopted
    /// heroes. Two Harmony patches:
    ///
    ///   1. KillCharacterAction.ApplyInternal (Prefix) — block campaign-side
    ///      death actions для adopted heroes. Pattern из BLT HarmonyPatches.cs
    ///      :532-546 (BLTNoDeathAllowed).
    ///   2. Mission.OnAgentRemoved (Prefix) — convert AgentState.Killed →
    ///      Unconscious для adopted hero агентов. Pattern из BLT
    ///      BLTAdoptAHeroCommonMissionBehavior.cs:156-201 (OnAgentRemovedPrefix).
    ///
    /// Зачем нужно:
    ///   Раньше: viewer adopts hero → hero dies в bой → permanent loss. Viewer
    ///   теряет heroic identity (с heroState rebuild через ActivateHeir flow).
    ///   Engagement loss: viewer должен заново строить hero, equipment, skills,
    ///   reputation. Часто означает "I quit playing".
    ///
    ///   Сейчас: adopted heroes по умолчанию unkillable. В Mission получают
    ///   Unconscious instead of Killed (Battle medic logic применяется,
    ///   они "приходят в себя" после battle с reduced HP). В Campaign actions
    ///   (execution, labor death, etc.) — death просто блокируется.
    ///
    /// Исключения (death всё-таки applies):
    ///   - isForced=true → KillCharacterAction явно forced (admin commands)
    ///   - killer == MainHero AND actionDetail == Executed → streamer
    ///     намеренно казнил adopted hero (например в plot drama)
    ///   - Не-adopted heroes (vanilla NPCs) — vanilla behavior preserved
    ///
    /// Config (потенциально — future):
    ///   - AllowDeath flag (default false) — глобально разрешить death
    ///   - DeathChance float (default 0) — random roll allowing death
    ///   - MinimumAge int (default 65) — старые heroes могут умереть от
    ///     возрастной death event
    ///   На данный момент не configurable — death просто всегда блокирован
    ///   для adopted heroes (кроме explicit exceptions выше).
    ///
    /// Safety:
    ///   - Prefix patches возвращают bool true для CONTINUE original (allow death),
    ///     false для SKIP (block). Defensive: на любую exception → return true
    ///     (let vanilla run, log error).
    ///   - Не патчим non-adopted heroes — vanilla behavior preserved → other
    ///     mods (Death/Birth events, etc.) not affected.
    ///   - Не патчим mount death — adopted hero horses dont currently get
    ///     protection (отдельный feature, TODO Stage 3+).
    /// </summary>
    [HarmonyPatch(typeof(KillCharacterAction), "ApplyInternal")]
    internal static class KillCharacterAction_ApplyInternal_Patch
    {
        [HarmonyPrefix]
        public static bool Prefix(
            Hero victim,
            Hero killer,
            KillCharacterAction.KillCharacterActionDetail actionDetail,
            bool showNotification,
            bool isForced)
        {
            try
            {
                // Не-adopted heroes — vanilla behavior. БЕЗ изменений.
                if (!HeroNaming.IsAdopted(victim)) return true;

                // 2026-07-24 АУДИТ РАДИУСА ПОРАЖЕНИЯ — дыра в защите.
                // Раньше первой строкой стояло `if (isForced) return true;` — то есть
                // ЛЮБАЯ форсированная смерть проходила насквозь. А ванильный
                // KillCharacterAction.ApplyByRemove объявлен как
                //     ApplyByRemove(Hero victim, bool showNotification = false,
                //                   bool isForced = true)   ← forced ПО УМОЛЧАНИЮ
                // и именно его зовёт DestroyClanAction на каждом герое клана.
                // Итог 2026-07-24: роспуск королевства уничтожил кланы и убил ДВУХ
                // посторонних зрителей — защита не сработала вообще. Вчерашний фикс
                // закрыл ОДИН путь (LeaveKingdomHandler), но к DestroyClanAction ведут
                // и другие: клан вымер/обанкротился, королевство пало от ИИ, будущие фичи.
                //
                // Блокируем узко: detail=Lost («герой вычеркнут из мира» — именно им
                // ходит уничтожение клана). Герой остаётся жив и становится бесклановым —
                // это штатное состояние, оно у нас уже поддержано (hero.leave_clan).
                // Остальные forced-смерти (админские, Executed, сюжетные) — как раньше.
                if (isForced
                    && actionDetail == KillCharacterAction.KillCharacterActionDetail.Lost)
                {
                    BannerlordLinkModule.Log(
                        $"[DeathProtect] BLOCKED forced Lost для @{victim?.Name} " +
                        "(уничтожение клана/королевства не должно убивать зрителя)");
                    return false;
                }

                // Прочие forced kills — proceed (admin / debug / specific game logic).
                if (isForced) return true;

                // Streamer (MainHero) намеренно казнил adopted hero — allow.
                // Pattern из BLT BLTNoDeathAllowed (line 539):
                //   if (killer == Hero.MainHero && actionDetail == Executed) return true;
                if (killer == Hero.MainHero
                    && actionDetail == KillCharacterAction.KillCharacterActionDetail.Executed)
                {
                    BannerlordLinkModule.Log(
                        $"[DeathProtect] Player executed adopted hero {victim?.Name} — allowing");
                    return true;
                }

                // Default: block death для adopted hero.
                // Log один раз per hero per session чтобы не флудить.
                // Workaround для TextObject — convert к string ДО ?? оператора
                // (?? не работает с TextObject + string).
                string killerName = killer?.Name?.ToString();
                if (string.IsNullOrEmpty(killerName)) killerName = "none";
                BannerlordLinkModule.LogVerbose(() =>
                    $"[DeathProtect] BLOCKED KillCharacterAction для @{victim?.Name} " +
                    $"(detail={actionDetail}, killer={killerName})");
                return false;
            }
            catch (Exception ex)
            {
                // Defensive: на error → let vanilla proceed (don't break game).
                BannerlordLinkModule.Log(
                    $"[DeathProtect] KillCharacterAction patch error: {ex.Message} — allowing default");
                return true;
            }
        }
    }

    /// <summary>
    /// 2026-05-29 Stage 3 — battle-side conversion Killed → Unconscious для
    /// adopted hero agents. Pattern из BLT BLTAdoptAHeroCommonMissionBehavior
    /// .cs:156-201 (OnAgentRemovedPrefix).
    ///
    /// Why separate from KillCharacterAction patch:
    ///   - KillCharacterAction = campaign-side death actions (execution,
    ///     labor, succession, etc.)
    ///   - Mission.OnAgentRemoved = battle-side agent removal event
    ///   Engine использует ОБА pathways. Иногда agent dies в bой → Mission
    ///   fires OnAgentRemoved with state=Killed → Mission system itself
    ///   triggers KillCharacterAction (через various behaviors). Если мы
    ///   convert state ДО KillCharacterAction fires — никакая death action
    ///   не triggers вообще.
    ///
    /// Effect:
    ///   - Adopted hero в bой получает Killed state from blow
    ///   - Our patch converts state to Unconscious BEFORE engine notifies
    ///     other systems (campaign behaviors, achievement trackers, etc.)
    ///   - Engine treats them as "knocked out" → они появятся живыми после
    ///     battle (с reduced HP / wounded state)
    ///
    /// Side effects:
    ///   - Adopted hero никогда не triggers "hero died" event chain в этом
    ///     pathway. KillCharacterAction patch above ловит остальные.
    ///   - Их retinue may still be killed (separate agents — мы патчим
    ///     только agents с adopted hero character).
    /// </summary>
    [HarmonyPatch(typeof(Mission), "OnAgentRemoved")]
    internal static class Mission_OnAgentRemoved_Patch
    {
        [HarmonyPrefix]
        public static void Prefix(
            Agent affectedAgent,
            Agent affectorAgent,
            ref AgentState agentState,
            KillingBlow killingBlow)
        {
            try
            {
                // Только Killed state → consider conversion. Unconscious /
                // Routed / etc. — pass through.
                if (agentState != AgentState.Killed) return;
                if (affectedAgent == null) return;

                // 2026-05-29 Stage 6 (BLT-RC22 pattern) — branch 1: adopted hero mount.
                // Если умирающий agent — это лошадь зарегистрированная в
                // AdoptedMountTrackerBehavior → защищаем. Saddle/harness
                // equipment не теряется → viewer не возвращается к extension'у
                // c "I lost my horse, refund please".
                //
                // Pattern из BLT BLTAdoptAHeroCommonMissionBehavior:186-189.
                if (affectedAgent.IsMount)
                {
                    var tracker = BannerlordLink.Behaviors.AdoptedMountTrackerBehavior.Current;
                    if (tracker != null && tracker.IsTracked(affectedAgent))
                    {
                        agentState = AgentState.Unconscious;
                        try { affectedAgent.State = AgentState.Unconscious; }
                        catch { /* swallow — ref param выше всё-равно сработал */ }

                        BannerlordLinkModule.LogVerbose(() =>
                            $"[DeathProtect] Converted adopted hero's mount " +
                            $"(idx={affectedAgent.Index}) Killed → Unconscious");
                    }
                    return;  // Mount handled — не fall-through к human check.
                }

                // Branch 2: human agent → check if adopted hero.
                if (!affectedAgent.IsHuman) return;

                // Извлечь Hero from agent character.
                var hero = (affectedAgent.Character as CharacterObject)?.HeroObject;
                if (hero == null) return;

                // Только adopted heroes — vanilla mobs/lords vanilla behavior.
                if (!HeroNaming.IsAdopted(hero)) return;

                // CONVERT: Killed → Unconscious.
                // affectedAgent.State также update'нем чтобы engine downstream
                // logic тоже видел Unconscious (BLT pattern line 174).
                agentState = AgentState.Unconscious;
                try
                {
                    affectedAgent.State = AgentState.Unconscious;
                }
                catch { /* State setter may not be settable directly в некоторых
                         * engine versions — ref param выше всё-равно работает */ }

                // affectorAgent.Name is string в engine — но защитимся даже так.
                string affectorName = affectorAgent?.Name;
                if (string.IsNullOrEmpty(affectorName)) affectorName = "none";
                BannerlordLinkModule.LogVerbose(() =>
                    $"[DeathProtect] Converted {hero.Name} Killed → Unconscious in mission " +
                    $"(killer={affectorName})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[DeathProtect] Mission.OnAgentRemoved patch error: {ex.Message}");
            }
        }
    }
}
