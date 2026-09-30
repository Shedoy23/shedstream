using System;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        // Owner policy 30.09: at least 70% healthy, and the hero must be fit.
        // This gates voluntary orders only, never an already forced encounter.
        internal static string VoluntaryAttackBlocked(MobileParty party)
        {
            if (party == null || Hero.MainHero == null) return "нет партии/героя";
            if (Hero.MainHero.IsWounded) return "герой ранен";
            int total = party.MemberRoster.TotalManCount;
            int healthy = total - party.MemberRoster.TotalWounded;
            if (total > 0 && (long)healthy * 100 < (long)total * 70)
                return "боеспособны меньше 70% отряда";
            return null;
        }

        private static bool RecoveryNeedsFood(MobileParty party)
        {
            // Same seven-day reserve already required by PreparationNeeded.
            float consumption = -party.FoodChange;
            return float.IsNaN(consumption) || float.IsInfinity(consumption)
                || consumption > 0 && party.TotalFoodAtInventory < consumption * 7f;
        }

        private bool SafeRecoveryPlace(MobileParty party, Settlement settlement)
        {
            return settlement != null && (settlement.IsTown || settlement.IsCastle)
                && !settlement.IsUnderSiege && !CannotStay(settlement)
                && party.MapFaction != null && settlement.MapFaction != null
                && !party.MapFaction.IsAtWarWith(settlement.MapFaction)
                && FindThreat(party, settlement.Position, ShelterThreatRadius, false, CurrentFleeRatio(party)) == null;
        }

        // Called only during native waiting. Existing settlement service purchases
        // food on its usual cadence; a foodless castle must not imprison the party.
        private bool HoldRecovery(MobileParty party, Settlement settlement)
        {
            if (_mode != Mode.Apply || !ControlsParty(party) || party.IsCurrentlyAtSea
                || VoluntaryAttackBlocked(party) == null || !SafeRecoveryPlace(party, settlement)
                || party.CurrentSettlement != settlement || party.MapEvent != null
                || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return false;
            TryServe(party, settlement, MenuDriver.CurrentMenuId, "восстановление");
            if (VoluntaryAttackBlocked(party) == null || RecoveryNeedsFood(party)) return false;
            _hasPendingDecision = false;
            return true;
        }

        private bool TryRecovery(MobileParty party, Settlement waitingIn)
        {
            if (_mode != Mode.Apply || !ControlsParty(party) || party.IsCurrentlyAtSea || _fleeFrom != null
                || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()
                || VoluntaryAttackBlocked(party) == null
                || waitingIn == null && !IsOnFreeMap(party)) return false;
            if (waitingIn != null && HoldRecovery(party, waitingIn)) return true;
            // Service may have recruited enough healthy troops to reach the threshold.
            string reason = VoluntaryAttackBlocked(party);
            if (reason == null) return false;
            bool needsFood = RecoveryNeedsFood(party);
            var destination = Settlement.All.Where(s => SafeRecoveryPlace(party, s)
                    && (!needsFood || s.IsTown && s.ItemRoster.TotalFood > 0)
                    && (s != waitingIn || !needsFood))
                .OrderBy(s => party.Position.DistanceSquared(s.Position)).FirstOrDefault();
            if (destination == null) return false; // Other supply routes stay available.
            var decision = new AIBehaviorData(destination, AiBehavior.GoToSettlement,
                MobileParty.NavigationType.Default, false, false, false);
            if (!IsSameDecision(decision, party))
                AutopilotLog.Write("ВОССТАНОВЛЕНИЕ: " + reason + "; идём в «" + destination.Name
                    + "»" + (needsFood ? " за едой и отдыхом" : " отдыхать до 70% боеспособных и выздоровления героя"));
            if (waitingIn != null)
            {
                _pendingDecision = decision; _pendingScore = 1f; _hasPendingDecision = true;
            }
            else ApplyDecision(party, decision, 1f);
            return true;
        }
    }
}