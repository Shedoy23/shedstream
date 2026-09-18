using System;
using System.Globalization;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
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
        private bool _preparingCampaign;
        private readonly List<MobileParty> _invitedParties = new List<MobileParty>();
        private static readonly MethodInfo NativeCohesionThink = typeof(Army).GetMethod("ThinkAboutCohesionBoost", BindingFlags.Instance | BindingFlags.NonPublic);

        private void MaintainArmy(MobileParty party)
        {
            if (_mode != Mode.Apply || party?.Army == null || !ControlsParty(party) || party.MapEvent != null
                || Hero.MainHero?.IsPrisoner == true || party.Army.Cohesion >= 50) return;
            try
            {
                if (NativeCohesionThink == null) throw new MissingMethodException("Army.ThinkAboutCohesionBoost");
                NativeCohesionThink.Invoke(party.Army, null);
                AutopilotLog.Write("АРМИЯ: штатная проверка сплочённости, сейчас " + party.Army.Cohesion.ToString("F0", CultureInfo.InvariantCulture));
            }
            catch (Exception ex) { Disable("сплочённость армии: " + ex.GetType().Name + ": " + ex.Message); }
        }

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
            if (_invitedParties.Count == 0)
            {
                DisbandArmyAction.ApplyByUnknownReason(party.Army);
                AutopilotLog.Write("АРМИЯ: приглашения потеряли доступность, пустая армия распущена");
                return true;
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
                string invalid = WhyNotApplicable(_armyObjective);
                if (invalid == null) ApplyDecision(party, _armyObjective, _armyObjectiveScore);
                else AutopilotLog.Write("АРМИЯ: цель после сбора требует пересчёта: " + invalid);
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
            float food = party.TotalFoodAtInventory;
            int total = party.MemberRoster.TotalManCount;
            int wounded = party.MemberRoster.TotalWounded;
            foreach (var attached in party.AttachedParties)
            {
                if (attached == null || attached == party || attached.Army != party.Army) continue;
                food += attached.TotalFoodAtInventory;
                consumption += Math.Max(0, -attached.FoodChange);
                total += attached.MemberRoster.TotalManCount;
                wounded += attached.MemberRoster.TotalWounded;
            }
            if (float.IsNaN(consumption) || float.IsInfinity(consumption)) return "неизвестен расход еды армии";
            if (consumption > 0 && food < consumption * 7f) return "еда меньше чем на 7 дней";
            if (Hero.MainHero.Gold < Math.Max(0, party.TotalWage) * 7f) return "золото меньше 7 дней жалования";
            if (total <= 0 || total - wounded < total * .7f) return "боеспособны меньше 70% отряда";
            if (Hero.MainHero.IsWounded) return "герой ранен";
            return null;
        }

        private static bool EnemyFortress(Settlement place, MobileParty party) =>
            place != null && (place.IsTown || place.IsCastle) && place.MapFaction != null
            && party?.MapFaction != null && party.MapFaction.IsAtWarWith(place.MapFaction);

        // Independent of the native AI: MainParty often receives no siege proposals at all.
        // Count the militia as one strength per soldier and nearby visible enemy parties at
        // full strength. This deliberately overestimates resistance rather than starting
        // an assault on a deceptively empty garrison.
        private static float SiegeDefenderStrength(Settlement place, MobileParty party)
        {
            float strength = Math.Max(0f, place.Town?.GarrisonParty?.Party.EstimatedStrength ?? 0f)
                + Math.Max(0f, place.Militia);
            foreach (var enemy in MobileParty.All)
            {
                if (enemy == null || enemy == party || enemy == place.Town?.GarrisonParty
                    || !enemy.IsActive || !enemy.IsVisible || enemy.IsMilitia
                    || enemy.CurrentSettlement != null || enemy.MapFaction == null
                    || !party.MapFaction.IsAtWarWith(enemy.MapFaction)
                    || enemy.Position.DistanceSquared(place.Position) > 35f * 35f) continue;
                strength += Math.Max(0f, enemy.Party.EstimatedStrength);
            }
            return strength;
        }

        private static float SiegeAttackerStrength(MobileParty party)
        {
            float strength = Math.Max(0f, party.Party.EstimatedStrength);
            if (party.Army?.LeaderParty == party)
                foreach (var attached in party.AttachedParties)
                    if (attached != null && attached != party && attached.Army == party.Army)
                        strength += Math.Max(0f, attached.Party.EstimatedStrength);
            return strength;
        }

        private bool TryFindSiegeTarget(MobileParty party, out AIBehaviorData target, out float score)
        {
            target = AIBehaviorData.Invalid;
            score = 0f;
            if (party?.MapFaction == null || !ControlsParty(party) || PreparationNeeded(party) != null)
                return false;
            float own = SiegeAttackerStrength(party);
            var allies = party.Army == null ? AffordableArmyMembers(party) : new List<MobileParty>();
            float assembled = own + allies.Sum(p => Math.Max(0f, p.Party.EstimatedStrength));
            Settlement best = null;
            bool gather = false;
            foreach (var place in Settlement.All)
            {
                if (!EnemyFortress(place, party) || place.IsUnderSiege || place.IsUnderRaid) continue;
                float defenders = SiegeDefenderStrength(place, party);
                bool needsArmy = defenders > own * 1.5f;
                if (needsArmy && (allies.Count == 0 || defenders > assembled * 1.5f)) continue;
                float distance = (float)Math.Sqrt(Math.Max(0f, party.Position.DistanceSquared(place.Position)));
                float candidateScore = 5f + Math.Min(3f, (needsArmy ? assembled : own) / Math.Max(1f, defenders))
                    - distance / 200f;
                if (candidateScore <= score) continue;
                best = place;
                gather = needsArmy;
                score = candidateScore;
            }
            if (best == null) return false;
            target = new AIBehaviorData(best, AiBehavior.BesiegeSettlement,
                MobileParty.NavigationType.Default, gather, false, false);
            return true;
        }

        private string SiegeTargetRejection(MobileParty party, Settlement place)
        {
            if (!EnemyFortress(place, party)) return "крепость больше не принадлежит врагу";
            if (place.IsUnderSiege) return "крепость уже осаждают";
            if (place.IsUnderRaid) return "поселение под налётом";
            string preparation = PreparationNeeded(party);
            if (preparation != null) return "поход не готов: " + preparation;
            float defenders = SiegeDefenderStrength(place, party);
            float own = SiegeAttackerStrength(party);
            if (defenders <= own * 1.5f) return null;
            var allies = party.Army == null ? AffordableArmyMembers(party) : new List<MobileParty>();
            float assembled = own + allies.Sum(p => Math.Max(0f, p.Party.EstimatedStrength));
            if (allies.Count > 0 && defenders <= assembled * 1.5f) return null;
            return "защитники " + defenders.ToString("F1", CultureInfo.InvariantCulture)
                + " > предел " + (assembled * 1.5f).ToString("F1", CultureInfo.InvariantCulture)
                + " (наша сила " + own.ToString("F1", CultureInfo.InvariantCulture)
                + ", доступная армия " + assembled.ToString("F1", CultureInfo.InvariantCulture) + ")";
        }

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
            // Native raid completion can clear PlayerEncounter before opening its result menu.
            bool raidResult = menu == "village_player_raid_ended" || menu == "village_raid_diplomatically_ended"
                || menu == "village_raid_ended_leaded_by_someone_else" || menu == "village_looted";
            if (place != _raidSettlement && !raidResult) return false;
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
                        if (TrySendTroopsWhenWounded()) return true;
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
            bool commanded = siege?.BesiegerCamp?.LeaderParty == party;
            bool participating = siege != null && party.Army?.LeaderParty != null
                && siege.BesiegerCamp?.LeaderParty == party.Army.LeaderParty;
            bool approaching = siege == null && EnemyFortress(place, party)
                && (_offensiveSiege == place || (party.DefaultBehavior == AiBehavior.BesiegeSettlement && party.TargetSettlement == place));
            if (_offensiveSiege == null && (commanded || approaching || participating)) _offensiveSiege = place;
            if (_offensiveSiege == null) return false;
            if (IsOnFreeMap(party) && siege == null && menu == null)
            {
                // Пока едем к выбранной крепости обычным приказом, намерение осадить
                // сохраняется: иначе оно терялось бы на первом же опросе.
                bool heading = party.TargetSettlement == _offensiveSiege
                               && (party.DefaultBehavior == AiBehavior.BesiegeSettlement
                                   || party.DefaultBehavior == AiBehavior.GoToSettlement);
                if (!heading) { _offensiveSiege = null; _configuredSiege = null; }
                return false;
            }
            if (!MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return true;
            try
            {
                if (participating && !commanded && menu == "menu_siege_strategies")
                {
                    _operationSettlement = place;
                    ResumeOperationWait(); return true;
                }
                if (menu == "encounter" && IsOwnedOperationBattle(party))
                { OperationClick("attack"); return true; }
                if (menu == "town_outside" || menu == "castle_outside")
                {
                    if (!approaching) return false;
                    string needed = PreparationNeeded(party);
                    if (needed != null)
                    {
                        AutopilotLog.Write("ПОХОД: перед осадой требуется восстановление: " + needed);
                        OperationClick("town_outside_leave"); return true;
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
