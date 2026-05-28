using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using TaleWorlds.CampaignSystem.MapEvents;
using TaleWorlds.Core;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-05-29 Stage 4 (BLT-RC22 engine bug fix) — vanilla bug где retreat
    /// от siege assault causes ENTIRE besieging army to be captured/killed,
    /// и lords made fugitive respawning with 1 troop. Pattern из BLT
    /// HarmonyPatches.cs:837-908 (BLT_SiegeRetreatFix).
    ///
    /// Engine behavior (vanilla bug):
    ///   1. Siege assault commits MapEventResults
    ///   2. Attackers defeated (defender has survivors)
    ///   3. Engine treats this as "total capture" — все attackers становятся
    ///      prisoners / killed
    ///   4. Their lords made fugitive → respawn with 1 troop (effectively
    ///      destroying army)
    ///
    /// What this patch does:
    ///   1. Prefix: если siege-related event AND HasWinner AND
    ///      RetreatingSide == None AND defeated has healthy survivors →
    ///      temporarily set RetreatingSide = DefeatedSide. Engine then
    ///      treats it как "retreat" не "wipe" → troops survive (wounded).
    ///   2. Postfix: restore RetreatingSide = None (так что later systems
    ///      видят correct battle result).
    ///
    /// Tracking:
    ///   _mutated HashSet хранит MapEvent instances которые мы мутировали —
    ///   Postfix restores только these (не touch'аем un-mutated events).
    ///
    /// Why we adopt this:
    ///   - Viewer-led parties getting wiped в siege retreats = engagement loss
    ///   - BLT-RC22 considers this engine bug worthy of dedicated patch
    ///   - Reflection-based access к private RetreatingSide setter (engine
    ///     does not expose это публично — это property с private set)
    ///
    /// Reflection delegate pattern из BLT (static field cached at class init):
    ///   - PropertyInfo lookup в static cctor
    ///   - GetValue/SetValue для read/write
    ///   - Null check на случай engine version mismatch (property renamed)
    /// </summary>
    [HarmonyPatch(typeof(MapEvent), "CalculateAndCommitMapEventResults")]
    internal static class MapEvent_CalculateAndCommitMapEventResults_SiegeRetreatPatch
    {
        // Reflection cache для private RetreatingSide setter. Engine doesn't
        // expose это публично — нам нужен write access для temporary
        // overwrite во время commit pathway.
        private static readonly PropertyInfo RetreatingSideProp =
            typeof(MapEvent).GetProperty("RetreatingSide",
                BindingFlags.Public | BindingFlags.Instance);

        // Tracks MapEvent instances которые мы мутировали — restore их в Postfix.
        // Static HashSet thread-safe wrap не нужен — RegisterBlow patches
        // synchronously вызываются engine'ом.
        private static readonly HashSet<MapEvent> _mutated = new HashSet<MapEvent>();

        private static bool IsSiegeRelated(MapEvent e)
        {
            return e.IsSiegeAssault || e.IsSallyOut || e.IsSiegeOutside;
        }

        [HarmonyPrefix]
        public static void Prefix(MapEvent __instance)
        {
            try
            {
                if (__instance == null) return;
                if (RetreatingSideProp == null) return;  // engine version mismatch

                if (!IsSiegeRelated(__instance)) return;
                if (!__instance.HasWinner) return;
                if (__instance.RetreatingSide != BattleSideEnum.None) return;

                var defeatedSide = __instance.GetMapEventSide(__instance.DefeatedSide);
                if (defeatedSide == null) return;

                int survivors = defeatedSide.GetTotalHealthyTroopCountOfSide();
                if (survivors <= 0) return;  // truly wiped → allow vanilla full capture

                // Mutate: temporarily set RetreatingSide = DefeatedSide.
                // Engine downstream logic тогда treats it как retreat, не capture.
                RetreatingSideProp.SetValue(__instance, __instance.DefeatedSide);
                _mutated.Add(__instance);

                BannerlordLinkModule.LogVerbose(() =>
                    $"[SiegeRetreatFix] {survivors} survivors on {__instance.DefeatedSide} side — " +
                    "suppressing troop capture (will restore in Postfix)");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[SiegeRetreatFix] Prefix error: {ex.GetType().Name}: {ex.Message}");
            }
        }

        [HarmonyPostfix]
        public static void Postfix(MapEvent __instance)
        {
            try
            {
                if (__instance == null) return;
                if (RetreatingSideProp == null) return;
                if (!_mutated.Remove(__instance)) return;

                // Restore: RetreatingSide → None так что later systems видят
                // correct battle result. Engine has already processed troop
                // disposition в commit pathway (using our temporary value),
                // так что restored None — это для consistency.
                RetreatingSideProp.SetValue(__instance, BattleSideEnum.None);

                BannerlordLinkModule.LogVerbose(() =>
                    "[SiegeRetreatFix] RetreatingSide restored to None");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[SiegeRetreatFix] Postfix error: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
