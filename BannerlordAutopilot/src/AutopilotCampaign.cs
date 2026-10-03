using System;
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
        /// <summary>03.10: поход на «Замок Астер» отменён через 3 с после приказа — за несколько
        /// игровых часов в радиус вошла подмога 1345, одного замера хватило. Нехватку сил
        /// терпим столько игровых часов подряд, прежде чем бросить закреплённую цель.</summary>
        internal const float SiegeShortfallGraceHours = 3f;
        private Settlement _shortfallSiege;
        private double _shortfallSince;

        private bool ContinueSiegeCampaign(MobileParty party, Settlement waitingIn)
        {
            if (_mode != Mode.Apply || _committedSiege == null || !ControlsParty(party)
                || party.IsCurrentlyAtSea) return false;
            if (!MapIsActiveScreen() || TaleWorlds.Library.InformationManager.IsAnyInquiryActive()) return true;
            var goal = new AIBehaviorData(_committedSiege, AiBehavior.BesiegeSettlement,
                MobileParty.NavigationType.Default, false, false, false);
            string rejection = SiegeTargetRejection(party, _committedSiege);
            string invalid = rejection ?? WhyNotApplicable(goal);
            // Both SiegeTargetRejection and WhyNotApplicable report a strength shortfall
            // with this prefix; every other reason (peace, not ours, border…) cancels at once.
            if (invalid != null && invalid.StartsWith(SiegeShortfallPrefix, StringComparison.Ordinal))
            {
                double now = CampaignTime.Now.ToHours;
                if (_shortfallSiege != _committedSiege) { _shortfallSiege = _committedSiege; _shortfallSince = now; }
                if (now - _shortfallSince < SiegeShortfallGraceHours)
                {
                    AutopilotLog.Write("ПОХОД: сил к «" + _committedSiege.Name + "» сейчас не хватает (" + invalid
                        + "); проверяем ещё " + (SiegeShortfallGraceHours - (now - _shortfallSince)).ToString("0.#",
                        System.Globalization.CultureInfo.InvariantCulture) + " ч., прежде чем бросить цель");
                    invalid = null;
                }
            }
            else if (invalid == null) _shortfallSiege = null;
            if (invalid != null)
            {
                _shortfallSiege = null;
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
