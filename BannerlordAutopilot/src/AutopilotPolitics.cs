using System;
using System.Collections.Generic;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Election;

namespace BannerlordAutopilot
{
    /// <summary>Политика королевства за клан стримера (23.09.2026, спека
    /// review/SPEC_POLITICS_2026-09-23.md).
    ///
    /// Штатный ИИ-клан раз в день сам предлагает королевству войну, мир или союз
    /// (KingdomDecisionProposalBehavior.DailyTickClan), но клан игрока там явно
    /// пропущен. Здесь то же для клана стримера: цифры считает игра
    /// (DiplomacyModel, CalculateSupport, CanMakeDecision), выбор — PoliticsPolicy,
    /// подача — Kingdom.AddDecision; дальше голосуют кланы, включая зрителей.
    /// Сбой политики выключает только политику, автопилот играет дальше.</summary>
    public partial class AutopilotBehavior
    {
        private double _politicsDay = -1;
        private bool _politicsBroken;

        partial void DailyPoliticsHook() => TryDailyPolitics();

        private void TryDailyPolitics()
        {
            if (_mode != Mode.Apply || _politicsBroken) return;
            double day = Math.Floor(CampaignTime.Now.ToDays);
            if (day == _politicsDay) return;
            _politicsDay = day;
            try { RunPolitics(); }
            catch (Exception ex)
            {
                // Отсутствие члена движка после обновления игры проявится здесь
                // (MissingMethodException при первом вызове) — отключаем только политику.
                _politicsBroken = true;
                AutopilotLog.Write("ПОЛИТИКА: выключена до перезапуска: " + ex.GetType().Name + ": " + ex.Message);
            }
        }

        private void RunPolitics()
        {
            Clan clan = Clan.PlayerClan;
            Kingdom ours = clan?.Kingdom;
            if (ours == null || ours.IsEliminated || clan.IsUnderMercenaryService || clan.Influence < 100f) return;
            var diplomacy = Campaign.Current.Models.DiplomacyModel;
            var decisions = new Dictionary<PoliticsCandidate, KingdomDecision[]>();
            var all = new List<PoliticsCandidate>();
            foreach (Kingdom other in Kingdom.All)
            {
                if (other == null || other == ours || other.IsEliminated) continue;
                var c = new PoliticsCandidate
                {
                    Name = other.Name?.ToString(),
                    AtWar = ours.IsAtWarWith(other),
                    ConstantWar = ours.IsAtConstantWarWith(other),
                    DaysSincePeace = ours.GetStanceWith(other).PeaceDeclarationDate.ElapsedDaysUntilNow,
                };
                KingdomDecision war = null, peace = null, alliance = null;
                if (c.AtWar)
                {
                    c.PeaceScore = diplomacy.GetScoreOfDeclaringPeace(ours, other);
                    int tribute = -1, days = 0;
                    if (other.RulingClan != null) tribute = diplomacy.GetDailyTributeToPay(clan, other.RulingClan, out days);
                    if (tribute >= 0 && diplomacy.IsPeaceSuitable(ours, other))
                    {
                        var decision = new MakePeaceKingdomDecision(clan, other, tribute, days);
                        if (decision.CanMakeDecision(out _) && !decision.ShouldBeCancelled())
                        {
                            c.PeacePossible = true; peace = decision;
                        }
                    }
                }
                else
                {
                    var decision = new DeclareWarDecision(clan, other);
                    if (decision.CanMakeDecision(out _) && !decision.ShouldBeCancelled())
                    {
                        c.WarPossible = true; c.WarSupport = decision.CalculateSupport(clan); war = decision;
                    }
                    var ally = new StartAllianceDecision(clan, other);
                    if (ally.CanMakeDecision(out _) && !ally.ShouldBeCancelled())
                    {
                        c.AlliancePossible = true; c.AllianceSupport = ally.CalculateSupport(clan, out _); alliance = ally;
                    }
                }
                all.Add(c);
                decisions[c] = new[] { war, peace, alliance };
            }

            var pending = ours.UnresolvedDecisions;
            var (move, target, why) = PoliticsPolicy.Decide(all,
                pending.Any(d => d is DeclareWarDecision),
                pending.Any(d => d is MakePeaceKingdomDecision),
                pending.Any(d => d is StartAllianceDecision),
                clan.Influence >= diplomacy.GetInfluenceCostOfProposingWar(clan),
                clan.Influence >= diplomacy.GetInfluenceCostOfProposingPeace(clan),
                clan.Influence >= Campaign.Current.Models.AllianceModel.GetInfluenceCostOfProposingStartingAlliance(clan));
            if (move == PoliticsMove.None) return;
            KingdomDecision chosen = decisions[target][move == PoliticsMove.War ? 0 : move == PoliticsMove.Peace ? 1 : 2];
            ours.AddDecision(chosen);
            AutopilotLog.Write("ПОЛИТИКА: предлагаем королевству "
                + (move == PoliticsMove.War ? "войну" : move == PoliticsMove.Peace ? "мир" : "союз")
                + " с «" + target.Name + "»: " + why + "; решают голоса кланов");
        }
    }
}
