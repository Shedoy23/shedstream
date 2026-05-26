using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.12 — `hero.leave_clan` action. Hero выходит из своего clan'а
    /// и возвращается в pool wanderer'ов (BLT pattern, ClanManagement.cs
    /// HandleLeaveCommand).
    ///
    /// Pre-checks:
    ///   • hero alive, not prisoner
    ///   • hero in clan
    ///   • hero NOT clan leader (BLT-style — leaders can't leave own clan)
    ///   • hero not в battle (party not in MapEvent)
    ///
    /// Steps:
    ///   1. Remove governor role if any
    ///   2. Remove from party member roster
    ///   3. Set occupation Wanderer
    ///   4. hero.Clan = null
    ///   5. Place в random town
    ///
    /// Free action (no Hero.Gold cost).
    /// </summary>
    public class LeaveClanHandler : IActionHandler
    {
        public string ActionType => "hero.leave_clan";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            // Sprint 5.29 / BLT-parity #3: pass actionId для refund-on-refuse.
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(username, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string actionId)
        {
            BannerlordLinkModule.Log(
                $"[leave_clan] @{username}: handler called, processing...");
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_clan] REFUSE @{username}: hero не найден ({hero == null}) / мёртв ({hero?.IsAlive == false})");
                    ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }
                if (hero.IsPrisoner)
                {
                    BannerlordLinkModule.Log($"[leave_clan] REFUSE @{username}: пленник");
                    ActionFeedback.PostFailed(actionId, "is_prisoner");
                    return;
                }
                if (hero.Clan == null)
                {
                    BannerlordLinkModule.Log($"[leave_clan] REFUSE @{username}: уже без клана");
                    ActionFeedback.PostFailed(actionId, "no_clan");
                    return;
                }
                // Sprint 5.29: если leader — auto-handle вместо отказа.
                // Раньше: «передай лидерство (TBD)» — viewer-clan'ы залочены
                // навсегда (большинство viewer'ов создали свой clan через
                // create_clan, они = leader → не могли выйти).
                //
                // Strategy (BLT-style):
                //   1. Если есть другие члены → transfer leadership старшему
                //      non-hero (по age desc).
                //   2. Если hero единственный → disband clan через
                //      DestroyClanAction (BLT pattern).
                if (hero.IsClanLeader)
                {
                    var clan = hero.Clan;
                    var members = clan.Heroes
                        .Where(h => h != null && h != hero && h.IsAlive)
                        .OrderByDescending(h => h.Age)
                        .ToList();
                    if (members.Count > 0)
                    {
                        var newLeader = members[0];
                        try
                        {
                            // Используем reflection — ClanLeader setter иногда
                            // protected. ChangeClanLeaderAction публичный API.
                            ChangeClanLeaderAction.ApplyWithSelectedNewLeader(
                                clan, newLeader);
                            BannerlordLinkModule.Log(
                                $"[leave_clan] @{username}: leader → лидерство " +
                                $"передано {newLeader.Name?.ToString() ?? "?"}");
                        }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[leave_clan] REFUSE @{username}: ChangeClanLeaderAction failed: {ex.Message}");
                            ActionFeedback.PostFailed(actionId, "transfer_leadership_failed");
                            return;
                        }
                    }
                    else
                    {
                        // Sprint 5.32 BLT-parity — заменяет reflection-хак на
                        // публичный engine API. BLT в ClanManagement.cs:802 для
                        // single-leader detach использует:
                        //   ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader(clan)
                        //
                        // Этот API внутри сам убирает leader без killing hero
                        // (в отличие от DestroyClanAction которое внутренне
                        // вызывает KillCharacterAction.ApplyByRemove(leader, Lost)).
                        //
                        // Fallback: reflection _leader=null если API недоступен
                        // в данной версии TaleWorlds (старые сборки 1.0-1.1).
                        bool detached = false;
                        try
                        {
                            // 1. Try public API (BLT pattern).
                            var apiType = typeof(ChangeClanLeaderAction);
                            var method = apiType.GetMethod(
                                "ApplyWithoutSelectedNewLeader",
                                System.Reflection.BindingFlags.Public |
                                System.Reflection.BindingFlags.Static);
                            if (method != null)
                            {
                                method.Invoke(null, new object[] { clan });
                                detached = true;
                                BannerlordLinkModule.Log(
                                    $"[leave_clan] @{username}: leader без членов → " +
                                    $"ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader OK");
                            }
                            else
                            {
                                // 2. Fallback: reflection _leader=null (Sprint 5.32 path).
                                BannerlordLinkModule.Log(
                                    $"[leave_clan] @{username}: " +
                                    $"ApplyWithoutSelectedNewLeader not found → reflection fallback");
                                var leaderField = HarmonyLib.AccessTools.Field(
                                    typeof(TaleWorlds.CampaignSystem.Clan), "_leader");
                                if (leaderField != null)
                                {
                                    leaderField.SetValue(clan, null);
                                    detached = true;
                                    BannerlordLinkModule.Log(
                                        $"[leave_clan] @{username}: reflection " +
                                        $"_leader=null OK (clan '{clan.Name}' orphaned)");
                                }
                            }
                        }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[leave_clan] @{username}: API failed ({ex.Message}) — " +
                                $"trying reflection fallback");
                            try
                            {
                                var leaderField = HarmonyLib.AccessTools.Field(
                                    typeof(TaleWorlds.CampaignSystem.Clan), "_leader");
                                if (leaderField != null)
                                {
                                    leaderField.SetValue(clan, null);
                                    detached = true;
                                    BannerlordLinkModule.Log(
                                        $"[leave_clan] @{username}: reflection " +
                                        $"_leader=null OK after API fail");
                                }
                            }
                            catch (Exception rex)
                            {
                                BannerlordLinkModule.Log(
                                    $"[leave_clan] REFUSE @{username}: both API + reflection " +
                                    $"failed: {rex.Message}");
                            }
                        }
                        if (!detached)
                        {
                            ActionFeedback.PostFailed(actionId, "detach_leader_failed");
                            return;
                        }
                    }
                }

                var oldParty = hero.PartyBelongedTo;
                if (oldParty != null && oldParty.MapEvent != null)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_clan] REFUSE @{username}: hero в битве");
                    ActionFeedback.PostFailed(actionId, "in_battle");
                    return;
                }

                if (hero.GovernorOf != null)
                {
                    try { ChangeGovernorAction.RemoveGovernorOf(hero); } catch { }
                }

                if (oldParty != null)
                {
                    try
                    {
                        bool wasLeader = oldParty.LeaderHero == hero;
                        oldParty.MemberRoster.RemoveTroop(hero.CharacterObject, 1,
                            default(UniqueTroopDescriptor), 0);
                        if (wasLeader && oldParty.IsLordParty)
                            DisbandPartyAction.StartDisband(oldParty);
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[leave_clan] @{username}: party remove warn: {ex.Message}");
                    }
                }

                var oldClanName = hero.Clan.Name?.ToString() ?? "?";
                hero.SetNewOccupation(Occupation.Wanderer);

                // Sprint 5.32 LEAVE-CLAN-FIX — гибрид setter + reflection fallback.
                // В Bannerlord 1.3.x `hero.Clan = null` setter молча no-op'ит
                // для не-leader path: HeroStateSync.Push сразу после показывал
                // clan='фен Туиль' хотя мы только что попросили reset. Engine
                // hides setter за internal validation который reject'ит null
                // для member hero'я (защищает от orphan'ов).
                //
                // Решение:
                //   1. Try public setter (как раньше).
                //   2. Verify hero.Clan == null после.
                //   3. Если setter no-op'нул → force reset через reflection
                //      `Hero._clan` private field (backing field public Clan
                //      property). Plus снять hero из старого clan._heroes list
                //      чтобы engine ивенты не пытались re-bind на daily tick.
                BannerlordLinkModule.LogVerbose(() =>
                    $"[leave_clan V] @{username}: pre-setter state " +
                    $"hero.Clan='{hero.Clan?.Name}' clan._heroes.size={hero.Clan?.Heroes?.Count} " +
                    $"hero.IsClanLeader={hero.IsClanLeader} hero.Occupation={hero.Occupation}");
                hero.Clan = null;
                BannerlordLinkModule.LogVerbose(() =>
                    $"[leave_clan V] @{username}: post-setter hero.Clan={hero.Clan?.Name?.ToString() ?? "(null)"}");
                if (hero.Clan != null)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_clan] @{username}: public setter NO-OP'нул " +
                        $"(clan still '{hero.Clan.Name}') — fallback к reflection");
                    try
                    {
                        var clanField = HarmonyLib.AccessTools.Field(typeof(Hero), "_clan");
                        var oldClan = hero.Clan;
                        BannerlordLinkModule.LogVerbose(() =>
                            $"[leave_clan V] @{username}: reflection lookup Hero._clan " +
                            $"field={(clanField != null ? "OK" : "NULL")} " +
                            $"current_value='{oldClan?.Name}'");
                        if (clanField != null)
                        {
                            clanField.SetValue(hero, null);
                            BannerlordLinkModule.LogVerbose(() =>
                                $"[leave_clan V] @{username}: reflection SetValue done, " +
                                $"new hero.Clan={hero.Clan?.Name?.ToString() ?? "(null)"}");
                        }
                        // Также remove hero из старого Clan._heroes list (если
                        // мутируемый). Без этого engine на ClanDailyTick
                        // может попытаться bind hero обратно.
                        try
                        {
                            var heroesField = HarmonyLib.AccessTools.Field(
                                typeof(TaleWorlds.CampaignSystem.Clan), "_heroes");
                            if (heroesField != null && oldClan != null)
                            {
                                var heroesList = heroesField.GetValue(oldClan)
                                    as System.Collections.IList;
                                if (heroesList != null && heroesList.Contains(hero))
                                {
                                    heroesList.Remove(hero);
                                    BannerlordLinkModule.Log(
                                        $"[leave_clan] @{username}: removed from " +
                                        $"Clan._heroes (size={heroesList.Count})");
                                }
                            }
                        }
                        catch (Exception lex)
                        {
                            BannerlordLinkModule.Log(
                                $"[leave_clan] @{username}: Clan._heroes remove warn: {lex.Message}");
                        }
                        // Final verify.
                        if (hero.Clan == null)
                        {
                            BannerlordLinkModule.Log(
                                $"[leave_clan] @{username}: reflection _clan=null OK");
                        }
                        else
                        {
                            BannerlordLinkModule.Log(
                                $"[leave_clan] REFUSE @{username}: reflection ALSO failed, " +
                                $"clan='{hero.Clan.Name}' остался. Aborting.");
                            ActionFeedback.PostFailed(actionId, "clan_setter_blocked");
                            return;
                        }
                    }
                    catch (Exception rex)
                    {
                        BannerlordLinkModule.Log(
                            $"[leave_clan] REFUSE @{username}: reflection crashed: {rex.Message}");
                        ActionFeedback.PostFailed(actionId, "clan_reflection_crashed");
                        return;
                    }
                }
                else
                {
                    BannerlordLinkModule.Log(
                        $"[leave_clan] @{username}: public setter OK (clan=null verified)");
                }

                // Sprint 5.32 BUGFIX — раньше placed в RANDOM town. Engine иногда
                // считал hero "Lost" если town был под осадой / враждебный /
                // далеко. Теперь ставим в таверну БЛИЖАЙШЕГО town'а + set
                // HomeSettlement — engine знает где hero "прописан".
                WandererHome.PlaceInNearestTavern(hero);

                BannerlordLinkModule.Log(
                    $"[leave_clan] @{username}: left '{oldClanName}' → wanderer");

                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    old_clan_name = oldClanName,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.clan_left", evtData));

                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[leave_clan] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
