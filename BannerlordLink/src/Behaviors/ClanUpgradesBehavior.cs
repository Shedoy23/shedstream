using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.26c — BLT-style clan upgrades.
    ///
    /// Behavior подписан на DailyTickEvent. Раз в день fetch'ит с backend'a
    /// map {username → [upgrade_id]} и catalog_effects {upgrade_id → {...}}.
    /// Для каждого adopted [BLink] hero вычисляет суммарные effects (renown_daily,
    /// influence_daily) и применяет их к Clan через AddRenown / AddInfluence.
    ///
    /// На этом этапе (5.26c) применяются ТОЛЬКО daily ticks (renown + влияние).
    /// Статические бонусы (party_size, retinue_size, speeds, max_parties,
    /// max_vassals) требуют Harmony patches и реализуются follow-up'ом.
    ///
    /// Performance: один HTTP-запрос в day-tick, кеш в _ownedCache до next tick.
    /// </summary>
    public class ClanUpgradesBehavior : CampaignBehaviorBase
    {
        // Кэш: username → list of upgrade_ids
        private Dictionary<string, List<string>> _ownedByUser = new Dictionary<string, List<string>>();
        // Кэш: upgrade_id → effects dict
        private Dictionary<string, Dictionary<string, double>> _effectsByUpgrade =
            new Dictionary<string, Dictionary<string, double>>();
        private bool _fetchedThisTick;

        public override void RegisterEvents()
        {
            CampaignEvents.DailyTickEvent.AddNonSerializedListener(this, OnDailyTick);
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoaded);
            CampaignEvents.OnSessionLaunchedEvent.AddNonSerializedListener(this, OnSessionLaunched);
        }

        public override void SyncData(IDataStore dataStore) { /* stateless */ }

        private void OnGameLoaded() => _ = FetchUpgradesAsync();
        private void OnSessionLaunched(CampaignGameStarter starter) => _ = FetchUpgradesAsync();

        private void OnDailyTick()
        {
            _fetchedThisTick = false;
            // Fetch fresh data (async, но мы не блочим day tick)
            _ = ApplyDailyTickAsync();
        }

        private async Task FetchUpgradesAsync()
        {
            try
            {
                string json = await BannerlordLinkModule.Backend
                    .GetAsync("bannerlord/clan-upgrades/all-owners");
                if (string.IsNullOrEmpty(json)) return;
                var parsed = JObject.Parse(json);
                if (parsed["success"] == null || !(bool)parsed["success"]) return;

                _ownedByUser.Clear();
                var ownersObj = parsed["owners"] as JObject;
                if (ownersObj != null)
                {
                    foreach (var kv in ownersObj)
                    {
                        var list = (kv.Value as JArray)?.Select(t => t.ToString()).ToList()
                                   ?? new List<string>();
                        _ownedByUser[kv.Key.ToLowerInvariant()] = list;
                    }
                }

                _effectsByUpgrade.Clear();
                var catalogObj = parsed["catalog_effects"] as JObject;
                if (catalogObj != null)
                {
                    foreach (var kv in catalogObj)
                    {
                        var effDict = new Dictionary<string, double>();
                        var effObj = kv.Value as JObject;
                        if (effObj != null)
                        {
                            foreach (var ek in effObj)
                                effDict[ek.Key] = (double)ek.Value;
                        }
                        _effectsByUpgrade[kv.Key] = effDict;
                    }
                }

                _fetchedThisTick = true;
                BannerlordLinkModule.Log(
                    $"[ClanUpgrades] fetched: {_ownedByUser.Count} owners, "
                    + $"{_effectsByUpgrade.Count} catalog entries");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[ClanUpgrades] fetch error: {ex.Message}");
            }
        }

        private async Task ApplyDailyTickAsync()
        {
            try
            {
                if (!_fetchedThisTick) await FetchUpgradesAsync();
                if (Campaign.Current?.AliveHeroes == null) return;

                int appliedRenown = 0, appliedInfluence = 0;
                foreach (var hero in Campaign.Current.AliveHeroes.ToList())
                {
                    if (hero?.Name == null || hero.Clan == null) continue;
                    if (!HeroNaming.IsAdopted(hero.Name.ToString())) continue;
                    var login = HeroNaming.ExtractUsername(hero.Name.ToString())?.ToLowerInvariant();
                    if (string.IsNullOrEmpty(login)) continue;
                    if (!_ownedByUser.TryGetValue(login, out var upgrades) || upgrades.Count == 0)
                        continue;

                    double renown = 0.0, influence = 0.0;
                    foreach (var upgId in upgrades)
                    {
                        if (!_effectsByUpgrade.TryGetValue(upgId, out var eff)) continue;
                        if (eff.TryGetValue("renown_daily", out var rv)) renown += rv;
                        if (eff.TryGetValue("influence_daily", out var iv)) influence += iv;
                    }

                    if (renown > 0)
                    {
                        try
                        {
                            hero.Clan.AddRenown((float)renown, false);
                            appliedRenown++;
                        }
                        catch { }
                    }
                    if (influence > 0)
                    {
                        try
                        {
                            // ChangeClanInfluenceAction.Apply — официальный API
                            ChangeClanInfluenceAction.Apply(hero.Clan, (float)influence);
                            appliedInfluence++;
                        }
                        catch { }
                    }
                }

                if (appliedRenown > 0 || appliedInfluence > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[ClanUpgrades] daily tick: renown→{appliedRenown} heroes, "
                        + $"influence→{appliedInfluence} heroes");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[ClanUpgrades] apply error: {ex.Message}");
            }
        }
    }
}
