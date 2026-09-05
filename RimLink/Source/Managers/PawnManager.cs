using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using RimWorld;
using Verse;
using RimLink.Components;

namespace RimLink.Managers
{
    /// <summary>
    /// Управляет пешками зрителей: регистрация, синхронизация данных на сервер,
    /// воскрешение, лечение.
    /// ВСЕ методы требуют вызова из главного потока Unity.
    /// </summary>
    public class PawnManager
    {
        // username (ник Twitch) → пешка
        private readonly Dictionary<string, Pawn> _pawns = new Dictionary<string, Pawn>(StringComparer.OrdinalIgnoreCase);

        // Кэш последнего состояния чтобы не спамить сервер одинаковыми данными
        // Хранит последний отправленный JSON для каждой пешки — для детекции изменений без коллизий хэшей
        private readonly Dictionary<string, string> _lastSentJson = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        // Кэш трупов для отслеживания мертвых персонажей
        private readonly Dictionary<string, Corpse> _corpses = new Dictionary<string, Corpse>(StringComparer.OrdinalIgnoreCase);

        // Кэш уже известных мёртвых пешек (чтобы не спамить сервер одним и тем же трупом)
        private readonly HashSet<string> _knownDeadPawns = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> _deathSyncInFlight = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, Dictionary<string, object>> _pendingSyncData =
            new Dictionary<string, Dictionary<string, object>>(StringComparer.OrdinalIgnoreCase);
        private readonly object _syncStateLock = new object();
        private readonly SemaphoreSlim _networkSyncGate = new SemaphoreSlim(1, 1);
        private int _sessionVersion;

        private sealed class SyncBatch
        {
            public readonly Dictionary<string, Dictionary<string, object>> Items =
                new Dictionary<string, Dictionary<string, object>>(StringComparer.OrdinalIgnoreCase);
            public readonly Dictionary<string, string> Snapshots =
                new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        }

        // ── Загрузка при старте ────────────────────────────────────────────────

        /// <summary>
        /// Проверяет, является ли пешка пешкой зрителя Twitch.
        /// Пешки зрителей имеют firstName="Twitch" и lastName="RimLink".
        /// </summary>
        private static bool IsViewerPawn(Pawn pawn)
        {
            if (ViewerIdentity.TryGetUsername(pawn, out _)) return true;
            if (pawn.Name is NameTriple t)
                return t.First == "Twitch" && t.Last == "RimLink";
            return false;
        }

        /// <summary>
        /// Сканирует все загруженные карты, регистрирует пешки зрителей Twitch, затем запускает
        /// ОДИН фоновый поток, который последовательно вызывает SessionStart() → SyncPawnsBulk().
        ///
        /// ИСПРАВЛЕНИЕ ГОНКИ ПОТОКОВ:
        ///   Раньше LoadFromCurrentMap() порождал по одному потоку на каждую пешку
        ///   (через SendPawn), а SessionStart() откладывался через LongEventHandler.
        ///   Фоновые потоки успевали добавить пешки в БД ДО того, как SessionStart()
        ///   их удалял — в результате живые пешки пропадали и не синхронизировались
        ///   заново до следующего SyncAll (50 с).
        ///
        ///   Теперь: данные собираются синхронно в главном потоке, после чего запускается
        ///   ровно один фоновый поток: SessionStart() → SyncPawnsBulk(). Никакой гонки.
        /// </summary>
        public void LoadFromCurrentMap()
        {
            if (Current.Game == null) return;
            var maps = (Find.Maps ?? new List<Map>())
                .Where(m => m != null)
                .Distinct()
                .ToList();
            if (maps.Count == 0 && Current.Game.CurrentMap != null)
                maps.Add(Current.Game.CurrentMap);

            _pawns.Clear();
            _corpses.Clear();
            int sessionVersion;
            lock (_syncStateLock)
            {
                sessionVersion = ++_sessionVersion;
                _lastSentJson.Clear();
                _knownDeadPawns.Clear();
                _deathSyncInFlight.Clear();
                _pendingSyncData.Clear();
            }

            // ── 1. Сканируем карту в главном потоке ──────────────────────────

            foreach (var pawn in PawnsFinder
                .AllMapsCaravansAndTravellingTransporters_Alive_FreeColonistsAndPrisoners)
            {
                if (pawn == null) continue;
                if (!IsViewerPawn(pawn)) continue;

                string username = PawnDataBuilder.ExtractUsername(pawn);
                if (string.IsNullOrEmpty(username)) continue;
                ViewerIdentity.Ensure(pawn, username); // миграция legacy-пешек по имени

                _pawns[username] = pawn;
                RimLinkLog.Msg($"[RimLink] Зарегистрирована пешка зрителя: {username}");
            }

            foreach (var map in maps)
            {
                foreach (var thing in map.listerThings.AllThings)
                {
                    if (!(thing is Corpse corpse) || corpse.InnerPawn == null || corpse.Destroyed) continue;
                    if (corpse.InnerPawn.Faction != Faction.OfPlayer) continue;
                    if (!IsViewerPawn(corpse.InnerPawn)) continue;

                    string username = PawnDataBuilder.ExtractUsername(corpse.InnerPawn);
                    if (string.IsNullOrEmpty(username)) continue;
                    ViewerIdentity.Ensure(corpse.InnerPawn, username);

                    _corpses[username] = corpse;
                    RimLinkLog.Msg($"[RimLink] Зарегистрирован труп: {username}");
                }
            }

            RimLinkLog.Msg($"[RimLink] Загружено пешек: {_pawns.Count}, трупов: {_corpses.Count}, карт: {maps.Count}");

            // ── 2. Собираем данные синхронно в главном потоке ─────────────────
            //    Это безопасно — читаем игровые объекты до того, как покинем главный поток.

            var bulkData = new List<Dictionary<string, object>>();
            var bulkSnapshots = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            foreach (var kv in _pawns)
            {
                try
                {
                    var data = PawnDataBuilder.BuildPawnData(kv.Key, kv.Value);
                    string json = Utils.SimpleJson.Serialize(data);
                    bulkSnapshots[kv.Key] = json;
                    bulkData.Add(data);
                }
                catch (Exception e)
                {
                    RimLinkLog.Warn($"[RimLink] LoadFromCurrentMap BuildPawnData({kv.Key}): {e.Message}");
                }
            }

            foreach (var kv in _corpses)
            {
                try
                {
                    var data = PawnDataBuilder.BuildCorpseData(kv.Key, kv.Value);
                    string json = Utils.SimpleJson.Serialize(data);
                    bulkSnapshots[kv.Key] = json;
                    bulkData.Add(data);
                }
                catch (Exception e)
                {
                    RimLinkLog.Warn($"[RimLink] LoadFromCurrentMap BuildCorpseData({kv.Key}): {e.Message}");
                }
            }

            // ── 3. Один фоновый поток: SessionStart → SyncPawnsBulk ───────────
            //    SessionStart() сначала чистит старые записи, потом мы заливаем свежие.
            //    Никаких параллельных потоков — гонка исключена.

            var capturedBulk = bulkData;
            var capturedSnapshots = bulkSnapshots;
            Task.Run(async () =>
            {
                await _networkSyncGate.WaitAsync().ConfigureAwait(false);
                try
                {
                    if (!IsSessionCurrent(sessionVersion)) return;
                    if (!RimLinkMod.API.SessionStart())
                        return;
                    if (!IsSessionCurrent(sessionVersion)) return;
                    RimLinkLog.Msg("[RimLink] SessionStart выполнен.");

                    if (capturedBulk.Count == 0 || RimLinkMod.API.SyncPawnsBulk(capturedBulk))
                    {
                        if (!IsSessionCurrent(sessionVersion)) return;
                        ApplySuccessfulSnapshots(capturedSnapshots);
                        if (capturedBulk.Count > 0)
                            RimLinkLog.Msg($"[RimLink] SyncPawnsBulk: отправлено {capturedBulk.Count} записей.");
                    }
                }
                catch (Exception ex)
                {
                    RimLinkLog.Err($"[RimLink] LoadFromCurrentMap bg thread: {ex.Message}");
                }
                finally { _networkSyncGate.Release(); }
            });
        }

        /// <summary>
        /// Проверяет, умерла ли какая-то из отслеживаемых пешек.
        /// Вызывать в главном потоке (например, в GameComponent.Tick или основном Update мода).
        /// </summary>
        public void CheckAndSyncDeaths()
        {
            foreach (var kv in _pawns.Concat(_corpses
                .Where(c => !_pawns.ContainsKey(c.Key))
                .Select(c => new KeyValuePair<string, Pawn>(c.Key, c.Value?.InnerPawn))).ToList())
            {
                var pawn = kv.Value;
                if (pawn != null && !pawn.Destroyed && !pawn.Dead)
                    continue;

                lock (_syncStateLock)
                {
                    if (_knownDeadPawns.Contains(kv.Key) || !_deathSyncInFlight.Add(kv.Key))
                        continue;
                }
                RimLinkLog.Msg($"[RimLink] ⚰️ Поймана смерть: {kv.Key}. Отправка трупа на сервер...");

                Corpse corpse = _corpses.TryGetValue(kv.Key, out var cached)
                    && cached != null && !cached.Destroyed ? cached : FindCorpseOnMap(kv.Key);
                if (corpse != null && !corpse.Destroyed)
                {
                    _corpses[kv.Key] = corpse;
                    SendCorpseData(kv.Key, corpse);
                }
                else
                {
                    var data = new Dictionary<string, object> { { "username", kv.Key }, { "is_alive", false } };
                    string username = kv.Key;
                    string json = Utils.SimpleJson.Serialize(data);
                    int sessionVersion = GetSessionVersion();
                    Task.Run(async () =>
                    {
                        await _networkSyncGate.WaitAsync().ConfigureAwait(false);
                        try
                        {
                            if (!IsSessionCurrent(sessionVersion)) return;
                            bool success = RimLinkMod.API.SyncPawn(data);
                            if (IsSessionCurrent(sessionVersion))
                                CompleteDeathSync(username, json, success, data);
                        }
                        catch (Exception ex)
                        {
                            if (IsSessionCurrent(sessionVersion))
                                CompleteDeathSync(username, json, false, data);
                            RimLinkLog.Warn($"[RimLink] SyncDeath bg: {ex.Message}");
                        }
                        finally { _networkSyncGate.Release(); }
                    });
                }
            }
        }

        /// <summary>Регистрирует новую пешку (вызывается при создании пешки для зрителя).</summary>
        public void Register(string username, Pawn pawn)
        {
            _pawns[username] = pawn;
            if (_corpses.ContainsKey(username))
                _corpses.Remove(username);

            lock (_syncStateLock)
            {
                _lastSentJson.Remove(username);
                _knownDeadPawns.Remove(username);
                _pendingSyncData.Remove(username);
            }
            RimLinkLog.Msg($"[RimLink] Зарегистрирована пешка для {username}");
        }

        /// <summary>Удаляет пешку из управления.</summary>
        public void Unregister(string username)
        {
            if (_pawns.ContainsKey(username))
            {
                _pawns.Remove(username);
                lock (_syncStateLock)
                {
                    _lastSentJson.Remove(username);
                    _knownDeadPawns.Remove(username);
                    _pendingSyncData.Remove(username);
                }
                RimLinkLog.Msg($"[RimLink] Пешка {username} удалена из управления");
            }

            if (_corpses.ContainsKey(username))
            {
                _corpses.Remove(username);
                RimLinkLog.Msg($"[RimLink] Труп {username} удален из управления");
            }
        }

        // ── Синхронизация ──────────────────────────────────────────────────────

        /// <summary>Синхронизирует всех известных пешек. Пропускает тех, данные которых не изменились.</summary>
        public void SyncAll()
        {
            var batch = CollectPawnData();
            if (batch.Items.Count == 0) return;

            var captured = batch.Items.Values.ToList();
            var capturedSnapshots = batch.Snapshots;
            int sessionVersion = GetSessionVersion();
            Task.Run(async () =>
            {
                await _networkSyncGate.WaitAsync().ConfigureAwait(false);
                try
                {
                    if (IsSessionCurrent(sessionVersion)
                        && RimLinkMod.API.SyncPawnsBulk(captured)
                        && IsSessionCurrent(sessionVersion))
                        ApplySuccessfulSnapshots(capturedSnapshots);
                }
                catch (Exception ex) { RimLinkLog.Warn($"[RimLink] SyncAll bulk: {ex.Message}"); }
                finally { _networkSyncGate.Release(); }
            });
        }

        /// <summary>Собирает данные всех пешек для отправки (вызывать из главного потока).</summary>
        private SyncBatch CollectPawnData()
        {
            var result = new SyncBatch();
            var dead = new List<string>();
            var removedCorpses = new List<string>();

            lock (_syncStateLock)
            {
                foreach (var kv in _pendingSyncData)
                {
                    result.Items[kv.Key] = kv.Value;
                    result.Snapshots[kv.Key] = Utils.SimpleJson.Serialize(kv.Value);
                }
            }

            foreach (var kv in _pawns.ToList())
            {
                var pawn = kv.Value;

                if (pawn == null || pawn.Destroyed)
                {
                    dead.Add(kv.Key);
                    continue;
                }

                try
                {
                    var data = PawnDataBuilder.BuildPawnData(kv.Key, pawn);
                    string json = Utils.SimpleJson.Serialize(data);

                    lock (_syncStateLock)
                    {
                        if (_lastSentJson.TryGetValue(kv.Key, out string prev) && prev == json)
                            continue;
                    }

                    result.Items[kv.Key] = data;
                    result.Snapshots[kv.Key] = json;
                }
                catch (Exception e)
                {
                    RimLinkLog.Warn($"[RimLink] CollectPawnData({kv.Key}): {e.Message}");
                }
            }

            foreach (var kv in _corpses.ToList())
            {
                var corpse = kv.Value;

                if (corpse == null || corpse.Destroyed || corpse.Map == null)
                {
                    removedCorpses.Add(kv.Key);
                    continue;
                }

                try
                {
                    var data = PawnDataBuilder.BuildCorpseData(kv.Key, corpse);
                    string json = Utils.SimpleJson.Serialize(data);

                    lock (_syncStateLock)
                    {
                        if (_lastSentJson.TryGetValue(kv.Key, out string prev) && prev == json)
                            continue;
                    }

                    result.Items[kv.Key] = data;
                    result.Snapshots[kv.Key] = json;
                }
                catch (Exception e)
                {
                    RimLinkLog.Warn($"[RimLink] CollectPawnData corpse({kv.Key}): {e.Message}");
                }
            }

            foreach (var username in dead)
            {
                _pawns.Remove(username);
                lock (_syncStateLock) _lastSentJson.Remove(username);

                lock (_syncStateLock)
                {
                    if (_knownDeadPawns.Contains(username))
                        continue;
                }

                Corpse corpse = FindCorpseOnMap(username);
                if (corpse != null)
                {
                    _corpses[username] = corpse;
                    // The corpse loop already ran: include this death in this batch.
                    var data = new Dictionary<string, object>
                    {
                        { "username", username }, { "is_alive", false }
                    };
                    result.Items[username] = data;
                    result.Snapshots[username] = Utils.SimpleJson.Serialize(data);
                    lock (_syncStateLock) _pendingSyncData[username] = data;
                    RimLinkLog.Msg($"[RimLink] Пешка {username} умерла, труп зарегистрирован");
                }
                else
                {
                    var data = new Dictionary<string, object>
                    {
                        { "username", username },
                        { "is_alive", false }
                    };
                    string json = Utils.SimpleJson.Serialize(data);
                    result.Items[username] = data;
                    result.Snapshots[username] = json;
                    lock (_syncStateLock) _pendingSyncData[username] = data;
                    RimLinkLog.Msg($"[RimLink] Пешка {username} больше не на карте (Destroyed=true), снимаем с отслеживания");
                }
            }

            foreach (var username in removedCorpses)
            {
                _corpses.Remove(username);
                lock (_syncStateLock) _lastSentJson.Remove(username);
                var data = new Dictionary<string, object>
                {
                    { "username", username },
                    { "is_alive", false }
                };
                string json = Utils.SimpleJson.Serialize(data);
                result.Items[username] = data;
                result.Snapshots[username] = json;
                lock (_syncStateLock) _pendingSyncData[username] = data;
                RimLinkLog.Msg($"[RimLink] Труп {username} больше не существует в игре (съеден/сожжён/похоронен), снят с отслеживания");
            }

            return result;
        }

        /// <summary>Принудительная синхронизация пешки с сервером (вызывается из команд).</summary>
        public void ForceSyncPawn(string username)
        {
            if (_pawns.TryGetValue(username, out var pawn) && pawn != null)
                SendPawn(username, pawn, force: true);
        }

        private void SendPawn(string username, Pawn pawn, bool force)
        {
            try
            {
                var data = PawnDataBuilder.BuildPawnData(username, pawn);
                string json = Utils.SimpleJson.Serialize(data);

                lock (_syncStateLock)
                {
                    if (!force && _lastSentJson.TryGetValue(username, out string prev) && prev == json)
                        return;
                }

                var capturedData = data;
                int sessionVersion = GetSessionVersion();
                Task.Run(async () =>
                {
                    await _networkSyncGate.WaitAsync().ConfigureAwait(false);
                    try
                    {
                        if (IsSessionCurrent(sessionVersion)
                            && RimLinkMod.API.SyncPawn(capturedData)
                            && IsSessionCurrent(sessionVersion))
                            ApplySuccessfulSnapshot(username, json);
                    }
                    catch (Exception ex) { RimLinkLog.Warn($"[RimLink] SyncPawn bg: {ex.Message}"); }
                    finally { _networkSyncGate.Release(); }
                });
            }
            catch (Exception e)
            {
                RimLinkLog.Warn($"[RimLink] SendPawn({username}): {e.Message}");
            }
        }

        private void SendCorpseData(string username, Corpse corpse)
        {
            try
            {
                var data = PawnDataBuilder.BuildCorpseData(username, corpse);
                string json = Utils.SimpleJson.Serialize(data);

                var capturedData = data;
                int sessionVersion = GetSessionVersion();
                Task.Run(async () =>
                {
                    await _networkSyncGate.WaitAsync().ConfigureAwait(false);
                    try
                    {
                        if (!IsSessionCurrent(sessionVersion)) return;
                        bool success = RimLinkMod.API.SyncPawn(capturedData);
                        if (IsSessionCurrent(sessionVersion))
                            CompleteDeathSync(username, json, success, capturedData);
                    }
                    catch (Exception ex)
                    {
                        if (IsSessionCurrent(sessionVersion))
                            CompleteDeathSync(username, json, false, capturedData);
                        RimLinkLog.Warn($"[RimLink] SyncCorpse bg: {ex.Message}");
                    }
                    finally { _networkSyncGate.Release(); }
                });
            }
            catch (Exception e)
            {
                lock (_syncStateLock) _deathSyncInFlight.Remove(username);
                RimLinkLog.Warn($"[RimLink] SendCorpseData({username}): {e.Message}");
            }
        }

        private void CompleteDeathSync(string username, string json, bool success,
            Dictionary<string, object> data)
        {
            lock (_syncStateLock)
            {
                _deathSyncInFlight.Remove(username);
                if (success)
                {
                    _lastSentJson[username] = json;
                    _knownDeadPawns.Add(username);
                    _pendingSyncData.Remove(username);
                }
                else
                {
                    _pendingSyncData[username] = data;
                }
            }
        }

        private void ApplySuccessfulSnapshot(string username, string json)
        {
            lock (_syncStateLock)
            {
                _lastSentJson[username] = json;
                if (_pendingSyncData.TryGetValue(username, out var pending)
                    && Utils.SimpleJson.Serialize(pending) == json)
                {
                    _pendingSyncData.Remove(username);
                    _knownDeadPawns.Add(username);
                }
            }
        }

        private void ApplySuccessfulSnapshots(Dictionary<string, string> snapshots)
        {
            if (snapshots == null) return;
            foreach (var kv in snapshots)
                ApplySuccessfulSnapshot(kv.Key, kv.Value);
        }

        private int GetSessionVersion()
        {
            lock (_syncStateLock) return _sessionVersion;
        }

        private bool IsSessionCurrent(int version)
        {
            lock (_syncStateLock) return version == _sessionVersion;
        }

        // ── Действия ──────────────────────────────────────────────────────────

        /// <summary>Полностью исцеляет пешку зрителя.</summary>
        public bool HealPawn(string username)
        {
            if (!_pawns.TryGetValue(username, out var pawn) || pawn == null || pawn.Dead)
                return false;

            bool mutated = false;
            try
            {
                var toRemove = pawn.health.hediffSet.hediffs
                    .Where(h => h != null &&
                                h.def.isBad &&
                                !(h.def.hediffClass == typeof(Hediff_AddedPart)) &&
                                !(h.def.hediffClass?.Name == "Hediff_Implant") &&
                                !(h.def.hediffClass == typeof(Hediff_Implant)))
                    .ToList();

                var missingParts = pawn.health.hediffSet.GetMissingPartsCommonAncestors()
                    .Where(part => part.Part != null)
                    .ToList();

                if (toRemove.Count == 0 && missingParts.Count == 0)
                    return false;

                foreach (var h in toRemove)
                {
                    pawn.health.RemoveHediff(h);
                    mutated = true;
                }

                foreach (var part in missingParts)
                {
                    pawn.health.RestorePart(part.Part);
                    mutated = true;
                }

                try { Messages.Message($"💊 {username} полностью исцелён!", pawn, MessageTypeDefOf.PositiveEvent); }
                catch (Exception ex) { RimLinkLog.Warn($"[RimLink] HealPawn message: {ex.Message}"); }
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                RimLinkLog.Err($"[RimLink] HealPawn: {e.Message}");
                // Если часть лечения уже применена, рефанд создал бы бесплатный
                // эффект. Считаем такую команду успешной и синхронизируем итог.
                if (mutated) SendPawn(username, pawn, force: true);
                return mutated;
            }
        }

        /// <summary>Воскрешает мёртвую пешку через ResurrectionSerum.</summary>
        public bool ResurrectPawn(string username)
        {
            Pawn pawn = null;
            Corpse corpse = null;
            bool resurrected = false;

            try
            {
                if (_pawns.TryGetValue(username, out var registered) && registered != null && !registered.Destroyed)
                    pawn = registered;

                if ((pawn == null || pawn.Dead) && _corpses.TryGetValue(username, out var cachedCorpse) && cachedCorpse?.InnerPawn != null)
                {
                    corpse = cachedCorpse;
                    pawn = corpse.InnerPawn;
                }

                if (pawn == null || !pawn.Dead)
                {
                    RimLinkLog.Msg($"[RimLink] 👤 {username} не мёртв или не найден.");
                    return false;
                }

                RimLinkLog.Msg($"[RimLink] ✨ Воскрешаем {username}...");
                Map resurrectionMap = corpse?.Map ?? pawn.MapHeld
                    ?? Current.Game?.CurrentMap ?? Find.AnyPlayerHomeMap;
                bool success = ResurrectionUtility.TryResurrect(pawn);

                if (!success || pawn.Dead)
                {
                    RimLinkLog.Warn($"[RimLink] ⚠️ Не удалось воскресить {username} (высокий урон/гниение).");
                    return false;
                }
                resurrected = true;

                try
                {
                    var sick = pawn.health.hediffSet.GetFirstHediffOfDef(HediffDefOf.ResurrectionSickness);
                    if (sick != null) pawn.health.RemoveHediff(sick);
                }
                catch (Exception ex) { RimLinkLog.Warn($"[RimLink] ResurrectPawn sickness: {ex.Message}"); }

                try
                {
                    if (resurrectionMap != null && !pawn.Spawned)
                        GenSpawn.Spawn(pawn, DropCellFinder.TradeDropSpot(resurrectionMap), resurrectionMap);
                }
                catch (Exception ex) { RimLinkLog.Warn($"[RimLink] ResurrectPawn spawn: {ex.Message}"); }

                lock (_syncStateLock)
                {
                    _knownDeadPawns.Remove(username);
                    _pendingSyncData.Remove(username);
                }
                if (_corpses.ContainsKey(username)) _corpses.Remove(username);

                try
                {
                    if (corpse != null && !corpse.Destroyed)
                        corpse.Destroy();
                }
                catch (Exception ex) { RimLinkLog.Warn($"[RimLink] ResurrectPawn corpse cleanup: {ex.Message}"); }

                Register(username, pawn);
                SendPawn(username, pawn, force: true);

                try { Messages.Message($"✨ {username} воскрешён и вернулся в строй!", pawn, MessageTypeDefOf.PositiveEvent); }
                catch (Exception ex) { RimLinkLog.Warn($"[RimLink] ResurrectPawn message: {ex.Message}"); }
                return true;
            }
            catch (Exception e)
            {
                RimLinkLog.Err($"[RimLink] ResurrectPawn: {e.Message}\n{e.StackTrace}");
                if (resurrected && pawn != null)
                {
                    Register(username, pawn);
                    SendPawn(username, pawn, force: true);
                    return true;
                }
                return false;
            }
        }

        /// <summary>Надевает предмет из DefDatabase на пешку.</summary>
        public bool EquipItem(string username, string defName)
        {
            if (!_pawns.TryGetValue(username, out var pawn) || pawn == null || pawn.Dead)
                return false;

            try
            {
                ThingDef def = DefDatabase<ThingDef>.GetNamed(defName, errorOnFail: false);
                if (def == null)
                {
                    RimLinkLog.Warn($"[RimLink] DefName не найден: {defName}");
                    return false;
                }

                if (def.building != null || typeof(Building).IsAssignableFrom(def.thingClass))
                {
                    RimLinkLog.Warn($"[RimLink] {defName} — это здание/структура, пропускаем EquipItem");
                    return false;
                }

                if (def.IsWeapon)
                {
                    var weapon = (ThingWithComps)ThingMaker.MakeThing(def, GenStuff.DefaultStuffFor(def));
                    ThingWithComps previous = pawn.equipment.Primary;
                    ThingWithComps dropped = null;

                    if (previous != null && pawn.Spawned
                        && !pawn.equipment.TryDropEquipment(previous, out dropped, pawn.Position, false))
                    {
                        weapon.Destroy();
                        RimLinkLog.Warn($"[RimLink] Не удалось безопасно снять старое оружие у {username}");
                        return false;
                    }
                    if (previous != null && !pawn.Spawned)
                    {
                        pawn.equipment.Remove(previous);
                        dropped = previous;
                    }

                    try
                    {
                        pawn.equipment.AddEquipment(weapon);
                    }
                    catch
                    {
                        if (!weapon.Destroyed) weapon.Destroy();
                        RestoreEquipment(pawn, dropped);
                        throw;
                    }

                    PreserveRemovedThing(pawn, dropped);

                    try { Messages.Message($"⚔️ {username} получил {def.LabelCap.ToString() ?? def.label ?? def.defName}!", pawn, MessageTypeDefOf.PositiveEvent); }
                    catch (Exception ex) { RimLinkLog.Warn($"[RimLink] EquipItem message: {ex.Message}"); }
                    SendPawn(username, pawn, force: true);
                    return true;
                }

                if (def.IsApparel)
                {
                    var apparel = (Apparel)ThingMaker.MakeThing(def, GenStuff.DefaultStuffFor(def));

                    var conflicting = pawn.apparel.WornApparel
                        .Where(a => !ApparelUtility.CanWearTogether(def, a.def, pawn.RaceProps.body))
                        .ToList();
                    var dropped = new List<Apparel>();

                    foreach (var c in conflicting)
                    {
                        Apparel removed;
                        bool removedOk;
                        if (pawn.Spawned)
                            removedOk = pawn.apparel.TryDrop(c, out removed, pawn.Position, false);
                        else
                        {
                            pawn.apparel.Remove(c);
                            removed = c;
                            removedOk = true;
                        }

                        if (!removedOk)
                        {
                            RestoreApparel(pawn, dropped);
                            apparel.Destroy();
                            RimLinkLog.Warn($"[RimLink] Не удалось безопасно снять конфликтующую одежду у {username}");
                            return false;
                        }
                        if (removed != null) dropped.Add(removed);
                    }

                    try
                    {
                        pawn.apparel.Wear(apparel, false, false);
                    }
                    catch
                    {
                        if (!apparel.Destroyed) apparel.Destroy();
                        RestoreApparel(pawn, dropped);
                        throw;
                    }

                    foreach (var item in dropped) PreserveRemovedThing(pawn, item);

                    try { Messages.Message($"👕 {username} надел {def.LabelCap.ToString() ?? def.label ?? def.defName}!", pawn, MessageTypeDefOf.PositiveEvent); }
                    catch (Exception ex) { RimLinkLog.Warn($"[RimLink] EquipItem message: {ex.Message}"); }
                    SendPawn(username, pawn, force: true);
                    return true;
                }

                RimLinkLog.Warn($"[RimLink] {defName} — не оружие и не одежда");
                return false;
            }
            catch (Exception e)
            {
                RimLinkLog.Err($"[RimLink] EquipItem: {e.Message}");
                return false;
            }
        }

        private static void RestoreEquipment(Pawn pawn, ThingWithComps equipment)
        {
            if (pawn?.equipment == null || equipment == null || equipment.Destroyed) return;
            try
            {
                if (equipment.Spawned) equipment.DeSpawn();
                pawn.equipment.AddEquipment(equipment);
            }
            catch (Exception ex)
            {
                RimLinkLog.Err($"[RimLink] Не удалось вернуть старое оружие: {ex.Message}");
            }
        }

        private static void PreserveRemovedThing(Pawn pawn, Thing thing)
        {
            if (thing == null || thing.Destroyed || thing.Spawned) return;
            try
            {
                if (pawn?.inventory?.innerContainer != null
                    && pawn.inventory.innerContainer.TryAdd(thing))
                    return;
                RimLinkLog.Warn($"[RimLink] Снятый предмет {thing.def?.defName} не удалось положить в инвентарь");
            }
            catch (Exception ex)
            {
                RimLinkLog.Warn($"[RimLink] Не удалось сохранить снятый предмет: {ex.Message}");
            }
        }

        private static void RestoreApparel(Pawn pawn, IEnumerable<Apparel> apparel)
        {
            if (pawn?.apparel == null || apparel == null) return;
            foreach (var item in apparel)
            {
                if (item == null || item.Destroyed) continue;
                try
                {
                    if (item.Spawned) item.DeSpawn();
                    pawn.apparel.Wear(item, false, false);
                }
                catch (Exception ex)
                {
                    RimLinkLog.Err($"[RimLink] Не удалось вернуть старую одежду: {ex.Message}");
                }
            }
        }

        /// <summary>Устанавливает имплант на пешку.</summary>
        public bool InstallImplant(string username, string defName)
        {
            return InstallImplant(username, defName, null);
        }

        /// <summary>Устанавливает имплант на пешку. partHint = "left" | "right" | ""</summary>
        public bool InstallImplant(string username, string defName, string partHint)
        {
            if (!_pawns.TryGetValue(username, out var pawn) || pawn == null || pawn.Dead)
                return false;

            try
            {
                HediffDef hediffDef = DefDatabase<HediffDef>.GetNamed(defName, errorOnFail: false);
                if (hediffDef == null)
                {
                    RimLinkLog.Warn($"[RimLink] HediffDef не найден: {defName}");
                    return false;
                }

                RecipeDef recipe = DefDatabase<RecipeDef>.AllDefs
                    .FirstOrDefault(r => r.addsHediff == hediffDef
                                     && r.appliedOnFixedBodyParts != null
                                     && r.appliedOnFixedBodyParts.Count > 0);

                BodyPartRecord targetPart = null;

                if (recipe != null)
                {
                    BodyPartDef bodyPartDef = recipe.appliedOnFixedBodyParts[0];
                    List<BodyPartRecord> candidates = pawn.health.hediffSet
                        .GetNotMissingParts()
                        .Where(p => p.def == bodyPartDef)
                        .ToList();

                    RimLinkLog.Msg($"[RimLink] Имплант {defName}: часть={bodyPartDef.defName}, кандидатов={candidates.Count}, hint={partHint}");

                    if (candidates.Count == 1)
                    {
                        targetPart = candidates[0];
                    }
                    else if (candidates.Count > 1)
                    {
                        string hint = (partHint ?? "").ToLowerInvariant().Trim();

                        if (hint == "left")
                            targetPart = candidates.FirstOrDefault(p => PawnDataBuilder.IsLeft(p)) ?? candidates.Last();
                        else if (hint == "right")
                            targetPart = candidates.FirstOrDefault(p => !PawnDataBuilder.IsLeft(p)) ?? candidates.First();
                        else
                            targetPart = candidates.FirstOrDefault(p =>
                                !pawn.health.hediffSet.hediffs.Any(h => h.def == hediffDef && h.Part == p))
                                ?? candidates[0];
                    }
                }

                if (targetPart == null)
                {
                    RimLinkLog.Warn($"[RimLink] Для импланта {defName} не найдена допустимая часть тела у {username}");
                    return false;
                }

                if (pawn.health.hediffSet.hediffs.Any(h => h.def == hediffDef && h.Part == targetPart))
                {
                    RimLinkLog.Msg($"[RimLink] Имплант {defName} уже стоит на {targetPart.Label} у {username}");
                    return false;
                }

                var hediff = HediffMaker.MakeHediff(hediffDef, pawn, targetPart);
                pawn.health.AddHediff(hediff);

                string partLabel = targetPart?.Label ?? "тело";
                Messages.Message($"🦾 {username} получил имплант {hediffDef.label} ({partLabel})!", pawn, MessageTypeDefOf.PositiveEvent);
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                RimLinkLog.Err($"[RimLink] InstallImplant: {e.Message}\n{e.StackTrace}");
                return false;
            }
        }

        /// <summary>
        /// Прокачивает навык пешки через нейротренер (defName вида "Neurotrainer_Shooting").
        /// Использует родную игровую механику — CompUseEffect_LearnSkill.DoEffect(pawn).
        /// </summary>
        public bool TrainSkill(string username, string neurotrainerDefName)
        {
            if (!_pawns.TryGetValue(username, out var pawn) || pawn == null || pawn.Dead)
                return false;

            try
            {
                ThingDef def = DefDatabase<ThingDef>.GetNamed(neurotrainerDefName, errorOnFail: false);
                if (def == null)
                {
                    RimLinkLog.Warn($"[RimLink] TrainSkill: нейротренер '{neurotrainerDefName}' не найден");
                    return false;
                }

                var thing = ThingMaker.MakeThing(def);
                bool applied = false;

                var comp = thing.TryGetComp<CompUsable>();
                if (comp != null)
                {
                    comp.UsedBy(pawn);
                    applied = true;
                }
                else
                {
                    var learnComp = thing.TryGetComp<CompUseEffect_LearnSkill>();
                    if (learnComp != null)
                    {
                        learnComp.DoEffect(pawn);
                        applied = true;
                    }
                }

                if (!applied)
                {
                    RimLinkLog.Warn($"[RimLink] TrainSkill: не удалось применить нейротренер {neurotrainerDefName}");
                    return false;
                }

                if (!thing.Destroyed) thing.Destroy();

                Messages.Message($"🧠 {username}: навык повышен нейротренером {def.LabelCap.ToString() ?? def.label ?? def.defName}!", pawn, MessageTypeDefOf.PositiveEvent);
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                RimLinkLog.Err($"[RimLink] TrainSkill: {e.Message}");
                return false;
            }
        }

        /// <summary>
        /// Устанавливает уровень страсти (Passion) к навыку.
        /// passion: 0 = None, 1 = Minor (⭐), 2 = Major (🔥)
        /// </summary>
        public bool SetPassion(string username, string skillDefName, int passion)
        {
            if (!_pawns.TryGetValue(username, out var pawn) || pawn == null || pawn.Dead)
                return false;

            if (pawn.skills == null)
            {
                RimLinkLog.Warn($"[RimLink] SetPassion: у пешки {username} нет компонента навыков");
                return false;
            }

            try
            {
                SkillDef def = DefDatabase<SkillDef>.GetNamed(skillDefName, errorOnFail: false);
                if (def == null)
                {
                    RimLinkLog.Warn($"[RimLink] SetPassion: SkillDef '{skillDefName}' не найден");
                    return false;
                }

                SkillRecord skill = pawn.skills.GetSkill(def);
                if (skill == null)
                {
                    RimLinkLog.Warn($"[RimLink] SetPassion: навык {skillDefName} не найден у {username}");
                    return false;
                }

                if (skill.TotallyDisabled)
                {
                    RimLinkLog.Warn($"[RimLink] SetPassion: навык {skillDefName} отключён у {username} (несовместимая черта)");
                    return false;
                }

                passion = System.Math.Max(0, System.Math.Min(2, passion));
                if ((int)skill.passion == passion)
                {
                    RimLinkLog.Msg($"[RimLink] SetPassion: у {username} уже установлен passion={passion} для {skillDefName}");
                    return false;
                }
                skill.passion = (Passion)passion;

                string icon = passion == 2 ? "🔥" : passion == 1 ? "⭐" : "—";
                string name = passion == 2 ? "Страсть" : passion == 1 ? "Интерес" : "нет страсти";
                Messages.Message(
                    $"{icon} {username}: {def.LabelCap} — {name}!",
                    pawn, MessageTypeDefOf.PositiveEvent);
                RimLinkLog.Msg($"[RimLink] SetPassion: {skillDefName} → passion={passion} ({name}) для {username}");
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                RimLinkLog.Err($"[RimLink] SetPassion: {e.Message}");
                return false;
            }
        }

        /// <summary>Добавляет черту характера пешке.</summary>
        public bool AddTrait(string username, string traitDefName, int degree = 0)
        {
            if (!_pawns.TryGetValue(username, out var pawn) || pawn?.story?.traits == null || pawn.Dead)
                return false;

            try
            {
                TraitDef def = DefDatabase<TraitDef>.GetNamed(traitDefName, errorOnFail: false);
                if (def == null)
                {
                    RimLinkLog.Warn($"[RimLink] TraitDef не найден: {traitDefName}");
                    return false;
                }

                if (pawn.story.traits.HasTrait(def))
                {
                    RimLinkLog.Msg($"[RimLink] Черта {traitDefName} уже есть у {username}");
                    return false;
                }

                pawn.story.traits.GainTrait(new Trait(def, degree));
                Messages.Message($"🎭 {username} получил черту {def.LabelCap.ToString() ?? def.label ?? def.defName}!", pawn, MessageTypeDefOf.PositiveEvent);
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                RimLinkLog.Err($"[RimLink] AddTrait: {e.Message}");
                return false;
            }
        }

        /// <summary>Удаляет черту характера у пешки.</summary>
        public bool RemoveTrait(string username, string traitDefName)
        {
            if (!_pawns.TryGetValue(username, out var pawn) || pawn?.story?.traits == null || pawn.Dead)
                return false;

            try
            {
                TraitDef def = DefDatabase<TraitDef>.GetNamed(traitDefName, errorOnFail: false);
                if (def == null)
                {
                    RimLinkLog.Warn($"[RimLink] TraitDef не найден: {traitDefName}");
                    return false;
                }

                var trait = pawn.story.traits.GetTrait(def);
                if (trait == null)
                {
                    RimLinkLog.Msg($"[RimLink] Черта {traitDefName} не найдена у {username}");
                    return false;
                }

                pawn.story.traits.RemoveTrait(trait);
                Messages.Message($"🎭 {username} потерял черту {def.LabelCap.ToString() ?? def.label ?? def.defName}", pawn, MessageTypeDefOf.NeutralEvent);
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                RimLinkLog.Err($"[RimLink] RemoveTrait: {e.Message}");
                return false;
            }
        }

        // ── Геттеры ────────────────────────────────────────────────────────────

        public bool TryGetPawn(string username, out Pawn pawn)
        {
            if (_pawns.TryGetValue(username, out pawn) && pawn != null && !pawn.Destroyed)
                return true;

            if (_corpses.TryGetValue(username, out var corpse) && corpse != null && !corpse.Destroyed)
            {
                pawn = corpse.InnerPawn;
                return pawn != null;
            }

            pawn = null;
            return false;
        }

        public Pawn GetPawn(string username)
        {
            if (_pawns.TryGetValue(username, out var p) && p != null && !p.Destroyed)
                return p;

            if (_corpses.TryGetValue(username, out var corpse) && corpse != null && !corpse.Destroyed)
                return corpse.InnerPawn;

            return null;
        }

        public bool HasPawn(string username)
        {
            return (_pawns.ContainsKey(username) && _pawns[username] != null && !_pawns[username].Destroyed) ||
                   (_corpses.ContainsKey(username) && _corpses[username] != null && !_corpses[username].Destroyed);
        }

        public List<Pawn> GetAllPawns()
        {
            var result = _pawns.Values.ToList();
            result.AddRange(_corpses.Values.Select(c => c.InnerPawn));
            return result;
        }

        /// <summary>
        /// Находит труп персонажа из фракции игрока на любой загруженной карте по identity.
        /// Намеренно ограничен фракцией игрока — не итерирует трупы рейдеров/животных.
        /// </summary>
        private Corpse FindCorpseOnMap(string username)
        {
            if (Current.Game == null) return null;

            if (_pawns.TryGetValue(username, out var knownPawn) && knownPawn != null && !knownPawn.Destroyed)
            {
                try
                {
                    var direct = knownPawn.Corpse;
                    if (direct != null && !direct.Destroyed && direct.Map != null)
                        return direct;
                }
                catch { /* pawn.Corpse недоступен в этой версии — fallback ниже */ }
            }

            foreach (var map in Find.Maps ?? new List<Map>())
            {
                if (map == null) continue;
                foreach (var thing in map.listerThings.AllThings)
                {
                    if (!(thing is Corpse corpse) || corpse.InnerPawn == null || corpse.Destroyed) continue;
                    if (corpse.InnerPawn.Faction != Faction.OfPlayer) continue;
                    if (!IsViewerPawn(corpse.InnerPawn)) continue;

                    string corpseUsername = PawnDataBuilder.ExtractUsername(corpse.InnerPawn);
                    if (string.Equals(corpseUsername, username, StringComparison.OrdinalIgnoreCase))
                        return corpse;
                }
            }

            return null;
        }

        /// <summary>Очищает все данные (при выгрузке карты или завершении игры).</summary>
        public void Clear()
        {
            _pawns.Clear();
            _corpses.Clear();
            lock (_syncStateLock)
            {
                _sessionVersion++;
                _lastSentJson.Clear();
                _knownDeadPawns.Clear();
                _deathSyncInFlight.Clear();
                _pendingSyncData.Clear();
            }
            RimLinkLog.Msg("[RimLink] PawnManager очищен");
        }
    }
}
