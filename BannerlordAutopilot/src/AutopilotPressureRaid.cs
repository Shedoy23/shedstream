using System;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        private Settlement _pressureVillage;
        private Settlement _pressureFort;

        // An economic raid is a native raid, not direct removal of food or soldiers.
        // Only villages feeding a frontier fort which we cannot currently besiege.
        private bool PressureRaidSafe(MobileParty party, Settlement village)
        {
            if (!EnemyVillage(village, party) || village.IsRaided || village.IsUnderRaid
                || PreparationNeeded(party) != null || !ControlsParty(party)) return false;
            float defense = Math.Max(0, village.Militia);
            foreach (var enemy in MobileParty.All)
                if (enemy != null && enemy.IsActive && enemy.IsLordParty && enemy.MapFaction != null
                    && party.MapFaction.IsAtWarWith(enemy.MapFaction)
                    && enemy.Position.DistanceSquared(village.Position) <= 25f * 25f)
                    defense += Math.Max(0, enemy.Party.EstimatedStrength);
            return SiegeAttackerStrength(party) >= defense * SiegeLiftRatio;
        }

        private bool TryFindPressureRaid(MobileParty party, out AIBehaviorData target)
        {
            target = AIBehaviorData.Invalid;
            if (!ControlsParty(party) || party.IsCurrentlyAtSea || PreparationNeeded(party) != null
                || party.SiegeEvent != null || party.MapEvent != null) return false;
            float available = SiegeAttackerStrength(party);
            if (party.Army == null) available += AffordableArmyMembers(party).Sum(p => Math.Max(0, p.Party.EstimatedStrength));
            Settlement best = null, fort = null;
            float distance = float.MaxValue;
            foreach (var village in Settlement.All)
            {
                if (!village.IsVillage || !PressureRaidSafe(party, village)) continue;
                float d = party.Position.DistanceSquared(village.Position);
                if (d > 100f * 100f) continue;
                // Bound is the direct village-food contribution. TradeBound is a market route,
                // possibly to another town; do not call that town the village's fortress.
                var supplied = village.Village?.Bound;
                if (!EnemyFortress(supplied, party) || SiegeBorderRejection(party, supplied) != null) continue;
                float own = available + AlliedCampStrength(supplied, party, out _);
                if (own >= SiegeDefenderStrength(supplied, party) * SiegeStrengthRatio) continue;
                // Do not zigzag between neighbouring villages during one raid march.
                if (village == _pressureVillage && party.TargetSettlement == village
                    && party.DefaultBehavior == AiBehavior.RaidSettlement) d = -1;
                if (d >= distance) continue;
                best = village; fort = supplied; distance = d;
            }
            if (best == null) return false;
            target = new AIBehaviorData(best, AiBehavior.RaidSettlement, MobileParty.NavigationType.Default, false, false, false);
            if (_pressureVillage != best || _pressureFort != fort)
                AutopilotLog.Write("СНАБЖЕНИЕ ВРАГА: «" + fort.Name + "» пока не по силам — набег на «" + best.Name
                    + "»; нарушаем снабжение, исход для гарнизона определяет игра");
            _pressureVillage = best; _pressureFort = fort;
            return true;
        }

        private void RecheckPressureRaid(MobileParty party)
        {
            if (_mode != Mode.Apply || _pressureVillage == null || !IsOnFreeMap(party)
                || party.DefaultBehavior != AiBehavior.RaidSettlement || party.TargetSettlement != _pressureVillage) return;
            if (EnemyFortress(_pressureFort, party) && PressureRaidSafe(party, _pressureVillage)) return;
            AutopilotLog.Write("СНАБЖЕНИЕ ВРАГА: набег на «" + _pressureVillage.Name + "» отменён — цель изменилась или подход стал опасен");
            party.SetMoveModeHold();
            _raidSettlement = null; _pressureVillage = null; _pressureFort = null; _lastTargetKey = null;
            _hoursSinceThink = ThinkPeriodHours;
        }
    }
}
