using System;
using System.Globalization;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        // Owner policy, 30.09: gather existing free lords of the attacked faction,
        // up to 120% of the ENTIRE attacking side, within the bandit gathering radius.
        private const float LordGatherRadius = 120f;
        private const float LordGatherMaxRatio = 1.2f;
        // Deliberately survives toggling F11: an uncertain join must not be retried
        // in the same battle even if the player re-enables the autopilot.
        private object _lordGatheredBattle;

        private static float LordBattleSidePower(MobileParty main, BattleSideEnum side)
        {
            var battle = main.MapEvent;
            var participants = side == BattleSideEnum.Attacker ? battle.AttackerSide.Parties : battle.DefenderSide.Parties;
            float total = 0;
            foreach (var participant in participants)
            {
                if (participant.Party == null) return float.NaN;
                float power = participant.Party.GetCustomStrength(side, battle.SimulationContext);
                if (power < 0 || float.IsNaN(power) || float.IsInfinity(power)) return float.NaN;
                total += power;
            }
            // Attached army parties have ALREADY joined through the native setter.
            // Army.Parties would count those twice and also count parties still en route.
            return total;
        }

        private static bool CanGatherLord(MobileParty candidate, MobileParty main, IFaction faction)
        {
            return candidate != null && candidate != main && candidate.IsLordParty && candidate.IsActive
                && candidate.MapFaction == faction && main.MapFaction != null && main.MapFaction.IsAtWarWith(faction)
                && !candidate.IsCurrentlyAtSea && !candidate.IsEngaging && !candidate.IsDisbanding
                && !candidate.IsTransitionInProgress && !candidate.IsCurrentlyUsedByAQuest
                && candidate.Ai != null && !candidate.Ai.IsDisabled && !candidate.Ai.DoNotMakeNewDecisions
                && candidate.MapEvent == null && candidate.Army == null && candidate.AttachedTo == null
                && candidate.AttachedParties.Count == 0 && candidate.SiegeEvent == null
                && candidate.BesiegedSettlement == null && candidate.CurrentSettlement == null
                && candidate.Party.NumberOfHealthyMembers > 0
                && candidate.Position.DistanceSquared(main.Position) <= LordGatherRadius * LordGatherRadius
                && main.MapEvent.CanPartyJoinBattle(candidate.Party, BattleSideEnum.Defender);
        }

        private bool LordGatherContextValid(MobileParty main, MobileParty target, IFaction faction,
            object battle, object encounter)
        {
            return _mode == Mode.Apply && main.IsActive && ReferenceEquals(main.MapEvent, battle)
                && ReferenceEquals(PlayerEncounter.Battle, battle) && ReferenceEquals(PlayerEncounter.Current, encounter)
                && !PlayerEncounter.Current.IsJoinedBattle && !main.IsCurrentlyAtSea
                && (main.Army == null || main.Army.LeaderParty == main)
                && MapIsActiveScreen() && !InformationManager.IsAnyInquiryActive()
                && MenuDriver.CurrentMenuId == "encounter" && MenuDriver.CanInvoke("attack", out _)
                && PlayerEncounter.EncounteredMobileParty == target && target.IsActive && target.IsLordParty
                && target.MapFaction == faction && !target.IsCurrentlyUsedByAQuest
                && target.MapEvent == main.MapEvent && target.Party.MapEventSide == main.MapEvent.DefenderSide
                && main.MapFaction != null && main.MapFaction.IsAtWarWith(faction)
                && main.MapEvent.PlayerSide == BattleSideEnum.Attacker
                && main.MapEvent.AttackerSide.LeaderParty == main.Party;
        }

        private bool GatherLordsForBattle(MobileParty main)
        {
            var battle = main?.MapEvent;
            var encounter = PlayerEncounter.Current;
            if (_mode != Mode.Apply || main == null || !main.IsActive || main.IsCurrentlyAtSea
                || encounter == null || encounter.IsJoinedBattle
                || !IsSupportedFieldBattleEncounter(main) || battle != PlayerEncounter.Battle
                || !battle.IsFieldBattle || battle.IsSiegeAssault || battle.IsSiegeOutside || battle.IsSallyOut || battle.IsRaid
                || battle.PlayerSide != BattleSideEnum.Attacker || battle.AttackerSide.LeaderParty != main.Party
                || (main.Army != null && main.Army.LeaderParty != main)
                || ReferenceEquals(_lordGatheredBattle, battle)) return true;
            var target = PlayerEncounter.EncounteredMobileParty;
            var faction = target?.MapFaction;
            if (faction == null || !LordGatherContextValid(main, target, faction, battle, encounter)) return true;
            _lordGatheredBattle = battle; // Consume before invoking any native callbacks.
            try
            {
                float ours = LordBattleSidePower(main, BattleSideEnum.Attacker);
                float before = LordBattleSidePower(main, BattleSideEnum.Defender);
                if (!PositivePower(ours) || !PositivePower(before) || before >= ours) return true;
                int gathered = 0;
                var nearby = MobileParty.All.Where(p => CanGatherLord(p, main, faction))
                    .OrderBy(p => p.Position.DistanceSquared(main.Position)).ToList();
                foreach (var candidate in nearby)
                {
                    if (!LordGatherContextValid(main, target, faction, battle, encounter))
                    {
                        Disable("сбор лордов: цель, фракция или бой изменились во время присоединения");
                        return false;
                    }
                    ours = LordBattleSidePower(main, BattleSideEnum.Attacker);
                    float enemies = LordBattleSidePower(main, BattleSideEnum.Defender);
                    if (!PositivePower(ours) || !PositivePower(enemies) || enemies >= ours) break;
                    if (!CanGatherLord(candidate, main, faction)) continue;
                    float addition = candidate.Party.GetCustomStrength(BattleSideEnum.Defender, battle.SimulationContext);
                    if (!PositivePower(addition) || enemies + addition > ours * LordGatherMaxRatio) continue;
                    var previousPosition = candidate.Position;
                    try
                    {
                        candidate.Position = main.Position;
                        // Native membership setter handles strength, rewards and callbacks once.
                        candidate.Party.MapEventSide = battle.DefenderSide;
                    }
                    catch
                    {
                        if (candidate.MapEvent == null) candidate.Position = previousPosition;
                        throw;
                    }
                    if (candidate.MapEvent != battle || candidate.Party.MapEventSide != battle.DefenderSide)
                    {
                        if (candidate.MapEvent == null) candidate.Position = previousPosition;
                        Disable("сбор лордов: присоединение не подтвердилось, повторять не буду");
                        return false;
                    }
                    if (!candidate.IsActive || candidate.MapFaction != faction
                        || !battle.CanPartyJoinBattle(candidate.Party, BattleSideEnum.Defender))
                    {
                        Disable("сбор лордов: после присоединения изменились отряд или его отношения со сторонами");
                        return false; // Membership is confirmed; do not undo native callback effects.
                    }
                    gathered++;
                    AutopilotLog.Write("СБОР ЛОРДОВ: добавлен «" + candidate.Name + "», сила "
                        + addition.ToString("F1", CultureInfo.InvariantCulture));
                }
                if (!LordGatherContextValid(main, target, faction, battle, encounter))
                {
                    Disable("сбор лордов: изменился контекст боя после присоединения");
                    return false;
                }
                float after = LordBattleSidePower(main, BattleSideEnum.Defender);
                ours = LordBattleSidePower(main, BattleSideEnum.Attacker);
                if (gathered > 0 && (!PositivePower(ours) || !PositivePower(after) || after > ours * LordGatherMaxRatio))
                {
                    Disable("сбор лордов: обработчики изменили силу сторон за предел120%; атака не нажата");
                    return false;
                }
                AutopilotLog.Write("СБОР ЛОРДОВ: цель «" + target.Name + "»; отрядов добавлено " + gathered
                    + "; сила врагов " + before.ToString("F1", CultureInfo.InvariantCulture) + " → "
                    + after.ToString("F1", CultureInfo.InvariantCulture) + "; вся наша сторона "
                    + ours.ToString("F1", CultureInfo.InvariantCulture) + "; предел добора120%; радиус " + LordGatherRadius);
                return true;
            }
            catch (Exception ex)
            {
                Disable("сбор лордов остановлен после исключения: " + ex);
                return false;
            }
        }
    }
}
