using System;
using BannerlordLink.Util;
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

        // 2026-05-28 BLT-PARITY (Lait AdoptAHero `Iteration` counter) —
        // tracks re-adopt count per viewer. Increments on each Register().
        // Useful для Heritage log (показывать "Hero #N of viewer @username").
        private Dictionary<string, int> _iterationByUsername =
            new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

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
                // 2026-05-28: iteration counter (per-username re-adopt count).
                dataStore.SyncData("BannerlordLink_HeroIteration_v1", ref _iterationByUsername);
                if (_iterationByUsername == null)
                    _iterationByUsername = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroIdentity] SyncData warn: {ex.Message}");
                if (_heroIdToUsername == null)
                    _heroIdToUsername = new Dictionary<string, string>(StringComparer.Ordinal);
                if (_iterationByUsername == null)
                    _iterationByUsername = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            }
        }

        /// <summary>Register mapping. Called from AdoptHeroHandler сразу после
        /// CreateSpecialHero + SetName.
        ///
        /// Returns iteration count (BLT-parity, per-username re-adopt counter,
        /// 0 для first adopt, 1 для second, etc.). Backend stores это в
        /// inheritance_log для отображения "Hero #N of @username".</summary>
        public int Register(Hero hero, string username)
        {
            if (hero == null || string.IsNullOrEmpty(username)) return 0;
            try
            {
                string userLower = username.ToLowerInvariant();
                _heroIdToUsername[hero.StringId] = userLower;
                int iteration = 0;
                if (_iterationByUsername.TryGetValue(userLower, out int prev))
                {
                    iteration = prev + 1;
                }
                _iterationByUsername[userLower] = iteration;
                BannerlordLinkModule.Log(
                    $"[HeroIdentity M9] register: {hero.StringId} → @{username} (iteration={iteration})");
                return iteration;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroIdentity M9] Register warn: {ex.Message}");
                return 0;
            }
        }

        /// <summary>Get current iteration count for username (-1 if never registered).</summary>
        public int GetIteration(string username)
        {
            if (string.IsNullOrEmpty(username)) return -1;
            return _iterationByUsername.TryGetValue(username.ToLowerInvariant(), out int n)
                ? n : -1;
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
                    // 2026-07-31: см. Util/HeroResolver.cs
                    var hero = HeroResolver.ByStringId(kv.Key, out string _idReason);
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
        /// <summary>
        /// Лечение кланов без «центра фракции» — по одному разу на загрузку.
        ///
        /// 2026-07-31, ПОСЛЕ КРАША НА СТРИМЕ (21:10). Наши кланы создавались без
        /// `CalculateMidSettlement()`, который ваниль зовёт явно. В итоге
        /// `FactionMidSettlement` оставался null, а выборы за владение
        /// (`SettlementClaimantDecision` → `DefaultSettlementValueModel`) читают
        /// его БЕЗ проверки:
        ///
        ///     if (faction.FactionMidSettlement.MapFaction != faction)   ← NRE
        ///
        /// Падает на дневном тике, то есть у зрителей на глазах.
        ///
        /// Создание уже починено (`ClanFactory`), но кланы, ЗАВЕДЁННЫЕ РАНЬШЕ,
        /// сидят в сейве со сломанным полем и продолжают ронять игру. Поэтому
        /// на каждой загрузке пересчитываем его всем кланам, у кого он пуст —
        /// операция дешёвая и идемпотентная, ваниль делает ровно это же.
        /// </summary>
        private void RepairClanMidSettlements()
        {
            try
            {
                int fixedCount = 0;
                var all = Clan.All;
                if (all == null) return;
                foreach (var clan in all)
                {
                    if (clan == null || clan.IsEliminated) continue;
                    if (clan.FactionMidSettlement != null) continue;
                    try
                    {
                        clan.CalculateMidSettlement();
                        if (clan.FactionMidSettlement != null) fixedCount++;
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[mid-repair] '{clan.Name}': {ex.Message}");
                    }
                }
                if (fixedCount > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[mid-repair] восстановлен центр фракции у {fixedCount} клан(ов) — "
                        + "без него выборы за владение роняют игру");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[mid-repair] упал: {ex.Message}");
            }
        }

        private void OnGameLoadFinished()
        {
            RepairClanMidSettlements();
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
