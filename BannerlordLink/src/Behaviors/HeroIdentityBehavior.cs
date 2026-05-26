using System;
using System.Collections.Generic;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.32 (BLT-parity M9) — persistent identity для adopted viewer heroes.
    ///
    /// Раньше: `[BLink] username` substring в Hero.Name был единственным маркером,
    /// что hero — adopted. Проблемы:
    ///   - Engine иногда переименовывает hero (clan promotion, retirement, lord
    ///     court UI, save migration в новые версии TaleWorlds).
    ///   - Username extraction завязан на parsing — каждый refactor имени = риск
    ///     потерять идентичность.
    ///   - Vanilla NPC случайно с похожим именем (тип `[BLink] something` от
    ///     mod conflict) — false-positive в IsAdopted.
    ///
    /// Теперь: `Dictionary&lt;heroStringId, username&gt;` сериализуется в save
    /// через SyncData. Регистрируется в AdoptHeroHandler.CreateHero сразу после
    /// HeroCreator.CreateSpecialHero. HeroLookup.FindByUsername сначала смотрит
    /// в dict, fallback к name-substring (BACKWARD COMPAT — старые saves до 5.32
    /// не имеют dict записей).
    ///
    /// Bootstrap: на OnGameLoaded сканим все alive heroes с [BLink] префиксом
    /// и populate dict — это one-time миграция для существующих save'ов.
    ///
    /// BLT использует похожий pattern (BLTAdoptAHeroCampaignBehavior._heroData
    /// Dictionary&lt;Hero, HeroData&gt; with SyncData). Мы храним по StringId
    /// (более resilient — Hero reference может change через save/load).
    /// </summary>
    public class HeroIdentityBehavior : CampaignBehaviorBase
    {
        public static HeroIdentityBehavior Instance { get; private set; }

        // Сериализуемый dict. Hero.StringId — стабильный engine-ID, не меняется
        // при rename. Username — viewer login (lowercase, без [BLink] prefix).
        private Dictionary<string, string> _heroIdToUsername =
            new Dictionary<string, string>(StringComparer.Ordinal);

        public override void RegisterEvents()
        {
            Instance = this;
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoadFinished);
        }

        public override void SyncData(IDataStore dataStore)
        {
            try
            {
                dataStore.SyncData("BannerlordLink_HeroIdentity_v1", ref _heroIdToUsername);
                if (_heroIdToUsername == null)
                    _heroIdToUsername = new Dictionary<string, string>(StringComparer.Ordinal);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroIdentity] SyncData warn: {ex.Message}");
                if (_heroIdToUsername == null)
                    _heroIdToUsername = new Dictionary<string, string>(StringComparer.Ordinal);
            }
        }

        /// <summary>Register mapping. Called from AdoptHeroHandler сразу после
        /// CreateSpecialHero + SetName.</summary>
        public void Register(Hero hero, string username)
        {
            if (hero == null || string.IsNullOrEmpty(username)) return;
            try
            {
                _heroIdToUsername[hero.StringId] = username.ToLowerInvariant();
                BannerlordLinkModule.Log(
                    $"[HeroIdentity M9] register: {hero.StringId} → @{username}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroIdentity M9] Register warn: {ex.Message}");
            }
        }

        /// <summary>Lookup username by hero ID. Returns null если не registered.</summary>
        public string GetUsername(Hero hero)
        {
            if (hero == null) return null;
            return _heroIdToUsername.TryGetValue(hero.StringId, out string u) ? u : null;
        }

        /// <summary>Lookup hero by username. Returns null если не найден.</summary>
        public Hero FindByUsername(string username)
        {
            if (string.IsNullOrEmpty(username)) return null;
            string lower = username.ToLowerInvariant();
            // Reverse lookup. Map обычно small (<200 viewers), linear OK.
            foreach (var kv in _heroIdToUsername)
            {
                if (!string.Equals(kv.Value, lower, StringComparison.Ordinal)) continue;
                try
                {
                    var hero = MBObjectManager.Instance.GetObject<Hero>(kv.Key);
                    if (hero != null && hero.IsAlive) return hero;
                }
                catch { /* hero может быть GC'нут engine'ом — skip */ }
            }
            return null;
        }

        /// <summary>Check is hero registered (= adopted).</summary>
        public bool IsRegistered(Hero hero)
        {
            return hero != null && _heroIdToUsername.ContainsKey(hero.StringId);
        }

        /// <summary>OnGameLoaded bootstrap: scan all alive heroes, populate
        /// dict для existing [BLink] heroes которые не имеют записи в нашем
        /// dict (старый save до 5.32). One-time миграция: после первого save
        /// dict персистится через SyncData.</summary>
        private void OnGameLoadFinished()
        {
            try
            {
                int bootstrapped = 0;
                var allHeroes = Hero.AllAliveHeroes;
                if (allHeroes == null) return;
                foreach (var hero in allHeroes)
                {
                    if (hero == null || hero.Name == null) continue;
                    if (_heroIdToUsername.ContainsKey(hero.StringId)) continue;
                    string name = hero.Name.ToString();
                    if (!BannerlordLink.Util.HeroNaming.IsAdopted(name)) continue;
                    string username = BannerlordLink.Util.HeroNaming.ExtractUsername(name);
                    if (string.IsNullOrEmpty(username)) continue;
                    _heroIdToUsername[hero.StringId] = username;
                    bootstrapped++;
                }
                if (bootstrapped > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[HeroIdentity M9] bootstrap: registered {bootstrapped} " +
                        $"existing [BLink] heroes (one-time миграция)");
                }
                else
                {
                    BannerlordLinkModule.Log(
                        $"[HeroIdentity M9] bootstrap: 0 new registrations, " +
                        $"dict size={_heroIdToUsername.Count} (persistent state)");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroIdentity M9] bootstrap crashed: {ex.Message}");
            }
        }
    }
}
