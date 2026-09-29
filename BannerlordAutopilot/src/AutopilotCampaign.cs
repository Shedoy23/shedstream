using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        // A strategic destination survives a temporary unloading route. It is
        // separate from _offensiveSiege, which owns the current native encounter.
        private Settlement _committedSiege;

        private bool ContinueSiegeCampaign(MobileParty party, Settlement waitingIn)
        {
            if (_mode != Mode.Apply || _committedSiege == null || !ControlsParty(party)
                || party.IsCurrentlyAtSea) return false;
            if (!MapIsActiveScreen() || TaleWorlds.Library.InformationManager.IsAnyInquiryActive()) return true;
            var goal = new AIBehaviorData(_committedSiege, AiBehavior.BesiegeSettlement,
                MobileParty.NavigationType.Default, false, false, false);
            string invalid = SiegeTargetRejection(party, _committedSiege) ?? WhyNotApplicable(goal);
            if (invalid != null)
            {
                var cancelled = _committedSiege;
                _committedSiege = null;
                NoteSiegeRejection(cancelled, invalid);
                AutopilotLog.Write("ПОХОД: прекращаем цель «" + cancelled.Name + "»: " + invalid);
                if (_hasPendingDecision && _pendingDecision.Party == cancelled) _hasPendingDecision = false;
                if (party.TargetSettlement == cancelled) StopSiegeMarch(party);
                return false;
            }

            // The normal 95% inventory margin should not interrupt a prepared
            // siege march. Actual excess weight still authorizes unloading.
            Settlement market = party.TotalWeightCarried > party.InventoryCapacity
                ? EquipmentAndTrade.FindUnloadingTown(party, s => _services.IsDue(s) && !CannotStay(s)) : null;
            var next = market == null ? goal : new AIBehaviorData(market, AiBehavior.GoToSettlement,
                MobileParty.NavigationType.Default, false, false, false);
            if (waitingIn != null)
            {
                if (waitingIn == market) TryServe(party, market, MenuDriver.CurrentMenuId, "разгрузка перед осадой");
                else { _pendingDecision = next; _pendingScore = 1f; _hasPendingDecision = true; }
                return true;
            }
            if (!IsSameDecision(next, party))
            {
                AutopilotLog.Write(market == null
                    ? "ПОХОД: возвращаемся к закреплённой цели «" + _committedSiege.Name + "»"
                    : "ПОХОД: разгружаемся в «" + market.Name + "», сохраняем цель «" + _committedSiege.Name + "»");
                ApplyDecision(party, next, 1f);
            }
            return true;
        }
    }
}
