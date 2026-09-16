using System;
using System.Globalization;
using System.Linq;
using TaleWorlds.CampaignSystem;
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
        private SiegeEvent _configuredSiege;

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

        private bool PollOffensiveSiege(MobileParty party)
        {
            if (_mode != Mode.Apply || party == null || party.IsCurrentlyAtSea) return false;
            string menu = MenuDriver.CurrentMenuId;
            var siege = party.SiegeEvent;
            var place = siege?.BesiegedSettlement ?? EncounterPlace(party);
            bool commanded = siege?.BesiegerCamp.LeaderParty == party;
            bool approaching = siege == null && party.DefaultBehavior == AiBehavior.BesiegeSettlement
                && party.TargetSettlement == place && EnemyFortress(place, party);
            if (_offensiveSiege == null && (commanded || approaching)) _offensiveSiege = place;
            if (_offensiveSiege == null) return false;
            if (IsOnFreeMap(party) && siege == null) { _offensiveSiege = null; _configuredSiege = null; return false; }
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
                if (menu == "menu_settlement_taken_player_army_member" || menu == "menu_settlement_taken_player_participant"
                    || menu == "siege_aftermath_contextual_summary")
                { OperationClick("menu_settlement_taken_continue"); return true; }
            }
            catch (Exception ex) { Disable("наступательная осада: " + ex.GetType().Name + ": " + ex.Message); return true; }
            return false;
        }
    }
}
