using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Helper для push'а full hero state на backend как `player.state_update` event.
    ///
    /// Sprint M19: расширяет state fields — gold + level + clan_name +
    /// kingdom_name + location + is_alive + is_prisoner. Дёргается из:
    ///   • AdoptHeroHandler — после adoption (initial state)
    ///   • SetClassHandler  — после class change (level/clan/kingdom могут
    ///     не меняться, но re-sync дешёвый, держит UI свежим)
    ///   • MainCampaignBehavior.OnHeroLevelledUp — level changed
    ///
    /// Backend whitelist (см. _adapter._on_player_state_update) принимает
    /// эти поля и UPDATE'ит bannerlord_heroes. Дополнительные поля игнорируются.
    ///
    /// Fire-and-forget — не блокирует main thread, ошибки log only.
    /// </summary>
    public static class HeroStateSync
    {
        /// <summary>Общий учёт отправок состояния — ОДИН на весь мод.
        ///
        /// 2026-09-09, вторая находка внешней проверки: `Push` ходила мимо
        /// трекера, поэтому событийный пуш (после покупки, левелапа, смены
        /// класса) шёл параллельно периодическому зеркалу и мог обогнать его.
        /// Сериализация в `PushIfChanged` этого не закрывала — она защищала
        /// только периодический путь. Теперь оба пути пользуются одним
        /// трекером, поэтому «в полёте» видит и тот, и другой.
        /// </summary>
        public static readonly StateSyncTracker Tracker = new StateSyncTracker();

        public static void Push(Hero hero)
        {
            string username;
            string json = BuildStateJson(hero, out username);
            if (json == null) return;
            // Через тот же трекер: если по герою уже летит снимок, этот пуш
            // пропускается, а актуальное состояние уедет ближайшим тиком
            // зеркала (не дольше 30 с). Отправить вдогонку значило бы вернуть
            // ту самую перестановку на сервере.
            StateSyncTracker.Attempt attempt;
            if (!Tracker.TryBeginSend(username, json, out attempt)) return;
            PostStateUpdate(username, json, Tracker, attempt);
            try
            {
                BannerlordLinkModule.Log(
                    $"[HeroStateSync] @{username} L{hero.Level} gold={hero.Gold} " +
                    $"clan={hero.Clan?.Name?.ToString() ?? "—"} " +
                    $"kingdom={hero.Clan?.Kingdom?.Name?.ToString() ?? "—"}");
            }
            catch { /* лог best-effort */ }
        }

        /// <summary>2026-06-05 — hash-gated вариант для периодического mirror-
        /// tick'а (MainCampaignBehavior.OnPropertiesTick). Строит ТОТ ЖЕ payload,
        /// но пушит ТОЛЬКО если сериализованный state изменился с прошлого раза
        /// (hashCache keyed by username). Возвращает true если запушили.
        /// Закрывает пробел: gold/level/skills зеркалятся без действий зрителя.</summary>
        /// 2026-09-09 — снимок считается доставленным только после ПОДТВЕРЖДЕНИЯ.
        /// Раньше хэш писался в кэш ДО отправки, а результат отправки
        /// выбрасывался: сбой сети означал, что неизменившийся снимок не уйдёт
        /// уже никогда, и зеркало замерзало до следующего изменения героя.
        /// Учёт вынесен в <see cref="StateSyncTracker"/> — он же держит защиту
        /// от обгона и от callback'ов прошлой сессии.
        public static bool PushIfChanged(Hero hero, StateSyncTracker tracker)
        {
            if (tracker == null) return false;
            string username;
            // JSON строится ЗДЕСЬ — на главном потоке. Всё, что уходит в
            // фоновую задачу ниже, это уже готовая строка: объекты движка из
            // другого потока не читаются.
            string json = BuildStateJson(hero, out username);
            if (json == null) return false;

            StateSyncTracker.Attempt attempt;
            if (!tracker.TryBeginSend(username, json, out attempt))
                return false;                 // ровно этот снимок уже подтверждён

            PostStateUpdate(username, json, tracker, attempt);
            return true;
        }

        /// <summary>POST player.state_update с учётом подтверждения.
        ///
        /// `PostEventAsync` возвращает true только если бэкенд подтвердил
        /// КОНКРЕТНЫЙ конверт (`acks[].success`), а не просто ответил
        /// `status: ok` — иначе отклонённое событие (например, тип не объявлен
        /// в манифесте) считалось бы доставленным.</summary>
        private static void PostStateUpdate(
            string username, string json,
            StateSyncTracker tracker = null,
            StateSyncTracker.Attempt attempt = default(StateSyncTracker.Attempt))
        {
            Task.Run(async () =>
            {
                bool ok = false;
                try
                {
                    ok = await BannerlordLinkModule.Backend
                        .PostEventAsync("bannerlord", "player.state_update", json);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[HeroStateSync] push @{username} failed: {ex.Message}");
                }
                finally
                {
                    // Отметку «в полёте» снимаем В ЛЮБОМ случае. Пропущенный
                    // вызов заблокировал бы отправку по этому герою навсегда:
                    // теперь на героя летит не больше одного запроса, и снять
                    // отметку больше некому.
                    if (tracker != null && attempt.IsValid)
                    {
                        if (ok)
                        {
                            if (!tracker.Confirm(attempt))
                                BannerlordLinkModule.Log(
                                    $"[HeroStateSync] @{username}: подтверждение устарело " +
                                    "(сменился сейв) — не кэшируем");
                        }
                        else
                        {
                            tracker.Fail(attempt);
                            BannerlordLinkModule.Log(
                                $"[HeroStateSync] @{username}: снимок НЕ подтверждён — " +
                                "повторим на следующем тике");
                        }
                    }
                }
            });
        }

        /// <summary>Строит JSON full-state payload для player.state_update.
        /// Возвращает null (+ username=null) если hero невалиден / не [BLink].
        /// Общий код для Push (событийный) и PushIfChanged (периодический).</summary>
        private static string BuildStateJson(Hero hero, out string username)
        {
            username = null;
            if (hero == null || hero.Name == null) return null;
            try
            {
                username = HeroNaming.ExtractUsername(hero.Name.ToString());
                if (string.IsNullOrEmpty(username)) return null;

                // Clan / Kingdom могут быть null (wanderer без клана / клан вне
                // королевства). Передаём явно null чтобы backend стёр поле
                // (e.g. heir после смерти лидера клана).
                string clanName = hero.Clan?.Name?.ToString();
                string kingdomName = hero.Clan?.Kingdom?.Name?.ToString();

                // Sprint 5.8: focus + attribute dicts для UI прогрессии.
                // {skill_stringId: {focus, level, xp}} / {attr_stringId: value}
                var skillsSnapshot = BuildSkillsSnapshot(hero);
                var attrsSnapshot = BuildAttributesSnapshot(hero);
                // Sprint 5.11: clan / kingdom info dicts для модалов.
                var clanInfo = BuildClanInfo(hero);
                var kingdomInfo = BuildKingdomInfo(hero);
                // Sprint 5.27c: family info (spouse + children + parents + siblings)
                var familyInfo = BuildFamilyInfo(hero);

                // Sprint 5.32 — is_wounded для KO state. Hero.IsWounded
                // возвращает true когда hero ранен в бою (KO'd, временно
                // не active). Через несколько дней оживёт автоматически.
                // ВАЖНО: IsAlive=true при IsWounded=true — KO != death.
                // Permanent death = IsAlive=false (через HeroKilledEvent).
                bool isWounded = false;
                try { isWounded = hero.IsWounded; }
                catch { /* old game version без IsWounded — оставляем false */ }

                var payload = new
                {
                    username      = username,
                    hero_id       = hero.StringId,
                    gold          = hero.Gold,
                    level         = hero.Level,
                    is_alive      = hero.IsAlive ? 1 : 0,
                    is_prisoner   = hero.IsPrisoner ? 1 : 0,
                    is_wounded    = isWounded ? 1 : 0,
                    is_female     = hero.IsFemale ? 1 : 0,
                    location      = hero.CurrentSettlement?.Name?.ToString(),
                    clan_name     = clanName,
                    kingdom_name  = kingdomName,
                    skills        = skillsSnapshot,
                    attributes    = attrsSnapshot,
                    clan_info     = clanInfo,
                    kingdom_info  = kingdomInfo,
                    family_info   = familyInfo,
                    party_info    = BuildPartyInfo(hero),
                };
                return JsonConvert.SerializeObject(payload);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroStateSync] BuildStateJson CRASHED: {ex.GetType().Name}: {ex.Message}");
                return null;
            }
        }

        /// <summary>Sprint 5.8: build snapshot всех skills с focus/level/xp.</summary>
        private static Dictionary<string, object> BuildSkillsSnapshot(Hero hero)
        {
            var result = new Dictionary<string, object>();
            try
            {
                if (hero?.HeroDeveloper == null) return result;
                var skills = MBObjectManager.Instance.GetObjectTypeList<SkillObject>();
                if (skills == null) return result;

                foreach (var s in skills)
                {
                    if (s == null) continue;
                    try
                    {
                        int focus = hero.HeroDeveloper.GetFocus(s);
                        int level = hero.GetSkillValue(s);
                        result[s.StringId] = new
                        {
                            level = level,
                            focus = focus,
                            name = s.Name?.ToString() ?? s.StringId,
                        };
                    }
                    catch { /* skill read failed — skip */ }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildSkillsSnapshot: {ex.Message}");
            }
            return result;
        }

        /// <summary>Sprint 5.11: clan info для modal.</summary>
        private static object BuildClanInfo(Hero hero)
        {
            try
            {
                var clan = hero?.Clan;
                if (clan == null) return null;
                return new
                {
                    name            = clan.Name?.ToString(),
                    leader_name     = clan.Leader?.Name?.ToString(),
                    is_leader       = clan.Leader == hero,
                    members_count   = clan.Heroes?.Count ?? 0,
                    tier            = clan.Tier,
                    renown          = (int)clan.Renown,
                    fiefs_count     = clan.Fiefs?.Count ?? 0,
                    parties_count   = clan.WarPartyComponents?.Count ?? 0,
                    culture         = clan.Culture?.StringId,
                    kingdom_name    = clan.Kingdom?.Name?.ToString(),
                };
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildClanInfo: {ex.Message}");
                return null;
            }
        }

        /// <summary>Sprint 5.11: kingdom info для modal.</summary>
        private static object BuildKingdomInfo(Hero hero)
        {
            try
            {
                var kingdom = hero?.Clan?.Kingdom;
                if (kingdom == null) return null;
                int atWarCount = 0;
                System.Collections.Generic.List<string> atWarNames = null;
                System.Collections.Generic.List<object> ownSettlements = null;
                System.Collections.Generic.List<object> enemySettlements = null;
                System.Collections.Generic.List<object> allKingdoms = null;
                try
                {
                    // 2026-06-14: рядом со счётчиком собираем имена враждующих
                    // королевств — фронт показывает их в скобках («Война с»).
                    var enemies = Kingdom.All?.Where(k => k != null && k != kingdom
                        && FactionManager.IsAtWarAgainstFaction(kingdom, k)).ToList();
                    atWarCount = enemies?.Count ?? 0;
                    atWarNames = enemies?
                        .Select(k => k.Name?.ToString())
                        .Where(n => !string.IsNullOrEmpty(n))
                        .ToList();

                    // 2026-06-14: списки городов для dropdown'а приказов отряда вместо
                    // ручного ввода. Защита/гарнизон → СВОИ, осада/грабёж → ВРАЖЕСКИЕ.
                    // {id=StringId, name, type=town/castle/village}. explicit foreach
                    // (надёжнее по типам, чем LINQ SelectMany).
                    // 2026-06-14 — примерные дни пути отряда до цели (прямая дистанция /
                    // скорость; rough, для «понимания» зрителю + сортировки во фронте).
                    var mpForDist = hero?.PartyBelongedTo;
                    System.Func<TaleWorlds.CampaignSystem.Settlements.Settlement, object> toObj = s =>
                    {
                        int days = 0;
                        try
                        {
                            if (mpForDist != null)
                            {
                                var pPos = mpForDist.GetPosition2D;     // рабочий accessor (см. TriggerWorldEventHandler)
                                var sPos = s.GatePosition.ToVec2();
                                float d = (pPos - sPos).Length;
                                float sp = mpForDist.Speed > 0.1f ? mpForDist.Speed : 4f;
                                days = (int)System.Math.Ceiling(d / sp);
                            }
                        }
                        catch { }
                        return new
                        {
                            id   = s.StringId,
                            name = s.Name?.ToString(),
                            type = s.IsTown ? "town" : (s.IsCastle ? "castle" : (s.IsVillage ? "village" : "other")),
                            days = days,
                        };
                    };
                    var ownList = new System.Collections.Generic.List<object>();
                    if (kingdom.Settlements != null)
                        foreach (var s in kingdom.Settlements)
                            if (s != null && (s.IsTown || s.IsCastle || s.IsVillage))
                                ownList.Add(toObj(s));
                    ownSettlements = ownList;

                    var enemyList = new System.Collections.Generic.List<object>();
                    if (enemies != null)
                        foreach (var k in enemies)
                        {
                            if (k?.Settlements == null) continue;
                            foreach (var s in k.Settlements)
                                if (s != null && (s.IsTown || s.IsCastle || s.IsVillage))
                                    enemyList.Add(toObj(s));
                        }
                    enemySettlements = enemyList;

                    // 2026-06-14: все королевства мира (кроме своего/элиминированных) +
                    // флаг at_war — для dropdown'а дипломатии (война = НЕ воюем, мир = воюем).
                    var akList = new System.Collections.Generic.List<object>();
                    if (Kingdom.All != null)
                        foreach (var k in Kingdom.All)
                            if (k != null && k != kingdom && !k.IsEliminated)
                                akList.Add(new
                                {
                                    id     = k.StringId,
                                    name   = k.Name?.ToString(),
                                    at_war = FactionManager.IsAtWarAgainstFaction(kingdom, k),
                                });
                    allKingdoms = akList;
                }
                catch { }
                return new
                {
                    id                = kingdom.StringId,                 // 2026-06-14: для kingdom-state derive
                    name              = kingdom.Name?.ToString(),
                    ruler_name        = kingdom.Leader?.Name?.ToString(),
                    is_ruler          = kingdom.Leader == hero,
                    is_clan_leader    = hero?.Clan?.Leader == hero,       // 2026-06-14: гейт политики/дипломатии
                    clans_count       = kingdom.Clans?.Count ?? 0,
                    fiefs_count       = kingdom.Fiefs?.Count ?? 0,
                    at_war_count      = atWarCount,
                    at_war_names      = atWarNames,
                    own_settlements   = ownSettlements,
                    enemy_settlements = enemySettlements,
                    all_kingdoms      = allKingdoms,
                    culture           = kingdom.Culture?.StringId,
                };
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildKingdomInfo: {ex.Message}");
                return null;
            }
        }

        /// <summary>2026-06-10 — party info для секции «Приказы отряда» в расширении:
        /// размер отряда + текущая задача движка (DefaultBehavior) + цель + в армии.</summary>
        private static object BuildPartyInfo(Hero hero)
        {
            try
            {
                var mp = hero?.PartyBelongedTo;
                if (mp == null) return null;
                string task = null;
                try { task = mp.DefaultBehavior.ToString(); } catch { }
                // Army MVP fast-follow — статус СВОЕЙ армии (лидер = наш герой).
                // has_army=1 только для лидера армии; в чужой армии in_army=1,
                // has_army=0. Поля аддитивные — фронт до вердикта Twitch их
                // не читает (см. ARMY_MVP_SPEC.md).
                var army = mp.Army;
                bool leadsArmy = army != null && army.LeaderParty == mp;
                return new
                {
                    size    = mp.MemberRoster.TotalManCount,
                    task    = task,          // engine AiBehavior: GoToSettlement / BesiegeSettlement / PatrolAroundPoint / Hold / EngageParty / ...
                    target  = mp.TargetSettlement?.Name?.ToString(),
                    in_army = army != null ? 1 : 0,
                    has_army         = leadsArmy ? 1 : 0,
                    army_party_count = leadsArmy ? (army.Parties?.Count ?? 1) : 0,
                    cohesion         = leadsArmy ? (int)army.Cohesion : 0,
                };
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildPartyInfo: {ex.Message}");
                return null;
            }
        }

        /// <summary>Sprint 5.8: build snapshot всех attributes.</summary>
        private static Dictionary<string, int> BuildAttributesSnapshot(Hero hero)
        {
            var result = new Dictionary<string, int>();
            try
            {
                var attrs = MBObjectManager.Instance.GetObjectTypeList<CharacterAttribute>();
                if (attrs == null) return result;
                foreach (var a in attrs)
                {
                    if (a == null) continue;
                    try { result[a.StringId] = hero.GetAttributeValue(a); }
                    catch { }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildAttributesSnapshot: {ex.Message}");
            }
            return result;
        }

        /// <summary>Sprint 5.27c: family info — spouse + children + parents + siblings.
        ///
        /// Sprint 5.31 #45e (audit MED-5) — каждое property-чтение в отдельный
        /// try/catch. Раньше TaleWorlds bug на `hero.Spouse?.IsPregnant` для
        /// dead spouse в 1.2.x ловился outer catch'ем → ВСЁ family_info уходило
        /// null'ом, UI не отличал "spouseless" от "engine threw". Теперь
        /// частичные пробои допустимы — отдаём то, что удалось прочитать.</summary>
        private static object BuildFamilyInfo(Hero hero)
        {
            try
            {
                if (hero == null) return null;

                // Safe-read helpers — каждое поле в своём try/catch.
                T Safe<T>(Func<T> getter, T fallback = default)
                {
                    try { return getter(); }
                    catch { return fallback; }
                }
                object SpouseObj(Hero s)
                {
                    if (s == null) return null;
                    return new
                    {
                        name        = Safe(() => s.Name?.ToString(), "?"),
                        age         = Safe(() => (int)s.Age, 0),
                        is_female   = Safe(() => s.IsFemale, false),
                        is_alive    = Safe(() => s.IsAlive, true),
                        // IsPregnant — known throw point для dead spouse в 1.2.x.
                        is_pregnant = Safe(() => s.IsPregnant, false),
                    };
                }
                System.Collections.Generic.List<object> ChildrenList(System.Collections.Generic.IEnumerable<Hero> kids)
                {
                    var list = new System.Collections.Generic.List<object>();
                    if (kids == null) return list;
                    foreach (var c in kids)
                    {
                        if (c == null) continue;
                        try
                        {
                            list.Add(new
                            {
                                name      = Safe(() => c.Name?.ToString(), "?"),
                                age       = Safe(() => (int)c.Age, 0),
                                is_female = Safe(() => c.IsFemale, false),
                                is_alive  = Safe(() => c.IsAlive, true),
                            });
                        }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[HeroStateSync] child entry skipped: {ex.Message}");
                        }
                    }
                    return list;
                }

                int siblingCount = Safe(
                    () => hero.Siblings?.Count(s => s != null && s.IsAlive) ?? 0, 0);
                return new
                {
                    spouse       = Safe<object>(() => SpouseObj(hero.Spouse)),
                    children     = ChildrenList(hero.Children),
                    father       = Safe<object>(() => SpouseObj(hero.Father)),
                    mother       = Safe<object>(() => SpouseObj(hero.Mother)),
                    sibling_count = siblingCount,
                };
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildFamilyInfo: {ex.Message}");
                return null;
            }
        }
    }
}
