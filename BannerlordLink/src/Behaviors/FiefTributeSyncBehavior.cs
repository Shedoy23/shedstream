using System;
using System.Collections.Generic;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity FIEF) — Daily fief tribute sync.
    ///
    /// OnDailyTick scan Settlement.All. Для каждого fief owned by adopted
    /// [BLink] hero (через Settlement.OwnerClan.Leader || Town.OwnerClan.Leader):
    ///   town    → diff Town.Gold     vs snapshot
    ///   castle  → diff Town.Gold     vs snapshot (castles тоже Town instance)
    ///   village → diff Village.Hearth vs snapshot (×10 multiplier — hearth ≈ income proxy)
    ///
    /// Push event hero.fief_tribute_sync с net_dinars. Backend конвертирует
    /// в крустики (200:1) с boost multiplier.
    ///
    /// OnGameLoaded seeds snapshots чтобы не payout'ить historical gold за раз.
    /// </summary>
    public class FiefTributeSyncBehavior : CampaignBehaviorBase
    {
        // fiefStringId → last Gold/Hearth snapshot
        private readonly Dictionary<string, int> _lastSnapshot
            = new Dictionary<string, int>();

        // Village hearth → dinars conversion proxy (hearth growth = prosperity gain).
        private const int VILLAGE_HEARTH_TO_DINARS = 10;

        public override void RegisterEvents()
        {
            CampaignEvents.DailyTickEvent.AddNonSerializedListener(this, OnDailyTick);
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoaded);
        }

        public override void SyncData(IDataStore dataStore)
        {
            // Stateless — snapshots rebuilt on game load.
        }

        private void OnGameLoaded()
        {
            try
            {
                _lastSnapshot.Clear();
                int seeded = 0;
                foreach (var s in Settlement.All)
                {
                    if (s == null) continue;
                    if (!IsOwnedByBLink(s)) continue;
                    _lastSnapshot[s.StringId] = ReadCurrentValue(s);
                    seeded++;
                }
                if (seeded > 0)
                    BannerlordLinkModule.Log($"[fief-sync] OnGameLoaded seeded {seeded} fief snapshots");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[fief-sync] OnGameLoaded crash: {ex.Message}");
            }
        }

        private void OnDailyTick()
        {
            try
            {
                int synced = 0;
                foreach (var s in Settlement.All)
                {
                    if (s == null) continue;
                    if (!IsOwnedByBLink(s, out var ownerLogin)) continue;
                    int curVal = ReadCurrentValue(s);
                    int prevVal;
                    if (!_lastSnapshot.TryGetValue(s.StringId, out prevVal))
                    {
                        // First observation — seed and skip.
                        _lastSnapshot[s.StringId] = curVal;
                        continue;
                    }
                    int diff = curVal - prevVal;
                    _lastSnapshot[s.StringId] = curVal;
                    if (diff <= 0) continue;

                    int netDinars;
                    string fiefType;
                    if (s.IsVillage)
                    {
                        netDinars = diff * VILLAGE_HEARTH_TO_DINARS;
                        fiefType = "village";
                    }
                    else if (s.IsCastle)
                    {
                        netDinars = diff;
                        fiefType = "castle";
                    }
                    else if (s.IsTown)
                    {
                        netDinars = diff;
                        fiefType = "town";
                    }
                    else continue;

                    PushSync(s, ownerLogin, fiefType, netDinars);
                    synced++;
                }
                if (synced > 0)
                    BannerlordLinkModule.Log($"[fief-sync] OnDailyTick pushed {synced} fief tributes");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[fief-sync] OnDailyTick crash: {ex.Message}");
            }
        }

        // ── Helpers ────────────────────────────────────────────────────────────

        private static int ReadCurrentValue(Settlement s)
        {
            try
            {
                if (s.IsVillage && s.Village != null) return (int)s.Village.Hearth;
                if (s.Town != null) return s.Town.Gold;
            }
            catch { }
            return 0;
        }

        private static bool IsOwnedByBLink(Settlement s)
        {
            return IsOwnedByBLink(s, out _);
        }

        private static bool IsOwnedByBLink(Settlement s, out string ownerLogin)
        {
            ownerLogin = null;
            try
            {
                Hero owner = null;
                // Town/Castle → OwnerClan.Leader. Village → bound town's owner or Village.Settlement.OwnerClan.
                if (s.OwnerClan?.Leader != null) owner = s.OwnerClan.Leader;
                if (owner == null) return false;
                if (owner.Name == null) return false;
                string nm = owner.Name.ToString();
                if (!HeroNaming.IsAdopted(nm)) return false;
                ownerLogin = HeroNaming.ExtractUsername(nm)?.ToLowerInvariant();
                return !string.IsNullOrEmpty(ownerLogin);
            }
            catch { return false; }
        }

        private static void PushSync(Settlement s, string ownerLogin, string fiefType, int netDinars)
        {
            try
            {
                string evtData = Newtonsoft.Json.JsonConvert.SerializeObject(new
                {
                    owner        = ownerLogin,
                    fief_id      = s.StringId,
                    fief_name    = s.Name?.ToString() ?? s.StringId,
                    fief_type    = fiefType,
                    net_dinars   = netDinars,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.fief_tribute_sync", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[fief-sync] push crash: {ex.Message}");
            }
        }
    }
}
