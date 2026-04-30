using System;
using System.Collections.Generic;
using System.Linq;
using RimWorld;
using Verse;

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

        // ── Загрузка при старте ────────────────────────────────────────────────

        /// <summary>
        /// Проверяет, является ли пешка пешкой зрителя Twitch.
        /// Пешки зрителей имеют firstName="Twitch" и lastName="RimLink".
        /// </summary>
        private static bool IsViewerPawn(Pawn pawn)
        {
            if (pawn.Name is NameTriple t)
                return t.First == "Twitch" && t.Last == "RimLink";
            return false;
        }

        /// <summary>
        /// Сканирует текущую карту, регистрирует пешки зрителей Twitch, затем запускает
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
            if (Current.Game?.CurrentMap == null) return;

            _pawns.Clear();
            _corpses.Clear();
            _lastSentJson.Clear();
            _knownDeadPawns.Clear();

            // ── 1. Сканируем карту в главном потоке ──────────────────────────

            int count = 0;
            foreach (var pawn in Current.Game.CurrentMap.mapPawns.FreeColonistsAndPrisoners)
            {
                if (pawn == null) continue;
                if (!IsViewerPawn(pawn)) continue;

                string username = PawnDataBuilder.ExtractUsername(pawn);
                if (string.IsNullOrEmpty(username)) continue;

                _pawns[username] = pawn;
                count++;
                Log.Message($"[RimLink] Зарегистрирована пешка зрителя: {username}");
            }

            int corpseCount = 0;
            List<Thing> allThings = Current.Game.CurrentMap.listerThings.AllThings;
            foreach (var thing in allThings)
            {
                if (!(thing is Corpse corpse) || corpse.InnerPawn == null || corpse.Destroyed) continue;
                if (corpse.InnerPawn.Faction != Faction.OfPlayer) continue;
                if (!IsViewerPawn(corpse.InnerPawn)) continue;

                string username = PawnDataBuilder.ExtractUsername(corpse.InnerPawn);
                if (string.IsNullOrEmpty(username)) continue;

                _corpses[username] = corpse;
                corpseCount++;
                Log.Message($"[RimLink] Зарегистрирован труп: {username}");
            }

            Log.Message($"[RimLink] Загружено пешек: {count}, трупов: {corpseCount}");

            // ── 2. Собираем данные синхронно в главном потоке ─────────────────
            //    Это безопасно — читаем игровые объекты до того, как покинем главный поток.

            var bulkData = new List<Dictionary<string, object>>();

            foreach (var kv in _pawns)
            {
                try
                {
                    var data = PawnDataBuilder.BuildPawnData(kv.Key, kv.Value);
                    string json = Utils.SimpleJson.Serialize(data);
                    _lastSentJson[kv.Key] = json;
                    bulkData.Add(data);
                }
                catch (Exception e)
                {
                    Log.Warning($"[RimLink] LoadFromCurrentMap BuildPawnData({kv.Key}): {e.Message}");
                }
            }

            foreach (var kv in _corpses)
            {
                try
                {
                    var data = PawnDataBuilder.BuildCorpseData(kv.Key, kv.Value);
                    string json = Utils.SimpleJson.Serialize(data);
                    _lastSentJson[kv.Key] = json;
                    bulkData.Add(data);
                }
                catch (Exception e)
                {
                    Log.Warning($"[RimLink] LoadFromCurrentMap BuildCorpseData({kv.Key}): {e.Message}");
                }
            }

            // ── 3. Один фоновый поток: SessionStart → SyncPawnsBulk ───────────
            //    SessionStart() сначала чистит старые записи, потом мы заливаем свежие.
            //    Никаких параллельных потоков — гонка исключена.

            var capturedBulk = bulkData;
            new System.Threading.Thread(() =>
            {
                try
                {
                    RimLinkMod.API.SessionStart();
                    Log.Message("[RimLink] SessionStart выполнен.");

                    if (capturedBulk.Count > 0)
                    {
                        RimLinkMod.API.SyncPawnsBulk(capturedBulk);
                        Log.Message($"[RimLink] SyncPawnsBulk: отправлено {capturedBulk.Count} записей.");
                    }
                }
                catch (Exception ex)
                {
                    Log.Error($"[RimLink] LoadFromCurrentMap bg thread: {ex.Message}");
                }
            }) { IsBackground = true, Name = "RimLink-SessionStart" }.Start();
        }

        /// <summary>
        /// Проверяет, умерла ли какая-то из отслеживаемых пешек.
        /// Вызывать в главном потоке (например, в GameComponent.Tick или основном Update мода).
        /// </summary>
        public void CheckAndSyncDeaths()
        {
            foreach (var kv in _pawns.ToList())
            {
                var pawn = kv.Value;
                if (pawn == null || pawn.Destroyed || _knownDeadPawns.Contains(kv.Key) || !pawn.Dead)
                    continue;

                _knownDeadPawns.Add(kv.Key);
                Log.Message($"[RimLink] ⚰️ Поймана смерть: {kv.Key}. Отправка трупа на сервер...");

                Corpse corpse = FindCorpseOnMap(kv.Key);
                if (corpse != null && !corpse.Destroyed)
                {
                    SendCorpseData(kv.Key, corpse);
                }
                else
                {
                    var data = new Dictionary<string, object> { { "username", kv.Key }, { "is_alive", false } };
                    new System.Threading.Thread(() =>
                    {
                        try { RimLinkMod.API.SyncPawn(data); } catch { }
                    }) { IsBackground = true }.Start();
                }
            }
        }

        /// <summary>Регистрирует новую пешку (вызывается при создании пешки для зрителя).</summary>
        public void Register(string username, Pawn pawn)
        {
            _pawns[username] = pawn;
            if (_corpses.ContainsKey(username))
                _corpses.Remove(username);

            _lastSentJson.Remove(username);
            Log.Message($"[RimLink] Зарегистрирована пешка для {username}");
        }

        /// <summary>Удаляет пешку из управления.</summary>
        public void Unregister(string username)
        {
            if (_pawns.ContainsKey(username))
            {
                _pawns.Remove(username);
                _lastSentJson.Remove(username);
                Log.Message($"[RimLink] Пешка {username} удалена из управления");
            }

            if (_corpses.ContainsKey(username))
            {
                _corpses.Remove(username);
                Log.Message($"[RimLink] Труп {username} удален из управления");
            }
        }

        // ── Синхронизация ──────────────────────────────────────────────────────

        /// <summary>Синхронизирует всех известных пешек. Пропускает тех, данные которых не изменились.</summary>
        public void SyncAll()
        {
            var pawnDataList = CollectPawnData();
            if (pawnDataList.Count == 0) return;

            var captured = pawnDataList;
            new System.Threading.Thread(() =>
            {
                try { RimLinkMod.API.SyncPawnsBulk(captured); }
                catch (Exception ex) { Log.Warning($"[RimLink] SyncAll bulk: {ex.Message}"); }
            }) { IsBackground = true, Name = "RimLink-SyncAll" }.Start();
        }

        /// <summary>Собирает данные всех пешек для отправки (вызывать из главного потока).</summary>
        public List<Dictionary<string, object>> CollectPawnData()
        {
            var result = new List<Dictionary<string, object>>();
            var dead = new List<string>();
            var removedCorpses = new List<string>();

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

                    if (_lastSentJson.TryGetValue(kv.Key, out string prev) && prev == json)
                        continue;

                    _lastSentJson[kv.Key] = json;
                    result.Add(data);
                }
                catch (Exception e)
                {
                    Log.Warning($"[RimLink] CollectPawnData({kv.Key}): {e.Message}");
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

                    if (_lastSentJson.TryGetValue(kv.Key, out string prev) && prev == json)
                        continue;

                    _lastSentJson[kv.Key] = json;
                    result.Add(data);
                }
                catch (Exception e)
                {
                    Log.Warning($"[RimLink] CollectPawnData corpse({kv.Key}): {e.Message}");
                }
            }

            foreach (var username in dead)
            {
                _pawns.Remove(username);
                _lastSentJson.Remove(username);

                if (_knownDeadPawns.Contains(username))
                    continue;

                Corpse corpse = FindCorpseOnMap(username);
                if (corpse != null)
                {
                    _corpses[username] = corpse;
                    Log.Message($"[RimLink] Пешка {username} умерла, труп зарегистрирован");
                }
                else
                {
                    result.Add(new Dictionary<string, object>
                    {
                        { "username", username },
                        { "is_alive", false }
                    });
                    Log.Message($"[RimLink] Пешка {username} больше не на карте (Destroyed=true), снимаем с отслеживания");
                }

                _knownDeadPawns.Add(username);
            }

            foreach (var username in removedCorpses)
            {
                _corpses.Remove(username);
                _lastSentJson.Remove(username);
                result.Add(new Dictionary<string, object>
                {
                    { "username", username },
                    { "is_alive", false }
                });
                Log.Message($"[RimLink] Труп {username} больше не существует в игре (съеден/сожжён/похоронен), снят с отслеживания");
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

                if (!force && _lastSentJson.TryGetValue(username, out string prev) && prev == json)
                    return;

                _lastSentJson[username] = json;

                var capturedData = data;
                new System.Threading.Thread(() =>
                {
                    try { RimLinkMod.API.SyncPawn(capturedData); }
                    catch (Exception ex) { Log.Warning($"[RimLink] SyncPawn bg: {ex.Message}"); }
                }) { IsBackground = true }.Start();
            }
            catch (Exception e)
            {
                Log.Warning($"[RimLink] SendPawn({username}): {e.Message}");
            }
        }

        private void SendCorpseData(string username, Corpse corpse)
        {
            try
            {
                var data = PawnDataBuilder.BuildCorpseData(username, corpse);
                string json = Utils.SimpleJson.Serialize(data);

                _lastSentJson[username] = json;

                var capturedData = data;
                new System.Threading.Thread(() =>
                {
                    try { RimLinkMod.API.SyncPawn(capturedData); }
                    catch (Exception ex) { Log.Warning($"[RimLink] SyncCorpse bg: {ex.Message}"); }
                }) { IsBackground = true }.Start();
            }
            catch (Exception e)
            {
                Log.Warning($"[RimLink] SendCorpseData({username}): {e.Message}");
            }
        }

        // ── Действия ──────────────────────────────────────────────────────────

        /// <summary>Полностью исцеляет пешку зрителя.</summary>
        public bool HealPawn(string username)
        {
            if (!_pawns.TryGetValue(username, out var pawn) || pawn == null || pawn.Dead)
                return false;

            try
            {
                var toRemove = pawn.health.hediffSet.hediffs
                    .Where(h => h != null &&
                                h.def.isBad &&
                                !(h.def.hediffClass == typeof(Hediff_AddedPart)) &&
                                !(h.def.hediffClass?.Name == "Hediff_Implant") &&
                                !(h.def.hediffClass == typeof(Hediff_Implant)))
                    .ToList();

                foreach (var h in toRemove)
                    pawn.health.RemoveHediff(h);

                foreach (var part in pawn.health.hediffSet.GetMissingPartsCommonAncestors())
                {
                    if (part.Part != null)
                        pawn.health.RestorePart(part.Part);
                }

                Messages.Message($"💊 {username} полностью исцелён!", pawn, MessageTypeDefOf.PositiveEvent);
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] HealPawn: {e.Message}");
                return false;
            }
        }

        /// <summary>Воскрешает мёртвую пешку через ResurrectionSerum.</summary>
        public bool ResurrectPawn(string username)
        {
            Pawn pawn = null;
            Corpse corpse = null;

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
                    Log.Message($"[RimLink] 👤 {username} не мёртв или не найден.");
                    return false;
                }

                Log.Message($"[RimLink] ✨ Воскрешаем {username}...");
                bool success = ResurrectionUtility.TryResurrect(pawn);

                if (!success || pawn.Dead)
                {
                    Log.Warning($"[RimLink] ⚠️ Не удалось воскресить {username} (высокий урон/гниение).");
                    return false;
                }

                var sick = pawn.health.hediffSet.GetFirstHediffOfDef(HediffDefOf.ResurrectionSickness);
                if (sick != null) pawn.health.RemoveHediff(sick);

                if (Current.Game?.CurrentMap != null && !pawn.Spawned)
                    GenSpawn.Spawn(pawn, DropCellFinder.TradeDropSpot(Current.Game.CurrentMap), Current.Game.CurrentMap);

                _knownDeadPawns.Remove(username);
                if (_corpses.ContainsKey(username)) _corpses.Remove(username);

                if (corpse != null && !corpse.Destroyed)
                    corpse.Destroy();

                Register(username, pawn);
                SendPawn(username, pawn, force: true);

                Messages.Message($"✨ {username} воскрешён и вернулся в строй!", pawn, MessageTypeDefOf.PositiveEvent);
                return true;
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] ResurrectPawn: {e.Message}\n{e.StackTrace}");
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
                    Log.Warning($"[RimLink] DefName не найден: {defName}");
                    return false;
                }

                if (def.building != null || typeof(Building).IsAssignableFrom(def.thingClass))
                {
                    Log.Warning($"[RimLink] {defName} — это здание/структура, пропускаем EquipItem");
                    return false;
                }

                if (def.IsWeapon)
                {
                    var weapon = (ThingWithComps)ThingMaker.MakeThing(def, GenStuff.DefaultStuffFor(def));
                    pawn.equipment.DestroyAllEquipment();
                    pawn.equipment.AddEquipment(weapon);
                    Messages.Message($"⚔️ {username} получил {def.LabelCap.ToString() ?? def.label ?? def.defName}!", pawn, MessageTypeDefOf.PositiveEvent);
                    SendPawn(username, pawn, force: true);
                    return true;
                }

                if (def.IsApparel)
                {
                    var apparel = (Apparel)ThingMaker.MakeThing(def, GenStuff.DefaultStuffFor(def));

                    var conflicting = pawn.apparel.WornApparel
                        .Where(a => !ApparelUtility.CanWearTogether(def, a.def, pawn.RaceProps.body))
                        .ToList();

                    foreach (var c in conflicting)
                        pawn.apparel.Remove(c);

                    pawn.apparel.Wear(apparel, false, false);
                    Messages.Message($"👕 {username} надел {def.LabelCap.ToString() ?? def.label ?? def.defName}!", pawn, MessageTypeDefOf.PositiveEvent);
                    SendPawn(username, pawn, force: true);
                    return true;
                }

                Log.Warning($"[RimLink] {defName} — не оружие и не одежда");
                return false;
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] EquipItem: {e.Message}");
                return false;
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
                    Log.Warning($"[RimLink] HediffDef не найден: {defName}");
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

                    Log.Message($"[RimLink] Имплант {defName}: часть={bodyPartDef.defName}, кандидатов={candidates.Count}, hint={partHint}");

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
                    targetPart = pawn.RaceProps.body.corePart;

                if (pawn.health.hediffSet.hediffs.Any(h => h.def == hediffDef && h.Part == targetPart))
                {
                    Log.Message($"[RimLink] Имплант {defName} уже стоит на {targetPart.Label} у {username}");
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
                Log.Error($"[RimLink] InstallImplant: {e.Message}\n{e.StackTrace}");
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
                    Log.Warning($"[RimLink] TrainSkill: нейротренер '{neurotrainerDefName}' не найден");
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
                    Log.Warning($"[RimLink] TrainSkill: не удалось применить нейротренер {neurotrainerDefName}");
                    return false;
                }

                if (!thing.Destroyed) thing.Destroy();

                Messages.Message($"🧠 {username}: навык повышен нейротренером {def.LabelCap.ToString() ?? def.label ?? def.defName}!", pawn, MessageTypeDefOf.PositiveEvent);
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] TrainSkill: {e.Message}");
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
                Log.Warning($"[RimLink] SetPassion: у пешки {username} нет компонента навыков");
                return false;
            }

            try
            {
                SkillDef def = DefDatabase<SkillDef>.GetNamed(skillDefName, errorOnFail: false);
                if (def == null)
                {
                    Log.Warning($"[RimLink] SetPassion: SkillDef '{skillDefName}' не найден");
                    return false;
                }

                SkillRecord skill = pawn.skills.GetSkill(def);
                if (skill == null)
                {
                    Log.Warning($"[RimLink] SetPassion: навык {skillDefName} не найден у {username}");
                    return false;
                }

                if (skill.TotallyDisabled)
                {
                    Log.Warning($"[RimLink] SetPassion: навык {skillDefName} отключён у {username} (несовместимая черта)");
                    return false;
                }

                passion = System.Math.Max(0, System.Math.Min(2, passion));
                skill.passion = (Passion)passion;

                string icon = passion == 2 ? "🔥" : passion == 1 ? "⭐" : "—";
                string name = passion == 2 ? "Страсть" : passion == 1 ? "Интерес" : "нет страсти";
                Messages.Message(
                    $"{icon} {username}: {def.LabelCap} — {name}!",
                    pawn, MessageTypeDefOf.PositiveEvent);
                Log.Message($"[RimLink] SetPassion: {skillDefName} → passion={passion} ({name}) для {username}");
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] SetPassion: {e.Message}");
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
                    Log.Warning($"[RimLink] TraitDef не найден: {traitDefName}");
                    return false;
                }

                if (pawn.story.traits.HasTrait(def))
                {
                    Log.Message($"[RimLink] Черта {traitDefName} уже есть у {username}");
                    return false;
                }

                pawn.story.traits.GainTrait(new Trait(def, degree));
                Messages.Message($"🎭 {username} получил черту {def.LabelCap.ToString() ?? def.label ?? def.defName}!", pawn, MessageTypeDefOf.PositiveEvent);
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] AddTrait: {e.Message}");
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
                    Log.Warning($"[RimLink] TraitDef не найден: {traitDefName}");
                    return false;
                }

                var trait = pawn.story.traits.GetTrait(def);
                if (trait == null)
                {
                    Log.Message($"[RimLink] Черта {traitDefName} не найдена у {username}");
                    return false;
                }

                pawn.story.traits.RemoveTrait(trait);
                Messages.Message($"🎭 {username} потерял черту {def.LabelCap.ToString() ?? def.label ?? def.defName}", pawn, MessageTypeDefOf.NeutralEvent);
                SendPawn(username, pawn, force: true);
                return true;
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] RemoveTrait: {e.Message}");
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
        /// Находит труп персонажа из фракции игрока на текущей карте по имени.
        /// Намеренно ограничен фракцией игрока — не итерирует трупы рейдеров/животных.
        /// </summary>
        private Corpse FindCorpseOnMap(string username)
        {
            if (Current.Game?.CurrentMap == null) return null;

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

            List<Thing> allThings = Current.Game.CurrentMap.listerThings.AllThings;
            foreach (var thing in allThings)
            {
                if (!(thing is Corpse corpse) || corpse.InnerPawn == null || corpse.Destroyed) continue;
                if (corpse.InnerPawn.Faction != Faction.OfPlayer) continue;
                if (!IsViewerPawn(corpse.InnerPawn)) continue;

                string corpseUsername = PawnDataBuilder.ExtractUsername(corpse.InnerPawn);
                if (string.Equals(corpseUsername, username, StringComparison.OrdinalIgnoreCase))
                    return corpse;
            }

            return null;
        }

        /// <summary>Очищает все данные (при выгрузке карты или завершении игры).</summary>
        public void Clear()
        {
            _pawns.Clear();
            _corpses.Clear();
            _lastSentJson.Clear();
            Log.Message("[RimLink] PawnManager очищен");
        }
    }
}
