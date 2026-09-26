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
        private string _politicsIdleReason;

        partial void DailyPoliticsHook() => TryDailyPolitics();

        /// <summary>26.09 (владелец, вариант «а»): войны выбираем по тому, что рядом с
        /// нашим отрядом, — радиус около двух дней пути.</summary>
        internal const float PoliticsLocalRadius = 150f;

        private static void LocalPicture(Kingdom other, PoliticsCandidate c)
        {
            MobileParty main = MobileParty.MainParty;
            float ours = System.Math.Max(1f, SiegeAttackerStrength(main));
            float r2 = PoliticsLocalRadius * PoliticsLocalRadius, theirs = 0f;
            bool nearby = false, weakFort = false;
            foreach (MobileParty p in MobileParty.All)
            {
                if (p == null || !p.IsActive || !p.IsLordParty || p.MapFaction != other
                    || p.Position.DistanceSquared(main.Position) > r2) continue;
                theirs += System.Math.Max(0f, p.Party.EstimatedStrength);
                nearby = true;
            }
            foreach (TaleWorlds.CampaignSystem.Settlements.Settlement s in TaleWorlds.CampaignSystem.Settlements.Settlement.All)
            {
                if (s == null || !(s.IsTown || s.IsCastle) || s.MapFaction != other
                    || s.Position.DistanceSquared(main.Position) > r2) continue;
                nearby = true;
                float walls = System.Math.Max(0f, s.Town?.GarrisonParty?.Party.EstimatedStrength ?? 0f) + System.Math.Max(0f, s.Militia);
                if (ours >= walls * SiegeStrengthRatio) weakFort = true;
            }
            c.StrengthRatio = theirs / ours;
            c.Nearby = nearby;
            c.WeakFortressNear = weakFort;
        }

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
            // 26.09: раньше выход был молчаливым — владелец видел «мира/войны не
            // предлагает» и не знал почему. Пишем причину при её смене.
            string idle = ours == null || ours.IsEliminated ? "клан не в королевстве"
                : clan.IsUnderMercenaryService ? "клан служит наёмником — по правилам игры наёмник не предлагает войну и мир"
                : clan.Influence < 100f ? "влияния " + clan.Influence.ToString("F0", System.Globalization.CultureInfo.InvariantCulture) + " < 100"
                : null;
            if (idle != _politicsIdleReason)
            {
                if (idle != null) AutopilotLog.Write("ПОЛИТИКА: не предлагаем — " + idle);
                _politicsIdleReason = idle;
            }
            if (idle != null) return;
            var diplomacy = Campaign.Current.Models.DiplomacyModel;
            var trade = Campaign.Current.Models.TradeAgreementModel;
            var decisions = new Dictionary<PoliticsCandidate, Dictionary<PoliticsMove, KingdomDecision>>();
            var all = new List<PoliticsCandidate>();
            var enemies = Kingdom.All.Where(k => k != null && k != ours && !k.IsEliminated
                && ours.IsAtWarWith(k) && !ours.IsAtConstantWarWith(k)).ToList();
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
                LocalPicture(other, c);
                var own = new Dictionary<PoliticsMove, KingdomDecision>();
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
                            c.PeacePossible = true; own[PoliticsMove.Peace] = decision;
                        }
                    }
                }
                else
                {
                    var decision = new DeclareWarDecision(clan, other);
                    if (decision.CanMakeDecision(out _) && !decision.ShouldBeCancelled())
                    {
                        c.WarPossible = true; c.WarSupport = decision.CalculateSupport(clan); own[PoliticsMove.War] = decision;
                    }
                    var ally = new StartAllianceDecision(clan, other);
                    if (ally.CanMakeDecision(out _) && !ally.ShouldBeCancelled())
                    {
                        c.AlliancePossible = true; c.AllianceSupport = ally.CalculateSupport(clan, out _); own[PoliticsMove.Alliance] = ally;
                    }
                    // Союзник, ещё не воюющий с нашим врагом: позвать его в войну.
                    if (ours.IsAllyWith(other))
                        foreach (Kingdom enemy in enemies)
                        {
                            if (other.IsAtWarWith(enemy)) continue;
                            var call = new ProposeCallToWarAgreementDecision(clan, other, enemy);
                            if (!call.CanMakeDecision(out _) || call.ShouldBeCancelled()) continue;
                            float support = call.CalculateSupport(clan);
                            if (c.CallToWarPossible && support <= c.CallToWarSupport) continue;
                            c.CallToWarPossible = true; c.CallToWarSupport = support;
                            c.CallToWarAgainst = enemy.Name?.ToString(); own[PoliticsMove.CallToWar] = call;
                        }
                    if (trade.CanMakeTradeAgreement(ours, other, true, out _))
                    {
                        var deal = new TradeAgreementDecision(clan, other);
                        if (deal.CanMakeDecision(out _) && !deal.ShouldBeCancelled())
                        {
                            c.TradePossible = true; c.TradeSupport = deal.CalculateSupport(clan, out _); own[PoliticsMove.Trade] = deal;
                        }
                    }
                }
                all.Add(c);
                decisions[c] = own;
            }

            var pending = ours.UnresolvedDecisions;
            var alliances = Campaign.Current.Models.AllianceModel;
            var (move, target, why) = PoliticsPolicy.Decide(all,
                new PoliticsFlags
                {
                    War = pending.Any(d => d is DeclareWarDecision),
                    Peace = pending.Any(d => d is MakePeaceKingdomDecision),
                    Alliance = pending.Any(d => d is StartAllianceDecision),
                    CallToWar = pending.Any(d => d is ProposeCallToWarAgreementDecision),
                    Trade = pending.Any(d => d is TradeAgreementDecision),
                },
                new PoliticsFlags
                {
                    War = clan.Influence >= diplomacy.GetInfluenceCostOfProposingWar(clan),
                    Peace = clan.Influence >= diplomacy.GetInfluenceCostOfProposingPeace(clan),
                    Alliance = clan.Influence >= alliances.GetInfluenceCostOfProposingStartingAlliance(clan),
                    CallToWar = clan.Influence >= alliances.GetInfluenceCostOfCallingToWar(clan),
                    Trade = clan.Influence >= trade.GetInfluenceCostOfProposingTradeAgreement(clan),
                });
            if (move == PoliticsMove.None) return;
            KingdomDecision chosen = decisions[target][move];
            ours.AddDecision(chosen);
            StreamStatus.Note("Предлагаем королевству "
                + (move == PoliticsMove.War ? "войну" : move == PoliticsMove.Peace ? "мир"
                    : move == PoliticsMove.CallToWar ? "позвать союзника в войну" : move == PoliticsMove.Trade ? "торговлю" : "союз")
                + " с «" + target.Name + "»");
            AutopilotLog.Write("ПОЛИТИКА: предлагаем королевству "
                + (move == PoliticsMove.War ? "войну" : move == PoliticsMove.Peace ? "мир"
                    : move == PoliticsMove.CallToWar ? "призвать в войну союзника" : move == PoliticsMove.Trade ? "торговое соглашение" : "союз")
                + " с «" + target.Name + "»: " + why + "; решают голоса кланов");
        }
    }
}
