using System;
using System.Globalization;
using System.Collections.Generic;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.Siege;
using TaleWorlds.Core;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        private Settlement _offensiveSiege;
        private Settlement _raidSettlement;
        private SiegeEvent _configuredSiege;
        private Army _gatheringArmy;
        private AIBehaviorData _armyObjective;
        private float _armyObjectiveScore;
        private double _gatheringSince;
        private readonly List<MobileParty> _invitedParties = new List<MobileParty>();

        private static bool ControlsParty(MobileParty party) => party != null
            && (party.Army == null || party.Army.LeaderParty == party);

        private List<MobileParty> AffordableArmyMembers(MobileParty party)
        {
            var result = new List<MobileParty>();
            if (party.Army != null || !(party.MapFaction is Kingdom) || PreparationNeeded(party) != null) return result;
            var model = Campaign.Current.Models.ArmyManagementCalculationModel;
            if (!model.CanPlayerCreateArmy(out _)) return result;
            float remaining = Clan.PlayerClan.Influence;
            var candidates = party.ThinkParamsCache.PossibleArmyMembersUponArmyCreation;
            if (candidates == null) return result;
            foreach (var candidate in candidates.Distinct())
            {
                if (candidate == null || candidate == party || !candidate.IsActive || candidate.MapFaction != party.MapFaction
                    || !model.CheckPartyEligibility(candidate, out _)) continue;
                int cost = model.CalculatePartyInfluenceCost(party, candidate);
                if (cost < 0 || cost > remaining) continue;
                remaining -= cost; result.Add(candidate);
            }
            return result;
        }

        private bool StartArmy(MobileParty party, AIBehaviorData data, float score)
        {
            var members = AffordableArmyMembers(party);
            if (members.Count == 0) return false;
            var model = Campaign.Current.Models.ArmyManagementCalculationModel;
            ((Kingdom)party.MapFaction).CreateArmy(Hero.MainHero, data.Party as Settlement,
                data.AiBehavior == AiBehavior.BesiegeSettlement ? Army.ArmyTypes.Besieger
                    : data.AiBehavior == AiBehavior.RaidSettlement ? Army.ArmyTypes.Raider : Army.ArmyTypes.Defender);
            if (party.Army == null || party.Army.LeaderParty != party) throw new InvalidOperationException("армия не создана движком");
            _invitedParties.Clear();
            foreach (var member in members)
            {
                if (!model.CheckPartyEligibility(member, out _)) continue;
                int cost = model.CalculatePartyInfluenceCost(party, member);
                if (cost < 0 || cost > Clan.PlayerClan.Influence) continue;
                // The setter has callbacks. Charge even if a callback throws after joining.
                try { member.Army = party.Army; }
                finally
                {
                    if (member.Army == party.Army)
                    {
                        ChangeClanInfluenceAction.Apply(Clan.PlayerClan, -cost);
                        _invitedParties.Add(member);
                    }
                }
            }
            _gatheringArmy = party.Army; _armyObjective = data; _armyObjectiveScore = score;
            _gatheringSince = CampaignTime.Now.ToHours;
            party.SetMoveModeHold();
            AutopilotLog.Write("АРМИЯ: приглашено " + _invitedParties.Count + ", ждём соединения перед " + data.AiBehavior);
            return true;
        }

        private bool PollArmy(MobileParty party)
        {
            if (party.Army == null) { _gatheringArmy = null; return false; }
            if (party.MapEvent != null || PlayerEncounter.Current != null || party.SiegeEvent != null) return false;
            if (!ControlsParty(party))
            {
                if (_mode == Mode.Apply && MapIsActiveScreen() && !InformationManager.IsAnyInquiryActive())
                {
                    if (party.AttachedTo == null && party.Army.LeaderParty != null)
                        SetPartyAiAction.GetActionForEscortingParty(party, party.Army.LeaderParty, MobileParty.NavigationType.Default, false, false);
                    if (Campaign.Current.CurrentMenuContext == null) KeepTimeRunning(party);
                    else ResumeOperationWait();
                }
                return true;
            }
            if (_gatheringArmy != party.Army) return false;
            if (_mode != Mode.Apply || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return true;
            bool assembled = _invitedParties.All(p => p.Army != party.Army || p.AttachedTo == party);
            if (assembled || CampaignTime.Now.ToHours - _gatheringSince >= 24)
            {
                _gatheringArmy = null;
                AutopilotLog.Write("АРМИЯ: сбор завершён; продолжаем штатную цель");
                ApplyDecision(party, _armyObjective, _armyObjectiveScore);
            }
            else KeepTimeRunning(party);
            return true;
        }

        // Owner-approved 16 September: seven days of food/wages, 70% healthy.
        private static string PreparationNeeded(MobileParty party)
        {
            if (party == null || Hero.MainHero == null) return "нет партии/героя";
            float consumption = -party.FoodChange;
            if (float.IsNaN(consumption) || float.IsInfinity(consumption)) return "неизвестен расход еды";
            if (consumption > 0 && party.TotalFoodAtInventory < consumption * 7f) return "еда меньше чем на 7 дней";
            if (Hero.MainHero.Gold < Math.Max(0, party.TotalWage) * 7f) return "золото меньше 7 дней жалования";
            int total = party.MemberRoster.TotalManCount;
            if (total <= 0 || total - party.MemberRoster.TotalWounded < total * .7f) return "боеспособны меньше 70% отряда";
            if (Hero.MainHero.IsWounded) return "герой ранен";
            return null;
        }

        private static bool EnemyFortress(Settlement place, MobileParty party) =>
            place != null && (place.IsTown || place.IsCastle) && place.MapFaction != null
            && party?.MapFaction != null && party.MapFaction.IsAtWarWith(place.MapFaction);

        private static bool EnemyVillage(Settlement place, MobileParty party) => place?.IsVillage == true
            && !place.IsRaided && place.MapFaction != null && party?.MapFaction != null
            && party.MapFaction.IsAtWarWith(place.MapFaction);

        private bool PollRaid(MobileParty party)
        {
            if (_mode != Mode.Apply || !ControlsParty(party) || party.IsCurrentlyAtSea) return false;
            var place = EncounterPlace(party);
            if (_raidSettlement == null && party.DefaultBehavior == AiBehavior.RaidSettlement
                && party.TargetSettlement == place && EnemyVillage(place, party)) _raidSettlement = place;
            if (_raidSettlement == null) return false;
            string menu = MenuDriver.CurrentMenuId;
            if (IsOnFreeMap(party) && menu == null)
            {
                if (party.DefaultBehavior != AiBehavior.RaidSettlement) _raidSettlement = null;
                return false;
            }
            if (!MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return true;
            if (place != _raidSettlement && menu != "village_player_raid_ended" && menu != "village_raid_diplomatically_ended") return false;
            try
            {
                _operationSettlement = _raidSettlement;
                switch (menu)
                {
                    case "village":
                        if (!EnemyVillage(place, party)) return false;
                        OperationClick("hostile_action"); return true;
                    case "village_hostile_action":
                        OperationClick(EnemyVillage(place, party) ? "raid_village" : "forget_it"); return true;
                    case "raid_village_no_resist_warn_player":
                        OperationClick(EnemyVillage(place, party) ? "raid_village_warn_continue" : "raid_village_warn_leave"); return true;
                    case "raiding_village":
                        if (PreparationNeeded(party) != null) OperationClick("raiding_village_end");
                        else ResumeOperationWait();
                        return true;
                    case "raid_occupied": OperationClick("raid_occuppied_continue"); return true;
                    case "village_player_raid_ended":
                    case "village_raid_ended_leaded_by_someone_else": OperationClick("continue"); return true;
                    case "village_looted":
                    case "village_raid_diplomatically_ended": OperationClick("leave"); return true;
                    case "encounter":
                        if (party.MapEvent?.MapEventSettlement != _raidSettlement) return false;
                        OperationClick(MenuDriver.CanInvoke("attack", out _) ? "attack" : "village_raid_action"); return true;
                }
            }
            catch (Exception ex) { Disable("рейд: " + ex.GetType().Name + ": " + ex.Message); return true; }
            return false;
        }

        private bool PollOffensiveSiege(MobileParty party)
        {
            if (_mode != Mode.Apply || party == null || party.IsCurrentlyAtSea) return false;
            string menu = MenuDriver.CurrentMenuId;
            var siege = party.SiegeEvent;
            var place = siege?.BesiegedSettlement ?? EncounterPlace(party);
            bool commanded = siege?.BesiegerCamp.LeaderParty == party;
            bool approaching = siege == null && EnemyFortress(place, party)
                && (_offensiveSiege == place || (party.DefaultBehavior == AiBehavior.BesiegeSettlement && party.TargetSettlement == place));
            if (_offensiveSiege == null && (commanded || approaching)) _offensiveSiege = place;
            if (_offensiveSiege == null) return false;
            if (IsOnFreeMap(party) && siege == null && menu == null)
            {
                if (party.DefaultBehavior != AiBehavior.BesiegeSettlement) { _offensiveSiege = null; _configuredSiege = null; }
                return false;
            }
            if (!MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return true;
            try
            {
                if (menu == "town_outside" || menu == "castle_outside")
                {
                    if (!approaching) return false;
                    string needed = PreparationNeeded(party);
                    if (needed != null)
                    {
                        AutopilotLog.Write("ПОХОД: перед осадой требуется восстановление: " + needed);
                        return false;
                    }
                    _operationSettlement = place;
                    OperationClick("town_besiege"); return true;
                }
                if (menu == "menu_siege_strategies" && commanded && place == _offensiveSiege)
                {
                    string needed = PreparationNeeded(party);
                    if (needed != null)
                    {
                        AutopilotLog.Write("ПОХОД: снимаем осаду для восстановления: " + needed);
                        OperationClick("menu_siege_strategies_leave"); return true;
                    }
                    if (_configuredSiege != siege)
                    {
                        var strategy = DefaultSiegeStrategies.AllAttackerStrategies
                            .OrderByDescending(s => Campaign.Current.Models.SiegeEventModel.GetSiegeStrategyScore(siege, BattleSideEnum.Attacker, s))
                            .FirstOrDefault();
                        if (strategy == null) { Disable("осада: нет штатной стратегии"); return true; }
                        siege.GetSiegeEventSide(BattleSideEnum.Attacker).SetSiegeStrategy(strategy);
                        _configuredSiege = siege;
                        _operationSettlement = place;
                        AutopilotLog.Write("ОСАДА: строительство машин и обстрел переданы штатной стратегии");
                    }
                    if (siege.BesiegerCamp.IsReadyToBesiege
                        && MenuDriver.CanInvoke("menu_siege_strategies_lead_assault", out _))
                        OperationClick("menu_siege_strategies_lead_assault");
                    else ResumeOperationWait();
                    return true;
                }
                if (menu == "assault_town") return true; // native init starts the mission
                if (menu == "menu_siege_strategies_break_siege")
                { OperationClick("menu_siege_strategies_break_siege_go_on"); return true; }
                if (menu == "menu_settlement_taken_player_leader")
                {
                    OperationClick(MenuDriver.CanInvoke("menu_settlement_taken_show_mercy", out _)
                        ? "menu_settlement_taken_show_mercy" : "menu_settlement_taken_pillage");
                    return true;
                }
                if (menu == "menu_settlement_taken_player_army_member" || menu == "menu_settlement_taken_player_participant"
                    || menu == "siege_aftermath_contextual_summary")
                { OperationClick("menu_settlement_taken_continue"); return true; }
            }
            catch (Exception ex) { Disable("наступательная осада: " + ex.GetType().Name + ": " + ex.Message); return true; }
            return false;
        }
    }
}
