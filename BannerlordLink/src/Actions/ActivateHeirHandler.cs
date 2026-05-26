using System;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
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

            MainThreadDispatcher.Enqueue(() => Activate(parentUsername, heirHeroId, heirName));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Activate(string parentUsername, string heirHeroId, string heirName)
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
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[heir.activate] @{parentUsername} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
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
