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
        private bool _preparingCampaign;
        private readonly List<MobileParty> _invitedParties = new List<MobileParty>();

        private void MaintainArmy(MobileParty party)
        {
            if (_mode != Mode.Apply || party?.Army == null || !ControlsParty(party) || party.MapEvent != null
                || Hero.MainHero?.IsPrisoner == true || party.Army.Cohesion >= 50) return;
            try
            {
                // ArmyManagementVM buys +10 with this model price. The private AI
                // ThinkAboutCohesionBoost can decline based on objective/randomness.
                var army = party.Army;
                int cost = Campaign.Current.Models.ArmyManagementCalculationModel.GetCohesionBoostInfluenceCost(army, 10);
                if (cost < 0) throw new InvalidOperationException("отрицательная цена сплочённости");
                if (Clan.PlayerClan.Influence < cost)
                {
                    AutopilotLog.Write("АРМИЯ: не хватает влияния для +10 сплочённости; цена " + cost);
                    return;
                }
                float before = army.Cohesion;
                army.BoostCohesionWithInfluence(10f, cost);
                AutopilotLog.Write("АРМИЯ: сплочённость " + before.ToString("F1", CultureInfo.InvariantCulture)
                    + " → " + army.Cohesion.ToString("F1", CultureInfo.InvariantCulture) + "; цена влияния " + cost);
            }
            catch (Exception ex) { Disable("сплочённость армии: " + ex.GetType().Name + ": " + ex.Message); }
        }

        private static bool IsArmyDispersedMenu(MobileParty party) => party != null
            && party.MapEvent == null && MenuDriver.CurrentMenuId == "army_dispersed";

        private bool PollArmyDispersed(MobileParty party)
        {
            if (!IsArmyDispersedMenu(party)) return false;
            if (_mode != Mode.Apply || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return true;
            try { OperationClick("army_dispersed_continue"); }
            catch (Exception ex) { Disable("экран распада армии: " + ex.GetType().Name + ": " + ex.Message); }
            return true; // The native consequence selects the settlement/menu to return to.
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
            // 26.09, владелец: «а армию что он не хочет собирать?» — 147 раз за день «армию
            // собрать не из кого». Список брали только у ИИ игры (CanLordCreateArmy), а он
            // для ИИ-лордов: зовёт отряды, заполненные > 60% и с едой > 15 дней, и как только
            // у королевства есть крепости, требует суммарной силы от 1000 — иначе список пуст.
            // Правитель-игрок зовёт вручную любого своего лорда за влияние (CheckPartyEligibility).
            // Поэтому добавляем своих лордов рядом сами; лорды зрителей с приказом из панели
            // (DoNotMakeNewDecisions) не трогаем — их ведёт зритель.
            var candidates = new List<MobileParty>();
            if (party.ThinkParamsCache.PossibleArmyMembersUponArmyCreation != null)
                candidates.AddRange(party.ThinkParamsCache.PossibleArmyMembersUponArmyCreation);
            int lords = 0, inArmy = 0, ordered = 0, far = 0, busy = 0, refused = 0, costly = 0;
            float r2 = ArmyCallRadius * ArmyCallRadius;
            foreach (var p in MobileParty.All)
            {
                if (p == null || p == party || !p.IsActive || !p.IsLordParty || p.MapFaction != party.MapFaction) continue;
                lords++;
                if (p.Army != null) inArmy++;
                else if (p.Ai != null && p.Ai.DoNotMakeNewDecisions) ordered++;
                else if (p.Position.DistanceSquared(party.Position) > r2) far++;
                else if (p.MapEvent != null || p.SiegeEvent != null || p.BesiegedSettlement != null
                         || p.CurrentSettlement?.SiegeEvent != null || p.IsDisbanding) busy++;
                else candidates.Add(p);
            }
            foreach (var candidate in candidates.Distinct().OrderByDescending(c => c.Party.EstimatedStrength))
            {
                if (candidate == null || candidate == party || !candidate.IsActive || candidate.MapFaction != party.MapFaction) continue;
                if (!model.CheckPartyEligibility(candidate, out _)) { refused++; continue; }
                int cost = model.CalculatePartyInfluenceCost(party, candidate);
                if (cost < 0 || cost > remaining) { costly++; continue; }
                remaining -= cost; result.Add(candidate);
            }
            double day = Math.Floor(CampaignTime.Now.ToHours / 24);
            if (result.Count == 0 && day != _armyEmptyLoggedDay)
            {
                _armyEmptyLoggedDay = day;
                AutopilotLog.Write("АРМИЯ: позвать некого — лордов королевства " + lords + ": уже в армии " + inArmy
                    + ", по приказу зрителя " + ordered + ", дальше " + ArmyCallRadius.ToString("F0", CultureInfo.InvariantCulture) + " " + far
                    + ", в бою/осаде " + busy + ", игра не пускает " + refused + ", не хватает влияния " + costly
                    + " (влияния " + Clan.PlayerClan.Influence.ToString("F0", CultureInfo.InvariantCulture) + ")");
            }
            return result;
        }

        /// <summary>Кого зовём в армию: около двух дней пути (как радиус местной
        /// политики) — дальние не успеют к походу.</summary>
        internal const float ArmyCallRadius = 150f;
        private double _armyEmptyLoggedDay = -1;

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

        /// <summary>25.09, владелец: «сначала качать отряд, нападая на отряды, потом с
        /// очень крепким идти в осады, а то с новичками дают пизды». В тот же вечер
        /// отряд из 320 бойцов, набранных за полчаса, пошёл на «Замок Ремтойл» при
        /// силе 453 против 382 и вернулся одним бойцом, герой в плену. Прежнее
        /// правило пускало на штурм, пока защитники не сильнее нас в 1,5 раза.</summary>
        /// 26.09 владелец: «измени 2 на 1.5, вдруг пойдёт» — за 1,5 ч войны при x2 не
        /// нашлось ни одной крепости. Всё ещё перевес (своих в 1,5 раза больше).
        internal const float SiegeStrengthRatio = 1.5f;
        /// <summary>Средний уровень (тир) бойцов отряда, с которого идём на стены.</summary>
        internal const float SiegeMinAverageTier = 3.5f;
        private string _lastSiegeReadiness;
        private double _siegeMissLoggedDay = double.MinValue;

        internal static float AverageTroopTier(MobileParty party)
        {
            int count = 0; float tiers = 0f;
            foreach (var element in party.MemberRoster.GetTroopRoster())
            {
                if (element.Character == null || element.Character.IsHero || element.Number <= 0) continue;
                count += element.Number;
                tiers += element.Character.Tier * element.Number;
            }
            return count == 0 ? 0f : tiers / count;
        }

        /// <summary>Почему отряд ещё не идёт на осады (null — готов). Пока не готов,
        /// он охотится (AutopilotHunt): бойцы растут в уровне в полевых боях.</summary>
        internal static string SiegeReadiness(MobileParty party)
        {
            float tier = AverageTroopTier(party);
            return tier >= SiegeMinAverageTier ? null
                : "отряд зелёный: средний уровень бойцов " + tier.ToString("F1", CultureInfo.InvariantCulture)
                  + " < " + SiegeMinAverageTier.ToString("F1", CultureInfo.InvariantCulture) + " — качаемся в поле";
        }

        /// <summary>26.09, владелец: «за защиту в осаде он будет строить катапы?» — нет:
        /// ваниль (SetDefaultTactics) ставит командиру-игроку стратегию Custom, при
        /// которой строится только поставленное вручную; ИИ-командиру — лучшую по
        /// оценке. Командуем обороной мы — выбираем, как игра выбрала бы за ИИ, и
        /// дальше машины строит игра.</summary>
        private object _configuredDefense;

        private void EnsureDefenderStrategy(Settlement place)
        {
            var siege = place?.SiegeEvent;
            if (siege == null || _configuredDefense == siege) return;
            if (Campaign.Current.Models.EncounterModel.GetLeaderOfSiegeEvent(siege, BattleSideEnum.Defender) != Hero.MainHero) return;
            var side = siege.GetSiegeEventSide(BattleSideEnum.Defender);
            if (side.SiegeStrategy != DefaultSiegeStrategies.Custom) { _configuredDefense = siege; return; }
            var strategy = DefaultSiegeStrategies.AllDefenderStrategies
                .Where(s => s != DefaultSiegeStrategies.Custom)
                .OrderByDescending(s => Campaign.Current.Models.SiegeEventModel.GetSiegeStrategyScore(siege, BattleSideEnum.Defender, s))
                .FirstOrDefault();
            if (strategy == null) return;
            side.SetSiegeStrategy(strategy);
            _configuredDefense = siege;
            AutopilotLog.Write("ОБОРОНА: командуем обороной «" + place.Name + "» — штатная стратегия " + strategy + ", машины строит игра");
        }

        private static bool EnemyFortress(Settlement place, MobileParty party) =>
            place != null && (place.IsTown || place.IsCastle) && place.MapFaction != null
            && party?.MapFaction != null && party.MapFaction.IsAtWarWith(place.MapFaction);

        // Independent of the native AI: MainParty often receives no siege proposals at all.
        // Count the militia as one strength per soldier and nearby visible enemy parties at
        // full strength. This deliberately overestimates resistance rather than starting
        // an assault on a deceptively empty garrison.
        //
        // 26.09: 25.09 сразу после начала осады нас дважды разбили в поле — 666 и 850
        // врагов при оценке защитников 382 (Ремтойл: 320 бойцов → 1, герой в плену).
        // Крепость зовёт на помощь с начала осады (ваниль: Settlement.LastAttackerParty
        // ставится при старте осады → лорды получают цель «оборона»), а подготовка к
        // штурму длится игровые дни. Прежняя оценка не видела лордов ВНУТРИ крепости
        // (пропускала всех, кто в поселении) и лордов дальше 35 или вне поля зрения.
        // Теперь: лорды в самой крепости и любые вражеские лорды в радиусе
        // SiegeReliefRadius (в поселении или нет, видны или нет) — подмога.
        // 26.09 владелец: «уменьши радиус поиска угрозы до 50» (было 100) — вместе со
        // штурмом по готовности лагеря осада короче, дальняя подмога не успевает.
        private const float SiegeReliefRadius = 50f;
        /// <summary>26.09, владелец: «надо снимать осаду и уходить, если чувствует, что
        /// ему бегут все давать пизды». Пока лагерь готовится к штурму, раз в игровой
        /// час пересчитываем защиту крепости вместе с подошедшей подмогой; перевес
        /// ниже этого — снимаем осаду. Меньше входного SiegeStrengthRatio, чтобы
        /// не снимать осаду от мелкого колебания оценки сразу после начала.</summary>
        internal const float SiegeLiftRatio = 1.2f;
        private double _siegeLiftCheckedHour = double.MinValue;

        private float SiegeDefenderStrength(Settlement place, MobileParty party)
            => Math.Max(SiegeDefenders(place, party, out _), RememberedDefense(place));

        /// <summary>26.09: «Замок Фрактори» с 17:08 до 18:55 осаждали 13 раз и 11 из них
        /// снимали через секунды — подмога 400–960 приходит только после начала осады,
        /// до начала её не видно, а запрет в 12 игровых часов при ускорении длится
        /// минуты. Защиту, которую увидели при снятии осады, помним столько дней и
        /// при выборе крепости берём большее из неё и текущей оценки.</summary>
        internal const double SiegeReliefMemoryHours = 72;
        private readonly Dictionary<Settlement, (float Defense, double Until)> _siegeDefenseSeen
            = new Dictionary<Settlement, (float, double)>();

        private float RememberedDefense(Settlement place) => place != null
            && _siegeDefenseSeen.TryGetValue(place, out var seen) && CampaignTime.Now.ToHours < seen.Until ? seen.Defense : 0f;

        /// <summary>Ближе этого вражеский лорд ударит по лагерю, куда бы ни шёл.</summary>
        private const float SiegeImminentRadius = 15f;

        /// <summary>26.09, владелец: «точно будет убегать от тех, кто идёт к нему, а не
        /// от мимо проходящих?» Идёт к нам — если у него (или у командира его армии)
        /// цель — эта крепость или наш отряд. До начала осады так не бывает: ваниль
        /// зовёт подмогу только со стартом осады, поэтому при выборе крепости считаем
        /// всех лордов в радиусе, а во время осады — только идущих к нам и вплотную.</summary>
        private static bool ComingTo(MobileParty enemy, Settlement place, MobileParty party)
        {
            MobileParty leader = enemy.Army?.LeaderParty ?? enemy;
            MobileParty ours = party.Army?.LeaderParty ?? party;
            return leader.TargetSettlement == place
                || leader.TargetParty == party || leader.TargetParty == ours
                || leader.ShortTermTargetParty == party || leader.ShortTermTargetParty == ours;
        }

        private static float SiegeDefenders(Settlement place, MobileParty party, out string breakdown, bool onlyComing = false)
        {
            float walls = Math.Max(0f, place.Town?.GarrisonParty?.Party.EstimatedStrength ?? 0f)
                + Math.Max(0f, place.Militia);
            float inside = 0f, relief = 0f, nearby = 0f, loneMax = 0f, loneSum = 0f;
            int lone = 0;
            foreach (var enemy in MobileParty.All)
            {
                if (enemy == null || enemy == party || enemy == place.Town?.GarrisonParty
                    || !enemy.IsActive || enemy.IsMilitia || enemy.MapFaction == null
                    || !party.MapFaction.IsAtWarWith(enemy.MapFaction)) continue;
                float strength = Math.Max(0f, enemy.Party.EstimatedStrength);
                float distance2 = enemy.Position.DistanceSquared(place.Position);
                if (enemy.CurrentSettlement == place) { inside += strength; continue; }
                if (onlyComing)
                {
                    // 26.09, владелец «сделай, попробуем»: после снятий осады Фрактори
                    // автопилот поодиночке бил ту же «подмогу 460–660» — 5–8 лордов по
                    // 46–157, каждый слабее нас в 5–19 раз. Армия и все, кто вплотную
                    // к лагерю, ударят вместе — их складываем; одиночки издалека
                    // подходят по одному — считаем только сильнейшего из них.
                    bool close = enemy.Position.DistanceSquared(party.Position) <= SiegeImminentRadius * SiegeImminentRadius;
                    bool coming = enemy.IsLordParty && ComingTo(enemy, place, party) && distance2 <= SiegeReliefRadius * SiegeReliefRadius;
                    bool passing = enemy.IsVisible && enemy.CurrentSettlement == null && distance2 <= 35f * 35f;
                    if (close && (enemy.IsLordParty || passing) || coming && enemy.Army != null) relief += strength;
                    else if (coming || passing) { lone++; loneSum += strength; loneMax = Math.Max(loneMax, strength); }
                    continue;
                }
                if (enemy.IsLordParty && distance2 <= SiegeReliefRadius * SiegeReliefRadius) relief += strength;
                else if (enemy.IsVisible && enemy.CurrentSettlement == null && distance2 <= 35f * 35f) nearby += strength;
            }
            if (onlyComing)
            {
                breakdown = "стены " + walls.ToString("F0", CultureInfo.InvariantCulture)
                    + " + лорды внутри " + inside.ToString("F0", CultureInfo.InvariantCulture)
                    + " + армии и вплотную " + relief.ToString("F0", CultureInfo.InvariantCulture)
                    + " + сильнейший из одиночек " + loneMax.ToString("F0", CultureInfo.InvariantCulture)
                    + " (одиночек " + lone + ", всего " + loneSum.ToString("F0", CultureInfo.InvariantCulture) + ")";
                return walls + inside + relief + loneMax;
            }
            breakdown = "стены " + walls.ToString("F0", CultureInfo.InvariantCulture)
                + " + лорды внутри " + inside.ToString("F0", CultureInfo.InvariantCulture)
                + " + подмога до " + SiegeReliefRadius.ToString("F0", CultureInfo.InvariantCulture) + " "
                + relief.ToString("F0", CultureInfo.InvariantCulture)
                + " + прочие рядом " + nearby.ToString("F0", CultureInfo.InvariantCulture);
            return walls + inside + relief + nearby;
        }

        private string BreakdownOf(Settlement place, MobileParty party)
        {
            float now = SiegeDefenders(place, party, out string breakdown), seen = RememberedDefense(place);
            return " (" + breakdown + (seen > now ? "; при прошлой осаде с подмогой было " + seen.ToString("F0", CultureInfo.InvariantCulture)
                + " — берём это" : "") + ")";
        }

        /// <summary>26.09, владелец «а почему нет»: вражескую крепость уже осаждает союзник
        /// (зритель igotpaws по приказу с 18:16 стоял у Фрактори) — идём к нему в лагерь,
        /// а не пропускаем крепость. Сила союзного лагеря без нас; leader == null — лагерь
        /// не союзный или его нет. Командование после входа перейдёт к стримеру само:
        /// ваниль отдаёт лагерь правителю королевства (DefaultEncounterModel.GetLeaderOfSiegeEvent).</summary>
        private static float AlliedCampStrength(Settlement place, MobileParty party, out MobileParty leader)
        {
            var camp = place?.SiegeEvent?.BesiegerCamp;
            leader = camp?.LeaderParty;
            if (camp == null || leader == null || leader == party || leader.MapFaction == null || party?.MapFaction == null
                || party.MapFaction.IsAtWarWith(leader.MapFaction) || party.BesiegerCamp == camp) { leader = null; return 0f; }
            float sum = 0f;
            foreach (var p in MobileParty.All)
                if (p != null && p != party && p.IsActive && p.BesiegerCamp == camp) sum += Math.Max(0f, p.Party.EstimatedStrength);
            return sum;
        }

        private static float SiegeAttackerStrength(MobileParty party)
        {
            // В лагере (своём или союзном) бьётся весь лагерь, а не только мы.
            var camp = party.BesiegerCamp;
            if (camp != null)
            {
                float all = 0f;
                foreach (var p in MobileParty.All)
                    if (p != null && p.IsActive && p.BesiegerCamp == camp) all += Math.Max(0f, p.Party.EstimatedStrength);
                if (all > 0f) return all;
            }
            float strength = Math.Max(0f, party.Party.EstimatedStrength);
            if (party.Army?.LeaderParty == party)
                foreach (var attached in party.AttachedParties)
                    if (attached != null && attached != party && attached.Army == party.Army)
                        strength += Math.Max(0f, attached.Party.EstimatedStrength);
            return strength;
        }

        // Geographic frontier approximation: one of the three closest forts to a
        // clan holding, at most 100 map units away. No route/path claim is made.
        private static string SiegeBorderRejection(MobileParty party, Settlement target)
        {
            if (target == null || party == null) return "нет цели";
            var homes = Clan.PlayerClan?.Fiefs.Select(f => f.Settlement)
                .Where(s => s != null && (s.IsTown || s.IsCastle) && s.MapFaction == party.MapFaction).Distinct().ToList()
                ?? new List<Settlement>();
            if (homes.Count == 0)
                return party.Position.DistanceSquared(target.Position) <= 100f * 100f
                    ? null : "первый феод слишком далеко от отряда (более 100 единиц карты)";
            foreach (var home in homes)
            {
                float distance = home.Position.DistanceSquared(target.Position);
                if (distance > 100f * 100f) continue;
                int closer = Settlement.All.Count(s => s != home && s != target && (s.IsTown || s.IsCastle)
                    && home.Position.DistanceSquared(s.Position) < distance);
                if (closer < 3) return null;
            }
            return "не приграничный феод: вне трёх ближайших крепостей в радиусе 100 от своих владений";
        }

        /// <summary>24.09: 18.09 отказались от «Замка Астер» по силам и через 3 с взяли
        /// его снова — отряд защитников вышел из круга подсчёта (35), цифра опять
        /// прошла под порог 1,5x, а следом армия 267 → 1. Отказ по силам держим
        /// 12 игровых часов.</summary>
        private const double SiegeRejectionHours = 12;
        private readonly Dictionary<Settlement, double> _siegeRejectedUntil = new Dictionary<Settlement, double>();

        private bool NoteSiegeRejection(Settlement place, string rejection)
        {
            if (place == null || rejection == null || !rejection.StartsWith("защитники", StringComparison.Ordinal)) return false;
            _siegeRejectedUntil[place] = CampaignTime.Now.ToHours + SiegeRejectionHours;
            AutopilotLog.Write("ПОХОД: «" + place.Name + "» не берём " + SiegeRejectionHours.ToString("F0", CultureInfo.InvariantCulture)
                + " игровых часов — отказались по силам");
            return true;
        }

        /// <summary>Отказались по силам — не идём дальше к этой крепости. Прежде
        /// «цель больше не предложена» оставляла партию в пути к ней же.</summary>
        private void StopSiegeMarch(MobileParty party)
        {
            if (_mode != Mode.Apply || !IsOnFreeMap(party)) return;
            party.SetMoveModeHold();
            _offensiveSiege = null; _lastTargetKey = null;
            _hoursSinceThink = ThinkPeriodHours;
            AutopilotLog.Write("ПОХОД: к отвергнутой крепости не идём, партия остановлена до нового решения");
        }

        private bool SiegeRecentlyRejected(Settlement place) => place != null
            && _siegeRejectedUntil.TryGetValue(place, out double until) && CampaignTime.Now.ToHours < until;

        private bool TryFindSiegeTarget(MobileParty party, out AIBehaviorData target, out float score)
        {
            target = AIBehaviorData.Invalid;
            score = 0f;
            if (party?.MapFaction == null || !ControlsParty(party) || PreparationNeeded(party) != null)
                return false;
            string readiness = SiegeReadiness(party);
            // Пишем только смену «готов / не готов», а не каждый пересчёт уровня.
            if ((readiness == null) != (_lastSiegeReadiness == null))
                AutopilotLog.Write(readiness == null ? "ПОХОД: отряд окреп — осады разрешены" : "ПОХОД: осад пока нет — " + readiness);
            _lastSiegeReadiness = readiness;
            if (readiness != null) return false;
            float own = SiegeAttackerStrength(party);
            var allies = party.Army == null ? AffordableArmyMembers(party) : new List<MobileParty>();
            float assembled = own + allies.Sum(p => Math.Max(0f, p.Party.EstimatedStrength));
            Settlement best = null;
            bool gather = false;
            // 26.09: после «отряд окреп» за 1,5 ч войны осад не было ни одной, а журнал
            // молчал почему. Раз в игровой день пишем крепость, ближе всех к порогу.
            Settlement closest = null; float closestDefenders = 0f; int fortresses = 0, borderSkipped = 0;
            MobileParty bestCampLeader = null; float bestCamp = 0f, bestDefenders = 0f;
            foreach (var place in Settlement.All)
            {
                if (!EnemyFortress(place, party) || place.IsUnderRaid || SiegeRecentlyRejected(place)) continue;
                MobileParty campLeader = null;
                float camp = place.IsUnderSiege ? AlliedCampStrength(place, party, out campLeader) : 0f;
                if (place.IsUnderSiege && campLeader == null) continue;
                fortresses++;
                if (SiegeBorderRejection(party, place) != null) { borderSkipped++; continue; }
                float defenders = SiegeDefenderStrength(place, party);
                bool needsArmy = own + camp < defenders * SiegeStrengthRatio;
                if (needsArmy && (allies.Count == 0 || assembled + camp < defenders * SiegeStrengthRatio))
                {
                    if (closest == null || defenders < closestDefenders) { closest = place; closestDefenders = defenders; }
                    continue;
                }
                float distance = (float)Math.Sqrt(Math.Max(0f, party.Position.DistanceSquared(place.Position)));
                float candidateScore = 5f + Math.Min(3f, ((needsArmy ? assembled : own) + camp) / Math.Max(1f, defenders))
                    - distance / 200f;
                if (candidateScore <= score) continue;
                best = place;
                gather = needsArmy;
                score = candidateScore;
                bestCampLeader = campLeader; bestCamp = camp; bestDefenders = defenders;
            }
            if (best == null)
            {
                double day = Math.Floor(CampaignTime.Now.ToHours / 24);
                if (fortresses > 0 && day != _siegeMissLoggedDay)
                {
                    _siegeMissLoggedDay = day;
                    AutopilotLog.Write("ПОХОД: крепостей по силам нет (вражеских " + fortresses + ", вне досягаемости " + borderSkipped + ")"
                        + (closest == null ? "" : "; ближе всех к порогу «" + closest.Name + "»: защитники "
                            + closestDefenders.ToString("F0", CultureInfo.InvariantCulture) + ", надо x"
                            + SiegeStrengthRatio.ToString("0.#", CultureInfo.InvariantCulture) + " = "
                            + (closestDefenders * SiegeStrengthRatio).ToString("F0", CultureInfo.InvariantCulture)
                            + ", у нас " + own.ToString("F0", CultureInfo.InvariantCulture)
                            + (allies.Count > 0 ? ", с армией " + assembled.ToString("F0", CultureInfo.InvariantCulture) : ", армию собрать не из кого")
                            + BreakdownOf(closest, party)));
                }
                return false;
            }
            if (bestCampLeader != null && _alliedSiegeNoted != best)
            {
                _alliedSiegeNoted = best;
                StreamStatus.Note("Идём на помощь к осаде «" + best.Name + "»");
                AutopilotLog.Write("ПОХОД: присоединяемся к осаде «" + best.Name + "» — лагерь «" + bestCampLeader.Name
                    + "» " + bestCamp.ToString("F0", CultureInfo.InvariantCulture) + " + мы " + own.ToString("F0", CultureInfo.InvariantCulture)
                    + " против защитников " + bestDefenders.ToString("F0", CultureInfo.InvariantCulture));
            }
            target = new AIBehaviorData(best, AiBehavior.BesiegeSettlement,
                MobileParty.NavigationType.Default, gather, false, false);
            return true;
        }

        private Settlement _alliedSiegeNoted;

        private string SiegeTargetRejection(MobileParty party, Settlement place)
        {
            if (!EnemyFortress(place, party)) return "крепость больше не принадлежит врагу";
            string border = SiegeBorderRejection(party, place);
            if (border != null) return border;
            float camp = AlliedCampStrength(place, party, out MobileParty campLeader);
            if (place.IsUnderSiege && campLeader == null) return "крепость уже осаждают";
            if (place.IsUnderRaid) return "поселение под налётом";
            string preparation = PreparationNeeded(party);
            if (preparation != null) return "поход не готов: " + preparation;
            string readiness = SiegeReadiness(party);
            if (readiness != null) return readiness;
            float defenders = SiegeDefenderStrength(place, party);
            float own = SiegeAttackerStrength(party) + camp;
            if (own >= defenders * SiegeStrengthRatio) return null;
            var allies = party.Army == null ? AffordableArmyMembers(party) : new List<MobileParty>();
            float assembled = own + allies.Sum(p => Math.Max(0f, p.Party.EstimatedStrength));
            if (allies.Count > 0 && assembled >= defenders * SiegeStrengthRatio) return null;
            return "защитники " + defenders.ToString("F1", CultureInfo.InvariantCulture)
                + " — нужен перевес x" + SiegeStrengthRatio.ToString("0.#", CultureInfo.InvariantCulture)
                + ", надо " + (defenders * SiegeStrengthRatio).ToString("F1", CultureInfo.InvariantCulture)
                + " (наша сила " + own.ToString("F1", CultureInfo.InvariantCulture)
                + ", доступная армия " + assembled.ToString("F1", CultureInfo.InvariantCulture) + ")"
                + BreakdownOf(place, party);
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
            // В союзном лагере командует правитель — стример; если командир всё же
            // другой, ждём его штурма, как в чужой армии.
            bool participating = siege != null && (party.Army?.LeaderParty != null
                && siege.BesiegerCamp?.LeaderParty == party.Army.LeaderParty
                || siege.BesiegerCamp != null && party.BesiegerCamp == siege.BesiegerCamp);
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
                // After loot the encounter is gone, but the native siege camp
                // remains and asks whether to resume preparation or leave.
                if (menu == "continue_siege_after_attack" && commanded && place == _offensiveSiege)
                {
                    string needed = PreparationNeeded(party);
                    _operationSettlement = place;
                    AutopilotLog.Write("ОСАДА ПОСЛЕ БОЯ: " + (needed == null
                        ? "возвращаемся к подготовке" : "снимаем осаду для восстановления: " + needed));
                    OperationClick(needed == null ? "continue_siege" : "leave_siege");
                    return true;
                }
                if (participating && !commanded && menu == "menu_siege_strategies")
                {
                    _operationSettlement = place;
                    ResumeOperationWait(); return true;
                }
                if (menu == "encounter" && IsOwnedOperationBattle(party))
                { OperationClick("attack"); return true; }
                if (menu == "join_siege_event" && approaching)
                {
                    AlliedCampStrength(place, party, out MobileParty campLeader);
                    if (campLeader == null) return false;
                    string needed = PreparationNeeded(party);
                    string joinWhy = null;
                    if (needed == null && MenuDriver.CanInvoke("join_siege_event", out joinWhy))
                    {
                        _operationSettlement = place;
                        AutopilotLog.Write("ОСАДА: входим в лагерь «" + campLeader.Name + "» у «" + place.Name + "»");
                        StreamStatus.Note("Присоединяемся к осаде «" + place.Name + "»");
                        OperationClick("join_siege_event"); return true;
                    }
                    _siegeRejectedUntil[place] = CampaignTime.Now.ToHours + SiegeRejectionHours;
                    _offensiveSiege = null;
                    AutopilotLog.Write("ОСАДА: в лагерь у «" + place.Name + "» не входим — "
                        + (needed != null ? "требуется восстановление: " + needed : joinWhy)
                        + "; не возвращаемся " + SiegeRejectionHours.ToString("F0", CultureInfo.InvariantCulture) + " игровых часов");
                    OperationClick("join_encounter_leave"); return true;
                }
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
                    StreamStatus.Note("Начинаем осаду «" + place.Name + "»");
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
                    // 26.09: проверка ниже (одна армия от FleeRatio) с 25.09 требует перевеса
                    // врага x5 — подмога x1,5–2 её не проходила, и 25.09 лагерь дважды
                    // разбили в поле (666 и 850 врагов). Считаем всю защиту: стены, лордов
                    // внутри и подмогу в радиусе — при бое у лагеря гарнизон выходит к ней.
                    double hour = Math.Floor(CampaignTime.Now.ToHours);
                    if (hour != _siegeLiftCheckedHour)
                    {
                        _siegeLiftCheckedHour = hour;
                        float defendersNow = SiegeDefenders(place, party, out string breakdown, onlyComing: true);
                        float ownNow = SiegeAttackerStrength(party);
                        if (ownNow < defendersNow * SiegeLiftRatio)
                        {
                            string why = "защитники с подмогой " + defendersNow.ToString("F0", CultureInfo.InvariantCulture)
                                + ", наша сила " + ownNow.ToString("F0", CultureInfo.InvariantCulture)
                                + " — перевес ниже x" + SiegeLiftRatio.ToString("0.#", CultureInfo.InvariantCulture)
                                + " (" + breakdown + ")";
                            AutopilotLog.Write("ПОХОД: снимаем осаду «" + place.Name + "» до удара — " + why);
                            NoteSiegeRejection(place, "защитники: " + why);
                            _siegeDefenseSeen[place] = (defendersNow, CampaignTime.Now.ToHours + SiegeReliefMemoryHours);
                            StreamStatus.Note("К крепости идёт подмога — снимаем осаду");
                            OperationClick("menu_siege_strategies_leave"); return true;
                        }
                    }
                    // 24.09: к лагерю идёт армия от 2x — снимаем осаду до удара, дальше
                    // отход на карте (18.09 и 21.09 такой бой стоил армии ~270 → 1).
                    var relief = FindThreat(party, party.Position, FleeDetectRadius, false, FleeRatio);
                    if (relief != null)
                    {
                        AutopilotLog.Write("ПОХОД: к лагерю идёт «" + relief.Name + "» сильнее нас от x"
                            + FleeRatio.ToString("F0", CultureInfo.InvariantCulture) + " — снимаем осаду до удара");
                        StreamStatus.Note("К лагерю идёт армия сильнее — снимаем осаду");
                        OperationClick("menu_siege_strategies_leave"); return true;
                    }
                    if (_configuredSiege != siege || siege.GetSiegeEventSide(BattleSideEnum.Attacker).SiegeStrategy == DefaultSiegeStrategies.Custom)
                    {
                        var strategy = DefaultSiegeStrategies.AllAttackerStrategies
                            // Native scoring deliberately prefers manual control (9000) for the player.
                            .Where(s => s != DefaultSiegeStrategies.Custom)
                            .OrderByDescending(s => Campaign.Current.Models.SiegeEventModel.GetSiegeStrategyScore(siege, BattleSideEnum.Attacker, s))
                            .FirstOrDefault();
                        if (strategy == null) { Disable("осада: нет штатной стратегии"); return true; }
                        siege.GetSiegeEventSide(BattleSideEnum.Attacker).SetSiegeStrategy(strategy);
                        _configuredSiege = siege;
                        _operationSettlement = place;
                        AutopilotLog.Write("ОСАДА: выбрана автоматическая стратегия " + strategy + "; штурм сразу, как готов лагерь (машины не ждём)");
                    }
                    // 26.09, владелец: «научить не тянуть и начинать только с осадным
                    // лагерем, без катапульт и прочих построек». Раньше ждали
                    // IsReadyToBesiege — это условие ИИ-лордов: лагерь готов И случайный
                    // бросок «штурм логичен», растущий с тараном/башней/машинами (ваниль
                    // BesiegerCamp.StartingAssaultOnBesiegedSettlementIsLogical), — лагерь
                    // стоял днями и подмога успевала. Игроку кнопка «Возглавить штурм»
                    // доступна, как только готов лагерь (IsPreparationComplete) — штурмуем тогда.
                    if (siege.BesiegerCamp.IsPreparationComplete
                        && MenuDriver.CanInvoke("menu_siege_strategies_lead_assault", out _))
                    {
                        AutopilotLog.Write("ОСАДА: лагерь готов — штурм, машины не ждём");
                        OperationClick("menu_siege_strategies_lead_assault");
                    }
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
