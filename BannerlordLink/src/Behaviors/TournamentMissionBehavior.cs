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

        // Sprint 5.28: track rounds won per username для escalating final reward.
        // BLT pattern: финальный приз масштабируется от количества выигранных раундов.
        private readonly Dictionary<string, int> _roundsWon = new Dictionary<string, int>();

        // Sprint 5.29 BLT-parity #10: anti-snowball list — последние WINNERS_HISTORY_SIZE
        // победителей турниров. При spawn в следующих турнирах их HP/health
        // снижается, чтобы один и тот же viewer не доминировал.
        // Static — persistent через mission lifecycle, переживает один заход в save.
        private static readonly List<string> _recentWinners = new List<string>();
        private const int WINNERS_HISTORY_SIZE = 5;
        private const float RECENT_WINNER_HP_PENALTY = 0.75f;  // 25% reduction (default)

        // Sprint 5.32 (BLT-parity M5) — per-class HP penalty.
        // Раньше blanket ×0.75 для всех — tank-классы переносили легко (large
        // HP pool + heavy armor абсорбирует урон), cavalry почти не страдала
        // (mobility компенсирует), но archer'ы / horse_archer'ы доминировали
        // потому что long-range advantage был нетронут. Теперь дифференцируем:
        //   tank/knight (heavy armor + shield)  → 0.85 (легчайший nerf)
        //   infantry/berserk/psycho             → 0.78 (medium)
        //   crossbow/heavy_crossbow             → 0.74 (range advantage)
        //   archer/heavy_archer                 → 0.72 (range advantage)
        //   cavalry/camel_cavalry/assassin      → 0.70 (mobility+range)
        //   horse_archer/camel_archer           → 0.65 (heaviest — best class)
        //   unknown / no class                  → 0.75 (legacy fallback)
        private static readonly Dictionary<string, float> _classHpPenalty =
            new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase)
            {
                ["tank"]            = 0.85f,
                ["knight"]          = 0.85f,
                ["infantry"]        = 0.78f,
                ["berserk"]         = 0.78f,
                ["psycho"]          = 0.78f,
                ["crossbow"]        = 0.74f,
                ["heavy_crossbow"]  = 0.74f,
                ["archer"]          = 0.72f,
                ["heavy_archer"]    = 0.72f,
                ["cavalry"]         = 0.70f,
                ["camel_cavalry"]   = 0.70f,
                ["assassin"]        = 0.70f,
                ["horse_archer"]    = 0.65f,
                ["camel_archer"]    = 0.65f,
            };

        private static float ComputePenaltyForUser(string username)
        {
            try
            {
                var hc = BannerlordLink.Net.PowerCache.GetHeroClass(username);
                if (hc.HasValue && !string.IsNullOrEmpty(hc.Value.classKey)
                    && _classHpPenalty.TryGetValue(hc.Value.classKey, out float p))
                {
                    return p;
                }
            }
            catch { }
            return RECENT_WINNER_HP_PENALTY;
        }

        // Rewards tuning
        public const int ROUND_WIN_GOLD  = 10_000;
        public const int ROUND_WIN_XP    =    500;
        public const int ROUND_LOSE_XP   =    200;
        // 5.28: финальный приз = FINAL_BASE + ROUND_WIN_GOLD × rounds_won.
        // Чемпион 4-этапного турнира получает 20K + 10K×4 = 60K (было flat 50K).
        // Финалист с 3 wins (если bracket позволил) получит 50K. Тонкая
        // корреляция с performance, не только с финальной победой.
        public const int FINAL_BASE_GOLD = 20_000;
        public const int FINAL_WIN_XP    =  2_000;

        public TournamentMissionBehavior(
            bool playerParticipates,
            List<TournamentQueueBehavior.QueueEntry> participants)
        {
            _playerParticipates = playerParticipates;
            _participants = participants ?? new List<TournamentQueueBehavior.QueueEntry>();
            // Sprint 5.32 (BLT-parity H8) — pull persistent recent winners из backend.
            // Раньше `_recentWinners` был static List который reset'ился на reload
            // save / restart игры. Теперь bannerlord_heroes.tournament_wins
            // (m47) — persistent counter, fetch'им top-5 GET'ом при init.
            // Fire-and-forget: если backend unreachable — fallback к in-memory list'у.
            _ = System.Threading.Tasks.Task.Run(async () =>
            {
                try { await RefreshRecentWinnersFromBackendAsync(); }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[tournament] H8 fetch recent winners warn: {ex.Message}");
                }
            });
        }

        // Sprint 5.32 (BLT-parity H8) — populate _recentWinners из backend
        // bannerlord_heroes.tournament_wins (через /api/bannerlord/recent-tournament-winners).
        private static async System.Threading.Tasks.Task RefreshRecentWinnersFromBackendAsync()
        {
            try
            {
                string resp = await BannerlordLinkModule.Backend.GetAsync(
                    "/api/bannerlord/recent-tournament-winners?limit=5");  // 2026-06-10 FIX: был без /api/ → 404
                if (string.IsNullOrEmpty(resp)) return;
                // Lightweight parse без full JSON deserializer — payload простой:
                // {"success": true, "winners": [{"username": "...", "wins": N}, ...]}
                var parsed = Newtonsoft.Json.Linq.JObject.Parse(resp);
                var winners = parsed["winners"] as Newtonsoft.Json.Linq.JArray;
                if (winners == null) return;
                var fresh = new List<string>();
                foreach (var w in winners)
                {
                    var name = w["username"]?.ToString();
                    if (!string.IsNullOrEmpty(name))
                        fresh.Add(name.ToLowerInvariant());
                }
                lock (_recentWinners)
                {
                    _recentWinners.Clear();
                    _recentWinners.AddRange(fresh);
                }
                BannerlordLinkModule.Log(
                    $"[tournament:anti-snowball H8] loaded {fresh.Count} recent winners " +
                    $"from backend: {string.Join(", ", fresh)}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[tournament:anti-snowball H8] fetch failed: {ex.Message}");
            }
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

            // Sprint 5.28: culture-aware filler — приоритезируем basic/elite
            // host-settlement'а (BLT pattern). Если их не хватает (редко) —
            // фоллбэк на all-cultures. Атмосферно: имперский турнир ловит
            // имперских troops, а не сборную солянку.
            var hostCulture = TaleWorlds.CampaignSystem.Settlements.Settlement.CurrentSettlement?.Culture;
            var fillerTroops = CollectFillerTroops(hostCulture);
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

        /// <summary>BLT-style filler: приоритезируем host-culture basic/elite,
        /// fallback на все культуры если не хватает.</summary>
        private static List<CharacterObject> CollectFillerTroops(CultureObject hostCulture)
        {
            var result = new List<CharacterObject>();
            try
            {
                // Step 1: host-culture первыми (basic + elite, дублицированы
                // в pool чтобы статистически чаще выпадали при random pick)
                if (hostCulture != null)
                {
                    for (int i = 0; i < 3; i++)
                    {
                        if (hostCulture.BasicTroop != null) result.Add(hostCulture.BasicTroop);
                        if (hostCulture.EliteBasicTroop != null) result.Add(hostCulture.EliteBasicTroop);
                    }
                }
                // Step 2: остальные культуры как fallback pool
                var cultures = MBObjectManager.Instance.GetObjectTypeList<CultureObject>();
                foreach (var c in cultures)
                {
                    if (c == null || c == hostCulture) continue;
                    if (c.BasicTroop != null) result.Add(c.BasicTroop);
                    if (c.EliteBasicTroop != null) result.Add(c.EliteBasicTroop);
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[tournament] CollectFillerTroops error: {ex.Message}");
            }
            return result;
        }

        /// <summary>Sprint 5.29 BLT-parity #10 — anti-snowball: при spawn agent'а
        /// который является recent winner, снижаем его HP на старте. Победители
        /// последних 5 турниров приходят с handicap, чтобы не доминировали.</summary>
        public override void OnAgentBuild(Agent agent, Banner banner)
        {
            base.OnAgentBuild(agent, banner);
            try
            {
                var hero = (agent?.Character as CharacterObject)?.HeroObject;
                if (hero?.Name == null) return;
                string heroName = hero.Name.ToString();
                if (!HeroNaming.IsAdopted(heroName)) return;
                string username = HeroNaming.ExtractUsername(heroName);
                if (string.IsNullOrEmpty(username)) return;
                if (!_recentWinners.Contains(username)) return;

                // Penalty: starting HP × 0.75. Health limit не трогаем — иначе
                // post-mission heal восстановит full normal HP (а не reduced).
                // Только текущая Health в момент tournament fight нерфится.
                if (agent.IsActive() && agent.HealthLimit > 0)
                {
                    // Sprint 5.32 (BLT-parity M5) — per-class penalty.
                    float penalty = ComputePenaltyForUser(username);
                    float newHp = agent.HealthLimit * penalty;
                    agent.Health = newHp;
                    BannerlordLinkModule.Log(
                        $"[tournament:anti-snowball M5] @{username} recent winner → " +
                        $"HP {agent.HealthLimit:F0} × {penalty:F2} = {newHp:F0} (per-class)");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[tournament:anti-snowball] OnAgentBuild error: {ex.Message}");
            }
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
                        // Sprint 5.30 #42 — sub reward_boost
                        int roundGold = BannerlordLink.Net.RewardBoostCache
                            .ApplyToInt(entry.Username, ROUND_WIN_GOLD);
                        int roundXp = BannerlordLink.Net.RewardBoostCache
                            .ApplyToInt(entry.Username, ROUND_WIN_XP);
                        GiveGoldAction.ApplyBetweenCharacters(null, entry.Hero, roundGold, true);
                        AddRandomSkillXp(entry.Hero, roundXp);
                        if (!string.IsNullOrEmpty(entry.Username))
                        {
                            _roundsWon.TryGetValue(entry.Username, out int prev);
                            _roundsWon[entry.Username] = prev + 1;
                        }
                        BannerlordLinkModule.Log(
                            $"[tournament] @{entry.Username} won round {roundIndex} → " +
                            $"+{roundGold}💰 +{roundXp}XP");
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
                // Sprint 5.31 #45c — было fire-and-forget без try/catch:
                // если backend POST fail'ит, событие тихо терялось.
                Task.Run(async () => {
                    try { await BannerlordLinkModule.Backend
                        .PostEventAsync("bannerlord", "tournament.round_ended", evtData); }
                    catch (Exception ex) {
                        BannerlordLinkModule.Log($"[tournament] round_ended push failed: {ex.Message}");
                    }
                });
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
                    // Sprint 5.29 BLT-parity #10: record в recent winners для
                    // anti-snowball debuff в следующих турнирах.
                    _recentWinners.Add(winnerUsername);
                    while (_recentWinners.Count > WINNERS_HISTORY_SIZE)
                        _recentWinners.RemoveAt(0);
                    BannerlordLinkModule.Log(
                        $"[tournament:anti-snowball] recent winners (last {WINNERS_HISTORY_SIZE}): " +
                        string.Join(", ", _recentWinners));

                    // 5.28: escalating final reward — base + per-round-won bonus.
                    // Чемпион 4-этапного: 20K + 4×10K = 60K. Без выигранных
                    // раундов (lucky bracket): только base 20K.
                    _roundsWon.TryGetValue(winnerUsername, out int wonCount);
                    int baseFinalGold = FINAL_BASE_GOLD + ROUND_WIN_GOLD * wonCount;
                    // Sprint 5.30 #42 — sub reward_boost для финального приза
                    int finalGold = BannerlordLink.Net.RewardBoostCache
                        .ApplyToInt(winnerUsername, baseFinalGold);
                    int finalXp = BannerlordLink.Net.RewardBoostCache
                        .ApplyToInt(winnerUsername, FINAL_WIN_XP);
                    GiveGoldAction.ApplyBetweenCharacters(null, winnerHero, finalGold, true);
                    AddRandomSkillXp(winnerHero, finalXp);

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
                                $"[tournament] @{winnerUsername} WON tournament " +
                                $"({wonCount} rounds) → +{finalGold}💰 (={FINAL_BASE_GOLD}+{ROUND_WIN_GOLD}×{wonCount}) " +
                                $"+{FINAL_WIN_XP}XP + prize {prize.StringId} в инвентарь");
                        }
                        else
                        {
                            BannerlordLinkModule.Log(
                                $"[tournament] @{winnerUsername} WON ({wonCount} rounds) → " +
                                $"+{finalGold}💰, но нет party — prize не выдан");
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
                // Sprint 5.31 #45c — wrap fire-and-forget с try/catch.
                Task.Run(async () => {
                    try { await BannerlordLinkModule.Backend
                        .PostEventAsync("bannerlord", "tournament.ended", evtData); }
                    catch (Exception ex) {
                        BannerlordLinkModule.Log($"[tournament] ended push failed (winner): {ex.Message}");
                    }
                });

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
                // Sprint 5.31 #45c — wrap fire-and-forget с try/catch.
                Task.Run(async () => {
                    try { await BannerlordLinkModule.Backend
                        .PostEventAsync("bannerlord", "tournament.ended", evtData); }
                    catch (Exception ex) {
                        BannerlordLinkModule.Log($"[tournament] ended push failed (aborted): {ex.Message}");
                    }
                });
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
