using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Helper для push'а full hero state на backend как `player.state_update` event.
    ///
    /// Sprint M19: расширяет state fields — gold + level + clan_name +
    /// kingdom_name + location + is_alive + is_prisoner. Дёргается из:
    ///   • AdoptHeroHandler — после adoption (initial state)
    ///   • SetClassHandler  — после class change (level/clan/kingdom могут
    ///     не меняться, но re-sync дешёвый, держит UI свежим)
    ///   • MainCampaignBehavior.OnHeroLevelledUp — level changed
    ///
    /// Backend whitelist (см. _adapter._on_player_state_update) принимает
    /// эти поля и UPDATE'ит bannerlord_heroes. Дополнительные поля игнорируются.
    ///
    /// Fire-and-forget — не блокирует main thread, ошибки log only.
    /// </summary>
    public static class HeroStateSync
    {
        public static void Push(Hero hero)
        {
            if (hero == null || hero.Name == null) return;
            try
            {
                string username = HeroNaming.ExtractUsername(hero.Name.ToString());
                if (string.IsNullOrEmpty(username)) return;

                // Clan / Kingdom могут быть null (wanderer без клана / клан вне
                // королевства). Передаём явно null чтобы backend стёр поле
                // (e.g. heir после смерти лидера клана).
                string clanName = hero.Clan?.Name?.ToString();
                string kingdomName = hero.Clan?.Kingdom?.Name?.ToString();

                // Sprint 5.8: focus + attribute dicts для UI прогрессии.
                // {skill_stringId: {focus, level, xp}} / {attr_stringId: value}
                var skillsSnapshot = BuildSkillsSnapshot(hero);
                var attrsSnapshot = BuildAttributesSnapshot(hero);
                // Sprint 5.11: clan / kingdom info dicts для модалов.
                var clanInfo = BuildClanInfo(hero);
                var kingdomInfo = BuildKingdomInfo(hero);

                var payload = new
                {
                    username      = username,
                    hero_id       = hero.StringId,
                    gold          = hero.Gold,
                    level         = hero.Level,
                    is_alive      = hero.IsAlive ? 1 : 0,
                    is_prisoner   = hero.IsPrisoner ? 1 : 0,
                    location      = hero.CurrentSettlement?.Name?.ToString(),
                    clan_name     = clanName,
                    kingdom_name  = kingdomName,
                    skills        = skillsSnapshot,
                    attributes    = attrsSnapshot,
                    clan_info     = clanInfo,
                    kingdom_info  = kingdomInfo,
                };
                string json = JsonConvert.SerializeObject(payload);

                Task.Run(async () =>
                {
                    try
                    {
                        await BannerlordLinkModule.Backend
                            .PostEventAsync("bannerlord", "player.state_update", json);
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[HeroStateSync] push @{username} failed: {ex.Message}");
                    }
                });

                BannerlordLinkModule.Log(
                    $"[HeroStateSync] @{username} L{hero.Level} " +
                    $"gold={hero.Gold} clan={clanName ?? "—"} kingdom={kingdomName ?? "—"}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroStateSync] CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>Sprint 5.8: build snapshot всех skills с focus/level/xp.</summary>
        private static Dictionary<string, object> BuildSkillsSnapshot(Hero hero)
        {
            var result = new Dictionary<string, object>();
            try
            {
                if (hero?.HeroDeveloper == null) return result;
                var skills = MBObjectManager.Instance.GetObjectTypeList<SkillObject>();
                if (skills == null) return result;

                foreach (var s in skills)
                {
                    if (s == null) continue;
                    try
                    {
                        int focus = hero.HeroDeveloper.GetFocus(s);
                        int level = hero.GetSkillValue(s);
                        result[s.StringId] = new
                        {
                            level = level,
                            focus = focus,
                            name = s.Name?.ToString() ?? s.StringId,
                        };
                    }
                    catch { /* skill read failed — skip */ }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildSkillsSnapshot: {ex.Message}");
            }
            return result;
        }

        /// <summary>Sprint 5.11: clan info для modal.</summary>
        private static object BuildClanInfo(Hero hero)
        {
            try
            {
                var clan = hero?.Clan;
                if (clan == null) return null;
                return new
                {
                    name            = clan.Name?.ToString(),
                    leader_name     = clan.Leader?.Name?.ToString(),
                    is_leader       = clan.Leader == hero,
                    members_count   = clan.Heroes?.Count ?? 0,
                    tier            = clan.Tier,
                    renown          = (int)clan.Renown,
                    fiefs_count     = clan.Fiefs?.Count ?? 0,
                    parties_count   = clan.WarPartyComponents?.Count ?? 0,
                    culture         = clan.Culture?.StringId,
                    kingdom_name    = clan.Kingdom?.Name?.ToString(),
                };
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildClanInfo: {ex.Message}");
                return null;
            }
        }

        /// <summary>Sprint 5.11: kingdom info для modal.</summary>
        private static object BuildKingdomInfo(Hero hero)
        {
            try
            {
                var kingdom = hero?.Clan?.Kingdom;
                if (kingdom == null) return null;
                int atWarCount = 0;
                try
                {
                    atWarCount = Kingdom.All?.Count(k => k != null && k != kingdom
                        && FactionManager.IsAtWarAgainstFaction(kingdom, k)) ?? 0;
                }
                catch { }
                return new
                {
                    name            = kingdom.Name?.ToString(),
                    ruler_name      = kingdom.Leader?.Name?.ToString(),
                    is_ruler        = kingdom.Leader == hero,
                    clans_count     = kingdom.Clans?.Count ?? 0,
                    fiefs_count     = kingdom.Fiefs?.Count ?? 0,
                    at_war_count    = atWarCount,
                    culture         = kingdom.Culture?.StringId,
                };
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildKingdomInfo: {ex.Message}");
                return null;
            }
        }

        /// <summary>Sprint 5.8: build snapshot всех attributes.</summary>
        private static Dictionary<string, int> BuildAttributesSnapshot(Hero hero)
        {
            var result = new Dictionary<string, int>();
            try
            {
                var attrs = MBObjectManager.Instance.GetObjectTypeList<CharacterAttribute>();
                if (attrs == null) return result;
                foreach (var a in attrs)
                {
                    if (a == null) continue;
                    try { result[a.StringId] = hero.GetAttributeValue(a); }
                    catch { }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HeroStateSync] BuildAttributesSnapshot: {ex.Message}");
            }
            return result;
        }
    }
}
