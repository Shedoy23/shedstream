using System;
using System.Globalization;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    /// <summary>Отход от армии «в разы» сильнее (23.09.2026, просьба владельца).
    ///
    /// Штатный ИИ сам умеет бежать (FleeToPoint/FleeToGate в
    /// DefaultMobilePartyAIModel.GetBestInitiativeBehavior), но отряду игрока
    /// игра инициативу не применяет, а автопилот брал из неё только нападение.
    /// Здесь: враг сильнее нас в 2x и больше идёт на нас — едем в ближайшую
    /// крепость не во вражде с нами, если успеваем раньше врага, и сидим там,
    /// пока он рядом; иначе уходим к поселению в сторону от врага. Порог 2x не
    /// пересекается с охотой (нападаем, пока враг не сильнее 1,25x).
    /// Проверка идёт в кадровом опросе: за игровой час армия успевает догнать.</summary>
    public partial class AutopilotBehavior
    {
        internal const float FleeRatio = 2f;
        /// <summary>Когда свой замок/город в осаде и мы можем его защищать —
        /// бросаем только перед такой силой. Владелец 23.09: «мы со зрителями
        /// отбивали даже подобные осады». Лог 22.09: как защитники отбили 1650 и
        /// 1685 врагов при отряде ~320 (~5,2x), проиграли при 2049 (6,4x) и выше.</summary>
        internal const float FleeRatioWhenDefending = 5f;
        private const float FleeDetectRadius = 12f;
        private const float FleeCloseDistance = 3f;
        private const float ShelterRadius = 25f;
        private const float RunToRadius = 40f;
        private const float ShelterThreatRadius = 15f;

        private MobileParty _fleeFrom;
        private Settlement _fleeTo;
        private Settlement _shelterIn;

        private static float PartyForce(MobileParty party)
        {
            MobileParty leader = party.Army?.LeaderParty ?? party;
            float strength = Math.Max(0f, leader.Party.EstimatedStrength);
            foreach (var attached in leader.AttachedParties)
                if (attached != null && attached != leader) strength += Math.Max(0f, attached.Party.EstimatedStrength);
            return strength;
        }

        private static float Distance(CampaignVec2 a, CampaignVec2 b) => (float)Math.Sqrt(Math.Max(0f, a.DistanceSquared(b)));

        /// <summary>Самая опасная вражеская сила «в разы» сильнее нас рядом с точке.
        /// chasing — только те, кто идёт на нас (или уже вплотную).</summary>
        private float CurrentFleeRatio(MobileParty party) =>
            _defenseTarget != null || FindEmergencyDefense(party) != null ? FleeRatioWhenDefending : FleeRatio;

        private static MobileParty FindThreat(MobileParty party, CampaignVec2 around, float radius, bool chasing, float ratio)
        {
            float ours = PartyForce(party);
            if (!(ours > 0f) || party.MapFaction == null) return null;
            MobileParty worst = null;
            float worstForce = 0f;
            foreach (MobileParty enemy in MobileParty.All)
            {
                if (enemy == null || enemy == party || !enemy.IsActive || !enemy.IsVisible
                    || enemy.CurrentSettlement != null || enemy.MapEvent != null || enemy.IsCurrentlyAtSea
                    || (enemy.Army != null && enemy.Army.LeaderParty != enemy)
                    || enemy.MapFaction == null || !party.MapFaction.IsAtWarWith(enemy.MapFaction)) continue;
                float distance = Distance(around, enemy.Position);
                if (distance > radius) continue;
                if (chasing && enemy.TargetParty != party && enemy.ShortTermTargetParty != party
                    && distance > FleeCloseDistance) continue;
                float force = PartyForce(enemy);
                if (force < ours * ratio || force <= worstForce) continue;
                worst = enemy; worstForce = force;
            }
            return worst;
        }

        private bool PollFlee(MobileParty party)
        {
            if (_mode != Mode.Apply || !ControlsParty(party) || party.IsCurrentlyAtSea
                || (party.Army != null && party.Army.LeaderParty != party)
                || !IsOnFreeMap(party) || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return false;
            MobileParty threat = FindThreat(party, party.Position, FleeDetectRadius, true, CurrentFleeRatio(party));
            if (threat == null)
            {
                if (_fleeFrom != null)
                {
                    AutopilotLog.Write("ОТХОД: погоня отстала, возвращаемся к обычным делам");
                    _fleeFrom = null; _fleeTo = null; _shelterIn = null;
                    _hoursSinceThink = ThinkPeriodHours;
                }
                return false;
            }

            float threatDistance = Distance(party.Position, threat.Position);
            Settlement shelter = Settlement.All
                .Where(s => s != null && (s.IsTown || s.IsCastle) && !s.IsUnderSiege && s.MapFaction != null
                    && !party.MapFaction.IsAtWarWith(s.MapFaction))
                .Select(s => new { Place = s, Us = Distance(party.Position, s.Position), Them = Distance(threat.Position, s.Position) })
                .Where(x => x.Us <= ShelterRadius && x.Us < x.Them)
                .OrderBy(x => (Clan.PlayerClan != null && Clan.PlayerClan.Fiefs.Any(f => f.Settlement == x.Place) ? 0f : 1000f) + x.Us)
                .Select(x => x.Place).FirstOrDefault();
            Settlement target = shelter ?? Settlement.All
                .Where(s => s != null && !s.IsHideout && !s.IsUnderSiege && s.MapFaction != null
                    && !party.MapFaction.IsAtWarWith(s.MapFaction))
                .Select(s => new { Place = s, Us = Distance(party.Position, s.Position), Gain = Distance(threat.Position, s.Position) - Distance(party.Position, s.Position) })
                .Where(x => x.Us <= RunToRadius && x.Gain > 0f)
                .OrderByDescending(x => x.Gain).Select(x => x.Place).FirstOrDefault();
            if (target == null)
            {
                if (_fleeFrom != threat) AutopilotLog.Write("ОТХОД: «" + threat.Name + "» идёт на нас, но уйти некуда — остаёмся на штатном ИИ");
                _fleeFrom = threat;
                return false;
            }
            _fleeFrom = threat; _shelterIn = shelter;
            if (_fleeTo == target && party.TargetSettlement == target) return false;
            _fleeTo = target;
            AutopilotLog.Write("ОТХОД: «" + threat.Name + "» идёт на нас (порог x"
                + CurrentFleeRatio(party).ToString("F0", CultureInfo.InvariantCulture) + ", сила "
                + PartyForce(threat).ToString("F0", CultureInfo.InvariantCulture) + " против наших "
                + PartyForce(party).ToString("F0", CultureInfo.InvariantCulture) + ", до него "
                + threatDistance.ToString("F1", CultureInfo.InvariantCulture) + "); "
                + (shelter != null ? "укрываемся в «" + target.Name + "»" : "уходим к «" + target.Name + "» прочь от врага"));
            ApplyDecision(party, new AIBehaviorData(target, AiBehavior.GoToSettlement,
                MobileParty.NavigationType.Default, false, false, false), 1f);
            return true;
        }

        /// <summary>В укрытии сидим, пока сильный враг рядом; ушёл — возвращаемся к делам.</summary>
        private bool HoldShelter(MobileParty party, Settlement settlement)
        {
            if (_mode != Mode.Apply || _shelterIn == null || settlement != _shelterIn
                || party.CurrentSettlement != settlement) return false;
            MobileParty threat = FindThreat(party, settlement.Position, ShelterThreatRadius, false, CurrentFleeRatio(party));
            if (threat != null)
            {
                if (_fleeFrom != threat)
                {
                    _fleeFrom = threat;
                    AutopilotLog.Write("УКРЫТИЕ: сидим в «" + settlement.Name + "», рядом «" + threat.Name + "»");
                }
                _hasPendingDecision = false;
                return true;
            }
            AutopilotLog.Write("УКРЫТИЕ: угроза у «" + settlement.Name + "» ушла, возвращаемся к обычным делам");
            _fleeFrom = null; _fleeTo = null; _shelterIn = null;
            _hoursSinceThink = ThinkPeriodHours;
            return false;
        }
    }
}
