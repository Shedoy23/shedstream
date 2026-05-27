using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Party.PartyComponents;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.Settlements.Workshops;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.32 (BLT-parity M2.1) — heir auto-activation на death.
    ///
    /// Backend `_on_player_died` пушит этот action когда у умершего viewer'а
    /// есть взрослый ребёнок в bannerlord_heirs queue. Handler:
    ///   1. Resolve heir Hero по heir_hero_id (MBObjectManager).
    ///   2. Rename heir → `[BLink] {parent_username}` через HeroNaming.Format.
    ///   3. Register identity в HeroIdentityBehavior (M9 dict).
    ///   4. Set Clan = parent's clan если возможно (preserve dynastic links).
    ///   5. Push `player.linked` (с новым hero_id) → backend UPSERT bannerlord_heroes.
    ///   6. Push `player.respawned` для consistent succession event log.
    ///   7. Heal HP до 100%, mark IsAlive (engine).
    ///
    /// Если heir уже мёртв / не найден / engine fail — silent log + push event
    /// hero.heir_died чтобы backend пометил activated → НЕ зацикливаемся на
    /// том же broken heir при следующем death.
    /// </summary>
    public class ActivateHeirHandler : IActionHandler
    {
        public string ActionType => "hero.activate_heir";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string parentUsername = (data["parent_username"]?.ToString()
                                     ?? data["target"]?.ToString() ?? "")
                                    .Trim().ToLowerInvariant();
            string heirHeroId = (data["heir_hero_id"]?.ToString() ?? "").Trim();
            string heirName = data["heir_name"]?.ToString() ?? heirHeroId;

            if (string.IsNullOrEmpty(parentUsername))
                return Task.FromResult<(bool, string)>((false, "no parent_username"));
            if (string.IsNullOrEmpty(heirHeroId))
                return Task.FromResult<(bool, string)>((false, "no heir_hero_id"));

            // Sprint 5.33 (BLT-parity HERITAGE) — capture inherited assets payload.
            // Backend collected viewer's active workshops/caravans, mod re-transfers
            // engine ownership к heir. Fiefs auto-handle через clan-leader change.
            var inheritedWorkshops = data["inherited_workshops"] as JArray;
            var inheritedCaravans  = data["inherited_caravans"]  as JArray;

            MainThreadDispatcher.Enqueue(() =>
                Activate(parentUsername, heirHeroId, heirName,
                         inheritedWorkshops, inheritedCaravans));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Activate(string parentUsername, string heirHeroId, string heirName,
            JArray inheritedWorkshops, JArray inheritedCaravans)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    BannerlordLinkModule.Log(
                        $"[heir.activate] @{parentUsername}: Campaign не active, skip");
                    return;
                }

                var heir = MBObjectManager.Instance.GetObject<Hero>(heirHeroId);
                if (heir == null)
                {
                    BannerlordLinkModule.Log(
                        $"[heir.activate] @{parentUsername}: heir {heirHeroId} " +
                        $"не найден в ObjectManager (heir killed/GC'd ДО activation?)");
                    PushHeirDied(heirHeroId);
                    return;
                }
                if (!heir.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[heir.activate] @{parentUsername}: heir '{heirName}' " +
                        $"уже мёртв в момент activation");
                    PushHeirDied(heirHeroId);
                    return;
                }

                // 1. Rename → [BLink] {parent_username}.
                var (fullName, firstName) = HeroNaming.Format(parentUsername);
                heir.SetName(fullName, firstName);

                // 2. Register identity (M9 dict). Hero.StringId не меняется при
                //    rename, поэтому Register pair (newStringId, parentUsername).
                try
                {
                    BannerlordLink.Behaviors.HeroIdentityBehavior.Instance
                        ?.Register(heir, parentUsername);
                }
                catch (Exception idEx)
                {
                    BannerlordLinkModule.Log(
                        $"[heir.activate] @{parentUsername} identity register warn: {idEx.Message}");
                }

                // 3. Set Clan = parent's clan если возможно (heir уже в нём
                //    обычно — это его dynastic clan; но если parent был
                //    clan_left'нут перед death, heir может быть в default
                //    minor clan engine'а — оставляем как есть, не forcer).
                //    Skip; engine handles dynastic clan через NPC family logic.

                // 4. Heal HP.
                try
                {
                    heir.HitPoints = heir.MaxHitPoints;
                }
                catch (Exception hex)
                {
                    BannerlordLinkModule.Log(
                        $"[heir.activate] @{parentUsername} heal warn: {hex.Message}");
                }

                BannerlordLinkModule.Log(
                    $"[heir.activate] @{parentUsername} → {heir.StringId} " +
                    $"({fullName}) AUTO-SUCCESSION OK");

                // 5. Push player.linked → backend UPSERT bannerlord_heroes
                //    с новым hero_id + is_alive=1 (через ON CONFLICT в _on_player_linked).
                string linkedData = JsonConvert.SerializeObject(new
                {
                    username = parentUsername,
                    hero_id = heir.StringId,
                    display_name = parentUsername,
                    culture = heir.Culture?.StringId,
                });
                Task.Run(async () =>
                {
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "player.linked", linkedData);
                });

                // 6. Push player.respawned для event log consistency.
                string respawnData = JsonConvert.SerializeObject(new
                {
                    username = parentUsername,
                    hero_id = heir.StringId,
                    via_heir = true,
                });
                Task.Run(async () =>
                {
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "player.respawned", respawnData);
                });

                // 7. Push full state — frontend сразу обновит badge.
                HeroStateSync.Push(heir);
                EquipmentSync.PushAll(heir);

                // 8. Sprint 5.33 (BLT-parity HERITAGE) — transfer inherited assets
                //    engine-side. Backend ownership preserved (heir keeps parent's
                //    username via rename), но engine ApplyByDeath uже распихал
                //    workshops/caravans к notables. Re-claim:
                int wsRestored = TransferInheritedWorkshops(heir, inheritedWorkshops);
                int caRestored = TransferInheritedCaravans(heir, inheritedCaravans);
                if (wsRestored + caRestored > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[heir.heritage] @{parentUsername} → heir reclaimed " +
                        $"{wsRestored} workshops + {caRestored} caravans engine-side");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[heir.activate] @{parentUsername} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        // ── Sprint 5.33 HERITAGE helpers ───────────────────────────────────────

        /// <summary>
        /// Re-claim workshops engine-side: find workshop by (settlement, type),
        /// transfer ownership к heir hero. Engine ApplyByDeath already moved
        /// them к random notables, мы переписываем obratно.
        /// </summary>
        private static int TransferInheritedWorkshops(Hero heir, JArray workshops)
        {
            if (workshops == null || workshops.Count == 0) return 0;
            int restored = 0;
            foreach (var entry in workshops)
            {
                try
                {
                    string settlementId = entry["settlement_id"]?.ToString();
                    string typeId       = entry["workshop_type"]?.ToString();
                    if (string.IsNullOrEmpty(settlementId)) continue;

                    Settlement s = MBObjectManager.Instance.GetObject<Settlement>(settlementId);
                    if (s?.Town == null) continue;
                    WorkshopType wsType = !string.IsNullOrEmpty(typeId)
                        ? MBObjectManager.Instance.GetObject<WorkshopType>(typeId)
                        : null;

                    // Find workshop: prefer matching type, else any в town не owned by [BLink].
                    Workshop target = null;
                    foreach (var w in s.Town.Workshops)
                    {
                        if (w == null) continue;
                        if (wsType != null && w.WorkshopType == wsType) { target = w; break; }
                    }
                    if (target == null)
                    {
                        // fallback: first available
                        foreach (var w in s.Town.Workshops)
                        {
                            if (w == null) continue;
                            target = w; break;
                        }
                    }
                    if (target == null) continue;

                    // Compute fresh capital. Engine ApplyByDeath обнулил, restore default.
                    int capital = Campaign.Current?.Models?.WorkshopModel?.InitialCapital ?? 1000;
                    ChangeOwnerOfWorkshopAction.ApplyByBankruptcy(
                        target, heir, wsType ?? target.WorkshopType, capital);
                    restored++;
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[heir.heritage] workshop restore warn: {ex.Message}");
                }
            }
            return restored;
        }

        /// <summary>
        /// Re-claim caravans engine-side. Если caravan engine party уже destroyed
        /// (ApplyByDeath), skip — backend пометит row sold/destroyed на next sync.
        /// Если ещё alive (transferred к notable) — transfer ownership к heir.
        /// </summary>
        private static int TransferInheritedCaravans(Hero heir, JArray caravans)
        {
            if (caravans == null || caravans.Count == 0) return 0;
            int restored = 0;
            foreach (var entry in caravans)
            {
                try
                {
                    string partyId = entry["party_id"]?.ToString();
                    if (string.IsNullOrEmpty(partyId)) continue;

                    MobileParty mp = null;
                    foreach (var p in MobileParty.AllCaravanParties)
                    {
                        if (p?.StringId == partyId) { mp = p; break; }
                    }
                    if (mp == null) continue;  // engine destroyed уже

                    var homeS = mp.HomeSettlement;
                    CaravanPartyComponent.TransferCaravanOwnership(mp, heir, homeS);
                    restored++;
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[heir.heritage] caravan restore warn: {ex.Message}");
                }
            }
            return restored;
        }

        private static void PushHeirDied(string heirHeroId)
        {
            try
            {
                string data = JsonConvert.SerializeObject(new { heir_hero_id = heirHeroId });
                Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.heir_died", data));
            }
            catch { }
        }
    }
}
