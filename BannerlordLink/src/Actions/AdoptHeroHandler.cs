using System;
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

            // Enqueue creation на main thread — НЕ ждём.
            // ACK backend'у уйдёт success=true сейчас (action accepted),
            // финальный результат — через player.linked event позже.
            MainThreadDispatcher.Enqueue(() => CreateHeroOnMainThread(username));

            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void CreateHeroOnMainThread(string username)
        {
            try
            {
                // Campaign не active (главное меню / mission battle) — skip
                if (Campaign.Current == null)
                {
                    BannerlordLinkModule.Log($"[hero.create] @{username}: Campaign не started, skip");
                    PostFailed(username, "campaign_not_started");
                    return;
                }

                // Get all wanderer templates (vanilla — culture-agnostic)
                var wandererTemplates = MBObjectManager.Instance
                    .GetObjectTypeList<CharacterObject>()
                    .Where(c => c.Occupation == Occupation.Wanderer)
                    .ToList();

                if (wandererTemplates.Count == 0)
                {
                    BannerlordLinkModule.Log($"[hero.create] @{username}: no wanderer templates found");
                    PostFailed(username, "no_wanderer_templates");
                    return;
                }

                var rng = new Random();
                var template = wandererTemplates[rng.Next(wandererTemplates.Count)];

                // 1. Create the hero
                Hero newHero = HeroCreator.CreateSpecialHero(template);
                newHero.ChangeState(Hero.CharacterStates.Active);

                // 2. Place в случайный town (default behaviour для wanderer'а)
                var towns = Settlement.All.Where(s => s.IsTown).ToList();
                if (towns.Count > 0)
                {
                    var settlement = towns[rng.Next(towns.Count)];
                    EnterSettlementAction.ApplyForCharacterOnly(newHero, settlement);
                }

                // 3. Reset all skills/attributes to 0 — equal start для всех viewers
                newHero.HeroDeveloper.ClearHero();

                // BLT discovery: wanderer с 0 skill points dies on save reload.
                // Даём 1 skill point в первый skill (минимум для survival).
                try
                {
                    // DefaultSkills.OneHanded — static field, гарантированно
                    // существует в vanilla 1.3.x. Никаких GetObjectTypeList
                    // (returns null для SkillObject — Skills register иначе).
                    newHero.HeroDeveloper.SetInitialSkillLevel(DefaultSkills.OneHanded, 1);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[hero.create] skill seed warn: {ex.Message}");
                }

                newHero.HeroDeveloper.InitializeHeroDeveloper();

                // 4. Rename → viewer login
                var nameText = new TextObject(username);
                newHero.SetName(nameText, nameText);

                BannerlordLinkModule.Log(
                    $"[hero.create] @{username} → hero_id={newHero.StringId} " +
                    $"culture={newHero.Culture?.StringId ?? "?"} " +
                    $"town={newHero.HomeSettlement?.Name?.ToString() ?? "—"}");

                // 5. Post player.linked обратно — backend upsert в bannerlord_heroes
                PostLinked(newHero, username);
                // 6. Sprint M19: post full state — UI показывает level/clan/kingdom
                HeroStateSync.Push(newHero);
                // 7. Push equipment snapshot — wanderer template имеет starting
                //    equipment, UI должен показать в hero card.
                EquipmentSync.PushAll(newHero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[hero.create] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                PostFailed(username, ex.Message);
            }
        }

        private static void PostLinked(Hero hero, string username)
        {
            string dataJson = JsonConvert.SerializeObject(new
            {
                username = username,
                hero_id = hero.StringId,
                display_name = username,
                culture = hero.Culture?.StringId,
            });
            Task.Run(async () =>
            {
                bool ok = await BannerlordLinkModule.Backend.PostEventAsync(
                    "bannerlord", "player.linked", dataJson);
                BannerlordLinkModule.Log(
                    $"[hero.create] player.linked event → {(ok ? "ACK" : "FAILED")}");
            });
        }

        private static void PostFailed(string username, string reason)
        {
            // Sprint 2.5+: можно добавить отдельный event hero.create_failed.
            // Пока — просто log, viewer увидит что hero нет в /api/bannerlord/my-hero
            // и сможет повторить попытку.
            string dataJson = JsonConvert.SerializeObject(new
            {
                username = username,
                reason = reason,
            });
            Task.Run(async () =>
            {
                await BannerlordLinkModule.Backend.PostEventAsync(
                    "bannerlord", "world.event_occurred", $"{{\"kind\":\"hero_create_failed\",\"username\":\"{username}\",\"reason\":\"{reason}\"}}");
            });
        }
    }
}
