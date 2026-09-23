using System.Collections.Generic;
using System.Linq;

namespace BannerlordAutopilot
{
    /// <summary>Одно чужое королевство глазами нашего — цифры посчитала игра.</summary>
    internal sealed class PoliticsCandidate
    {
        public string Name;
        public bool AtWar, ConstantWar;
        public double DaysSincePeace = 1000;
        /// <summary>DiplomacyModel.GetScoreOfDeclaringPeace(мы, они): чем выше, тем нужнее нам мир.</summary>
        public float PeaceScore;
        /// <summary>IsPeaceSuitable + дань посчитана + решение можно подать.</summary>
        public bool PeacePossible;
        /// <summary>DeclareWarDecision.CalculateSupport(наш клан) и можно ли подать.</summary>
        public float WarSupport; public bool WarPossible;
        public float AllianceSupport; public bool AlliancePossible;
    }

    internal enum PoliticsMove { None, War, Peace, Alliance }

    /// <summary>Что предложить королевству сегодня. Без игры внутри — проверяется
    /// тестом; оценки выгоды берутся у игры (DiplomacyModel, CalculateSupport).
    /// Решение владельца 23.09: держать ровно одну войну; союзы рассматривать всегда.</summary>
    internal static class PoliticsPolicy
    {
        internal const int TargetWars = 1;
        /// <summary>Штатный ИИ не предлагает войну тому, с кем мир моложе 20 дней
        /// (KingdomDecisionProposalBehavior.GetRandomWarDecision) — повторяем.</summary>
        internal const double TruceDays = 20;
        /// <summary>Порог поддержки союза — как у штатного ConsiderWar для войны.</summary>
        internal const float AllianceSupportNeeded = 50f;

        internal static (PoliticsMove Move, PoliticsCandidate Target, string Why) Decide(
            IList<PoliticsCandidate> all, bool warPending, bool peacePending, bool alliancePending,
            bool canPayWar, bool canPayPeace, bool canPayAlliance)
        {
            int wars = all.Count(c => c.AtWar && !c.ConstantWar);
            if (wars < TargetWars && !warPending && canPayWar)
            {
                var target = all.Where(c => !c.AtWar && c.DaysSincePeace > TruceDays && c.WarPossible)
                    .OrderByDescending(c => c.WarSupport).FirstOrDefault();
                if (target != null) return (PoliticsMove.War, target, "войн " + wars + " из " + TargetWars
                    + "; поддержка нашего клана " + target.WarSupport.ToString("F0"));
            }
            if (wars > TargetWars && !peacePending && canPayPeace)
            {
                // Мир с той войной, где он нам нужнее всего по оценке игры, — а не с
                // самой новой: новая часто оплачена зрителем.
                var target = all.Where(c => c.AtWar && !c.ConstantWar && c.PeacePossible)
                    .OrderByDescending(c => c.PeaceScore).FirstOrDefault();
                if (target != null) return (PoliticsMove.Peace, target, "войн " + wars + " при цели " + TargetWars
                    + "; мир нужнее всего здесь (оценка " + target.PeaceScore.ToString("F0") + ")");
            }
            if (!alliancePending && canPayAlliance)
            {
                var target = all.Where(c => !c.AtWar && c.AlliancePossible && c.AllianceSupport > AllianceSupportNeeded)
                    .OrderByDescending(c => c.AllianceSupport).FirstOrDefault();
                if (target != null) return (PoliticsMove.Alliance, target, "поддержка союза " + target.AllianceSupport.ToString("F0"));
            }
            return (PoliticsMove.None, null, null);
        }
    }
}
