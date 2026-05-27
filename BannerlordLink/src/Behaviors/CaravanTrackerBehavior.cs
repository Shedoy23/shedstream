using System;
using System.Collections.Generic;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Party.PartyComponents;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity CARAVAN) — Caravan profit sync + destruction tracking.
    ///
    /// OnDailyTick: scan MobileParty.AllCaravanParties где Owner = adopted
    /// [BLink] hero. Diff PartyTradeGold vs snapshot → push net_dinars event.
    ///
    /// MobilePartyDestroyed: filter caravans owned by [BLink] heroes → push
    /// hero.caravan_destroyed event (backend opens rescue pool).
    ///
    /// Both behaviors auto-credit viewer's crustic balance через backend
    /// _on_caravan_profit_sync (150:1 ratio).
    /// </summary>
    public class CaravanTrackerBehavior : CampaignBehaviorBase
    {
        // party StringId → last PartyTradeGold snapshot
        private readonly Dictionary<string, int> _lastGoldSnap
            = new Dictionary<string, int>();

        public override void RegisterEvents()
        {
            CampaignEvents.DailyTickEvent.AddNonSerializedListener(this, OnDailyTick);
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoaded);
            CampaignEvents.MobilePartyDestroyed.AddNonSerializedListener(this, OnMobilePartyDestroyed);
        }

        public override void SyncData(IDataStore dataStore) { /* stateless */ }

        private void OnGameLoaded()
        {
            try
            {
                _lastGoldSnap.Clear();
                int seeded = 0;
                foreach (var mp in MobileParty.AllCaravanParties)
                {
                    if (mp == null || !mp.IsCaravan) continue;
                    if (!IsBLinkOwned(mp, out _)) continue;
                    _lastGoldSnap[mp.StringId] = mp.PartyTradeGold;
                    seeded++;
                }
                if (seeded > 0)
                    BannerlordLinkModule.Log($"[caravan-sync] OnGameLoaded seeded {seeded} caravan snapshots");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[caravan-sync] OnGameLoaded crash: {ex.Message}");
            }
        }

        private void OnDailyTick()
        {
            try
            {
                int synced = 0;
                foreach (var mp in MobileParty.AllCaravanParties)
                {
                    if (mp == null || !mp.IsCaravan) continue;
                    string ownerLogin;
                    if (!IsBLinkOwned(mp, out ownerLogin)) continue;
                    int currentGold = mp.PartyTradeGold;
                    int prev;
                    if (!_lastGoldSnap.TryGetValue(mp.StringId, out prev))
                    {
                        _lastGoldSnap[mp.StringId] = currentGold;
                        continue;
                    }
                    int diff = currentGold - prev;
                    _lastGoldSnap[mp.StringId] = currentGold;
                    if (diff <= 0) continue;  // losses or no change, skip

                    PushSync(mp, ownerLogin, diff);
                    synced++;
                }
                if (synced > 0)
                    BannerlordLinkModule.Log($"[caravan-sync] OnDailyTick pushed {synced} caravan syncs");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[caravan-sync] OnDailyTick crash: {ex.Message}");
            }
        }

        private void OnMobilePartyDestroyed(MobileParty mp, PartyBase destroyer)
        {
            try
            {
                if (mp == null || !mp.IsCaravan) return;
                if (!IsBLinkOwned(mp, out string ownerLogin)) return;
                string captorName = destroyer?.Name?.ToString() ?? "unknown";
                BannerlordLinkModule.Log(
                    $"[caravan-destroyed] @{ownerLogin} caravan {mp.StringId} destroyed by {captorName}");

                string evtData = Newtonsoft.Json.JsonConvert.SerializeObject(new
                {
                    owner       = ownerLogin,
                    party_id    = mp.StringId,
                    captor_name = captorName,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.caravan_destroyed", evtData));

                // Clear snapshot so если caravan respawned same StringId — fresh start.
                _lastGoldSnap.Remove(mp.StringId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[caravan-destroyed] crash: {ex.Message}");
            }
        }

        // ── Helpers ────────────────────────────────────────────────────────────

        private static bool IsBLinkOwned(MobileParty mp, out string ownerLogin)
        {
            ownerLogin = null;
            try
            {
                // Caravan owner: CaravanPartyComponent.Owner OR LeaderHero.
                Hero owner = null;
                var comp = mp.PartyComponent as CaravanPartyComponent;
                if (comp != null && comp.Owner != null) owner = comp.Owner;
                if (owner == null) owner = mp.LeaderHero;
                if (owner?.Name == null) return false;
                string nm = owner.Name.ToString();
                if (!HeroNaming.IsAdopted(nm)) return false;
                ownerLogin = HeroNaming.ExtractUsername(nm)?.ToLowerInvariant();
                return !string.IsNullOrEmpty(ownerLogin);
            }
            catch { return false; }
        }

        private static void PushSync(MobileParty mp, string ownerLogin, int netDinars)
        {
            try
            {
                string evtData = Newtonsoft.Json.JsonConvert.SerializeObject(new
                {
                    owner      = ownerLogin,
                    party_id   = mp.StringId,
                    net_dinars = netDinars,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.caravan_profit_sync", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[caravan-sync] push crash: {ex.Message}");
            }
        }
    }
}
