using System;
using System.Collections.Generic;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.Settlements.Workshops;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity SHOP) — Workshop daily profit sync.
    ///
    /// OnDailyTick: for each Workshop owned by an adopted [BLink] hero, compute
    /// net dinars since last sync (current Capital - last_known_capital).
    /// Push event hero.workshop_profit_sync с amount → backend конвертирует
    /// в крустики (100:1) и credit'ит viewer'у.
    ///
    /// Tracking: _lastKnownCapital snapshot для каждого workshop_id (StringId).
    /// Workshop.Capital растёт за счёт ProfitMade-Expense, так что diff =
    /// чистая прибыль.
    /// </summary>
    public class WorkshopProfitSyncBehavior : CampaignBehaviorBase
    {
        // workshopStringId → last known Capital snapshot
        private readonly Dictionary<string, int> _lastKnownCapital
            = new Dictionary<string, int>();

        public override void RegisterEvents()
        {
            CampaignEvents.DailyTickEvent.AddNonSerializedListener(this, OnDailyTick);
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoaded);
        }

        public override void SyncData(IDataStore dataStore)
        {
            // Stateless — snapshots rebuilt на game load.
        }

        private void OnGameLoaded()
        {
            try
            {
                _lastKnownCapital.Clear();
                int seeded = 0;
                foreach (var s in Settlement.All)
                {
                    if (s?.IsTown != true || s.Town == null) continue;
                    foreach (var w in s.Town.Workshops)
                    {
                        if (w?.Owner == null) continue;
                        if (!IsBLinkHero(w.Owner)) continue;
                        _lastKnownCapital[KeyFor(w)] = w.Capital;
                        seeded++;
                    }
                }
                if (seeded > 0)
                    BannerlordLinkModule.Log($"[shop-sync] OnGameLoaded seeded {seeded} workshop snapshots");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[shop-sync] OnGameLoaded crash: {ex.Message}");
            }
        }

        private void OnDailyTick()
        {
            try
            {
                int synced = 0;
                foreach (var s in Settlement.All)
                {
                    if (s?.IsTown != true || s.Town == null) continue;
                    foreach (var w in s.Town.Workshops)
                    {
                        if (w?.Owner == null) continue;
                        if (!IsBLinkHero(w.Owner)) continue;
                        string key = KeyFor(w);
                        int currentCap = w.Capital;
                        int prevCap;
                        if (!_lastKnownCapital.TryGetValue(key, out prevCap))
                        {
                            // First observation — seed and skip (no diff to push).
                            _lastKnownCapital[key] = currentCap;
                            continue;
                        }
                        int netDinars = currentCap - prevCap;
                        if (netDinars <= 0)
                        {
                            // Capital dropped or stayed (losses, expenses) — update snapshot, skip payout.
                            _lastKnownCapital[key] = currentCap;
                            continue;
                        }
                        _lastKnownCapital[key] = currentCap;

                        // Push event с {workshop_id (engine StringId), owner, net_dinars}.
                        // Backend matches engine StringId через workshop_id_mod field.
                        string ownerLogin = HeroNaming.ExtractUsername(
                            w.Owner.Name?.ToString() ?? "")?.ToLowerInvariant();
                        if (string.IsNullOrEmpty(ownerLogin)) continue;

                        PushSync(w, ownerLogin, netDinars);
                        synced++;
                    }
                }
                if (synced > 0)
                    BannerlordLinkModule.Log($"[shop-sync] OnDailyTick pushed {synced} workshop syncs");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[shop-sync] OnDailyTick crash: {ex.Message}");
            }
        }

        private static void PushSync(Workshop w, string ownerLogin, int netDinars)
        {
            try
            {
                // Push event: owner + workshop_id (backend resolves через
                // settlement+type lookup) + net_dinars.
                string evtData = Newtonsoft.Json.JsonConvert.SerializeObject(new
                {
                    owner            = ownerLogin,
                    settlement_id    = w.Settlement?.StringId ?? "",
                    workshop_type    = w.WorkshopType?.StringId ?? "",
                    net_dinars       = netDinars,
                    capital_now      = w.Capital,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.workshop_profit_sync", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[shop-sync] push crash: {ex.Message}");
            }
        }

        private static bool IsBLinkHero(Hero h)
        {
            if (h?.Name == null) return false;
            return HeroNaming.IsAdopted(h.Name.ToString());
        }

        private static string KeyFor(Workshop w)
        {
            return $"{w.Settlement?.StringId}::{w.WorkshopType?.StringId}::{w.Owner?.StringId}";
        }

        /// <summary>2026-06-02 (PROPERTIES-MIRROR) — полный список мастерских
        /// [BLink]-героев СЕЙЧАС для snapshot-зеркала на backend.</summary>
        public static System.Collections.Generic.List<object> BuildWorkshopSnapshot()
        {
            var items = new System.Collections.Generic.List<object>();
            try
            {
                foreach (var s in Settlement.All)
                {
                    if (s?.IsTown != true || s.Town == null) continue;
                    foreach (var w in s.Town.Workshops)
                    {
                        if (w?.Owner == null) continue;
                        if (!IsBLinkHero(w.Owner)) continue;
                        string ownerLogin = HeroNaming.ExtractUsername(
                            w.Owner.Name?.ToString() ?? "")?.ToLowerInvariant();
                        if (string.IsNullOrEmpty(ownerLogin)) continue;
                        items.Add(new
                        {
                            owner              = ownerLogin,
                            settlement_id      = w.Settlement?.StringId ?? "",
                            settlement_name    = w.Settlement?.Name?.ToString() ?? "",
                            workshop_type      = w.WorkshopType?.StringId ?? "",
                            workshop_type_name = w.WorkshopType?.Name?.ToString() ?? "",
                        });
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[shop-sync] BuildWorkshopSnapshot crash: {ex.Message}");
            }
            return items;
        }
    }
}
