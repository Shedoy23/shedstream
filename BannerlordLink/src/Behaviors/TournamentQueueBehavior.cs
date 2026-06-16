using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using BannerlordLink.Actions;
using BannerlordLink.Util;
using HarmonyLib;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
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

        // Sprint 5.32 BUGFIX — REVERT Sprint 5.31 #45d (CWT was overkill +
        // broken in practice). Crash dump показал что Postfix фоторепортно не
        // вызывался — `[tournament:patch] roster replaced` отсутствует в
        // логах. Причина: Settlement reference, переданный в Postfix, не
        // reference-equal с тем что сохранили в CWT → TryGetValue=false →
        // silent skip. Race window'а на main-thread synchronous menu callback
        // нет — возвращаемся к простому static field + Settlement check.
        public static TournamentMissionBehavior StartingTournament;
        public static Settlement StartingSettlement;   // safety check для Postfix

        public static TournamentMissionBehavior GetStartingFor(Settlement settlement)
        {
            if (StartingTournament == null) return null;
            // Soft check: либо одинаковый settlement, либо StartingSettlement не
            // зарегистрирован (legacy fallback).
            if (StartingSettlement != null && settlement != null &&
                StartingSettlement != settlement)
            {
                // Different settlement — это vanilla tournament в другом городе,
                // не наш. Пропускаем без logging (нормальная ситуация).
                return null;
            }
            return StartingTournament;
        }

        private static void SetStartingFor(Settlement settlement, TournamentMissionBehavior beh)
        {
            StartingTournament = beh;
            StartingSettlement = settlement;
            BannerlordLinkModule.Log(
                $"[tournament] StartingTournament set: settlement={settlement?.StringId ?? "?"}");
        }

        private static void ClearStartingFor(Settlement settlement)
        {
            StartingTournament = null;
            StartingSettlement = null;
        }

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

        // Sprint 5.28: persist queue через SyncData. BLT тоже это делает —
        // мы раньше комментировали что «BLT re-инициализирует», но это
        // неверно. Без persistence стример сохраняется с 6 в очереди,
        // загружает save — пусто. Сейчас фиксим: сериализуем usernames +
        // entry fees, на load восстанавливаем Hero через HeroLookup.
        // Storage tag — короткий, version-prefixed для будущей миграции.
        private const string SAVE_KEY = "blink_tournament_queue_v1";

        public override void SyncData(IDataStore dataStore)
        {
            try
            {
                if (dataStore.IsSaving)
                {
                    var rows = _queue
                        .Where(e => e?.Hero != null && !e.Hero.IsDead)
                        .Select(e => $"{e.Username}|{e.EntryFee}")
                        .ToList();
                    string blob = string.Join(";", rows);
                    dataStore.SyncData(SAVE_KEY, ref blob);
                }
                else  // loading
                {
                    string blob = null;
                    dataStore.SyncData(SAVE_KEY, ref blob);
                    _queue.Clear();
                    if (string.IsNullOrEmpty(blob)) return;

                    int restored = 0, skipped = 0;
                    foreach (var row in blob.Split(';'))
                    {
                        if (string.IsNullOrWhiteSpace(row)) continue;
                        var parts = row.Split('|');
                        if (parts.Length < 1) continue;
                        string username = parts[0].Trim().ToLowerInvariant();
                        int fee = 0;
                        if (parts.Length >= 2) int.TryParse(parts[1], out fee);
                        var hero = HeroLookup.FindByUsername(username);
                        if (hero == null || !hero.IsAlive) { skipped++; continue; }
                        _queue.Add(new QueueEntry
                        {
                            Username = username,
                            Hero = hero,
                            EntryFee = fee,
                        });
                        restored++;
                    }
                    BannerlordLinkModule.Log(
                        $"[tournament] SyncData load: restored {restored} queue entries " +
                        $"({skipped} skipped — dead/missing)");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[tournament] SyncData error: {ex.Message}");
            }
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

            // 2026-06-16 (bug #18) — реконсиляция очереди с backend на загрузке.
            // In-game очередь — per-save (SyncData); если стример сейв-скамит
            // (грузит сейв, сделанный ДО записи зрителя), запись молча выпадает,
            // а расширение всё равно показывает «в очереди» (берёт из backend).
            // Backend-очередь — durable source of truth «кто записался»; домерджим
            // тех, кого нет в in-game очереди. Только ДОБАВЛЯЕМ — поэтому откат
            // сейва за уже прошедший турнир не ломает очередь из того сейва.
            _ = FetchAndMergeBackendQueueAsync();
        }

        /// <summary>Фетчит backend-очередь и домерджит на главном потоке (bug #18).</summary>
        private async Task FetchAndMergeBackendQueueAsync()
        {
            try
            {
                string json = await BannerlordLinkModule.Backend
                    .GetAsync("/api/bannerlord/tournament/queue-usernames");
                if (string.IsNullOrEmpty(json)) return;
                var parsed = JObject.Parse(json);
                if (parsed["success"] == null || !(bool)parsed["success"]) return;
                var arr = parsed["usernames"] as JArray;
                if (arr == null || arr.Count == 0) return;
                var users = arr
                    .Select(t => (t.ToString() ?? "").Trim().ToLowerInvariant())
                    .Where(u => !string.IsNullOrEmpty(u))
                    .ToList();
                // Очередь — main-thread state; мутируем только на главном потоке.
                MainThreadDispatcher.Enqueue(() => MergeBackendQueue(users));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[tournament] backend queue fetch error: {ex.Message}");
            }
        }

        private void MergeBackendQueue(List<string> backendUsers)
        {
            try
            {
                int added = 0, skipped = 0;
                foreach (var username in backendUsers)
                {
                    if (_queue.Count >= TOURNAMENT_SIZE) break;
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null || !hero.IsAlive) { skipped++; continue; }
                    if (_queue.Any(e => e.Hero == hero)) continue;   // уже в очереди
                    _queue.Add(new QueueEntry
                    {
                        Username = username,
                        Hero = hero,
                        EntryFee = 0,
                    });
                    added++;
                }
                if (added > 0 || skipped > 0)
                    BannerlordLinkModule.Log(
                        $"[tournament] backend reconcile: +{added} merged, " +
                        $"{skipped} skipped (dead/missing)");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[tournament] merge error: {ex.Message}");
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
                // patch на GetParticipantCharacters читает starting tournament
                // по settlement key (см. ConditionalWeakTable выше).
                var startingTournament = new TournamentMissionBehavior(
                    playerParticipates, snapshot);
                SetStartingFor(settlement, startingTournament);

                var tournamentGame = Campaign.Current.Models.TournamentModel
                    .CreateTournament(settlement.Town);
                tournamentGame.PrepareForTournamentGame(playerParticipates);

                MissionState.Current.CurrentMission.AddMissionBehavior(startingTournament);
                startingTournament.PrepareForTournamentGame();

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

                ClearStartingFor(settlement);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[tournament] StartViewerTournament FAILED: {ex.Message}");
                ClearStartingFor(Settlement.CurrentSettlement);
            }
        }
    }
}
