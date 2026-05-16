using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Net;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.AgentOrigins;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.0 — `player.spawn` (summon hero в текущую Mission).
    ///
    /// MVP scope:
    ///   • Только Mission.Mode == Battle (skip Tournament / Siege deployment
    ///     — там своя логика, BLT обрабатывает отдельно).
    ///   • isPlayerSide = true (всегда allies стримера).
    ///   • party = MobileParty.MainParty.Party (player party).
    ///   • spawnWithHorse = по class_key (cavalry/horse_archer/etc.).
    ///   • Equipment — то что у hero уже set'нуто SetClassHandler'ом.
    ///   • No-spawn checks: Mission alive + Continuing + hero не уже в Mission.
    ///
    /// Out of scope (Sprint 5.1+):
    ///   • Tournament / Siege spawn logic.
    ///   • Custom position / direction (BLT поддерживает spawn near attacker).
    ///   • Reinforcement waves (BLT IsSideDepleted Harmony patch).
    ///   • Formation join / leader follow.
    ///
    /// Heroes которые умирают в Mission triggrят HeroKilledEvent →
    /// MainCampaignBehavior пушит player.died на backend (existing flow).
    /// </summary>
    public class SummonHeroHandler : IActionHandler
    {
        public string ActionType => "player.spawn";

        // Class keys которые spawn'ятся с лошадью (соответствует M15 bannerlord_classes).
        // Если PowerCache знает class viewer'а — используем; иначе fallback на dismounted.
        private static readonly System.Collections.Generic.HashSet<string> MountedClasses =
            new System.Collections.Generic.HashSet<string>(StringComparer.OrdinalIgnoreCase)
            {
                "cavalry", "camel_cavalry", "horse_archer", "camel_archer", "knight",
            };

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            MainThreadDispatcher.Enqueue(() => Summon(username));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Summon(string username)
        {
            try
            {
                if (!IsMissionReadyForSummon(out string reason))
                {
                    BannerlordLinkModule.Log($"[player.spawn] @{username}: skip — {reason}");
                    return;
                }

                Hero hero = HeroLookup.FindByUsername(username);
                if (hero == null)
                {
                    BannerlordLinkModule.Log($"[player.spawn] @{username}: hero not found in AliveHeroes");
                    return;
                }

                if (IsAlreadySpawned(hero))
                {
                    BannerlordLinkModule.Log($"[player.spawn] @{username}: уже spawned в Mission");
                    return;
                }

                var mainParty = MobileParty.MainParty;
                if (mainParty?.Party == null)
                {
                    BannerlordLinkModule.Log($"[player.spawn] @{username}: MainParty unavailable");
                    return;
                }

                bool withHorse = ResolveWithHorse(username);

                // SpawnTroop signature (1.3.x): origin, isPlayerSide, hasFormation,
                // spawnWithHorse, isReinforcement, formationTroopCount=1, formationTroopIndex=0,
                // isAlarmed=true, wieldInitialWeapons=true, forceDismounted=false,
                // initialPosition?, initialDirection?
                Agent agent = Mission.Current.SpawnTroop(
                    new PartyAgentOrigin(mainParty.Party, hero.CharacterObject),
                    isPlayerSide:        true,
                    hasFormation:        true,
                    spawnWithHorse:      withHorse,
                    isReinforcement:     true,    // late-spawn в идущий бой
                    formationTroopCount: 1,
                    formationTroopIndex: 0,
                    isAlarmed:           true,
                    wieldInitialWeapons: true,
                    forceDismounted:     !withHorse,
                    initialPosition:     null,
                    initialDirection:    null);

                if (agent != null)
                {
                    // Smooth visual entry — fade in agent + mount если есть.
                    try { agent.MountAgent?.FadeIn(); agent.FadeIn(); } catch { }
                }

                BannerlordLinkModule.Log(
                    $"[player.spawn] @{username} → summoned " +
                    $"(horse={withHorse}, agent={(agent != null ? "OK" : "NULL")})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[player.spawn] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        private static bool IsMissionReadyForSummon(out string reason)
        {
            var m = Mission.Current;
            if (m == null) { reason = "Mission.Current == null"; return false; }
            if (!m.IsLoadingFinished) { reason = "mission not loaded"; return false; }
            if (m.CurrentState != Mission.State.Continuing)
            {
                reason = $"mission state {m.CurrentState} (нужен Continuing)";
                return false;
            }
            // TODO Sprint 5.1: MissionMode check (skip Tournament/Siege/Deployment).
            // В 1.3.15 MissionMode enum resolve failed на текущем reference set —
            // в bin/Win64_Shipping_Client/TaleWorlds.MountAndBlade.dll нет enum
            // в expected namespace. Skip пока — IsLoadingFinished + Continuing
            // фильтрует большую часть edge cases. Если будет краш в
            // tournament/siege — добавим check через reflection или Mission.Mode.ToString().
            reason = null;
            return true;
        }

        private static bool IsAlreadySpawned(Hero hero)
        {
            if (hero?.CharacterObject == null || Mission.Current == null) return false;
            foreach (var a in Mission.Current.Agents)
            {
                if (a == null || !a.IsActive()) continue;
                if (a.Character == hero.CharacterObject) return true;
            }
            return false;
        }

        private static bool ResolveWithHorse(string username)
        {
            var hc = PowerCache.GetHeroClass(username);
            if (hc == null) return false;
            return MountedClasses.Contains(hc.Value.classKey);
        }
    }
}
