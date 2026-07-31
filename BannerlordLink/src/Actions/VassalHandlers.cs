using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.Library;
using TaleWorlds.Localization;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity VAS) — Vassal sub-clan management handlers.
    ///
    /// 3 handlers:
    ///   - CreateVassalClanHandler — hero.create_vassal_clan
    ///     Backend payload: {parent_username, heir_hero_id, heir_name, vassal_name,
    ///                       placeholder_clan_id}.
    ///     Logic: resolve heir → CreateClan(name) → SetInitialHomeSettlement →
    ///            ChangeClanLeader to heir → heir.Clan = newClan → push event
    ///            `hero.vassal_created` с real clan_id для backend backfill.
    ///
    ///   - RecruitVassalClanHandler — hero.recruit_vassal_clan (2026-06-17)
    ///     Backend payload: {initiated_by, [clan_name]}.
    ///     Logic: RULER-only. Generate fresh NPC lord of kingdom culture →
    ///            CreateClan → join OWNER's kingdom as vassal → charge 3M dinars.
    ///            NO party/troops (engine-managed), NO auto-follow (real vassal).
    ///
    ///   - RenameVassalHandler — hero.rename_vassal
    ///     Backend payload: {vassal_clan_id, new_name, old_name}.
    ///     Logic: resolve Clan → ChangeClanName.
    /// </summary>
    public class CreateVassalClanHandler : IActionHandler
    {
        public string ActionType => "hero.create_vassal_clan";

        // 2026-05-29 currency re-map: вассал-клан платится динарами инициатора
        // (parentUser), как обычный клан (CreateClanHandler — 1M). MIRROR
        // VASSAL_GOLD_COST в bannerlord_vassals.py (backend pre-check кэша).
        private const int VASSAL_GOLD_COST = 250_000;

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string parentUser = (data["parent_username"]?.ToString() ?? "").ToLowerInvariant();
            string heirId = (data["heir_hero_id"]?.ToString() ?? "").Trim();
            string heirName = data["heir_name"]?.ToString() ?? heirId;
            string vassalName = (data["vassal_name"]?.ToString() ?? "").Trim();
            string placeholderClanId = (data["placeholder_clan_id"]?.ToString() ?? "").Trim();

            if (string.IsNullOrEmpty(heirId) || string.IsNullOrEmpty(vassalName) ||
                string.IsNullOrEmpty(placeholderClanId))
                return Task.FromResult<(bool, string)>((false, "missing params"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
                Create(parentUser, heirId, heirName, vassalName, placeholderClanId, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Create(string parentUser, string heirId, string heirName,
            string vassalName, string placeholderClanId, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }

                // 2026-07-31: см. Util/HeroResolver.cs — heirId это id
                // CharacterObject, поиском по Hero он не находился (7 отказов
                // из 7 на проде).
                Hero heir = HeroResolver.ByStringId(heirId, out string _heirReason);
                if (heir == null || !heir.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[vassal.create] REFUSE: heir '{heirName}' ({heirId}) not found/alive");
                    ActionFeedback.PostFailed(actionId, "heir_not_found");
                    return;
                }

                // 2026-05-29 currency re-map: резолвим инициатора (parentUser) и
                // проверяем его Hero.Gold ДО создания клана — чтобы не плодить
                // clan при нехватке. Backend уже проверил кэш, здесь —
                // авторитетная проверка по live-золоту.
                Hero parentHero = null;
                try { parentHero = HeroLookup.FindByUsername(parentUser); } catch { }
                if (parentHero == null || !parentHero.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[vassal.create] REFUSE: parent @{parentUser} not found/alive");
                    ActionFeedback.PostFailed(actionId, "parent_not_found");
                    return;
                }
                if (parentHero.Gold < VASSAL_GOLD_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[vassal.create] REFUSE @{parentUser}: not enough hero gold " +
                        $"({parentHero.Gold} < {VASSAL_GOLD_COST})");
                    ActionFeedback.PostFailed(actionId, "not_enough_hero_gold");
                    return;
                }

                // Create new Clan через engine API. Pattern из CreateClanHandler.
                var nameObj = new TextObject(vassalName);
                Clan newClan = Clan.CreateClan(vassalName);  // engine assigns StringId
                if (newClan == null)
                {
                    BannerlordLinkModule.Log("[vassal.create] CreateClan returned null");
                    ActionFeedback.PostFailed(actionId, "clan_create_failed");
                    return;
                }
                newClan.ChangeClanName(nameObj, nameObj);
                newClan.Culture = heir.Culture;
                if (newClan.Banner == null)
                {
                    try { newClan.Banner = Banner.CreateRandomBanner(); }
                    catch (Exception bex)
                    {
                        BannerlordLinkModule.Log($"[vassal.create] banner warn: {bex.Message}");
                    }
                }
                // Vassal kingdom = parent's kingdom (если есть). MVP — null (independent).
                newClan.Kingdom = null;
                // Stand-alone clan; small renown starter
                newClan.AddRenown(50f, false);
                // Home settlement — heir's current settlement OR fallback to parent's home.
                try
                {
                    var home = heir.HomeSettlement ?? heir.CurrentSettlement;
                    if (home != null) newClan.SetInitialHomeSettlement(home);
                }
                catch { }
                newClan.IsNoble = true;

                // Transfer heir into new clan as leader.
                heir.Clan = newClan;
                // 2026-07-31, ПОСЛЕ КРАША ИГРЫ. Здесь исключение ПРОГЛАТЫВАЛОСЬ, и
                // код ехал дальше: создавал клан БЕЗ ЛИДЕРА, списывал 250 000💰 и
                // регистрировал автоследование. Игра падала на следующем тике.
                //
                // Почему падало назначение: `ChangeClanLeaderAction` — это СМЕНА
                // существующего лидера, движок внутри обращается к текущему
                // (`clan.Leader`). У только что созданного клана его нет → NRE.
                //
                // Путь этот до 31.07 вообще не исполнялся: поиск наследника падал
                // раньше (7 отказов из 7), и поломка была не видна. Починив поиск,
                // я её и вскрыл — а проглоченное исключение превратило её в краш
                // вместо честного отказа.
                //
                // Теперь: не смогли поставить лидера — откатываем всё и отказываем.
                // Лучше зритель получит деньги назад, чем сломанный клан в сейве.
                bool leaderOk = false;
                try
                {
                    ChangeClanLeaderAction.ApplyWithSelectedNewLeader(newClan, heir);
                    leaderOk = newClan.Leader == heir;
                }
                catch (Exception lex)
                {
                    BannerlordLinkModule.Log($"[vassal.create] SetLeader упал: {lex.Message}");
                }
                if (!leaderOk)
                {
                    BannerlordLinkModule.Log(
                        "[vassal.create] ОТКАЗ: лидер клана не назначен — откатываем, "
                        + "иначе в кампании остаётся клан без лидера (краш 31.07)");
                    try
                    {
                        heir.Clan = parentHero != null ? parentHero.Clan : null;
                        DestroyClanAction.Apply(newClan);
                    }
                    catch (Exception dex)
                    {
                        BannerlordLinkModule.Log($"[vassal.create] откат клана: {dex.Message}");
                    }
                    ActionFeedback.PostFailed(actionId, "clan_leader_not_set");
                    return;
                }

                // Списать стоимость вассал-клана с инициатора (динары).
                try
                {
                    GiveGoldAction.ApplyBetweenCharacters(parentHero, null, VASSAL_GOLD_COST, true);
                    BannerlordLinkModule.Log(
                        $"[vassal.create] @{parentUser}: -{VASSAL_GOLD_COST}💰, gold={parentHero.Gold}");
                }
                catch (Exception gex)
                {
                    BannerlordLinkModule.Log($"[vassal.create] gold deduct warn: {gex.Message}");
                }

                string realClanId = newClan.StringId ?? "";
                BannerlordLinkModule.Log(
                    $"[vassal.create] OK: parent=@{parentUser} heir='{heirName}' " +
                    $"vassal='{vassalName}' clan_id={realClanId}");

                // 2026-05-29 Stage 7 (BLT-RC22 pattern) — register vassal с
                // VassalAutoFollowBehavior. Это значит на любой kingdom move /
                // war / peace master'а (parentUser) — этот vassal автоматически
                // следует за ним. См. Behaviors/VassalAutoFollowBehavior.cs.
                try
                {
                    BannerlordLink.Behaviors.VassalAutoFollowBehavior.Current?
                        .RegisterVassal(newClan, parentUser);
                }
                catch (Exception vex)
                {
                    BannerlordLinkModule.Log(
                        $"[vassal.create] auto-follow register warn: {vex.Message}");
                }

                // Push event для backend backfill (placeholder_clan_id → real_clan_id).
                string evtData = JsonConvert.SerializeObject(new
                {
                    placeholder_clan_id = placeholderClanId,
                    real_clan_id = realClanId,
                    parent_username = parentUser,
                    heir_hero_id = heirId,
                    vassal_name = vassalName,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.vassal_created", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[vassal.create] CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed:" + ex.Message);
            }
        }
    }

    // ── RecruitVassalClanHandler ───────────────────────────────────────────────
    /// <summary>
    /// 2026-06-17 — hero.recruit_vassal_clan. Правитель королевства нанимает свежий
    /// NPC-вассальный клан (tier-1) в СВОЁ королевство за 3M динаров.
    ///
    /// MIRROR CreateVassalClanHandler, но 2 отличия:
    ///   (a) лидер — свежесгенерированный NPC-лорд культуры королевства, НЕ heir;
    ///   (b) клан сразу вступает вассалом в королевство правителя (не independent).
    ///
    /// Без стартовой партии/войск — движок сам управляет кланом дальше. Без
    /// VassalAutoFollow — это настоящий engine-managed вассал королевства. Лимита
    /// нет: цена 3M — единственный ограничитель.
    /// </summary>
    public class RecruitVassalClanHandler : IActionHandler
    {
        public string ActionType => "hero.recruit_vassal_clan";

        // MIRROR backend RECRUIT_VASSAL_COST (routes/bannerlord.py pre-check).
        // Списывается с инициатора (правителя) ПОСЛЕ успешного создания клана.
        private const int RECRUIT_VASSAL_COST = 3_000_000;

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            // optional clan name; пусто → auto-generate из имени NPC-лидера.
            string clanName = (data["clan_name"]?.ToString() ??
                               data["vassal_name"]?.ToString() ?? "").Trim();

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Recruit(username, clanName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Recruit(string username, string clanName, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }

                Hero hero;
                try { hero = HeroLookup.FindByUsername(username); }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[recruit_vassal] FindByUsername('{username}') crashed: {ex.Message}");
                    ActionFeedback.PostFailed(actionId, "hero_lookup_crash");
                    return;
                }
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[recruit_vassal] REFUSE @{username}: hero not found/alive");
                    ActionFeedback.PostFailed(actionId, "hero_not_found");
                    return;
                }
                if (hero.IsPrisoner)
                {
                    BannerlordLinkModule.Log($"[recruit_vassal] REFUSE @{username}: prisoner");
                    ActionFeedback.PostFailed(actionId, "hero_prisoner");
                    return;
                }
                if (hero.Clan == null || !hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[recruit_vassal] REFUSE @{username}: not clan leader");
                    ActionFeedback.PostFailed(actionId, "not_clan_leader");
                    return;
                }
                Kingdom kingdom = hero.Clan.Kingdom;
                if (kingdom == null)
                {
                    BannerlordLinkModule.Log($"[recruit_vassal] REFUSE @{username}: no kingdom");
                    ActionFeedback.PostFailed(actionId, "no_kingdom");
                    return;
                }
                // Только ПРАВИТЕЛЬ королевства (ruling clan / kingdom leader).
                bool isRuler = (kingdom.RulingClan == hero.Clan) || (kingdom.Leader == hero);
                if (!isRuler)
                {
                    BannerlordLinkModule.Log(
                        $"[recruit_vassal] REFUSE @{username}: not ruler of '{kingdom.Name}'");
                    ActionFeedback.PostFailed(actionId, "not_ruler");
                    return;
                }
                // Золото — ДО создания NPC/клана (не плодим сущности при нехватке).
                if (hero.Gold < RECRUIT_VASSAL_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[recruit_vassal] REFUSE @{username}: not enough gold " +
                        $"({hero.Gold} < {RECRUIT_VASSAL_COST})");
                    ActionFeedback.PostFailed(actionId, "not_enough_hero_gold");
                    return;
                }

                CultureObject culture = kingdom.Culture ?? hero.Culture;
                var rng = new Random();

                // 1. Culture-appropriate lord template (pattern из AdoptHeroHandler,
                //    но Occupation.Lord). Fallbacks держат robust на edge/modded культурах.
                CharacterObject template = null;
                try
                {
                    var allChars = MBObjectManager.Instance.GetObjectTypeList<CharacterObject>();
                    var pool = allChars.Where(c => c != null && c.Occupation == Occupation.Lord
                                   && c.Culture == culture).ToList();
                    if (pool.Count == 0)
                        pool = allChars.Where(c => c != null && c.Occupation == Occupation.Wanderer
                                   && c.Culture == culture).ToList();
                    if (pool.Count == 0)
                        pool = allChars.Where(c => c != null && c.Occupation == Occupation.Lord).ToList();
                    if (pool.Count > 0)
                        template = pool[rng.Next(pool.Count)];
                }
                catch (Exception tex)
                {
                    BannerlordLinkModule.Log($"[recruit_vassal] template pick warn: {tex.Message}");
                }
                if (template == null)
                {
                    BannerlordLinkModule.Log($"[recruit_vassal] REFUSE @{username}: no lord template");
                    ActionFeedback.PostFailed(actionId, "no_lord_template");
                    return;
                }

                // 2. NPC-лорд: adult + alive + Lord occupation. Без партии (движок сам).
                Hero npc = HeroCreator.CreateSpecialHero(template);
                npc.ChangeState(Hero.CharacterStates.Active);
                try
                {
                    int years = rng.Next(28, 46);
                    npc.SetBirthDay(CampaignTime.YearsFromNow(-years));
                }
                catch (Exception aex)
                {
                    BannerlordLinkModule.Log($"[recruit_vassal] age warn: {aex.Message}");
                }
                try { npc.SetNewOccupation(Occupation.Lord); } catch { }
                try { npc.SetHasMet(); } catch { }

                // 3. Имя клана: payload OR авто из имени лидера.
                string finalName = string.IsNullOrEmpty(clanName)
                    ? (npc.Name?.ToString() ?? culture?.Name?.ToString() ?? "Vassal Clan")
                    : clanName;

                // 4. Клан — clan-setup verbatim из CreateVassalClanHandler.
                var nameObj = new TextObject(finalName);
                Clan newClan = Clan.CreateClan(finalName);
                if (newClan == null)
                {
                    BannerlordLinkModule.Log("[recruit_vassal] CreateClan returned null");
                    ActionFeedback.PostFailed(actionId, "clan_create_failed");
                    return;
                }
                newClan.ChangeClanName(nameObj, nameObj);
                newClan.Culture = culture;
                if (newClan.Banner == null)
                {
                    try { newClan.Banner = Banner.CreateRandomBanner(); }
                    catch (Exception bex)
                    {
                        BannerlordLinkModule.Log($"[recruit_vassal] banner warn: {bex.Message}");
                    }
                }
                newClan.AddRenown(50f, false);          // tier-1 starter
                newClan.IsNoble = true;
                try
                {
                    var home = hero.Clan?.HomeSettlement ?? hero.HomeSettlement ?? hero.CurrentSettlement;
                    if (home != null) newClan.SetInitialHomeSettlement(home);
                }
                catch { }

                // 5. NPC-лорд — лидер клана. 2026-06-17 КРАШ-ФИКС: НЕ использовать
                // ChangeClanLeaderAction для НОВОГО клана — её ApplyInternal делает
                // `leader.Gold` у clan.Leader==null → NRE; раньше хендлер глотал этот NRE
                // и создавал БЕЗЛИДЕРНЫЙ клан, вступавший в королевство → краш движка.
                // Ставим лидера напрямую clan.SetLeader (public; это и есть то, что
                // action зовёт в конце) — без NRE и без ненужной нам party-creation.
                npc.Clan = newClan;
                try { newClan.SetLeader(npc); }
                catch (Exception lex)
                {
                    BannerlordLinkModule.Log($"[recruit_vassal] SetLeader failed: {lex.Message}");
                    ActionFeedback.PostFailed(actionId, "leader_set_failed");
                    return;
                }
                // Гард: безлидерный клан крашит движок — если лидер не встал, АБОРТ
                // ДО вступления в королевство и списания 3M (не плодим битый клан).
                if (newClan.Leader != npc)
                {
                    BannerlordLinkModule.Log("[recruit_vassal] REFUSE: лидер не установился → abort");
                    ActionFeedback.PostFailed(actionId, "leader_not_set");
                    return;
                }

                // 6. Клан вступает вассалом в королевство правителя.
                try
                {
                    ChangeKingdomAction.ApplyByJoinToKingdom(newClan, kingdom, showNotification: false);
                }
                catch (Exception kex)
                {
                    BannerlordLinkModule.Log(
                        $"[recruit_vassal] ApplyByJoinToKingdom failed: {kex.Message}");
                    ActionFeedback.PostFailed(actionId, "kingdom_join_failed");
                    return;
                }
                // Безфиефный клан → reconcile HomeSettlement (как JoinKingdomHandler),
                // иначе ванильный daily-tick роняет NRE на null HomeSettlement.
                try
                {
                    if (newClan.Fiefs.Count == 0)
                    {
                        newClan.ConsiderAndUpdateHomeSettlement();
                        foreach (var hh in newClan.Heroes) hh.UpdateHomeSettlement();
                    }
                }
                catch (Exception hsEx)
                {
                    BannerlordLinkModule.Log($"[recruit_vassal] home reconcile warn: {hsEx.Message}");
                }

                // 7. Списываем 3M динаров с правителя (ПОСЛЕ успешного создания).
                try
                {
                    GiveGoldAction.ApplyBetweenCharacters(hero, null, RECRUIT_VASSAL_COST, true);
                }
                catch (Exception gex)
                {
                    BannerlordLinkModule.Log($"[recruit_vassal] gold deduct warn: {gex.Message}");
                }

                BannerlordLinkModule.Log(
                    $"[recruit_vassal] OK: @{username} hired clan '{finalName}' " +
                    $"(leader='{npc.Name}', clan_id={newClan.StringId}) → kingdom '{kingdom.Name}', " +
                    $"-{RECRUIT_VASSAL_COST}💰 gold={hero.Gold}");

                // Обновить backend-кэш золота правителя.
                try { HeroStateSync.Push(hero); } catch { }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[recruit_vassal] CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed:" + ex.Message);
            }
        }
    }

    // ── RenameVassalHandler ────────────────────────────────────────────────────
    public class RenameVassalHandler : IActionHandler
    {
        public string ActionType => "hero.rename_vassal";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string clanId = (data["vassal_clan_id"]?.ToString() ?? "").Trim();
            string newName = (data["new_name"]?.ToString() ?? "").Trim();
            string oldName = data["old_name"]?.ToString() ?? "?";

            if (string.IsNullOrEmpty(clanId) || string.IsNullOrEmpty(newName))
                return Task.FromResult<(bool, string)>((false, "missing params"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(clanId, newName, oldName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string clanId, string newName, string oldName, string actionId)
        {
            try
            {
                Clan clan;
                try { clan = MBObjectManager.Instance.GetObject<Clan>(clanId); }
                catch
                {
                    ActionFeedback.PostFailed(actionId, "clan_lookup_crash");
                    return;
                }
                if (clan == null)
                {
                    BannerlordLinkModule.Log(
                        $"[vassal.rename] REFUSE: clan '{clanId}' not found");
                    ActionFeedback.PostFailed(actionId, "clan_not_found");
                    return;
                }
                var nameObj = new TextObject(newName);
                clan.ChangeClanName(nameObj, nameObj);
                BannerlordLinkModule.Log(
                    $"[vassal.rename] OK: '{oldName}' → '{newName}' ({clanId})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[vassal.rename] CRASHED: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }
}
