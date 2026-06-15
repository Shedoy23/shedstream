using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// `hero.recruit_troops` — BLT-style retinue recruit/upgrade.
    ///
    /// data: { target }
    /// Логика (BLT pattern, BLTAdoptAHeroCampaignBehavior.UpgradeRetinue):
    ///   1. Skip если Mission.Current != null (snar/retinue locked in battle).
    ///   2. Read retinue snapshot из game ?
    ///      У нас mod-side не хранит state — backend хранит в bannerlord_retinue.
    ///      Mod просто получает существующий retinue через action_data:
    ///        data.retinue = [{slot_index, troop_id, tier}, ...]
    ///      и решает что делать (add/upgrade).
    ///   3. Если len(retinue) < MAX_RETINUE (5):
    ///      • Pick basic troop из hero.Culture (BasicTroop)
    ///      • Hero.Gold cost = TIER_COSTS[0] = 5000
    ///      • Insert new slot
    ///   4. Else: upgrade lowest-tier troop:
    ///      • Find min tier in retinue
    ///      • CharacterObject.UpgradeTargets.SelectRandom() → new troop
    ///      • Cost = TIER_COSTS[tier]
    ///   5. Push event hero.retinue_changed {slots: [...]} → backend syncs.
    ///
    /// Hero.Gold cost (BLT defaults):
    ///   T0→T1: 5000, T1→T2: 10000, T2→T3: 20000, T3→T4: 30000, T4→T5: 50000
    /// </summary>
    public class RecruitTroopsHandler : IActionHandler
    {
        public string ActionType => "hero.recruit_troops";

        private const int MAX_RETINUE = 5;
        private const float ELITE_COST_MULTIPLIER = 3f;   // Sprint 5.14: 3× для elite

        private static readonly int[] TIER_COSTS =
        {
            5_000,   // recruit (tier 0)
            10_000,  // upgrade tier 0 → 1
            20_000,  // tier 1 → 2
            30_000,  // tier 2 → 3
            50_000,  // tier 3 → 4
            80_000,  // tier 4 → 5
        };

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            // Sprint 5.14: is_elite flag — recruit/upgrade culture.EliteBasicTroop
            bool isElite = (bool?)data["is_elite"] ?? false;

            // Backend passes current retinue snapshot (из bannerlord_retinue).
            // Mod использует чтобы знать какие slots filled и какие troops upgrade'ить.
            var retinueJson = data["retinue"] as JArray;
            var existingSlots = new List<(int slot, string troopId, int tier, bool isElite)>();
            if (retinueJson != null)
            {
                foreach (var item in retinueJson)
                {
                    int slot = (int?)item["slot_index"] ?? -1;
                    string troopId = item["troop_id"]?.ToString();
                    int tier = (int?)item["tier"] ?? 0;
                    bool slotElite = (bool?)item["is_elite"] ?? false;
                    if (slot >= 0 && !string.IsNullOrEmpty(troopId))
                        existingSlots.Add((slot, troopId, tier, slotElite));
                }
            }

            MainThreadDispatcher.Enqueue(() => Recruit(username, existingSlots, isElite));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Recruit(string username,
            List<(int slot, string troopId, int tier, bool isElite)> existing,
            bool wantElite)
        {
            try
            {
                // 2026-06-06 — УБРАН guard `Mission.Current != null`. Раньше он
                // блокировал рекрут в ЛЮБОЙ миссии, включая город/таверну (там
                // Mission.Current != null) → стример видел «свита не нанимается».
                // Рекрут безопасен в любом контексте: только списывает Hero.Gold
                // и пушит hero.retinue_changed — никакого SpawnTroop в текущем бою
                // (новые войска появятся при СЛЕДУЮЩЕМ призыве). Был BLT-зеркалом с
                // campaign-tick контекста, для viewer-действия слишком строго.

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[recruit_troops] @{username}: hero не найден или мёртв");
                    return;
                }

                // 2026-06-10 FIX — кэп свиты = 5 + retinue_size_bonus от clan upgrades.
                // Раньше MAX_RETINUE был захардкожен 5 → апгрейд «Усиленная свита»
                // (retinue_size_bonus) не открывал дополнительный слот свиты.
                int retinueCap = MAX_RETINUE;
                try
                {
                    retinueCap += (int)(BannerlordLink.Behaviors.ClanUpgradesBehavior
                        .Current?.GetBonusFor(hero, "retinue_size_bonus") ?? 0.0);
                }
                catch { }

                // Decide: add new troop OR upgrade existing?
                // Sprint 5.14: для upgrade pickaем slot нужного типа (elite/basic),
                // чтобы wantElite=true upgrade'ил elite trooper, не basic.
                bool addNew = existing.Count < retinueCap;
                int tier = 0;
                if (!addNew)
                {
                    var sameTypeSlots = existing.Where(s => s.isElite == wantElite).ToList();
                    if (sameTypeSlots.Count == 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[recruit_troops] @{username}: " +
                            $"нет {(wantElite ? "elite" : "basic")} troop'ов для upgrade " +
                            "(только противоположный тип)");
                        return;
                    }
                    tier = sameTypeSlots.OrderBy(s => s.tier).First().tier;
                }
                int baseCost = tier < TIER_COSTS.Length ? TIER_COSTS[tier] : TIER_COSTS[TIER_COSTS.Length - 1];
                int cost = wantElite ? (int)(baseCost * ELITE_COST_MULTIPLIER) : baseCost;

                if (hero.Gold < cost)
                {
                    BannerlordLinkModule.Log(
                        $"[recruit_troops] @{username}: not enough gold ({hero.Gold} < {cost}) " +
                        $"для {(addNew ? "recruit" : $"upgrade T{tier}")} " +
                        $"{(wantElite ? "[ELITE 3×]" : "")}");
                    return;
                }

                CharacterObject newTroop = null;
                int newTier = 0;
                int updatedSlot;

                if (addNew)
                {
                    var culture = hero.Culture;
                    if (culture == null)
                    {
                        BannerlordLinkModule.Log(
                            $"[recruit_troops] @{username}: hero.Culture == null");
                        return;
                    }
                    // Sprint 5.14: pick basic OR elite troop по wantElite
                    newTroop = wantElite ? culture.EliteBasicTroop : culture.BasicTroop;
                    if (newTroop == null || newTroop.Culture != culture)
                    {
                        BannerlordLinkModule.Log(
                            $"[recruit_troops] @{username}: " +
                            $"culture.{(wantElite ? "EliteBasicTroop" : "BasicTroop")} mismatch! " +
                            $"hero.Culture={culture.StringId}, " +
                            $"got={newTroop?.StringId ?? "null"}. " +
                            "Fallback к explicit search.");
                        newTroop = FindCultureRecruit(culture, wantElite);
                        if (newTroop == null)
                        {
                            BannerlordLinkModule.Log(
                                $"[recruit_troops] @{username}: no T0 " +
                                $"{(wantElite ? "elite" : "basic")} troop для {culture.StringId}");
                            return;
                        }
                    }

                    // Sprint 5.32 (BLT-parity M12) — class-aware troop selection.
                    // Cavalry viewer должен получать cavalry-troop'а, archer — archer.
                    // BFS вниз по UpgradeTargets от basic/elite recruit'а ищет
                    // первого troop'а с подходящим FormationClass. Если не находим
                    // (culture может не иметь cavalry-tree, e.g. Empire mainline)
                    // — fallback к default basic/elite (старый behavior).
                    try
                    {
                        var desiredFormation = ResolveDesiredFormation(username);
                        if (desiredFormation.HasValue)
                        {
                            var matched = FindTroopByFormationBfs(newTroop, desiredFormation.Value, maxDepth: 3);
                            if (matched != null && matched != newTroop)
                            {
                                BannerlordLinkModule.Log(
                                    $"[recruit_troops M12] @{username}: class-match → " +
                                    $"{matched.StringId} ({desiredFormation.Value}) " +
                                    $"вместо default {newTroop.StringId}");
                                newTroop = matched;
                            }
                        }
                    }
                    catch (Exception fmEx)
                    {
                        BannerlordLinkModule.Log(
                            $"[recruit_troops M12] @{username}: formation-match warn: {fmEx.Message}");
                    }

                    newTier = (int)newTroop.Tier;
                    updatedSlot = existing.Count;
                    BannerlordLinkModule.Log(
                        $"[recruit_troops] @{username}: hero.Culture={culture.StringId}, " +
                        $"picked {newTroop.StringId} {(wantElite ? "[ELITE]" : "[basic]")}");
                }
                else
                {
                    // Upgrade lowest-tier troop того же типа что wantElite.
                    var slot = existing.Where(s => s.isElite == wantElite)
                                       .OrderBy(s => s.tier).First();
                    var current = MBObjectManager.Instance.GetObject<CharacterObject>(slot.troopId);
                    if (current?.UpgradeTargets == null || current.UpgradeTargets.Length == 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[recruit_troops] @{username}: troop {slot.troopId} has no UpgradeTargets " +
                            "(уже maxed)");
                        return;
                    }
                    // Safety: предпочитаем upgrade targets совпадающие с hero.Culture.
                    // Если retinue troop изначально WAR другой культуры (legacy bug
                    // или херо сменил клан), upgrade оставит its own culture chain.
                    // Filter, и если ничего не найдено — используем любой target.
                    var rng = new Random();
                    var sameCulture = current.UpgradeTargets
                        .Where(t => t != null && t.Culture == hero.Culture)
                        .ToList();
                    var pool = sameCulture.Count > 0
                        ? sameCulture
                        : current.UpgradeTargets.ToList();
                    newTroop = pool[rng.Next(pool.Count)];
                    newTier = (int)newTroop.Tier;
                    updatedSlot = slot.slot;
                    BannerlordLinkModule.Log(
                        $"[recruit_troops] @{username}: upgrade {current.StringId} → " +
                        $"{newTroop.StringId} (Culture={newTroop.Culture?.StringId}, " +
                        $"hero.Culture={hero.Culture?.StringId})");
                }

                // Deduct gold + push event
                GiveGoldAction.ApplyBetweenCharacters(hero, null, cost, true);
                BannerlordLinkModule.Log(
                    $"[recruit_troops] @{username}: {(addNew ? "recruited" : "upgraded")} " +
                    $"slot {updatedSlot} → {newTroop.StringId} T{newTier + 1} " +
                    $"(-{cost} dinars, gold={hero.Gold})");

                // Push event for backend update
                var payload = new
                {
                    username = username,
                    slot_index = updatedSlot,
                    troop_id = newTroop.StringId,
                    troop_name = newTroop.Name?.ToString() ?? newTroop.StringId,
                    tier = newTier,
                    is_elite = wantElite,
                    action = addNew ? "recruit" : "upgrade",
                };
                string json = JsonConvert.SerializeObject(payload);
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.retinue_changed", json));

                // 2026-06-15 — per-save профиль свиты (SyncData): строим ИТОГОВЫЙ
                // список слотов (existing + это изменение) → восстановится на
                // загрузке сейва, как класс/стойка/тир.
                try
                {
                    var resultSlots = new List<(int, string, int, bool)>();
                    foreach (var s in existing)
                    {
                        if (!addNew && s.slot == updatedSlot)
                            resultSlots.Add((updatedSlot, newTroop.StringId, newTier, wantElite));
                        else
                            resultSlots.Add((s.slot, s.troopId, s.tier, s.isElite));
                    }
                    if (addNew)
                        resultSlots.Add((updatedSlot, newTroop.StringId, newTier, wantElite));
                    BannerlordLink.Behaviors.HeroProfileBehavior.Instance?.SetRetinue(
                        username, BannerlordLink.Behaviors.HeroProfileBehavior.BuildRetinueJson(resultSlots));
                }
                catch { }

                // Full state sync — gold updated
                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[recruit_troops] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>Sprint 5.10d/5.14: explicit search для T0/T1 troop'a по culture.
        /// Fallback когда culture.BasicTroop/EliteBasicTroop сломан (mod conflict).
        /// elite=true → ищем "elite" в StringId (vlandian_squire / khuzait_oathsworn / etc.).</summary>
        private static CharacterObject FindCultureRecruit(CultureObject culture, bool elite = false)
        {
            if (culture == null) return null;
            try
            {
                var all = MBObjectManager.Instance.GetObjectTypeList<CharacterObject>();
                if (all == null) return null;
                // Filter: same culture + soldier (not hero / wanderer) + tier 0/1
                var candidates = all
                    .Where(c => c != null
                                && c.Culture == culture
                                && c.IsBasicTroop
                                && !c.IsHero
                                && (int)c.Tier <= 1
                                && (!elite || (c.StringId?.Contains("elite") ?? false)
                                    || (c.StringId?.Contains("squire") ?? false)
                                    || (c.StringId?.Contains("noble") ?? false)
                                    || (c.StringId?.Contains("oathsworn") ?? false)))
                    .OrderBy(c => (int)c.Tier)
                    .ToList();
                if (candidates.Count == 0)
                {
                    // Relax — just any troop of this culture с low tier
                    candidates = all
                        .Where(c => c != null
                                    && c.Culture == culture
                                    && !c.IsHero
                                    && (int)c.Tier <= 1)
                        .OrderBy(c => (int)c.Tier)
                        .ToList();
                }
                return candidates.Count > 0 ? candidates[0] : null;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[recruit_troops] FindCultureRecruit({culture.StringId}) crashed: {ex.Message}");
                return null;
            }
        }

        // Sprint 5.32 (BLT-parity M12) — class viewer'а → желаемый FormationClass
        // для retinue. Map mirror'ит C# class_key → TaleWorlds FormationClass.
        // Возвращает null если class неизвестен / нет в cache (используем default).
        private static readonly System.Collections.Generic.Dictionary<string, FormationClass>
            _classToFormation = new System.Collections.Generic.Dictionary<string, FormationClass>(
                StringComparer.OrdinalIgnoreCase)
            {
                ["tank"]            = FormationClass.Infantry,
                ["knight"]          = FormationClass.Cavalry,
                ["psycho"]          = FormationClass.Infantry,
                ["berserk"]         = FormationClass.Infantry,
                ["assassin"]        = FormationClass.Infantry,
                ["archer"]          = FormationClass.Ranged,
                ["heavy_archer"]    = FormationClass.Ranged,
                ["crossbow"]        = FormationClass.Ranged,
                ["heavy_crossbow"]  = FormationClass.Ranged,
                ["cavalry"]         = FormationClass.Cavalry,
                ["camel_cavalry"]   = FormationClass.Cavalry,
                ["horse_archer"]    = FormationClass.HorseArcher,
                ["camel_archer"]    = FormationClass.HorseArcher,
            };

        private static FormationClass? ResolveDesiredFormation(string username)
        {
            try
            {
                var hc = BannerlordLink.Net.PowerCache.GetHeroClass(username);
                if (hc.HasValue && !string.IsNullOrEmpty(hc.Value.classKey)
                    && _classToFormation.TryGetValue(hc.Value.classKey, out var fc))
                {
                    return fc;
                }
            }
            catch { }
            return null;
        }

        /// <summary>BFS вниз по UpgradeTargets дереву от root'а ищем
        /// первого troop'а с заданным FormationClass. Limit depth = 3
        /// (T0 → T1 → T2 → T3 максимум — обычно cavalry/archer branch
        /// разделяется на tier 1-2). Возвращает root если match не найден
        /// в depth limit (caller'у решать что делать).</summary>
        private static CharacterObject FindTroopByFormationBfs(
            CharacterObject root, FormationClass desired, int maxDepth)
        {
            if (root == null) return null;
            // Quick exit: root уже матчится.
            try { if (root.GetFormationClass() == desired) return root; }
            catch { return root; }  // GetFormationClass может бросать на некоторых troop'ах

            var visited = new System.Collections.Generic.HashSet<CharacterObject> { root };
            var queue = new System.Collections.Generic.Queue<(CharacterObject troop, int depth)>();
            queue.Enqueue((root, 0));
            while (queue.Count > 0)
            {
                var (cur, depth) = queue.Dequeue();
                if (depth >= maxDepth) continue;
                if (cur.UpgradeTargets == null) continue;
                foreach (var next in cur.UpgradeTargets)
                {
                    if (next == null || visited.Contains(next)) continue;
                    visited.Add(next);
                    try { if (next.GetFormationClass() == desired) return next; }
                    catch { continue; }
                    queue.Enqueue((next, depth + 1));
                }
            }
            // Not found — caller'у решать.
            return null;
        }
    }
}
