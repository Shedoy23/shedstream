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
        // Static accessor для model replacements (вызываются из BLUpgradeModels.cs).
        // Pattern скопирован с BLT'шного UpgradeBehavior.Current.
        public static ClanUpgradesBehavior Current { get; private set; }

        public ClanUpgradesBehavior() { Current = this; }

        // Sprint 5.29 audit fix #31 (HIGH thread-safety):
        // Раньше plain Dictionary mutated с background Task.Run (Fetch выполняется
        // на ThreadPool) + read из model overrides (engine может звать с любого
        // thread'а, особенно AI/path-finding). Это давало torn reads / Collection
        // modified crashes под нагрузкой.
        //
        // Fix: atomic-swap pattern. FetchUpgradesAsync строит НОВЫЕ dicts и
        // atomic-replace под lock. GetBonusFor читает snapshot через volatile
        // reference (один read → consistent view, без lock на каждом call'е).
        private readonly object _cacheLock = new object();
        private volatile Dictionary<string, List<string>> _ownedByUser
            = new Dictionary<string, List<string>>();
        private volatile Dictionary<string, Dictionary<string, double>> _effectsByUpgrade
            = new Dictionary<string, Dictionary<string, double>>();
        private bool _fetchedThisTick;
        // 2026-06-15 — per-save persistence owned-апгрейдов (SyncData в файле сейва).
        // FetchUpgradesAsync зеркалит сюда последний НЕ-пустой owned-список; на
        // загрузке RestoreOwnedFromSave ре-пушит его на backend (после вайпа сейва).
        private volatile string _ownedJson = "";

        /// <summary>
        /// Суммарный эффект effectKey для конкретного hero. Возвращает 0 если
        /// hero не [BLink], не имеет купленных upgrades, или ключ не присутствует
        /// ни в одном из его upgrades.
        /// </summary>
        public double GetBonusFor(Hero hero, string effectKey)
        {
            if (hero?.Name == null) return 0.0;
            if (!HeroNaming.IsAdopted(hero.Name.ToString())) return 0.0;
            var login = HeroNaming.ExtractUsername(hero.Name.ToString())?.ToLowerInvariant();
            if (string.IsNullOrEmpty(login)) return 0.0;

            // Atomic snapshot — capture refs локально. Если фоновый Fetch
            // в этот момент свапает _ownedByUser/_effectsByUpgrade, мы держим
            // self-consistent старый snapshot до конца метода.
            var ownedSnap   = _ownedByUser;
            var effectsSnap = _effectsByUpgrade;
            if (!ownedSnap.TryGetValue(login, out var upgrades)) return 0.0;

            double total = 0.0;
            foreach (var upgId in upgrades)
            {
                if (!effectsSnap.TryGetValue(upgId, out var eff)) continue;
                if (eff.TryGetValue(effectKey, out var v)) total += v;
            }
            return total;
        }

        /// <summary>Sum effect для clan'а (берёт у clan.Leader).</summary>
        public double GetBonusForClan(Clan clan, string effectKey)
        {
            if (clan?.Leader == null) return 0.0;
            return GetBonusFor(clan.Leader, effectKey);
        }

        public override void RegisterEvents()
        {
            CampaignEvents.DailyTickEvent.AddNonSerializedListener(this, OnDailyTick);
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoaded);
            CampaignEvents.OnSessionLaunchedEvent.AddNonSerializedListener(this, OnSessionLaunched);
        }

        public override void SyncData(IDataStore dataStore)
        {
            try
            {
                string s = _ownedJson;
                dataStore.SyncData("BannerlordLink_ClanUpgrades_v1", ref s);
                _ownedJson = s ?? "";
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[ClanUpgrades] SyncData warn: {ex.Message}");
            }
        }

        private void OnGameLoaded() => _ = OnEnterCampaignAsync();
        private void OnSessionLaunched(CampaignGameStarter starter) => _ = OnEnterCampaignAsync();

        // 2026-06-15 — на входе в кампанию: восстанавливаем owned-апгрейды ЭТОГО
        // сейва из SyncData → backend (после вайпа на смене сейва), затем фетчим
        // ТОЛЬКО catalog. Owned из backend на загрузке НЕ берём — он post-wipe пустой
        // и затёр бы restore; новые покупки подхватит дневной тик (fetchOwned=true).
        private async Task OnEnterCampaignAsync()
        {
            RestoreOwnedFromSave();
            await FetchUpgradesAsync(fetchOwned: false);
        }

        private void RestoreOwnedFromSave()
        {
            try
            {
                if (string.IsNullOrEmpty(_ownedJson)) return;
                var owned = JsonConvert.DeserializeObject<Dictionary<string, List<string>>>(_ownedJson);
                if (owned == null || owned.Count == 0) return;
                lock (_cacheLock) { _ownedByUser = owned; }   // tick работает сразу
                string json = JsonConvert.SerializeObject(new { owned });
                Task.Run(async () =>
                {
                    try { await BannerlordLinkModule.Backend.PostEventAsync("bannerlord", "hero.restore_clan_upgrades", json); }
                    catch (Exception ex) { BannerlordLinkModule.Log($"[ClanUpgrades] restore push failed: {ex.Message}"); }
                });
                BannerlordLinkModule.Log($"[ClanUpgrades] save-load: restored {owned.Count} owner(s) to backend");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[ClanUpgrades] restore parse warn: {ex.Message}");
            }
        }

        private void OnDailyTick()
        {
            _fetchedThisTick = false;
            // Fetch fresh data (async, но мы не блочим day tick)
            _ = ApplyDailyTickAsync();
        }

        private async Task FetchUpgradesAsync(bool fetchOwned = true)
        {
            try
            {
                // Sprint 5.32 BUGFIX — missing `/api/` prefix. Раньше URL был
                // `bannerlord/clan-upgrades/all-owners` без префикса → backend
                // отвечал 404, daily upgrade tick никогда не применялся.
                string json = await BannerlordLinkModule.Backend
                    .GetAsync("/api/bannerlord/clan-upgrades/all-owners");
                if (string.IsNullOrEmpty(json)) return;
                var parsed = JObject.Parse(json);
                if (parsed["success"] == null || !(bool)parsed["success"]) return;

                // Sprint 5.29 audit fix #31: atomic-swap pattern. Build new
                // dicts локально, replace refs под lock в конце. GetBonusFor
                // captures snapshot ref → старые dicts держатся пока кто-то
                // читает, новые сразу видны на следующем read.
                var newOwned = new Dictionary<string, List<string>>();
                var ownersObj = parsed["owners"] as JObject;
                if (ownersObj != null)
                {
                    foreach (var kv in ownersObj)
                    {
                        var list = (kv.Value as JArray)?.Select(t => t.ToString()).ToList()
                                   ?? new List<string>();
                        newOwned[kv.Key.ToLowerInvariant()] = list;
                    }
                }

                var newEffects = new Dictionary<string, Dictionary<string, double>>();
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
                        newEffects[kv.Key] = effDict;
                    }
                }

                // Atomic swap — readers см. либо полностью old, либо полностью new,
                // но не половинку. volatile field assignment → нет need в memory barrier.
                lock (_cacheLock)
                {
                    if (fetchOwned) _ownedByUser = newOwned;
                    _effectsByUpgrade = newEffects;
                    // Зеркалим owned в SyncData-поле — но только НЕ-пустой: post-wipe
                    // пустой фетч не должен затирать сохранённый per-save список.
                    if (fetchOwned && newOwned.Count > 0)
                    {
                        try { _ownedJson = JsonConvert.SerializeObject(newOwned); } catch { }
                    }
                }

                _fetchedThisTick = true;
                BannerlordLinkModule.Log(
                    $"[ClanUpgrades] fetched: {newOwned.Count} owners, "
                    + $"{newEffects.Count} catalog entries");
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
                // Sprint 5.29 audit fix #31: snapshot вначале — atomic view.
                var ownedSnap   = _ownedByUser;
                var effectsSnap = _effectsByUpgrade;

                foreach (var hero in Campaign.Current.AliveHeroes.ToList())
                {
                    if (hero?.Name == null || hero.Clan == null) continue;
                    if (!HeroNaming.IsAdopted(hero.Name.ToString())) continue;
                    var login = HeroNaming.ExtractUsername(hero.Name.ToString())?.ToLowerInvariant();
                    if (string.IsNullOrEmpty(login)) continue;
                    if (!ownedSnap.TryGetValue(login, out var upgrades) || upgrades.Count == 0)
                        continue;

                    double renown = 0.0, influence = 0.0;
                    foreach (var upgId in upgrades)
                    {
                        if (!effectsSnap.TryGetValue(upgId, out var eff)) continue;
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
