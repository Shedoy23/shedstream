using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// 2026-06-15 — per-save persistence для backend-only состояния героя, которое
    /// мод НЕ может прочитать из игры напрямую (нет свойства на Hero). Хранится
    /// ВНУТРИ сейва через SyncData (как HeroIdentityBehavior), поэтому каждый сейв
    /// помнит СВОЁ, и переключение сейвов не путает класс/стойку/тир.
    ///
    /// Проблема, которую решаем: backend хранит class_key / combat_stance / gear_tier
    /// по ключу (channel, username) БЕЗ привязки к сейву → один набор на все сейвы
    /// канала. На смене сейва фронт показывал значения прошлого playthrough.
    ///
    /// Поток:
    ///   • Мод ловит значения, когда мимо проходит action (set_class / set_combat_stance
    ///     / upgrade_gear) — Set*() обновляет запись в _profiles (per-username JSON).
    ///   • SyncData сохраняет _profiles в файл сейва.
    ///   • OnGameLoadFinished → ре-пушим каждый профиль на backend (hero.restore_profile),
    ///     backend перезаписывает class/stance/gear_tier для героев ЭТОГО сейва.
    ///
    /// Свита (retinue) сюда добавится отдельно через backend-эхо: мод по-слотно НЕ
    /// получает troop_name неизменённых слотов, поэтому полный список ему присылает
    /// backend (у него источник правды).
    ///
    /// Формат значения: JSON {"class_key":..,"stance":..,"gear_tier":N} — расширяемо.
    /// </summary>
    public class HeroProfileBehavior : CampaignBehaviorBase
    {
        public static HeroProfileBehavior Instance { get; private set; }

        // username (lowercase) → profile JSON string.
        private Dictionary<string, string> _profiles =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        public override void RegisterEvents()
        {
            Instance = this;
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoadFinished);
        }

        public override void SyncData(IDataStore dataStore)
        {
            try
            {
                dataStore.SyncData("BannerlordLink_HeroProfile_v1", ref _profiles);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroProfile] SyncData warn: {ex.Message}");
            }
            if (_profiles == null)
                _profiles = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        }

        // ── Capture API (зовут action handler'ы) ───────────────────────────────
        public void SetClass(string username, string classKey) => SetField(username, "class_key", classKey);
        public void SetStance(string username, string stance)   => SetField(username, "stance", stance);
        public void SetGearTier(string username, int gearTier)  => SetField(username, "gear_tier", gearTier);
        public void SetRetinue(string username, JArray slots)   => SetField(username, "retinue", slots);

        /// <summary>Строит retinue JArray из сырых слотов, резолвя troop_name из
        /// troop_id через игру (бэк имён не знает — их источник в движке). Зовут
        /// recruit/train handler'ы после изменения свиты.</summary>
        public static JArray BuildRetinueJson(
            IEnumerable<(int slot, string troopId, int tier, bool isElite)> slots)
        {
            var arr = new JArray();
            foreach (var s in slots)
            {
                if (string.IsNullOrEmpty(s.troopId)) continue;
                string name = s.troopId;
                try
                {
                    var co = MBObjectManager.Instance.GetObject<CharacterObject>(s.troopId);
                    if (co?.Name != null) name = co.Name.ToString();
                }
                catch { /* имя best-effort */ }
                arr.Add(new JObject
                {
                    ["slot_index"] = s.slot,
                    ["troop_id"]   = s.troopId,
                    ["troop_name"] = name,
                    ["tier"]       = s.tier,
                    ["is_elite"]   = s.isElite,
                });
            }
            return arr;
        }

        private void SetField(string username, string field, JToken value)
        {
            if (string.IsNullOrEmpty(username) || value == null) return;
            try
            {
                string key = username.ToLowerInvariant();
                JObject p;
                if (_profiles.TryGetValue(key, out var s) && !string.IsNullOrEmpty(s))
                {
                    try { p = JObject.Parse(s); } catch { p = new JObject(); }
                }
                else p = new JObject();
                p[field] = value;
                _profiles[key] = p.ToString(Newtonsoft.Json.Formatting.None);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroProfile] SetField {field} @{username} warn: {ex.Message}");
            }
        }

        // ── Restore on load ─────────────────────────────────────────────────────
        private void OnGameLoadFinished()
        {
            try
            {
                var backend = BannerlordLinkModule.Backend;
                if (backend == null || _profiles == null || _profiles.Count == 0) return;
                int n = 0;
                foreach (var kv in _profiles)
                {
                    if (string.IsNullOrEmpty(kv.Value)) continue;
                    JObject p;
                    try { p = JObject.Parse(kv.Value); } catch { continue; }
                    p["username"] = kv.Key;
                    string json = p.ToString(Newtonsoft.Json.Formatting.None);
                    Task.Run(async () =>
                    {
                        try { await backend.PostEventAsync("bannerlord", "hero.restore_profile", json); }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log($"[HeroProfile] restore push @{kv.Key} failed: {ex.Message}");
                        }
                    });
                    n++;
                }
                BannerlordLinkModule.Log($"[HeroProfile] save-load: restored {n} hero profile(s) to backend");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroProfile] OnGameLoadFinished error: {ex.Message}");
            }
        }
    }
}
