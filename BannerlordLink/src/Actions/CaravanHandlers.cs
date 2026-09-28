using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Helpers;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Party.PartyComponents;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity CARAVAN) — mobile passive income trilogy closer.
    ///
    /// BuyCaravanHandler:
    ///   - Resolve viewer.Hero + home Settlement (Town).
    ///   - Create caravan via CaravanPartyComponent.CreateCaravanParty(
    ///       owner=viewerHero, home=settlement, template=random by culture).
    ///   - Push event hero.caravan_created с {caravan_id (backend row), party_id (engine StringId)}.
    ///
    /// SellCaravanHandler:
    ///   - Find caravan owned by viewer (filter MobileParty.AllCaravanParties).
    ///   - TransferCaravanOwnership к Hero.MainHero (engine refund handled).
    /// </summary>
    public class BuyCaravanHandler : IActionHandler
    {
        public string ActionType => "hero.buy_caravan";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            int caravanId = 0;
            try { caravanId = data["caravan_id"]?.ToObject<int>() ?? 0; } catch { }
            string homeId = (data["home_settlement_id"]?.ToString() ?? "").Trim();
            string homeName = data["home_settlement_name"]?.ToString() ?? homeId;
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[caravan-buy ENTRY] @{username} home='{homeName}' (id={homeId}) " +
                $"caravan_row={caravanId} action_id={actionId}");

            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(homeId) || caravanId <= 0)
            {
                BannerlordLinkModule.Log(
                    $"[caravan-buy REFUSE] missing fields (user='{username}' home='{homeId}' caravanId={caravanId})");
                return Task.FromResult<(bool, string)>((false, "missing fields"));
            }

            MainThreadDispatcher.Enqueue(() =>
                Apply(username, caravanId, homeId, homeName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, int caravanId,
            string homeId, string homeName, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }
                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    ActionFeedback.PostFailed(actionId, "hero_not_found");
                    return;
                }
                // 2026-06-02 (CLAN-GATE) — караван только у ГЛАВЫ клана (в ванили
                // ими владеют лидеры; бесклановый/участник = engine-edge-кейсы +
                // источник наших stale-проблем). Фронт прячет вкладку, но он обходим
                // → авторитетный отказ. action.failed → backend рефандит списанное.
                if (!hero.IsClanLeader)
                {
                    ActionFeedback.PostFailed(actionId, "not_clan_leader");
                    return;
                }

                Settlement home = null;
                try { home = MBObjectManager.Instance.GetObject<Settlement>(homeId); }
                catch { }
                if (home == null)
                {
                    string needle = (homeName ?? "").ToLowerInvariant();
                    if (needle.Length >= 3)
                    {
                        foreach (var s in Settlement.All)
                        {
                            if (s?.IsTown != true) continue;
                            if ((s.Name?.ToString() ?? "").ToLowerInvariant().Contains(needle))
                            { home = s; break; }
                        }
                    }
                }
                if (home == null || !home.IsTown)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-buy] REFUSE @{username}: town '{homeId}' not found");
                    ActionFeedback.PostFailed(actionId, "town_not_found");
                    return;
                }

                // Sprint 5.33 VERIFY-1 fix — culture cascade. CaravanHelper.
                // GetRandomCaravanTemplate может вернуть null если для конкретной
                // culture нет template'ов с matching (isElite, isInitial) flags.
                // Раньше передавали home.Culture (settlement) — но caravan units
                // обычно spawn'ятся from OWNER culture. Пробуем cascade:
                //   1. hero.Culture (owner) с (false, false)
                //   2. home.Culture (settlement) с (false, false)
                //   3. ЛЮБОЙ culture с template'ами — last resort
                PartyTemplateObject template = TryResolveCaravanTemplate(hero, home);
                if (template == null)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-buy] REFUSE @{username}: no caravan template found " +
                        $"(hero.Culture='{hero.Culture?.StringId}' home.Culture='{home.Culture?.StringId}')");
                    ActionFeedback.PostFailed(actionId, "no_template");
                    return;
                }
                BannerlordLinkModule.Log(
                    $"[caravan-buy] resolved template id='{template.StringId}'");

                // Create caravan party. Signature 1.3.x:
                // CreateCaravanParty(owner, home, template, isInitialSpawn, caravanLeader, itemRoster, isElite)
                MobileParty caravan = null;
                try
                {
                    caravan = CaravanPartyComponent.CreateCaravanParty(
                        hero, home, template, false, null, null, false);
                }
                catch (Exception cEx)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-buy] CreateCaravanParty crashed: {cEx.Message}");
                    ActionFeedback.PostFailed(actionId, "create_failed");
                    return;
                }
                if (caravan == null)
                {
                    ActionFeedback.PostFailed(actionId, "create_returned_null");
                    return;
                }

                BannerlordLinkModule.Log(
                    $"[caravan-buy] @{username} → caravan id={caravan.StringId} home={home.Name}");

                // Push event с engine StringId → backend backfill.
                string evtData = Newtonsoft.Json.JsonConvert.SerializeObject(new
                {
                    caravan_id = caravanId,
                    party_id   = caravan.StringId,
                    owner      = username,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.caravan_created", evtData));
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[caravan-buy] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }

        /// <summary>Sprint 5.33 WORKSHOP-FIX (2026-05-28) — bulletproof template resolver.
        ///
        /// Strategy:
        ///   1. Try CaravanHelper.GetRandomCaravanTemplate on cascade of cultures
        ///      (hero → home → MainHero → any-non-bandit).
        ///   2. Brute-force: MBObjectManager.GetObjectTypeList<PartyTemplateObject>
        ///      + StringId.Contains("caravan") — last resort if Helper is broken.
        ///   3. Каждая попытка логируется → видно что не сработало.</summary>
        private static PartyTemplateObject TryResolveCaravanTemplate(Hero hero, Settlement home)
        {
            PartyTemplateObject Try(CultureObject c, string label)
            {
                if (c == null) return null;
                try
                {
                    // 2026-06-05 (AUTOTEST fix) — 3-й арг GetRandomCaravanTemplate =
                    // isLand, НЕ isElite/isInitial. Было false (=naval-only) → land-
                    // культуры не имеют naval-template'ов → каждый lookup → null →
                    // brute-force брал чужую культуру (aserai-template / vlandia-id).
                    var t = CaravanHelper.GetRandomCaravanTemplate(c, false, true);
                    if (t != null)
                    {
                        BannerlordLinkModule.Log(
                            $"[caravan-buy] template via {label} (culture='{c.StringId}') → {t.StringId}");
                        return t;
                    }
                    BannerlordLinkModule.Log(
                        $"[caravan-buy] {label} (culture='{c.StringId}') → null");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-buy] template via {label} threw: {ex.Message}");
                }
                return null;
            }

            // Stage 1: cascade of explicit cultures.
            var result = Try(hero?.Culture, "hero.Culture")
                      ?? Try(home?.Culture, "home.Culture")
                      ?? Try(Hero.MainHero?.Culture, "MainHero.Culture");
            if (result != null) return result;

            // Stage 2: enumerate all non-bandit cultures.
            try
            {
                var allCultures = MBObjectManager.Instance.GetObjectTypeList<CultureObject>();
                foreach (var c in allCultures ?? (System.Collections.Generic.IEnumerable<CultureObject>)Array.Empty<CultureObject>())
                {
                    if (c == null) continue;
                    if (c.IsBandit) continue;
                    var t = Try(c, $"enum-culture[{c.StringId}]");
                    if (t != null) return t;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[caravan-buy] enum cultures crash: {ex.Message}");
            }

            // Stage 3: brute-force любой PartyTemplate с "caravan" в StringId.
            try
            {
                var templates = MBObjectManager.Instance.GetObjectTypeList<PartyTemplateObject>();
                LogCaravanTemplatesCatalog(templates);
                foreach (var t in templates ?? (System.Collections.Generic.IEnumerable<PartyTemplateObject>)Array.Empty<PartyTemplateObject>())
                {
                    if (t == null || t.StringId == null) continue;
                    string id = t.StringId.ToLowerInvariant();
                    if (!id.Contains("caravan")) continue;
                    if (id.Contains("elite") || id.Contains("bandit")) continue;
                    BannerlordLinkModule.Log(
                        $"[caravan-buy] brute-force template fallback → {t.StringId}");
                    return t;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[caravan-buy] brute-force crash: {ex.Message}");
            }

            return null;
        }

        // Catalog logger — runs at most once per session to expose все templates.
        private static bool _templateCatalogLogged;
        private static void LogCaravanTemplatesCatalog(System.Collections.Generic.IEnumerable<PartyTemplateObject> templates)
        {
            if (_templateCatalogLogged) return;
            _templateCatalogLogged = true;
            try
            {
                var sb = new System.Text.StringBuilder();
                sb.Append("[caravan-buy CATALOG] PartyTemplateObject containing 'caravan':");
                int n = 0;
                foreach (var t in templates ?? (System.Collections.Generic.IEnumerable<PartyTemplateObject>)Array.Empty<PartyTemplateObject>())
                {
                    if (t?.StringId == null) continue;
                    if (!t.StringId.ToLowerInvariant().Contains("caravan")) continue;
                    sb.Append($"\n  - '{t.StringId}'");
                    n++;
                }
                sb.Append($"\n  (total {n} caravan-related templates)");
                BannerlordLinkModule.Log(sb.ToString());
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[caravan-buy CATALOG] enumeration failed: {ex.Message}");
            }
        }
    }

    // ── SellCaravanHandler ─────────────────────────────────────────────────────
    public class SellCaravanHandler : IActionHandler
    {
        public string ActionType => "hero.sell_caravan";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string partyId = (data["party_id"]?.ToString() ?? "").Trim();
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[caravan-sell ENTRY] @{username} party_id={partyId} action_id={actionId}");

            if (string.IsNullOrEmpty(username))
            {
                BannerlordLinkModule.Log("[caravan-sell REFUSE] no username");
                return Task.FromResult<(bool, string)>((false, "no username"));
            }

            MainThreadDispatcher.Enqueue(() => Apply(username, partyId, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string partyId, string actionId)
        {
            try
            {
                if (Campaign.Current == null) { ActionFeedback.PostFailed(actionId, "no_campaign"); return; }
                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
                if (hero == null) { ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }

                // 2026-06-02 — party_id мог ПРОТУХНУТЬ (караван уничтожен бандитами
                // и пересоздан через rescue → новый StringId, а в БД старый).
                // Раньше жёсткий фильтр `mp.StringId != partyId → continue` скипал
                // ВСЁ при stale id → «не найден». Теперь ищем караван ВЛАДЕЛЬЦА;
                // точный party_id — лишь предпочтение (для тех, у кого несколько).
                MobileParty target = null, ownedFallback = null;
                foreach (var mp in MobileParty.AllCaravanParties)
                {
                    if (mp == null || !mp.IsCaravan) continue;
                    if (mp.LeaderHero != hero && mp.Owner != hero) continue;
                    if (ownedFallback == null) ownedFallback = mp;
                    if (!string.IsNullOrEmpty(partyId) && mp.StringId == partyId)
                    { target = mp; break; }
                }
                if (target == null) target = ownedFallback;
                if (target == null)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-sell] REFUSE @{username}: у героя нет каравана (party_id={partyId})");
                    ActionFeedback.PostFailed(actionId, "not_found");
                    return;
                }

                try
                {
                    // Transfer ownership to MainHero — engine refund logic.
                    var homeS = target.HomeSettlement;
                    CaravanPartyComponent.TransferCaravanOwnership(
                        target, Hero.MainHero, homeS);
                    BannerlordLinkModule.Log(
                        $"[caravan-sell] @{username} → transfer to MainHero (home={homeS?.Name})");
                    ActionFeedback.PostApplied(actionId);
                }
                catch (Exception sx)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-sell] crashed: {sx.Message}");
                    ActionFeedback.PostFailed(actionId, "transfer_failed");
                    return;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[caravan-sell] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── PayCaravanRescueHandler — backend-only side, but mod может pre-validate.
    // (Actually pay_ransom/pay_caravan_rescue handled fully backend-side; no mod
    // action needed. Backend re-issues hero.buy_caravan when pool full.)
    // Removed — no C# handler registered for hero.pay_caravan_rescue.
}
