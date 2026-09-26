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
        /// <summary>Этот союзник ещё не воюет с нашим врагом: позвать его в войну.</summary>
        public float CallToWarSupport; public bool CallToWarPossible; public string CallToWarAgainst;
        public float TradeSupport; public bool TradePossible;
        /// <summary>МЕСТНАЯ сила: их лорды рядом с нашим отрядом / сила нашего отряда.
        /// 26.09 владелец выбрал вариант «а»: общая сила королевств для нас бесполезна —
        /// наше королевство это наш отряд и кланы зрителей, слабее нас не было никого, и
        /// политика объявила войну Стургии x16. Больше 1 — рядом они сильнее нас.</summary>
        public float StrengthRatio;
        /// <summary>У них рядом есть крепость, которую наш отряд возьмёт (перевес по правилу осады).</summary>
        public bool WeakFortressNear;
        /// <summary>У них рядом хоть кто-то: лорды или крепости. Нет — войне негде идти.</summary>
        public bool Nearby = true;
        /// <summary>Доля голосов «да» за войну / мир по оценке игры (KingdomElection —
        /// так же штатный ИИ в ConsiderWar). 26.09: автопилот раз в день предлагал мир
        /// с Вландией, королевство отвечало «Нет» 100% — предлагать без голосов значит
        /// жечь влияние и спамить стримеру голосованием.</summary>
        public float WarVotes = 1f, PeaceVotes = 1f;
        /// <summary>Что мы уже предлагали этому королевству за последние
        /// DaysBetweenSameProposal дней.</summary>
        public HashSet<PoliticsMove> Recent = new HashSet<PoliticsMove>();
    }

    /// <summary>Есть ли уже своя заявка каждого вида / хватает ли влияния на неё.</summary>
    internal sealed class PoliticsFlags { public bool War, Peace, Alliance, CallToWar, Trade; }

    internal enum PoliticsMove { None, War, Peace, CallToWar, Alliance, Trade }

    /// <summary>Что предложить королевству сегодня. Без игры внутри — проверяется
    /// тестом; оценки выгоды берутся у игры (DiplomacyModel, CalculateSupport).
    /// Решение владельца 23.09: держать ровно одну войну; союзы рассматривать всегда.</summary>
    internal static class PoliticsPolicy
    {
        internal const int TargetWars = 1;
        /// <summary>Штатный ИИ не предлагает войну тому, с кем мир моложе 20 дней
        /// (KingdomDecisionProposalBehavior.GetRandomWarDecision) — повторяем.</summary>
        internal const double TruceDays = 20;
        /// <summary>Порог поддержки союза, призыва союзника и торговли — как у
        /// штатного ИИ (ConsiderWar, ConsiderTradeAgreement: > 50).</summary>
        internal const float AllianceSupportNeeded = 50f;
        /// <summary>26.09, владелец: «странно, что он мир Вландии не предлагает и не
        /// нападает на более слабых». Единственную войну с тем, кто сильнее нас в
        /// столько раз, меняем на войну со слабым: сперва мир, потом война.</summary>
        internal const float StrongEnemyRatio = 2f;
        /// <summary>Итог выбирает правитель — автопилот берёт самый популярный вариант,
        /// значит без половины голосов «да» предложение гарантированно проваливается.</summary>
        internal const float VotesNeeded = 0.5f;
        /// <summary>Штатный ИИ не повторяет то же предложение 5 дней
        /// (KingdomDecisionProposalBehavior.DaysBetweenSameProposal) — повторяем.</summary>
        internal const double DaysBetweenSameProposal = 5;

        private static bool WarCandidate(PoliticsCandidate c) => !c.AtWar && c.DaysSincePeace > TruceDays && c.WarPossible
            && c.WarVotes >= VotesNeeded && !c.Recent.Contains(PoliticsMove.War);
        private static bool PeaceCandidate(PoliticsCandidate c) => c.AtWar && !c.ConstantWar && c.PeacePossible
            && c.PeaceVotes >= VotesNeeded && !c.Recent.Contains(PoliticsMove.Peace);
        private static string Votes(float v) => "; голосов «да» " + (v * 100).ToString("F0") + "%";

        internal static (PoliticsMove Move, PoliticsCandidate Target, string Why) Decide(
            IList<PoliticsCandidate> all, PoliticsFlags pending, PoliticsFlags canPay)
        {
            bool warPending = pending.War, peacePending = pending.Peace, alliancePending = pending.Alliance;
            bool canPayWar = canPay.War, canPayPeace = canPay.Peace, canPayAlliance = canPay.Alliance;
            int wars = all.Count(c => c.AtWar && !c.ConstantWar);
            if (wars < TargetWars && !warPending && canPayWar)
            {
                // 26.09 (вариант «а»): сперва у кого рядом слабая крепость, потом кто рядом
                // и слабее нас на месте, потом кто хоть рядом, среди равных — поддержка клана.
                var target = all.Where(WarCandidate)
                    .OrderByDescending(c => c.WeakFortressNear)
                    .ThenByDescending(c => c.Nearby && c.StrengthRatio < 1f)
                    .ThenByDescending(c => c.Nearby)
                    .ThenByDescending(c => c.WarSupport).FirstOrDefault();
                if (target != null) return (PoliticsMove.War, target, "войн " + wars + " из " + TargetWars
                    + "; поддержка нашего клана " + target.WarSupport.ToString("F0")
                    + "; рядом их сила/наша x" + target.StrengthRatio.ToString("F1")
                    + (target.WeakFortressNear ? "; рядом их крепость по силам" : "")
                    + (target.Nearby ? "" : "; рядом их нет") + Votes(target.WarVotes));
            }
            if (wars > TargetWars && !peacePending && canPayPeace)
            {
                // Мир с той войной, где он нам нужнее всего по оценке игры, — а не с
                // самой новой: новая часто оплачена зрителем.
                var target = all.Where(PeaceCandidate)
                    .OrderByDescending(c => c.PeaceScore).FirstOrDefault();
                if (target != null) return (PoliticsMove.Peace, target, "войн " + wars + " при цели " + TargetWars
                    + "; мир нужнее всего здесь (оценка " + target.PeaceScore.ToString("F0") + ")" + Votes(target.PeaceVotes));
            }
            // 26.09: единственная война — с тем, кто сильнее нас вдвое, а есть кого
            // бить слабее: мир, чтобы завтра объявить войну слабому. Без слабой
            // альтернативы мир не предлагаем — иначе мир и новая война с тем же по кругу.
            if (wars == TargetWars && !peacePending && canPayPeace
                && all.Any(c => WarCandidate(c) && c.Nearby && (c.WeakFortressNear || c.StrengthRatio < 1f)))
            {
                var strong = all.FirstOrDefault(c => PeaceCandidate(c) && c.StrengthRatio >= StrongEnemyRatio);
                if (strong != null) return (PoliticsMove.Peace, strong, "единственная война — с тем, кто рядом сильнее нас в "
                    + strong.StrengthRatio.ToString("F1") + " раза; есть рядом противник слабее — меняем цель" + Votes(strong.PeaceVotes));
            }
            // Призвать союзника в текущую войну — больше крупных боёв (23.09).
            if (wars > 0 && !pending.CallToWar && canPay.CallToWar)
            {
                var target = all.Where(c => c.CallToWarPossible && c.CallToWarSupport > AllianceSupportNeeded && !c.Recent.Contains(PoliticsMove.CallToWar))
                    .OrderByDescending(c => c.CallToWarSupport).FirstOrDefault();
                if (target != null) return (PoliticsMove.CallToWar, target, "союзник ещё не воюет с «" + target.CallToWarAgainst
                    + "»; поддержка " + target.CallToWarSupport.ToString("F0"));
            }
            if (!alliancePending && canPayAlliance)
            {
                var target = all.Where(c => !c.AtWar && c.AlliancePossible && c.AllianceSupport > AllianceSupportNeeded && !c.Recent.Contains(PoliticsMove.Alliance))
                    .OrderByDescending(c => c.AllianceSupport).FirstOrDefault();
                if (target != null) return (PoliticsMove.Alliance, target, "поддержка союза " + target.AllianceSupport.ToString("F0"));
            }
            if (!pending.Trade && canPay.Trade)
            {
                var target = all.Where(c => !c.AtWar && c.TradePossible && c.TradeSupport > AllianceSupportNeeded && !c.Recent.Contains(PoliticsMove.Trade))
                    .OrderByDescending(c => c.TradeSupport).FirstOrDefault();
                if (target != null) return (PoliticsMove.Trade, target, "поддержка торгового соглашения " + target.TradeSupport.ToString("F0"));
            }
            return (PoliticsMove.None, null, null);
        }
    }
}
