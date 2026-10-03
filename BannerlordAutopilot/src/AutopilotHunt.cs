using System;
using System.Globalization;
using System.Collections.Generic;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordAutopilot
{
    /// <summary>Охота: самому искать рядом бой по силам (23.09.2026).
    ///
    /// Штатная инициатива игры (DefaultMobilePartyAIModel.CalculateInitiativeScoresForEnemy)
    /// рассматривает нападение только при `0.5·(1+a) > 1/a`, то есть при перевесе
    /// a &gt; 1 — никакая «агрессивность» отряда этого порога не сдвигает. Владелец
    /// хочет «безбашенного»: нападать и при 0,8x, потому что зрители любят бои.
    /// Поэтому цель выбирает автопилот, а движение, встречу и сам бой ведёт игра
    /// штатным приказом EngageParty. Силы сторон — оценка движка (EstimatedStrength).</summary>
    public partial class AutopilotBehavior
    {
        /// <summary>Нападаем, если наша сила не меньше этой доли вражеской. Решение владельца 23.09.</summary>
        internal const float HuntMinRatio = 0.8f;
        /// <summary>На армию — только когда сильнее её (владелец 26.09: «добивать, когда
        /// сильнее»): проигрыш армии стоит всего отряда, «безбашенные» 0,8x тут не годятся.</summary>
        internal const float HuntArmyMinRatio = 1f;
        /// <summary>Радиус поиска цели в единицах карты.</summary>
        private const float HuntRadius = 30f;
        /// <summary>Радиус охоты, пока идём на осаду или снабжаемся перед ней:
        /// «рядом можно навалять — навалять», но с маршрута далеко не сворачиваем.</summary>
        private const float HuntRadiusOnCampaign = 10f;
        /// <summary>С какого заполнения на войне осада важнее набора до 90%.</summary>
        internal const float SiegeOverRecruitFill = OffensiveMinFill; // 03.10: было .7 — шли в осаду недобранными
        private string _siegeOverRecruitKey;
        /// <summary>Быстрее нас и дальше этого — не догнать, не гонимся.</summary>
        private const float HuntCatchDistance = 5f;
        /// <summary>Сколько игровых часов держим начатую погоню после последнего
        /// подтверждения цели (25.09): одного шестичасового пересчёта хватает,
        /// чтобы партия не развернулась на миг «не догнать».</summary>
        private const float HuntHoldHours = 6f;
        private double _huntConfirmedHours = double.MinValue;
        private MobileParty _chaseProgressTarget;
        private float _chaseBestDistance;
        private const float ChaseProgressDistance = .5f;
        /// <summary>03.10, владелец: «так высоко ценит бой с грабителями». За 4,7 ч стрима
        /// 46 из 90 нападений охоты — на бандитов при перевесе до x77, 32 погони брошены как
        /// бесполезные. Бандитов трогаем только вплотную, когда они идут на нас, или когда
        /// отряду нечего делать (стоит/патрулирует).</summary>
        internal const float BanditNearDistance = 3f;
        /// <summary>03.10: брошенную погоню не повторяем сутки (было 6 ч. — на ускорении это
        /// секунды, и та же цель бралась снова: цикл «охота → бросили → снова охота»).</summary>
        internal const float ChaseCooldownHours = 24f;
        /// <summary>Куда сейчас едем набирать (ставит ветка «ПОПОЛНЕНИЕ»), чтобы охота не
        /// сбивала поездку за добровольцами.</summary>
        private Settlement _recruitingAt;
        private readonly Dictionary<MobileParty, double> _chaseCooldown = new Dictionary<MobileParty, double>();

        internal void ResetChase()
        {
            _chaseProgressTarget = null;
            _huntConfirmedHours = double.MinValue;
            _chaseCooldown.Clear();
        }

        internal void BeginChase(MobileParty party, MobileParty target)
        {
            if (_chaseProgressTarget == target && CampaignTime.Now.ToHours >= _huntConfirmedHours) return;
            _chaseProgressTarget = target;
            _chaseBestDistance = (float)Math.Sqrt(party.Position.DistanceSquared(target.Position));
            _huntConfirmedHours = CampaignTime.Now.ToHours;
        }

        internal string ChaseRejectedReason(MobileParty party, MobileParty target)
        {
            if (party == null || target == null) return "нет партии для погони";
            string recovery = VoluntaryAttackBlocked(party);
            if (recovery != null) return recovery;
            if (!target.IsActive || !target.IsVisible) return "цель неактивна или скрылась из виду";
            double now = CampaignTime.Now.ToHours;
            float distance = (float)Math.Sqrt(party.Position.DistanceSquared(target.Position));
            // An engaged or slower party can actually be caught again. 03.10: a faster
            // party that merely paused is NOT catchable — it rode off again and the
            // chase was dropped as useless (lots of «расстояние не сокращается» on stream).
            if (target.MapEvent != null || target.Speed < party.Speed)
            {
                _chaseCooldown.Remove(target);
                if (_chaseProgressTarget == target) {
                    _huntConfirmedHours = now;
                    _chaseBestDistance = distance;
                }
                return null;
            }
            if (_chaseCooldown.TryGetValue(target, out double until))
            {
                if (now < until) return "погоня не сокращала расстояние, цель временно пропущена";
                _chaseCooldown.Remove(target);
                if (_chaseProgressTarget == target) _chaseProgressTarget = null;
            }
            bool active = party.DefaultBehavior == AiBehavior.EngageParty && party.TargetParty == target;
            if (active)
            {
                BeginChase(party, target);
                if (_chaseBestDistance - distance >= ChaseProgressDistance)
                {
                    _chaseBestDistance = distance;
                    _huntConfirmedHours = now;
                }
                if (now - _huntConfirmedHours <= HuntHoldHours) return null;
                _chaseCooldown[target] = now + ChaseCooldownHours;
                AutopilotLog.Write("ОХОТА: прекращаем погоню за «" + target.Name
                    + "» — расстояние не сокращается 6 ч.; скорость цели "
                    + target.Speed.ToString("F2", CultureInfo.InvariantCulture) + ", наша "
                    + party.Speed.ToString("F2", CultureInfo.InvariantCulture) + "; повтор не раньше чем через 24 ч.");
                return "цель не медленнее нас, за 6 ч. не сблизились";
            }
            return distance > HuntCatchDistance ? "цель не медленнее нас и далеко для перехвата" : null;
        }

        /// <summary>Почему сейчас не охотимся (null — можно). Это режим
        /// «Восстановление»: после поражения сначала набрать армию, иначе
        /// «безбашенный» автопилот сольёт остатки и зрителям некуда призываться.</summary>
        internal static string HuntBlocked(MobileParty party, bool allowOwnArmy = false)
        {
            if (party?.Party == null || Hero.MainHero == null) return "нет партии/героя";
            string recovery = VoluntaryAttackBlocked(party);
            if (recovery != null) return recovery;
            if (party.Army != null && (!allowOwnArmy || party.Army.LeaderParty != party)) return "в армии решает её лидер";
            int total = party.MemberRoster.TotalManCount;
            int limit = party.Party.PartySizeLimit;
            if (limit > 0 && total < limit * .5f) return "отряд заполнен меньше чем наполовину";
            if (total <= 0) return "нет бойцов";
            return null;
        }

        private bool TryHunt(MobileParty party)
        {
            if (HoldCurrentChase(party, HuntRadiusFor(party))) return true;
            if (_mode != Mode.Apply || !ControlsParty(party) || party.IsCurrentlyAtSea || HuntBlocked(party) != null
                || _fleeFrom != null
                || party.SiegeEvent != null || party.BesiegedSettlement != null
                || party.DefaultBehavior == AiBehavior.RaidSettlement) return false;
            float radius = HuntRadiusFor(party);
            float ours = party.Party.EstimatedStrength;
            if (!(ours > 0f)) return false;
            string errand = HuntErrand(party);
            // 03.10: недобранный отряд (< 85%) сам в бой не лезет — только если враг идёт на нас.
            int sizeLimit = party.Party.PartySizeLimit;
            if (errand == null && sizeLimit > 0 && party.Party.NumberOfAllMembers < sizeLimit * OffensiveMinFill)
                errand = "отряд недобран — сначала набор";
            // Свободен: стоит или патрулирует без дела — тогда и бандиты годятся.
            bool idle = errand == null && (party.DefaultBehavior == AiBehavior.Hold
                || party.DefaultBehavior == AiBehavior.PatrolAroundPoint || party.DefaultBehavior == AiBehavior.None);

            MobileParty best = null;
            float bestScore = 0f, bestRatio = 0f, bestDistance = 0f, bestTheirs = 0f;
            foreach (MobileParty enemy in MobileParty.All)
            {
                // 26.09, владелец: армия не взяла Усанк, отступила — «надо было её
                // добить». Армии раньше не рассматривались вовсе; теперь — через её
                // лидера и с силой всей армии (лидер + присоединённые), а рядовые
                // участники армии целью не бывают.
                bool army = enemy?.Army != null;
                if (enemy == null || enemy == party || !enemy.IsActive || !enemy.IsVisible
                    || enemy.CurrentSettlement != null || enemy.MapEvent != null
                    || army && enemy.Army.LeaderParty != enemy
                    || enemy.IsMilitia || enemy.IsCurrentlyAtSea
                    || !(enemy.IsLordParty || enemy.IsBandit)
                    || enemy.MapFaction == null || party.MapFaction == null
                    || !party.MapFaction.IsAtWarWith(enemy.MapFaction)) continue;
                float distance = (float)Math.Sqrt(party.Position.DistanceSquared(enemy.Position));
                if (distance > radius) continue;
                bool comingAtUs = enemy.TargetParty == party;
                // 03.10: занятый делом (набор, поход на крепость) отряд не сворачивает ради
                // охоты — только если враг сам идёт на нас.
                if (errand != null && !comingAtUs) continue;
                // 03.10, владелец: «а если ему нечего делать — пусть гоняет бандитов».
                if (enemy.IsBandit && !army && distance > BanditNearDistance && !comingAtUs && !idle) continue;
                if (ChaseRejectedReason(party, enemy) != null) continue;
                if (_stuckTarget != null && CampaignTime.Now.ToHours < _stuckTargetUntil
                    && ReferenceEquals(enemy, _stuckTarget)) continue;
                float theirs = army ? enemy.Army.EstimatedStrength : enemy.Party.EstimatedStrength;
                if (!(theirs > 0f) || ours < theirs * (army ? HuntArmyMinRatio : HuntMinRatio)) continue;
                if (InLeftForeignBattle(enemy)) continue;
                // Лорд важнее бандитов, крупный бой важнее мелкого, ближе — лучше.
                float score = (enemy.IsLordParty ? 2f : 1f) * theirs / (1f + distance);
                if (score > bestScore)
                {
                    best = enemy; bestScore = score; bestRatio = ours / theirs; bestDistance = distance; bestTheirs = theirs;
                }
            }
            if (best == null)
            {
                if (!HoldsChase(party, radius)) return false;
                AutopilotLog.Write("ОХОТА: продолжаем погоню за «" + party.TargetParty.Name
                    + "» — цель на миг вне досягаемости, не разворачиваемся");
                return true;
            }
            if (party.DefaultBehavior == AiBehavior.EngageParty && party.TargetParty == best)
            {
                BeginChase(party, best);
                return true;
            }

            string kind = best.Army != null ? "армия, отрядов " + (best.Army.LeaderParty.AttachedParties.Count + 1)
                : best.IsLordParty ? "отряд лорда" : "бандиты";
            AutopilotLog.Write("ОХОТА: атакуем «" + best.Name + "» (" + kind
                + "); силы наши " + ours.ToString("F0", CultureInfo.InvariantCulture)
                + " против " + bestTheirs.ToString("F0", CultureInfo.InvariantCulture)
                + " (x" + bestRatio.ToString("F2", CultureInfo.InvariantCulture) + ", порог x"
                + (best.Army != null ? HuntArmyMinRatio : HuntMinRatio).ToString("F1", CultureInfo.InvariantCulture) + "); до цели "
                + bestDistance.ToString("F1", CultureInfo.InvariantCulture));
            Thoughts.Say(best.Army != null ? "hunt_army" : best.IsLordParty ? "hunt_lord" : "hunt_bandits", best.Name?.ToString(),
                best.Name, bestTheirs.ToString("F0", CultureInfo.InvariantCulture), ours.ToString("F0", CultureInfo.InvariantCulture));
            ApplyDecision(party, new AIBehaviorData(best, AiBehavior.EngageParty,
                MobileParty.NavigationType.Default, false, false, false), 1f);
            BeginChase(party, best);
            return true;
        }

        /// <summary>25.09: погоня срывалась, как только бандиты на миг оказывались
        /// быстрее нас (условие «догоним» выше), — шестичасовой пересчёт уводил в
        /// патруль, а через час охота брала ту же цель снова: до 77 разворотов в час
        /// на стриме. Начатую погоню держим, пока цель жива, враждебна, не в чужом
        /// бою и в радиусе охоты, но не дольше HuntHoldHours после подтверждения.</summary>
        private float HuntRadiusFor(MobileParty party)
            => _preparingCampaign || HeadingToSiegeTarget(party) ? HuntRadiusOnCampaign : HuntRadius;

        /// <summary>Чем отряд занят так, что охота его не сбивает (null — свободен).
        /// 03.10, владелец: цель сменилась 215 раз за 4,7 ч, 87 раз — из-за охоты.</summary>
        private string HuntErrand(MobileParty party)
        {
            if (HeadingToSiegeTarget(party)) return "идём на крепость";
            // 03.10, владелец: «приказ защищать осаждённый феод сбрасывается, проёбываем
            // замки» — в логе DefendSettlement, и через секунду «ОХОТА: атакуем» грабителей
            // в 17 ед. Осаждающих бьёт сама оборона; охота её не перебивает.
            if (party.DefaultBehavior == AiBehavior.DefendSettlement && party.TargetSettlement != null) return "защищаем крепость";
            if (_recruitingAt != null && party.DefaultBehavior == AiBehavior.GoToSettlement
                && party.TargetSettlement == _recruitingAt && NeedsRecruitment(party)) return "едем за добровольцами";
            return null;
        }

        internal bool HoldsChase(MobileParty party, float radius)
        {
            MobileParty target = _combatTarget;
            if (target == null || party.DefaultBehavior != AiBehavior.EngageParty || party.TargetParty != target) return false;
            if (_mode != Mode.Apply || !ControlsParty(party) || _fleeFrom != null
                || party.IsCurrentlyAtSea || party.SiegeEvent != null || party.BesiegedSettlement != null
                || HuntBlocked(party, allowOwnArmy: true) != null) return false;
            if (!target.IsActive || !target.IsVisible || target.CurrentSettlement != null || target.MapEvent != null
                || target.MapFaction == null || party.MapFaction == null
                || !party.MapFaction.IsAtWarWith(target.MapFaction) || InLeftForeignBattle(target)) return false;
            if (ChaseRejectedReason(party, target) != null) return false;
            float theirs = target.Army != null ? target.Army.EstimatedStrength : target.Party.EstimatedStrength;
            if (SiegeAttackerStrength(party) < theirs * (target.Army != null ? HuntArmyMinRatio : HuntMinRatio)) return false;
            return Math.Sqrt(party.Position.DistanceSquared(target.Position)) <= radius;
        }

        private bool HoldCurrentChase(MobileParty party, float radius)
        {
            // A rejected order remains active in the engine until replaced. Stop
            // only our own free-map chase; zero scored alternatives must not mean
            // another six hours of moving after a rejected target.
            var ownedTarget = _combatTarget;
            if (_mode == Mode.Apply && ControlsParty(party) && _fleeFrom == null
                && party.MapEvent == null && party.CurrentSettlement == null
                && party.SiegeEvent == null && party.BesiegedSettlement == null && !party.IsCurrentlyAtSea
                && TaleWorlds.CampaignSystem.Encounters.PlayerEncounter.Current == null
                && ownedTarget != null && party.DefaultBehavior == AiBehavior.EngageParty
                && party.TargetParty == ownedTarget)
            {
                string rejected = ChaseRejectedReason(party, ownedTarget);
                if (rejected != null)
                {
                    party.SetMoveModeHold();
                    _combatTarget = null;
                    AutopilotLog.Write("ОХОТА: приказ погони снят — " + rejected);
                    return false;
                }
            }
            if (!HoldsChase(party, radius)) return false;
            var target = party.TargetParty;
            if (target.IsMoving && target.Speed >= party.Speed)
                AutopilotLog.Write("ОХОТА: продолжаем погоню за «" + target.Name + "» — проверяем сближение, не разворачиваемся");
            return true;
        }

        /// <summary>Вопрос 18.09 «осада или набор до 90%» закрыт владельцем 23.09:
        /// на войне осада. Если отряд заполнен хотя бы на 70%, к походу готов и
        /// крепость по силам есть (тот же поиск, что в часовом расчёте) — набор до
        /// 90% не перебивает поход: сразу считаем цель заново.</summary>
        private bool SiegeBeforeRecruitment(MobileParty party)
        {
            int limit = party.Party.PartySizeLimit;
            if (limit <= 0 || party.Party.NumberOfAllMembers < limit * SiegeOverRecruitFill) return false;
            if (!TryFindSiegeTarget(party, out AIBehaviorData siege, out _)) return false;
            _hoursSinceThink = ThinkPeriodHours;
            string key = (siege.Party as Settlement)?.StringId;
            if (key != _siegeOverRecruitKey)
            {
                _siegeOverRecruitKey = key;
                Thoughts.Say("siege_go", key, (siege.Party as Settlement)?.Name);
                AutopilotLog.Write("ПОХОД: на войне осада важнее набора до 90%: заполнение "
                    + party.Party.NumberOfAllMembers + "/" + limit + ", крепость «" + (siege.Party as Settlement)?.Name + "»");
            }
            return true;
        }
    }
}
