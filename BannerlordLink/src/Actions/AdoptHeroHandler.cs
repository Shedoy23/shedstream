using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.CharacterDevelopment;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
using TaleWorlds.Localization;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Real handler для `hero.create` action — adoption flow.
    ///
    /// Flow:
    ///   1. Background thread: handler принимает action data {target_username}
    ///   2. Enqueue работу на main thread (Hero creation API requires это)
    ///   3. Main thread (через MainThreadDispatcher.DrainQueue в OnApplicationTick):
    ///        - Get random wanderer template (vanilla, no DLC requirement)
    ///        - HeroCreator.CreateSpecialHero(template)
    ///        - ChangeState(Active)
    ///        - Place в случайный town (EnterSettlementAction)
    ///        - HeroDeveloper.ClearHero() — сбрасывает все skills/attributes к 0
    ///        - SetInitialSkillLevel(first_skill, 1) — wanderer MUST have ≥1 skill
    ///          point иначе dies on save load (BLT discovery)
    ///        - InitializeHeroDeveloper()
    ///        - SetName(viewer_login)
    ///        - POST player.linked event назад backend → upsert в bannerlord_heroes
    ///   4. Handler returns success=true ДО самой creation — backend marks acked
    ///      сразу. Async creation сама себя report'ит через player.linked event.
    ///
    /// Edge cases:
    ///   - Campaign не started → main thread skip + POST с error
    ///   - No wanderer templates → POST с error в data
    ///   - Hero creation crash → log + POST player.unlinked (cleanup hint)
    /// </summary>
    public class AdoptHeroHandler : IActionHandler
    {
        public string ActionType => "hero.create";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
            {
                return Task.FromResult<(bool, string)>((false, "no target username in action data"));
            }

            // Optional culture choice: data.culture = empire/sturgia/vlandia/
            // aserai/khuzait/battania (lowercase). Null/empty = random.
            string culture = (data["culture"]?.ToString() ?? "").Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);

            // Enqueue creation на main thread — НЕ ждём.
            // ACK backend'у уйдёт success=true сейчас (action accepted),
            // финальный результат — через player.linked event позже.
            MainThreadDispatcher.Enqueue(() => CreateHeroOnMainThread(username, culture, actionId));

            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void CreateHeroOnMainThread(string username, string requestedCulture,
            string actionId)
        {
            try
            {
                // Campaign не active (главное меню / mission battle) — skip
                if (Campaign.Current == null)
                {
                    BannerlordLinkModule.Log($"[hero.create] @{username}: Campaign не started, skip");
                    PostCreateFailedEvent(username, "campaign_not_started");
                    ActionFeedback.PostFailed(actionId, "campaign_not_started");
                    return;
                }

                // Sprint 5.32 (BLT-parity H6) — duplicate-adopt guard.
                // BLT pattern (BLTAdoptAHeroCampaignBehavior.GetAdoptedHero) —
                // нельзя выдать viewer'у второго [BLink]-hero пока существующий
                // живой. Backend race может пропустить параллельные adoption
                // запросы (один JWT → 2 POST'а в один тик до того как player.linked
                // дойдёт). Mod-side guard защищает на main thread.
                //
                // Не учитываем мёртвых — для них viewer должен сделать re-adopt
                // (это разрешено, H4-fix).
                var existing = HeroLookup.FindByUsername(username);
                if (existing != null && existing.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[hero.create] REFUSE @{username}: уже есть живой " +
                        $"[BLink]-hero (id={existing.StringId}, clan={existing.Clan?.Name?.ToString() ?? "—"}). " +
                        $"Используй существующего или /leave_clan для retire.");
                    PostCreateFailedEvent(username, "already_adopted");
                    ActionFeedback.PostFailed(actionId, "already_adopted");
                    // Re-push state — frontend может быть рассинхронизирован
                    // (например, потерял linked event раньше). Push гарантирует
                    // UI снова видит существующего hero.
                    try { HeroStateSync.Push(existing); } catch { }
                    return;
                }

                // Get all wanderer templates. Filter по requested culture
                // (data.culture). Если culture пустой / unknown / нет templates
                // для неё — fallback на random любой wanderer.
                var allWanderers = MBObjectManager.Instance
                    .GetObjectTypeList<CharacterObject>()
                    .Where(c => c.Occupation == Occupation.Wanderer)
                    .ToList();

                if (allWanderers.Count == 0)
                {
                    BannerlordLinkModule.Log($"[hero.create] @{username}: no wanderer templates found");
                    PostCreateFailedEvent(username, "no_wanderer_templates");
                    ActionFeedback.PostFailed(actionId, "no_wanderer_templates");
                    return;
                }

                var rng = new Random();
                List<CharacterObject> pool = allWanderers;
                if (!string.IsNullOrEmpty(requestedCulture))
                {
                    var filtered = allWanderers
                        .Where(c => string.Equals(c.Culture?.StringId, requestedCulture,
                            StringComparison.OrdinalIgnoreCase))
                        .ToList();
                    if (filtered.Count > 0)
                    {
                        pool = filtered;
                    }
                    else
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.create] @{username}: no wanderers for culture '{requestedCulture}', fallback random");
                    }
                }
                var template = pool[rng.Next(pool.Count)];

                // 1. Create the hero
                Hero newHero = HeroCreator.CreateSpecialHero(template);
                newHero.ChangeState(Hero.CharacterStates.Active);

                // 1a. AGE OVERRIDE (2026-05-28, BLT-parity audit fix).
                // Wanderer templates могут быть children (< 18) или elderly
                // (60+). Engine refuses many actions для children (clan,
                // marriage, иногда summon в Mission); elderly mрут от age
                // через несколько game-months. Forcing adult range 22-35.
                //
                // BLT pattern (Lait AdoptAHero.ExecuteInternal):
                //   newHero.SetBirthDay(CampaignTime.YearsFromNow(-Math.Max(
                //       AgeModel.HeroComesOfAge, StartingAgeRange.Random())));
                try
                {
                    int minAge = 22;
                    int maxAge = 35;
                    try
                    {
                        int comesOfAge = Campaign.Current.Models.AgeModel
                            ?.HeroComesOfAge ?? 18;
                        if (comesOfAge > minAge) minAge = comesOfAge;
                    }
                    catch { }
                    int years = rng.Next(minAge, maxAge + 1);
                    newHero.SetBirthDay(CampaignTime.YearsFromNow(-years));
                    BannerlordLinkModule.Log(
                        $"[hero.create] @{username}: age set to {years} (adult range {minAge}-{maxAge})");
                }
                catch (Exception ageEx)
                {
                    BannerlordLinkModule.Log(
                        $"[hero.create] @{username} SetBirthDay warn: {ageEx.Message}");
                }

                // 2. Place в таверну ближайшего town'а — wanderer'ам там
                // прямая прописка. Sprint 5.32 — раньше random town, но без
                // HomeSettlement engine иногда считал героя orphan и помечал
                // Lost. WandererHome ставит HomeSettlement + tavern character.
                BannerlordLink.Util.WandererHome.PlaceInNearestTavern(newHero);

                // 3. Reset all skills/attributes to 0 — equal start для всех viewers
                newHero.HeroDeveloper.ClearHero();

                // 2026-06-02 (BLT-parity POWER) — раньше сеяли 1 очко в OneHanded
                // (survival-минимум) → герой махал T6-шмотом с ~0 скилла: мажет,
                // отскакивает, не наносит урон. BLT инхерит развитого NPC (~100-250).
                // Сеем БОЕВОЙ флор ~120 во все боевые скиллы → герой компетентен
                // любым оружием, которое даст класс. Не-боевые остаются 0 (fighter,
                // не omni-гений). Класс-powers (*_skill_boost) поднимают специализацию
                // ВЫШЕ флора (SetClassHandler.ApplyClassSkillBoosts, проверка >current).
                try
                {
                    const int BASE_COMBAT_SKILL = 120;   // BLT-parity боевой флор
                    var combatSkills = new[]
                    {
                        DefaultSkills.OneHanded, DefaultSkills.TwoHanded,
                        DefaultSkills.Polearm,   DefaultSkills.Bow,
                        DefaultSkills.Crossbow,  DefaultSkills.Throwing,
                        DefaultSkills.Riding,    DefaultSkills.Athletics,
                    };
                    foreach (var sk in combatSkills)
                        newHero.HeroDeveloper.SetInitialSkillLevel(sk, BASE_COMBAT_SKILL);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[hero.create] skill seed warn: {ex.Message}");
                }

                newHero.HeroDeveloper.InitializeHeroDeveloper();

                // Sprint 5.10b: strip wanderer's starting equipment. Иначе
                // engine иногда выдаёт T5-T6 шмот рандомно (зависит от
                // template — некоторые "Khergit Defector" etc. идут с
                // high-tier стандартным набором). Bypasses gear progression
                // system → unfair. Чистим все 11 slots до пустоты —
                // viewer получит шмот через hero.set_class.
                try
                {
                    StripEquipment(newHero);
                    BannerlordLinkModule.Log(
                        $"[hero.create] @{username}: equipment stripped " +
                        "(базовое, viewer set_class даст start гир)");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[hero.create] @{username} StripEquipment warn: {ex.Message}");
                }

                // 4. Rename → "[BLink] {viewer_login}" full / "{viewer_login}" first
                var (fullName, firstName) = HeroNaming.Format(username);
                newHero.SetName(fullName, firstName);

                // Sprint 5.32 (BLT-parity M9) — persistent identity registration.
                // Backbone для М9 — dict heroId→username сохраняется через SyncData.
                // Future-proof: если engine переименует hero (clan promotion, save
                // migration), HeroLookup.FindByUsername найдёт его через dict, не
                // через name-substring parsing.
                //
                // 2026-05-28: Register() now returns iteration count
                // (re-adopt counter, BLT-parity AdoptAHero.Iteration).
                int heroIteration = 0;
                try
                {
                    heroIteration = BannerlordLink.Behaviors.HeroIdentityBehavior
                        .Instance?.Register(newHero, username) ?? 0;
                }
                catch (Exception idEx)
                {
                    BannerlordLinkModule.Log(
                        $"[hero.create] @{username} HeroIdentity register warn: {idEx.Message}");
                }

                // STARTING GOLD (2026-05-28, BLT-parity).
                // BLT даёт configurable starting gold + наследство от прошлых
                // adoption iterations. У нас простой 1000 динаров — viewer
                // может сразу что-то купить в-game (cheap consumable) без
                // grind. Прирост = (iteration * 500) — bonus за re-adopt'ы.
                try
                {
                    int baseGold = 1000;
                    int legacyBonus = heroIteration * 500;
                    int total = baseGold + legacyBonus;
                    newHero.ChangeHeroGold(total);
                    BannerlordLinkModule.Log(
                        $"[hero.create] @{username}: starting gold +{total}💰 " +
                        $"(base={baseGold}, legacy_bonus={legacyBonus} from iter={heroIteration})");
                }
                catch (Exception gEx)
                {
                    BannerlordLinkModule.Log(
                        $"[hero.create] @{username} starting gold warn: {gEx.Message}");
                }

                // Sprint 5.16: убираем fog-of-war — MainHero "знакомится" с
                // новым hero, чтобы он сразу появлялся в encyclopedia /
                // clan UI / diplomacy на стороне стримера. Без этого engine
                // показывает viewer'а как "Unknown wanderer" пока не встретят
                // физически на карте.
                try
                {
                    newHero.SetHasMet();
                    BannerlordLinkModule.Log(
                        $"[hero.create] @{username}: marked as met by MainHero " +
                        "(visible в encyclopedia)");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[hero.create] @{username} SetHasMet warn: {ex.Message}");
                }

                BannerlordLinkModule.Log(
                    $"[hero.create] @{username} → hero_id={newHero.StringId} " +
                    $"culture={newHero.Culture?.StringId ?? "?"} " +
                    $"town={newHero.HomeSettlement?.Name?.ToString() ?? "—"}");

                // 5. Post player.linked обратно — backend upsert в bannerlord_heroes
                PostLinked(newHero, username, heroIteration);
                // 6. Sprint M19: post full state — UI показывает level/clan/kingdom
                HeroStateSync.Push(newHero);
                // 7. Push equipment snapshot — wanderer template имеет starting
                //    equipment, UI должен показать в hero card.
                EquipmentSync.PushAll(newHero);
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[hero.create] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                PostCreateFailedEvent(username, ex.Message);
                ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
            }
        }

        // Sprint 5.10b: clear все 11 equipment slots (battle + civilian).
        // Set EquipmentElement.Invalid → engine видит slot как пустой.
        private static void StripEquipment(Hero hero)
        {
            if (hero == null) return;
            var slots = new[]
            {
                EquipmentIndex.Weapon0, EquipmentIndex.Weapon1,
                EquipmentIndex.Weapon2, EquipmentIndex.Weapon3,
                EquipmentIndex.Head, EquipmentIndex.Body,
                EquipmentIndex.Leg, EquipmentIndex.Gloves,
                EquipmentIndex.Cape,
                EquipmentIndex.Horse, EquipmentIndex.HorseHarness,
            };
            try
            {
                var battle = hero.BattleEquipment;
                if (battle != null)
                {
                    foreach (var idx in slots)
                        battle[idx] = EquipmentElement.Invalid;
                }
            }
            catch { }
            try
            {
                var civ = hero.CivilianEquipment;
                if (civ != null)
                {
                    foreach (var idx in slots)
                        civ[idx] = EquipmentElement.Invalid;
                }
            }
            catch { }
        }

        private static void PostLinked(Hero hero, string username, int iteration)
        {
            string dataJson = JsonConvert.SerializeObject(new
            {
                username = username,
                hero_id = hero.StringId,
                display_name = username,
                culture = hero.Culture?.StringId,
                // 2026-05-28: iteration counter (BLT-parity, для Heritage log).
                // 0 = first adoption, 1 = second, ... etc.
                iteration = iteration,
            });
            Task.Run(async () =>
            {
                bool ok = await BannerlordLinkModule.Backend.PostEventAsync(
                    "bannerlord", "player.linked", dataJson);
                BannerlordLinkModule.Log(
                    $"[hero.create] player.linked event → {(ok ? "ACK" : "FAILED")}");
            });
        }

        // Sprint 5.31 #45g (codegraph audit MED-6) — renamed from PostFailed
        // чтобы не было naming collision с Util.ActionFeedback.PostFailed
        // (одинаковая сигнатура (string, string), противоположная семантика —
        // тут username vs там actionId). Раньше неосторожный рефактор мог
        // переключить вызов и сломать refund pipeline без compile error.
        private static void PostCreateFailedEvent(string username, string reason)
        {
            // Sprint 2.5+: можно добавить отдельный event hero.create_failed.
            // Пока — просто log, viewer увидит что hero нет в /api/bannerlord/my-hero
            // и сможет повторить попытку.
            Task.Run(async () =>
            {
                await BannerlordLinkModule.Backend.PostEventAsync(
                    "bannerlord", "world.event_occurred", $"{{\"kind\":\"hero_create_failed\",\"username\":\"{username}\",\"reason\":\"{reason}\"}}");
            });
        }
    }
}
