using System;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.Library;
using TaleWorlds.Localization;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity VAS) — Vassal sub-clan management handlers.
    ///
    /// 2 handlers:
    ///   - CreateVassalClanHandler — hero.create_vassal_clan
    ///     Backend payload: {parent_username, heir_hero_id, heir_name, vassal_name,
    ///                       placeholder_clan_id}.
    ///     Logic: resolve heir → CreateClan(name) → SetInitialHomeSettlement →
    ///            ChangeClanLeader to heir → heir.Clan = newClan → push event
    ///            `hero.vassal_created` с real clan_id для backend backfill.
    ///
    ///   - RenameVassalHandler — hero.rename_vassal
    ///     Backend payload: {vassal_clan_id, new_name, old_name}.
    ///     Logic: resolve Clan → ChangeClanName.
    /// </summary>
    public class CreateVassalClanHandler : IActionHandler
    {
        public string ActionType => "hero.create_vassal_clan";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string parentUser = (data["parent_username"]?.ToString() ?? "").ToLowerInvariant();
            string heirId = (data["heir_hero_id"]?.ToString() ?? "").Trim();
            string heirName = data["heir_name"]?.ToString() ?? heirId;
            string vassalName = (data["vassal_name"]?.ToString() ?? "").Trim();
            string placeholderClanId = (data["placeholder_clan_id"]?.ToString() ?? "").Trim();

            if (string.IsNullOrEmpty(heirId) || string.IsNullOrEmpty(vassalName) ||
                string.IsNullOrEmpty(placeholderClanId))
                return Task.FromResult<(bool, string)>((false, "missing params"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
                Create(parentUser, heirId, heirName, vassalName, placeholderClanId, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Create(string parentUser, string heirId, string heirName,
            string vassalName, string placeholderClanId, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }

                Hero heir;
                try { heir = MBObjectManager.Instance.GetObject<Hero>(heirId); }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[vassal.create] GetObject<Hero>('{heirId}') crashed: {ex.Message}");
                    ActionFeedback.PostFailed(actionId, "heir_lookup_crash");
                    return;
                }
                if (heir == null || !heir.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[vassal.create] REFUSE: heir '{heirName}' ({heirId}) not found/alive");
                    ActionFeedback.PostFailed(actionId, "heir_not_found");
                    return;
                }

                // Create new Clan через engine API. Pattern из CreateClanHandler.
                var nameObj = new TextObject(vassalName);
                Clan newClan = Clan.CreateClan(vassalName);  // engine assigns StringId
                if (newClan == null)
                {
                    BannerlordLinkModule.Log("[vassal.create] CreateClan returned null");
                    ActionFeedback.PostFailed(actionId, "clan_create_failed");
                    return;
                }
                newClan.ChangeClanName(nameObj, nameObj);
                newClan.Culture = heir.Culture;
                if (newClan.Banner == null)
                {
                    try { newClan.Banner = Banner.CreateRandomBanner(); }
                    catch (Exception bex)
                    {
                        BannerlordLinkModule.Log($"[vassal.create] banner warn: {bex.Message}");
                    }
                }
                // Vassal kingdom = parent's kingdom (если есть). MVP — null (independent).
                newClan.Kingdom = null;
                // Stand-alone clan; small renown starter
                newClan.AddRenown(50f, false);
                // Home settlement — heir's current settlement OR fallback to parent's home.
                try
                {
                    var home = heir.HomeSettlement ?? heir.CurrentSettlement;
                    if (home != null) newClan.SetInitialHomeSettlement(home);
                }
                catch { }
                newClan.IsNoble = true;

                // Transfer heir into new clan as leader.
                heir.Clan = newClan;
                try
                {
                    ChangeClanLeaderAction.ApplyWithSelectedNewLeader(newClan, heir);
                }
                catch (Exception lex)
                {
                    BannerlordLinkModule.Log($"[vassal.create] SetLeader warn: {lex.Message}");
                }

                string realClanId = newClan.StringId ?? "";
                BannerlordLinkModule.Log(
                    $"[vassal.create] OK: parent=@{parentUser} heir='{heirName}' " +
                    $"vassal='{vassalName}' clan_id={realClanId}");

                // Push event для backend backfill (placeholder_clan_id → real_clan_id).
                string evtData = JsonConvert.SerializeObject(new
                {
                    placeholder_clan_id = placeholderClanId,
                    real_clan_id = realClanId,
                    parent_username = parentUser,
                    heir_hero_id = heirId,
                    vassal_name = vassalName,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.vassal_created", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[vassal.create] CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed:" + ex.Message);
            }
        }
    }

    // ── RenameVassalHandler ────────────────────────────────────────────────────
    public class RenameVassalHandler : IActionHandler
    {
        public string ActionType => "hero.rename_vassal";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string clanId = (data["vassal_clan_id"]?.ToString() ?? "").Trim();
            string newName = (data["new_name"]?.ToString() ?? "").Trim();
            string oldName = data["old_name"]?.ToString() ?? "?";

            if (string.IsNullOrEmpty(clanId) || string.IsNullOrEmpty(newName))
                return Task.FromResult<(bool, string)>((false, "missing params"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(clanId, newName, oldName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string clanId, string newName, string oldName, string actionId)
        {
            try
            {
                Clan clan;
                try { clan = MBObjectManager.Instance.GetObject<Clan>(clanId); }
                catch
                {
                    ActionFeedback.PostFailed(actionId, "clan_lookup_crash");
                    return;
                }
                if (clan == null)
                {
                    BannerlordLinkModule.Log(
                        $"[vassal.rename] REFUSE: clan '{clanId}' not found");
                    ActionFeedback.PostFailed(actionId, "clan_not_found");
                    return;
                }
                var nameObj = new TextObject(newName);
                clan.ChangeClanName(nameObj, nameObj);
                BannerlordLinkModule.Log(
                    $"[vassal.rename] OK: '{oldName}' → '{newName}' ({clanId})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[vassal.rename] CRASHED: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }
}
