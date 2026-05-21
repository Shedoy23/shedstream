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

            MainThreadDispatcher.Enqueue(() =>
            {
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null)
                    {
                        BannerlordLinkModule.Log($"[hero.marry] @{username}: hero не найден");
                        return;
                    }
                    if (!hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[hero.marry] @{username}: hero мёртв");
                        return;
                    }
                    if (hero.Spouse != null)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.marry] @{username}: уже в браке с {hero.Spouse.Name}");
                        return;
                    }
                    if (hero.Age < 18)
                    {
                        BannerlordLinkModule.Log($"[hero.marry] @{username}: too young");
                        return;
                    }

                    // Найти suitable NPC
                    var candidates = Hero.AllAliveHeroes
                        .Where(h => h != null
                                 && h != hero
                                 && h.IsAlive
                                 && h.Age >= 18 && h.Age < 50
                                 && h.IsFemale != hero.IsFemale
                                 && h.Spouse == null
                                 && h.Name != null
                                 && !HeroNaming.IsAdopted(h.Name.ToString())
                                 && !h.IsClanLeader
                                 && h != Hero.MainHero
                                 && h.Clan != null
                                 && !h.IsPrisoner
                                 && !h.IsFugitive)
                        .ToList();

                    if (candidates.Count == 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.marry] @{username}: нет подходящих NPC для брака");
                        return;
                    }

                    // Random pick из 5 случайных кандидатов (variety)
                    var rng = new Random();
                    var npc = candidates[rng.Next(candidates.Count)];

                    // Apply marriage (pattern из BLT)
                    var oldClan = npc.Clan;

                    npc.Spouse = hero;
                    hero.Spouse = npc;

                    // BLT housekeeping для NPC которая переезжает
                    if (npc.GovernorOf != null)
                    {
                        try { ChangeGovernorAction.RemoveGovernorOf(npc); } catch { }
                    }
                    if (npc.PartyBelongedTo != null)
                    {
                        try
                        {
                            var oldParty = npc.PartyBelongedTo;
                            bool wasLeader = oldParty.LeaderHero == npc;
                            oldParty.MemberRoster.RemoveTroop(
                                npc.CharacterObject, 1, default, 0);
                            MakeHeroFugitiveAction.Apply(npc, false);
                            if (wasLeader && oldParty.IsLordParty)
                            {
                                DisbandPartyAction.StartDisband(oldParty);
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
                        + $"(was clan: {oldClan?.Name}, now: {npc.Clan?.Name})");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[hero.marry] @{username} CRASHED: {ex.Message}");
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
