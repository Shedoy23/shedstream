using System;
using System.Globalization;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;

namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        // Owner policy, 16.09: comparable fight, up to 120% of OUR PARTY's native power.
        // Radius matches the owner's former Bandit Black Hole configuration (30 map units).
        private const float BanditGatherRadius = 30f;
        private const float BanditGatherMaxRatio = 1.2f;
        private object _banditGatheredBattle;
        private bool _banditGatherPreviewFault;
        private const string BanditGatherDialogId = "autopilot_bandit_gather";

        private void RegisterBanditGatherDialog(CampaignGameStarter starter)
        {
            // Native bandit_start_fight supplies the NPC response and sets Hostile.
            // No private reflection, patched native dialogue or Black Hole dependency.
            starter.AddPlayerLine(BanditGatherDialogId, "bandit_attacker", "bandit_start_fight",
                "{=!}Собирайте ближайшие отряды. Сразимся со всеми сразу!", CanOfferBanditGatherDialog, null, 101);
        }

        private bool CanOfferBanditGatherDialog()
        {
            if (_mode != Mode.Apply || _banditGatherPreviewFault) return false;
            try
            {
                var main = MobileParty.MainParty;
                var target = _combatTarget ?? (main?.DefaultBehavior == AiBehavior.EngageParty ? main.TargetParty : null);
                if (main == null || !main.IsActive || main.IsCurrentlyAtSea || main.Army != null || main.MapEvent != null
                    || main.SiegeEvent != null || main.BesiegedSettlement != null || PlayerEncounter.Current == null
                    || PlayerEncounter.EncounterSettlement != null || target == null
                    || PlayerEncounter.EncounteredMobileParty != target
                    || Campaign.Current?.ConversationManager?.ConversationParty != target
                    || !IsFreeNearbyBandit(target, main)) return false;
                var context = Campaign.Current.Models.MilitaryPowerModel.GetContextForPosition(main.Position);
                float ours = main.Party.GetCustomStrength(BattleSideEnum.Attacker, context);
                float total = target.Party.GetCustomStrength(BattleSideEnum.Defender, context);
                if (!PositivePower(ours) || !PositivePower(total) || total >= ours) return false;
                foreach (var candidate in MobileParty.AllBanditParties.Where(p => p != target && IsFreeNearbyBandit(p, main))
                    .OrderBy(p => p.Position.DistanceSquared(main.Position)))
                {
                    if (target.MapFaction.IsAtWarWith(candidate.MapFaction)) continue;
                    float power = candidate.Party.GetCustomStrength(BattleSideEnum.Defender, context);
                    if (!PositivePower(power) || total + power > ours * BanditGatherMaxRatio) continue;
                    total += power;
                    if (total >= ours) return true;
                }
                return false;
            }
            catch (Exception ex)
            {
                _banditGatherPreviewFault = true;
                AutopilotLog.Write("СБОР БАНДИТОВ: оценка группы недоступна до следующего включения: " + ex);
                return false;
            }
        }

        private bool TrySelectBanditGatherDialog()
        {
            var conversation = Campaign.Current?.ConversationManager;
            var options = conversation?.CurOptions;
            for (int i = 0; options != null && i < options.Count; i++)
                if (options[i].Id == BanditGatherDialogId && options[i].IsClickable && CanOfferBanditGatherDialog())
                {
                    conversation.DoOption(i);
                    AutopilotLog.Write("СБОР БАНДИТОВ: выбран вызов общей группы вместо ультиматума; добор после создания боя");
                    return true;
                }
            return false;
        }

        private static bool PositivePower(float power) => power > 0 && !float.IsNaN(power) && !float.IsInfinity(power);

        private static float BanditEnemyPower(MobileParty main)
        {
            var battle = main.MapEvent;
            var enemy = battle.DefenderSide; // Gathering only when the player is the attacker.
            float total = 0;
            foreach (var member in enemy.Parties)
            {
                // Include every existing opponent, not only the original target.
                if (member.Party?.MobileParty?.IsBandit != true) return float.NaN;
                float power = member.Party.GetCustomStrength(BattleSideEnum.Defender, battle.SimulationContext);
                if (power < 0 || float.IsNaN(power) || float.IsInfinity(power)) return float.NaN;
                total += power;
            }
            return total;
        }

        private static bool IsFreeNearbyBandit(MobileParty candidate, MobileParty main)
        {
            return candidate != null && candidate != main && candidate.IsBandit && candidate.IsActive
                && !candidate.IsCurrentlyAtSea && !candidate.IsEngaging && !candidate.IsDisbanding
                && !candidate.IsTransitionInProgress && candidate.MapEvent == null
                && candidate.Army == null && candidate.AttachedTo == null && candidate.AttachedParties.Count == 0
                && candidate.SiegeEvent == null && candidate.BesiegedSettlement == null && candidate.CurrentSettlement == null
                && candidate.Party.NumberOfHealthyMembers > 0 && candidate.MapFaction != null && main.MapFaction != null
                && main.MapFaction.IsAtWarWith(candidate.MapFaction)
                && candidate.Position.DistanceSquared(main.Position) <= BanditGatherRadius * BanditGatherRadius;
        }

        private static bool CanGatherBandit(MobileParty candidate, MobileParty main) => IsFreeNearbyBandit(candidate, main)
            && main.MapEvent.CanPartyJoinBattle(candidate.Party, BattleSideEnum.Defender);

        /// <summary>One synchronous pass immediately before the native attack button.
        /// Membership goes through the SAME PartyBase.MapEventSide setter as
        /// PlayerEncounter.OnPartyJoinEncounter in 1.4.8. That setter already adds
        /// native strength/rewards; an extra recalculation would double-count it.</summary>
        private bool GatherBanditsForBattle(MobileParty main)
        {
            var battle = main?.MapEvent;
            if (_mode != Mode.Apply || main == null || !main.IsActive || main.IsCurrentlyAtSea
                || main.Army != null
                || !IsSupportedFieldBattleEncounter(main) || battle != PlayerEncounter.Battle
                || battle.PlayerSide != BattleSideEnum.Attacker || !battle.IsFieldBattle
                || ReferenceEquals(_banditGatheredBattle, battle)) return true;
            _banditGatheredBattle = battle; // Consume before callbacks; uncertain effects are never retried.
            try
            {
                float ours = main.Party.GetCustomStrength(BattleSideEnum.Attacker, battle.SimulationContext);
                float before = BanditEnemyPower(main);
                if (!PositivePower(ours) || !PositivePower(before) || before >= ours) return true;
                int gathered = 0;
                var nearby = MobileParty.AllBanditParties.Where(p => CanGatherBandit(p, main))
                    .OrderBy(p => p.Position.DistanceSquared(main.Position)).ToList();
                foreach (var candidate in nearby)
                {
                    // Native callbacks may alter membership, rosters, mode or encounter.
                    if (_mode != Mode.Apply || main.MapEvent != battle || PlayerEncounter.Battle != battle) return false;
                    ours = main.Party.GetCustomStrength(BattleSideEnum.Attacker, battle.SimulationContext);
                    float enemies = BanditEnemyPower(main);
                    if (!PositivePower(ours) || !PositivePower(enemies) || enemies >= ours) break;
                    if (!CanGatherBandit(candidate, main)) continue;
                    float addition = candidate.Party.GetCustomStrength(BattleSideEnum.Defender, battle.SimulationContext);
                    if (!PositivePower(addition) || enemies + addition > ours * BanditGatherMaxRatio) continue;

                    var previousPosition = candidate.Position;
                    try
                    {
                        candidate.Position = main.Position;
                        candidate.Party.MapEventSide = battle.DefenderSide;
                    }
                    catch
                    {
                        // If a callback threw after joining, preserve the native effect.
                        if (candidate.MapEvent == null) candidate.Position = previousPosition;
                        throw;
                    }
                    if (candidate.MapEvent != battle || candidate.Party.MapEventSide != battle.DefenderSide)
                    {
                        if (candidate.MapEvent == null) candidate.Position = previousPosition;
                        Disable("сбор бандитов: присоединение не подтвердилось, повторять не буду");
                        return false;
                    }
                    gathered++;
                    AutopilotLog.Write("СБОР БАНДИТОВ: добавлен «" + candidate.Name + "», сила "
                        + addition.ToString("F1", CultureInfo.InvariantCulture));
                }
                if (_mode != Mode.Apply || main.MapEvent != battle || PlayerEncounter.Battle != battle) return false;
                float after = BanditEnemyPower(main);
                ours = main.Party.GetCustomStrength(BattleSideEnum.Attacker, battle.SimulationContext);
                if (gathered > 0 && (!PositivePower(ours) || !PositivePower(after) || after > ours * BanditGatherMaxRatio))
                {
                    Disable("сбор бандитов: обработчики присоединения изменили силу сторон за предел 120%; атака не нажата");
                    return false;
                }
                AutopilotLog.Write("СБОР БАНДИТОВ: отрядов добавлено " + gathered + "; сила врагов "
                    + before.ToString("F1", CultureInfo.InvariantCulture) + " → " + after.ToString("F1", CultureInfo.InvariantCulture)
                    + "; наша " + ours.ToString("F1", CultureInfo.InvariantCulture) + "; предел добора 120%; радиус 30");
                return true;
            }
            catch (Exception ex)
            {
                Disable("сбор бандитов остановлен после исключения: " + ex);
                return false;
            }
        }
    }
}
