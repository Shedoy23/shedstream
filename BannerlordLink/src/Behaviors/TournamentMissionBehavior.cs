using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using HarmonyLib;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.CharacterDevelopment;
using TaleWorlds.CampaignSystem.TournamentGames;
using TaleWorlds.Core;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;
using TaleWorlds.ObjectSystem;
using SandBox.Tournaments.MissionLogics;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.3 — Mission-scope behavior, активен только во время бои
    /// турнира. Hooks:
    ///   • PrepareForTournamentGame() — register OnTournamentEnd
    ///   • Harmony Postfix EndCurrentMatch → round_ended + per-round rewards
    ///   • OnTournamentEnd → final winner + big prize + reset
    ///
    /// Rewards (BLT-pattern, наши значения):
    ///   Round win : +10K Hero.Gold, +500 random skill XP
    ///   Round lose: +200 random skill XP (consolation)
    ///   Final win : +50K Hero.Gold, +2000 random skill XP, prize item в inventory
    /// </summary>
    public class TournamentMissionBehavior : MissionBehavior
    {
        public override MissionBehaviorType BehaviorType => MissionBehaviorType.Other;

        private readonly bool _playerParticipates;
        private readonly List<TournamentQueueBehavior.QueueEntry> _participants;
        private bool _hasGeneratedRoster;
        private List<CharacterObject> _cachedRoster;
        private bool _completed;   // true если OnTournamentEnd сработал штатно
        private bool _abortedSent; // dedupe abort event

        // Rewards tuning
        public const int ROUND_WIN_GOLD  = 10_000;
        public const int ROUND_WIN_XP    =    500;
        public const int ROUND_LOSE_XP   =    200;
        public const int FINAL_WIN_GOLD  = 50_000;
        public const int FINAL_WIN_XP    =  2_000;

        public TournamentMissionBehavior(
            bool playerParticipates,
            List<TournamentQueueBehavior.QueueEntry> participants)
        {
            _playerParticipates = playerParticipates;
            _participants = participants ?? new List<TournamentQueueBehavior.QueueEntry>();
        }

        /// <summary>Called by patch on FightTournamentGame.GetParticipantCharacters
        /// чтобы сформировать ростер участников.</summary>
        public List<CharacterObject> GetParticipantCharacters()
        {
            if (_hasGeneratedRoster && _cachedRoster != null)
                return _cachedRoster;
            _hasGeneratedRoster = true;

            var roster = new List<CharacterObject>();
            if (_playerParticipates && Hero.MainHero?.CharacterObject != null)
                roster.Add(Hero.MainHero.CharacterObject);

            foreach (var entry in _participants)
            {
                if (entry?.Hero?.CharacterObject != null && !entry.Hero.IsDead)
                    roster.Add(entry.Hero.CharacterObject);
            }

            // Fill до 16 culture basic/elite troops
            var fillerTroops = CollectFillerTroops();
            var rng = new Random();
            while (roster.Count < TournamentQueueBehavior.TOURNAMENT_SIZE && fillerTroops.Count > 0)
            {
                roster.Add(fillerTroops[rng.Next(fillerTroops.Count)]);
            }

            _cachedRoster = roster;
            BannerlordLinkModule.Log(
                $"[tournament] roster generated: {roster.Count} participants " +
                $"({_participants.Count} adopted + filler)");
            return _cachedRoster;
        }

        private static List<CharacterObject> CollectFillerTroops()
        {
            var result = new List<CharacterObject>();
            try
            {
                var cultures = MBObjectManager.Instance.GetObjectTypeList<CultureObject>();
                foreach (var c in cultures)
                {
                    if (c?.BasicTroop != null) result.Add(c.BasicTroop);
                    if (c?.EliteBasicTroop != null) result.Add(c.EliteBasicTroop);
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[tournament] CollectFillerTroops error: {ex.Message}");
            }
            return result;
        }

        /// <summary>Wire up TournamentBehavior callbacks. Called после AddMissionBehavior.</summary>
        public void PrepareForTournamentGame()
        {
            try
            {
                var tb = Mission.GetMissionBehavior<TournamentBehavior>();
                if (tb != null)
                {
                    tb.TournamentEnd += OnTournamentEnd;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[tournament] PrepareForTournamentGame error: {ex.Message}");
            }
        }

        /// <summary>Called from Harmony Postfix EndCurrentMatch (after match resolves).</summary>
        public void HandleMatchEnd(TournamentBehavior tournamentBehavior)
        {
            if (tournamentBehavior?.LastMatch == null) return;

            try
            {
                int roundIndex = Math.Max(0, tournamentBehavior.CurrentRoundIndex - 1);
                var lastMatch = tournamentBehavior.LastMatch;
                var winners = lastMatch.Winners?.Select(w => w.Character?.HeroObject)
                                                  .Where(h => h != null).ToList()
                                                  ?? new List<Hero>();

                // For each adopted participant, apply reward по результату
                foreach (var entry in _participants)
                {
                    if (entry?.Hero == null) continue;
                    bool participated = lastMatch.Participants
                        ?.Any(p => p.Character?.HeroObject == entry.Hero) ?? false;
                    if (!participated) continue;

                    bool won = winners.Contains(entry.Hero);
                    if (won)
                    {
                        GiveGoldAction.ApplyBetweenCharacters(null, entry.Hero, ROUND_WIN_GOLD, true);
                        AddRandomSkillXp(entry.Hero, ROUND_WIN_XP);
                        BannerlordLinkModule.Log(
                            $"[tournament] @{entry.Username} won round {roundIndex} → " +
                            $"+{ROUND_WIN_GOLD}💰 +{ROUND_WIN_XP}XP");
                    }
                    else
                    {
                        AddRandomSkillXp(entry.Hero, ROUND_LOSE_XP);
                        BannerlordLinkModule.Log(
                            $"[tournament] @{entry.Username} lost round {roundIndex} → " +
                            $"+{ROUND_LOSE_XP}XP");
                    }
                }

                // Backend event: who survived this round (для bet resolution).
                var survivors = winners
                    .Where(h => h?.Name != null
                                && HeroNaming.IsAdopted(h.Name.ToString()))
                    .Select(h => HeroNaming.ExtractUsername(h.Name.ToString()))
                    .Where(u => !string.IsNullOrEmpty(u))
                    .Distinct()
                    .ToArray();
                string evtData = JsonConvert.SerializeObject(new
                {
                    round_index = roundIndex,
                    survivors = survivors,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "tournament.round_ended", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[tournament] HandleMatchEnd error: {ex.Message}");
            }
        }

        private void OnTournamentEnd()
        {
            try
            {
                var tb = Mission?.GetMissionBehavior<TournamentBehavior>();
                if (tb == null) return;

                var winnerHero = tb.Winner.Character?.HeroObject;
                string winnerUsername = null;
                bool adoptedWinner = false;

                if (winnerHero?.Name != null && HeroNaming.IsAdopted(winnerHero.Name.ToString()))
                {
                    winnerUsername = HeroNaming.ExtractUsername(winnerHero.Name.ToString());
                    adoptedWinner = !string.IsNullOrEmpty(winnerUsername);
                }

                if (adoptedWinner)
                {
                    GiveGoldAction.ApplyBetweenCharacters(null, winnerHero, FINAL_WIN_GOLD, true);
                    AddRandomSkillXp(winnerHero, FINAL_WIN_XP);

                    // Prize item — добавляем в hero inventory если есть PartyBelongedTo
                    var prize = tb.TournamentGame?.Prize;
                    if (prize != null)
                    {
                        var party = winnerHero.PartyBelongedTo?.ItemRoster
                                    ?? winnerHero.PartyBelongedToAsPrisoner?.ItemRoster;
                        if (party != null)
                        {
                            party.AddToCounts(prize, 1);
                            BannerlordLinkModule.Log(
                                $"[tournament] @{winnerUsername} WON tournament → " +
                                $"+{FINAL_WIN_GOLD}💰 +{FINAL_WIN_XP}XP + prize {prize.StringId} в инвентарь");
                        }
                        else
                        {
                            BannerlordLinkModule.Log(
                                $"[tournament] @{winnerUsername} WON но нет party — prize не выдан");
                        }
                    }
                }
                else
                {
                    BannerlordLinkModule.Log(
                        $"[tournament] ENDED, winner = non-adopted ({winnerHero?.Name?.ToString() ?? "?"})");
                }

                // Push event
                var participantUsernames = _participants
                    .Select(e => e.Username)
                    .Where(u => !string.IsNullOrEmpty(u))
                    .ToArray();
                string evtData = JsonConvert.SerializeObject(new
                {
                    winner = winnerUsername,
                    adopted_winner = adoptedWinner,
                    participants = participantUsernames,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "tournament.ended", evtData));

                _hasGeneratedRoster = false;
                _cachedRoster = null;
                _completed = true;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[tournament] OnTournamentEnd error: {ex.Message}");
            }
        }

        /// <summary>Mission ends (стример вышел из города / закрыл турнир досрочно).
        /// Если турнир не отработал OnTournamentEnd — пушим tournament.ended
        /// с winner=null чтобы backend сбросил status='idle'.</summary>
        protected override void OnEndMission()
        {
            base.OnEndMission();
            try
            {
                if (_completed || _abortedSent) return;
                _abortedSent = true;

                var participantUsernames = _participants
                    .Select(e => e.Username)
                    .Where(u => !string.IsNullOrEmpty(u))
                    .ToArray();
                string evtData = JsonConvert.SerializeObject(new
                {
                    winner = (string)null,
                    adopted_winner = false,
                    aborted = true,
                    participants = participantUsernames,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "tournament.ended", evtData));
                BannerlordLinkModule.Log(
                    "[tournament] OnEndMission: aborted (стример вышел досрочно), " +
                    "pushed tournament.ended winner=null");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[tournament] OnEndMission abort error: {ex.Message}");
            }
        }

        private static void AddRandomSkillXp(Hero hero, int xp)
        {
            if (hero?.HeroDeveloper == null || xp <= 0) return;
            try
            {
                var skills = MBObjectManager.Instance.GetObjectTypeList<SkillObject>();
                if (skills == null || skills.Count == 0) return;
                var rng = new Random();
                var skill = skills[rng.Next(skills.Count)];
                hero.HeroDeveloper.AddSkillXp(skill, xp);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[tournament] AddRandomSkillXp error: {ex.Message}");
            }
        }
    }
}
