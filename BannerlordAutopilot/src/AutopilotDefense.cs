using System;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        private Settlement _defenseTarget;
        private string _lastDefenseStatus;
        private readonly System.Collections.Generic.Dictionary<Settlement, double> _reliefRetryAfter = new System.Collections.Generic.Dictionary<Settlement, double>();
        private bool ReliefUnavailable(Settlement place) => place != null && _reliefRetryAfter.TryGetValue(place, out double until) && CampaignTime.Now.ToHours < until;

        private static bool OwnFort(Settlement place) => place != null && (place.IsTown || place.IsCastle)
            && Clan.PlayerClan != null && Clan.PlayerClan.Fiefs.Any(f => f.Settlement == place);

        /// <summary>03.10, владелец: «все замки, но до которых успеет дойти; странно видеть, как он
        /// проходит мимо замка, который забирают». Срочная оборона была только для замков своего
        /// клана; крепости королевства (кланы зрителей и лорды) проигрывали обычным целям.</summary>
        private static bool KingdomFort(Settlement place, MobileParty party) => place != null
            && (place.IsTown || place.IsCastle) && party?.MapFaction != null && place.MapFaction == party.MapFaction;

        /// <summary>Чужой (не своего клана) замок королевства спасаем, только если дойдём за столько
        /// игровых часов по нашей скорости — оценка по прямой, нижняя граница.</summary>
        internal const float KingdomReliefMaxHours = 24f;
        /// <summary>…и если мы с гарнизоном не слабее этой доли осаждающих (как порог охоты).</summary>
        internal const float KingdomReliefMinRatio = .8f;

        private static float BesiegerStrength(Settlement place)
        {
            var camp = place?.SiegeEvent?.BesiegerCamp;
            if (camp == null) return 0f;
            float sum = 0f;
            foreach (var p in MobileParty.All)
                if (p != null && p.IsActive && p.BesiegerCamp == camp) sum += Math.Max(0f, p.Party.EstimatedStrength);
            return sum;
        }

        private static float GarrisonStrength(Settlement place)
        {
            float garrison = place?.Town?.GarrisonParty?.Party != null ? Math.Max(0f, place.Town.GarrisonParty.Party.EstimatedStrength) : 0f;
            return garrison + Math.Max(0f, place?.Militia ?? 0f);
        }

        /// <summary>null — успеваем и по силам; иначе причина.</summary>
        private static string KingdomReliefRejection(Settlement place, MobileParty party)
        {
            // Свой феод спасаем и раненым (решение владельца); чужой замок королевства — нет:
            // раненому герою сначала лечение (поймал тест «раненый герой идёт в ближайшую крепость»).
            if (Hero.MainHero != null && Hero.MainHero.IsWounded) return "герой ранен";
            float distance = (float)Math.Sqrt(Math.Max(0f, party.Position.DistanceSquared(place.Position)));
            float hours = distance / Math.Max(.5f, party.Speed);
            if (hours > KingdomReliefMaxHours) return "не успеем: ~" + hours.ToString("F0") + " ч. пути";
            float besiegers = BesiegerStrength(place);
            float ours = Math.Max(0f, party.Party.EstimatedStrength) + GarrisonStrength(place);
            if (besiegers > 0f && ours < besiegers * KingdomReliefMinRatio)
                return "не по силам: мы с гарнизоном " + ours.ToString("F0") + " против " + besiegers.ToString("F0");
            return null;
        }

        private bool DefendableFort(Settlement place, MobileParty party) => OwnFort(place)
            || KingdomFort(place, party) && KingdomReliefRejection(place, party) == null;

        // Emergency defense does not wait for 90% capacity, seven days of supplies,
        // or the offensive campaign's 70% health. Casualties on entry stay native.
        private static string DefenseReadiness(MobileParty party)
        {
            int total = party?.MemberRoster.TotalManCount ?? 0;
            int healthy = total - (party?.MemberRoster.TotalWounded ?? 0);
            return total > 0 && healthy > 0 && healthy >= Math.Ceiling(total * .5)
                ? null : "боеспособны меньше 50% отряда (" + healthy + "/" + total + ")";
        }

        private Settlement FindEmergencyDefense(MobileParty party)
        {
            if (!ControlsParty(party) || party.IsCurrentlyAtSea || party.Ai == null || party.Ai.IsDisabled
                || Hero.MainHero == null || Hero.MainHero.IsPrisoner || DefenseReadiness(party) != null) return null;
            bool Usable(Settlement s) => FriendlySiege(s, party) && !ReliefUnavailable(s)
                && !(s == _stuckTarget && CampaignTime.Now.ToHours < _stuckTargetUntil);
            var candidates = Clan.PlayerClan?.Fiefs.Select(f => f.Settlement)
                .Where(s => OwnFort(s) && Usable(s)).ToList() ?? new System.Collections.Generic.List<Settlement>();
            // Свои первыми; если своих в осаде нет — крепости королевства, до которых успеваем и по силам.
            if (candidates.Count == 0)
                candidates = Settlement.All.Where(s => KingdomFort(s, party) && !OwnFort(s) && Usable(s)
                    && KingdomReliefRejection(s, party) == null).ToList();
            if (candidates.Count == 0) return null;
            return candidates.Contains(_defenseTarget) ? _defenseTarget
                : candidates.OrderBy(s => party.Position.DistanceSquared(s.Position)).First();
        }

        private void LogEmergencyDefense(MobileParty party, Settlement target, string action)
        {
            string key = target.StringId + "|" + action;
            if (_lastDefenseStatus == key) return;
            _lastDefenseStatus = key;
            Thoughts.Say("defend", target.StringId, target.Name);
            int total = party.MemberRoster.TotalManCount;
            AutopilotLog.Write("ОБОРОНА: «" + target.Name + "»; боеспособны "
                + (total - party.MemberRoster.TotalWounded) + "/" + total
                + "; заполнение " + party.Party.NumberOfAllMembers + "/" + party.Party.PartySizeLimit
                + "; " + action + "; прорыв и потери — по правилам игры");
        }

        private bool TryEmergencyDefense(MobileParty party, Settlement waitingIn)
        {
            if (_mode != Mode.Apply || !ControlsParty(party) || party.IsCurrentlyAtSea
                || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return false;
            if (_defenseTarget != null && (!DefendableFort(_defenseTarget, party) || !FriendlySiege(_defenseTarget, party)
                || DefenseReadiness(party) != null))
            {
                AutopilotLog.Write("ОБОРОНА: маршрут к «" + _defenseTarget.Name + "» отменён: "
                    + (!DefendableFort(_defenseTarget, party) ? (KingdomFort(_defenseTarget, party)
                        ? KingdomReliefRejection(_defenseTarget, party) : "поселение больше не наше") : !FriendlySiege(_defenseTarget, party)
                        ? "осада завершилась или сменился владелец" : DefenseReadiness(party)));
                if (party.TargetSettlement == _defenseTarget && IsOnFreeMap(party)) party.SetMoveModeHold();
                if (_hasPendingDecision && _pendingDecision.Party == _defenseTarget) _hasPendingDecision = false;
                _defenseTarget = null; _lastDefenseStatus = null; _lastTargetKey = null;
            }
            var target = FindEmergencyDefense(party);
            if (target == null) return false;
            _defenseTarget = target;
            _postBattleRestPending = false;
            _postBattleRestSettlement = null;
            _postBattleRestUntil = -1;
            _preparingCampaign = false;
            _offensiveSiege = null; _configuredSiege = null;
            _raidSettlement = null; _hideoutRoute = null;
            _travelTown = null; _travelOrigin = null;
            // Existing invitees can still join the army on the road; do not wait
            // a day for all of them while our fort is being assaulted.
            ClearArmyGathering();
            LogEmergencyDefense(party, target, (OwnFort(target) ? "идём спасать свой феод" : "идём спасать крепость королевства")
                + ", приоритет над наймом, снабжением и захватом");
            var decision = new AIBehaviorData(target, AiBehavior.DefendSettlement,
                MobileParty.NavigationType.Default, false, false, false);
            if (waitingIn != null)
            {
                _pendingDecision = decision; _pendingScore = 1f; _hasPendingDecision = true;
            }
            else ApplyDecision(party, decision, 1f);
            return true;
        }

        // Only native, interruptible wait screens. Never abandon an active battle,
        // a defender siege, a modal dialog or another leader's army.
        private bool PollEmergencyDefense(MobileParty party)
        {
            if (_mode != Mode.Apply || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return false;
            string menu = MenuDriver.CurrentMenuId;
            bool raidWait = menu == "raiding_village" && PlayerEncounter.Current != null;
            if (party == null || (party.MapEvent != null && (!raidWait || !party.MapEvent.IsRaid))) return false;
            bool siegeWait = menu == "menu_siege_strategies" && party.SiegeEvent?.BesiegerCamp?.LeaderParty == party;
            if (!siegeWait && !raidWait) return false;
            var target = FindEmergencyDefense(party);
            if (target == null) return false;
            string option = siegeWait ? "menu_siege_strategies_leave" : "raiding_village_end";
            if (!MenuDriver.CanInvoke(option, out _)) return false;
            _defenseTarget = target;
            LogEmergencyDefense(party, target, siegeWait ? "снимаем наступательную осаду" : "прекращаем рейд");
            OperationClick(option);
            return true;
        }
    }
}
