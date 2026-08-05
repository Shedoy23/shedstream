using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.27b — брак adopted-героя с NPC.
    ///
    /// Pattern: BLT FamilyManagement.cs MarryHero. Различия:
    ///   - У нас брак САМОГО adopted-героя с NPC (не его children)
    ///   - Auto-pick random suitable NPC (BLT тоже supports target by name,
    ///     но MVP — random)
    ///   - NPC переезжает в clan героя (BLT: h1 в h2.Clan; у нас наоборот
    ///     чтоб не терять clan progress)
    ///
    /// Eligibility NPC:
    ///   - alive, age 18+ (< 50 для realism)
    ///   - opposite gender (Bannerlord не любит same-sex)
    ///   - не уже в браке (Spouse == null)
    ///   - не [BLink] (adopted)
    ///   - не clan leader (BLT restriction)
    ///   - не player.MainHero / family.MainHero spouse
    ///
    /// Body: {"target": username}. Optional: ничего больше — random pick.
    /// </summary>
    public class MarryHandler : IActionHandler
    {
        public string ActionType => "hero.marry";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            // Sprint 5.29 / BLT-parity #3: actionId для refund-on-refuse.
            string actionId = ActionFeedback.GetActionId(data);

            MainThreadDispatcher.Enqueue(() =>
            {
                BannerlordLinkModule.Log(
                    $"[hero.marry] @{username}: handler called, processing...");
                Hero chargedHero = null;
                Hero selectedNpc = null;
                int chargedAmount = 0;
                bool marriageCommitted = false;
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null)
                    {
                        BannerlordLinkModule.Log($"[hero.marry] REFUSE @{username}: hero не найден");
                        ActionFeedback.PostFailed(actionId, "hero_not_found");
                        return;
                    }
                    if (!hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[hero.marry] REFUSE @{username}: hero мёртв");
                        ActionFeedback.PostFailed(actionId, "hero_dead");
                        return;
                    }
                    if (hero.Spouse != null)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.marry] REFUSE @{username}: уже в браке с {hero.Spouse.Name}");
                        ActionFeedback.PostFailed(actionId, "already_married");
                        return;
                    }
                    if (hero.Age < 18)
                    {
                        BannerlordLinkModule.Log($"[hero.marry] REFUSE @{username}: too young");
                        ActionFeedback.PostFailed(actionId, "too_young");
                        return;
                    }

                    // Sprint 5.29: relaxed filter + диагностика. Раньше filter
                    // слишком строгий (Age < 50, !IsClanLeader, Clan != null) →
                    // в late-game часто 0 кандидатов. Viewer кликает «жениться»
                    // → мод silently returns → user видит success-toast в
                    // overlay но в игре ничего не меняется.
                    //
                    // Tiered fallback: сначала strict, потом relax.
                    var allCandidates = Hero.AllAliveHeroes
                        .Where(h => h != null
                                 && h != hero
                                 && h.IsAlive
                                 && h.IsFemale != hero.IsFemale
                                 && h.Spouse == null
                                 && h.Name != null
                                 && !HeroNaming.IsAdopted(h.Name.ToString())
                                 && h != Hero.MainHero
                                 && !h.IsPrisoner
                                 && !h.IsFugitive
                                 && h.Age >= 18)
                        .ToList();

                    // Tier 1 (best): age < 50 + not leader + has clan
                    var candidates = allCandidates
                        .Where(h => h.Age < 50 && !h.IsClanLeader && h.Clan != null)
                        .ToList();
                    string tier = "T1 (strict)";

                    // Tier 2: drop age cap (older nobles OK)
                    if (candidates.Count == 0)
                    {
                        candidates = allCandidates
                            .Where(h => !h.IsClanLeader && h.Clan != null)
                            .ToList();
                        tier = "T2 (no age cap)";
                    }
                    // Tier 3: allow clanless
                    if (candidates.Count == 0)
                    {
                        candidates = allCandidates
                            .Where(h => !h.IsClanLeader)
                            .ToList();
                        tier = "T3 (clanless OK)";
                    }
                    // Tier 4: allow clan leaders (last resort)
                    if (candidates.Count == 0)
                    {
                        candidates = allCandidates;
                        tier = "T4 (leaders OK)";
                    }

                    if (candidates.Count == 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.marry] REFUSE @{username}: 0 подходящих NPC " +
                            $"(всего alive {Hero.AllAliveHeroes.Count()}, opposite gender single = 0). " +
                            $"Triggering refund.");
                        ActionFeedback.PostFailed(actionId, "no_candidates");
                        return;
                    }
                    BannerlordLinkModule.Log(
                        $"[hero.marry] @{username}: candidates pool={candidates.Count} ({tier})");

                    // Sprint 5.32 (BLT-parity LOW-5) — TaleWorlds.Core.MBRandom
                    // вместо `new Random()`. `new Random()` использует Environment.TickCount
                    // как seed — если две action'ы вызваны в той же миллисекунде (rare
                    // но возможно при batch'е actions on main thread tick), они получат
                    // одинаковый seed → одинаковый pick. MBRandom — engine-grade, shared
                    // state, гарантировано unique sequence.
                    var npc = candidates[TaleWorlds.Core.MBRandom.RandomInt(candidates.Count)];
                    selectedNpc = npc;

                    // Apply marriage (engine housekeeping)
                    var formerClan = npc.Clan;

                    // 2026-07-31: списываем объявленную бэкендом цену В ДИНАРАХ.
                    // До этого поле `hero_gold_cost` не читал никто, и действие
                    // выполнялось бесплатно (подтверждено прогоном в игре).
                    if (!HeroGoldCharge.TryCharge(
                        hero, data, actionId, "hero.marry", out chargedAmount))
                        return;
                    chargedHero = hero;

                    npc.Spouse = hero;
                    hero.Spouse = npc;
                    if (hero.Spouse != npc || npc.Spouse != hero)
                        throw new InvalidOperationException("marriage postcondition failed");
                    marriageCommitted = true;

                    // Housekeeping для NPC которая переезжает
                    if (npc.GovernorOf != null)
                    {
                        try { ChangeGovernorAction.RemoveGovernorOf(npc); } catch { }
                    }
                    if (npc.PartyBelongedTo != null)
                    {
                        try
                        {
                            var formerParty = npc.PartyBelongedTo;
                            bool heroWasLeader = formerParty.LeaderHero == npc;
                            formerParty.MemberRoster.RemoveTroop(
                                npc.CharacterObject, 1, default, 0);
                            MakeHeroFugitiveAction.Apply(npc, false);
                            if (heroWasLeader && formerParty.IsLordParty)
                            {
                                DisbandPartyAction.StartDisband(formerParty);
                            }
                        }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[hero.marry] party cleanup error: {ex.Message}");
                        }
                    }

                    // NPC переезжает в clan героя (если есть)
                    if (hero.Clan != null && npc.Clan != hero.Clan)
                    {
                        npc.Clan = hero.Clan;
                    }

                    // Relation boost
                    try
                    {
                        var marriageModel = Campaign.Current.Models.MarriageModel;
                        npc.UpdateHomeSettlement();
                        ChangeRelationAction.ApplyRelationChangeBetweenHeroes(
                            hero, npc, marriageModel.GetEffectiveRelationIncrease(hero, npc), false);
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log($"[hero.marry] relation update error: {ex.Message}");
                    }

                    BannerlordLinkModule.Log(
                        $"[hero.marry] @{username} ↔ {npc.Name} "
                        + $"(was clan: {formerClan?.Name}, now: {npc.Clan?.Name})");
                }
                catch (Exception ex)
                {
                    if (!marriageCommitted && chargedHero != null)
                    {
                        try
                        {
                            if (chargedHero.Spouse == selectedNpc) chargedHero.Spouse = null;
                            if (selectedNpc?.Spouse == chargedHero) selectedNpc.Spouse = null;
                        }
                        catch { }
                        HeroGoldCharge.Refund(chargedHero, chargedAmount, "hero.marry");
                    }
                    BannerlordLinkModule.Log($"[hero.marry] @{username} CRASHED: {ex.Message}");
                    if (!marriageCommitted)
                        ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }


    /// <summary>
    /// Sprint 5.27b — развод (free, no cost). Возвращает супругу в roaming
    /// pool но не пытаемся вернуть в old clan (engine разрулит).
    /// </summary>
    public class DivorceHandler : IActionHandler
    {
        public string ActionType => "hero.divorce";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            MainThreadDispatcher.Enqueue(() =>
            {
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null) return;
                    if (hero.Spouse == null)
                    {
                        BannerlordLinkModule.Log($"[hero.divorce] @{username}: не в браке");
                        return;
                    }

                    var spouse = hero.Spouse;
                    spouse.Spouse = null;
                    hero.Spouse = null;
                    BannerlordLinkModule.Log(
                        $"[hero.divorce] @{username} разведён с {spouse.Name}");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[hero.divorce] @{username} CRASHED: {ex.Message}");
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
