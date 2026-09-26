using System;
using System.Globalization;
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
        internal const float SiegeOverRecruitFill = .7f;
        private string _siegeOverRecruitKey;
        /// <summary>Быстрее нас и дальше этого — не догнать, не гонимся.</summary>
        private const float HuntCatchDistance = 5f;
        /// <summary>Сколько игровых часов держим начатую погоню после последнего
        /// подтверждения цели (25.09): одного шестичасового пересчёта хватает,
        /// чтобы партия не развернулась на миг «не догнать».</summary>
        private const float HuntHoldHours = 6f;
        private double _huntConfirmedHours = double.MinValue;

        /// <summary>Почему сейчас не охотимся (null — можно). Это режим
        /// «Восстановление»: после поражения сначала набрать армию, иначе
        /// «безбашенный» автопилот сольёт остатки и зрителям некуда призываться.</summary>
        internal static string HuntBlocked(MobileParty party)
        {
            if (party?.Party == null || Hero.MainHero == null) return "нет партии/героя";
            if (Hero.MainHero.IsWounded) return "герой ранен";
            if (party.Army != null) return "в армии решает её лидер";
            int total = party.MemberRoster.TotalManCount;
            int healthy = total - party.MemberRoster.TotalWounded;
            int limit = party.Party.PartySizeLimit;
            if (limit > 0 && total < limit * .5f) return "отряд заполнен меньше чем наполовину";
            if (total <= 0 || healthy < total * .5f) return "боеспособны меньше половины";
            return null;
        }

        private bool TryHunt(MobileParty party)
        {
            if (_mode != Mode.Apply || !ControlsParty(party) || party.IsCurrentlyAtSea || HuntBlocked(party) != null
                || _fleeFrom != null
                || party.SiegeEvent != null || party.BesiegedSettlement != null
                || party.DefaultBehavior == AiBehavior.RaidSettlement) return false;
            float radius = HuntRadiusFor(party);
            float ours = party.Party.EstimatedStrength;
            if (!(ours > 0f)) return false;

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
                if (enemy.IsMoving && enemy.Speed > party.Speed && distance > HuntCatchDistance) continue;
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
                _huntConfirmedHours = CampaignTime.Now.ToHours;
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
            StreamStatus.Note("Нападаем на «" + best.Name + "» (" + kind + ")");
            ApplyDecision(party, new AIBehaviorData(best, AiBehavior.EngageParty,
                MobileParty.NavigationType.Default, false, false, false), 1f);
            _huntConfirmedHours = CampaignTime.Now.ToHours;
            return true;
        }

        /// <summary>25.09: погоня срывалась, как только бандиты на миг оказывались
        /// быстрее нас (условие «догоним» выше), — шестичасовой пересчёт уводил в
        /// патруль, а через час охота брала ту же цель снова: до 77 разворотов в час
        /// на стриме. Начатую погоню держим, пока цель жива, враждебна, не в чужом
        /// бою и в радиусе охоты, но не дольше HuntHoldHours после подтверждения.</summary>
        private float HuntRadiusFor(MobileParty party)
            => _preparingCampaign || HeadingToSiegeTarget(party) ? HuntRadiusOnCampaign : HuntRadius;

        internal bool HoldsChase(MobileParty party, float radius)
        {
            MobileParty target = _combatTarget;
            if (target == null || party.DefaultBehavior != AiBehavior.EngageParty || party.TargetParty != target) return false;
            if (_mode != Mode.Apply || !ControlsParty(party) || _fleeFrom != null || HuntBlocked(party) != null) return false;
            if (CampaignTime.Now.ToHours - _huntConfirmedHours > HuntHoldHours) return false;
            if (!target.IsActive || target.CurrentSettlement != null || target.MapEvent != null
                || target.MapFaction == null || party.MapFaction == null
                || !party.MapFaction.IsAtWarWith(target.MapFaction) || InLeftForeignBattle(target)) return false;
            return Math.Sqrt(party.Position.DistanceSquared(target.Position)) <= radius;
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
                StreamStatus.Note("Идём на осаду «" + (siege.Party as Settlement)?.Name + "»");
                AutopilotLog.Write("ПОХОД: на войне осада важнее набора до 90%: заполнение "
                    + party.Party.NumberOfAllMembers + "/" + limit + ", крепость «" + (siege.Party as Settlement)?.Name + "»");
            }
            return true;
        }
    }
}
