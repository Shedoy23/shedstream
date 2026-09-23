using System;
using System.Globalization;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;

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
        /// <summary>Радиус поиска цели в единицах карты.</summary>
        private const float HuntRadius = 30f;
        /// <summary>Быстрее нас и дальше этого — не догнать, не гонимся.</summary>
        private const float HuntCatchDistance = 5f;

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
                || _preparingCampaign || HeadingToSiegeTarget(party)
                || party.DefaultBehavior == AiBehavior.RaidSettlement
                || party.DefaultBehavior == AiBehavior.BesiegeSettlement) return false;
            float ours = party.Party.EstimatedStrength;
            if (!(ours > 0f)) return false;

            MobileParty best = null;
            float bestScore = 0f, bestRatio = 0f, bestDistance = 0f;
            foreach (MobileParty enemy in MobileParty.All)
            {
                if (enemy == null || enemy == party || !enemy.IsActive || !enemy.IsVisible
                    || enemy.CurrentSettlement != null || enemy.MapEvent != null || enemy.Army != null
                    || enemy.IsMilitia || enemy.IsCurrentlyAtSea
                    || !(enemy.IsLordParty || enemy.IsBandit)
                    || enemy.MapFaction == null || party.MapFaction == null
                    || !party.MapFaction.IsAtWarWith(enemy.MapFaction)) continue;
                float distance = (float)Math.Sqrt(party.Position.DistanceSquared(enemy.Position));
                if (distance > HuntRadius) continue;
                if (enemy.IsMoving && enemy.Speed > party.Speed && distance > HuntCatchDistance) continue;
                if (_stuckTarget != null && CampaignTime.Now.ToHours < _stuckTargetUntil
                    && ReferenceEquals(enemy, _stuckTarget)) continue;
                float theirs = enemy.Party.EstimatedStrength;
                if (!(theirs > 0f) || ours < theirs * HuntMinRatio) continue;
                if (InLeftForeignBattle(enemy)) continue;
                // Лорд важнее бандитов, крупный бой важнее мелкого, ближе — лучше.
                float score = (enemy.IsLordParty ? 2f : 1f) * theirs / (1f + distance);
                if (score > bestScore)
                {
                    best = enemy; bestScore = score; bestRatio = ours / theirs; bestDistance = distance;
                }
            }
            if (best == null) return false;
            if (party.DefaultBehavior == AiBehavior.EngageParty && party.TargetParty == best) return true;

            AutopilotLog.Write("ОХОТА: атакуем «" + best.Name + "» (" + (best.IsLordParty ? "отряд лорда" : "бандиты")
                + "); силы наши " + ours.ToString("F0", CultureInfo.InvariantCulture)
                + " против " + best.Party.EstimatedStrength.ToString("F0", CultureInfo.InvariantCulture)
                + " (x" + bestRatio.ToString("F2", CultureInfo.InvariantCulture) + ", порог x"
                + HuntMinRatio.ToString("F1", CultureInfo.InvariantCulture) + "); до цели "
                + bestDistance.ToString("F1", CultureInfo.InvariantCulture));
            ApplyDecision(party, new AIBehaviorData(best, AiBehavior.EngageParty,
                MobileParty.NavigationType.Default, false, false, false), 1f);
            return true;
        }
    }
}
