using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Actions;
using BannerlordLink.Util;
using HarmonyLib;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.TournamentGames;
using TaleWorlds.MountAndBlade;
using TaleWorlds.Localization;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.3 — BLT-style viewer tournaments (clean-room re-impl, ref:
    /// BLT-v5.2.4 BLTTournamentQueueBehavior).
    ///
    /// Owns:
    ///   • TournamentQueue — list of adopted heroes waiting to enter
    ///   • Game menu options в town_arena: «Start viewer tournament» / Watch
    ///   • Spawn a real Bannerlord tournament + inject queued heroes как
    ///     participants через TournamentParticipantsPatch (Harmony Postfix
    ///     на FightTournamentGame.GetParticipantCharacters)
    ///
    /// Source of truth для очереди в-игре. Backend хранит mirror для UI,
    /// получает события tournament.joined/left/started/ended.
    ///
    /// JoinTournamentHandler (action hero.join_tournament) → AddToQueue
    /// → push event tournament.joined → backend INSERT.
    /// </summary>
    public class TournamentQueueBehavior : CampaignBehaviorBase
    {
        public const int TOURNAMENT_SIZE = 16;
        public const int ENTRY_FEE_GOLD = 5_000;

        public static TournamentQueueBehavior Current =>
            Campaign.Current?.GetCampaignBehavior<TournamentQueueBehavior>();

        public class QueueEntry
        {
            public string Username { get; set; }
            public Hero Hero { get; set; }
            public int EntryFee { get; set; }
        }

        private readonly List<QueueEntry> _queue = new List<QueueEntry>();
        public IReadOnlyList<QueueEntry> Queue => _queue;
        public bool TournamentAvailable => _queue.Count > 0;

        // Reference grabbed by patch to enumerate participants.
        public static TournamentMissionBehavior StartingTournament;

        public override void RegisterEvents()
        {
            CampaignEvents.HeroKilledEvent.AddNonSerializedListener(this,
                (victim, killer, detail, notify) =>
                {
                    int removed = _queue.RemoveAll(e =>
                        e.Hero == null || e.Hero.IsDead || e.Hero == victim);
                    if (removed > 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[tournament] hero killed → removed {removed} from queue");
                    }
                });

            CampaignEvents.OnSessionLaunchedEvent.AddNonSerializedListener(this,
                OnSessionLaunched);
        }

        public override void SyncData(IDataStore dataStore)
        {
            // Stateless — очередь не переживает save/load (как BLT, который
            // тоже re-инициализирует queue на каждую сессию).
        }

        private void OnSessionLaunched(CampaignGameStarter starter)
        {
            try
            {
                AddTournamentGameMenus(starter);
                BannerlordLinkModule.Log(
                    "[tournament] game menu options registered (town_arena)");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[tournament] game menu register FAILED: {ex.Message}");
            }
        }

        /// <summary>Добавляет 2 опции в town_arena: запустить / смотреть viewer tournament.</summary>
        private void AddTournamentGameMenus(CampaignGameStarter starter)
        {
            starter.AddGameMenuOption(
                "town_arena",
                "blink_start_viewer_tournament",
                "{=!}⚔️ Запустить турнир зрителей ({QUEUE_SIZE})",
                args =>
                {
                    args.optionLeaveType = GameMenuOption.LeaveType.HostileAction;
                    MBTextManager.SetTextVariable("QUEUE_SIZE", _queue.Count.ToString(), false);
                    return _queue.Count > 0;
                },
                args =>
                {
                    StartViewerTournament(playerParticipates: true);
                },
                index: 2);

            starter.AddGameMenuOption(
                "town_arena",
                "blink_watch_viewer_tournament",
                "{=!}👁 Смотреть турнир зрителей",
                args =>
                {
                    args.optionLeaveType = GameMenuOption.LeaveType.HostileAction;
                    return _queue.Count > 0;
                },
                args =>
                {
                    StartViewerTournament(playerParticipates: false);
                },
                index: 3);
        }

        /// <summary>Add viewer's hero to queue. Returns (ok, message).</summary>
        public (bool ok, string message) AddToQueue(string username, int entryFee)
        {
            username = (username ?? "").Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return (false, "no username");

            var hero = HeroLookup.FindByUsername(username);
            if (hero == null || !hero.IsAlive)
                return (false, "hero не найден или мёртв");

            if (_queue.Any(e => e.Hero == hero))
                return (false, "уже в очереди");

            _queue.Add(new QueueEntry
            {
                Username = username,
                Hero = hero,
                EntryFee = entryFee,
            });
            return (true, $"position {_queue.Count}/{TOURNAMENT_SIZE}");
        }

        public void RemoveFromQueue(string username)
        {
            username = (username ?? "").Trim().ToLowerInvariant();
            _queue.RemoveAll(e =>
                string.Equals(e.Username, username, StringComparison.OrdinalIgnoreCase));
        }

        private void StartViewerTournament(bool playerParticipates)
        {
            try
            {
                var settlement = Settlement.CurrentSettlement;
                if (settlement?.Town == null)
                {
                    BannerlordLinkModule.Log(
                        "[tournament] StartViewerTournament: no current town");
                    return;
                }

                // Snapshot ровно столько участников сколько влезет
                int maxViewers = playerParticipates
                    ? TOURNAMENT_SIZE - 1
                    : TOURNAMENT_SIZE;
                var snapshot = _queue.Take(maxViewers).ToList();

                // Создаём mission behaviour ДО реального tournament create —
                // patch на GetParticipantCharacters читает StartingTournament.
                StartingTournament = new TournamentMissionBehavior(
                    playerParticipates, snapshot);

                var tournamentGame = Campaign.Current.Models.TournamentModel
                    .CreateTournament(settlement.Town);
                tournamentGame.PrepareForTournamentGame(playerParticipates);

                MissionState.Current.CurrentMission.AddMissionBehavior(StartingTournament);
                StartingTournament.PrepareForTournamentGame();

                // Очередь сбрасываем — snapshot уже в активном турнире.
                _queue.RemoveAll(e => snapshot.Contains(e));

                // Push event tournament.started
                var participantUsernames = snapshot
                    .Select(e => e.Username)
                    .Where(u => !string.IsNullOrEmpty(u))
                    .Distinct()
                    .ToArray();
                string evtData = JsonConvert.SerializeObject(new
                {
                    participants = participantUsernames,
                    settlement = settlement.Name?.ToString() ?? settlement.StringId,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "tournament.started", evtData));

                BannerlordLinkModule.Log(
                    $"[tournament] STARTED at {settlement.StringId}, " +
                    $"{participantUsernames.Length} viewers " +
                    $"(player_in={playerParticipates})");

                StartingTournament = null;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[tournament] StartViewerTournament FAILED: {ex.Message}");
                StartingTournament = null;
            }
        }
    }
}
