using System;
using System.Collections.Generic;
using System.Globalization;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.CampaignBehaviors;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink.Patches
{
    // Read-only provenance, independent of viewer events/backend. No changes to rosters,
    // gold, recruitment or the limiter. Totals are observed after a native operation.
    internal static class LordTroopDiagnostics
    {
        private sealed class Batch { internal string Label; internal int Added, Calls, LastTotal; }
        private static readonly Dictionary<string, Batch> Pending = new Dictionary<string, Batch>();
        private static double _day = double.NaN;
        private static bool _reportedError;

        internal static void Reset() { Pending.Clear(); _day = double.NaN; _reportedError = false; }
        private static bool Eligible(MobileParty party) => party != null && party != MobileParty.MainParty
            && party.IsLordParty && party.LeaderHero != null && party.MapFaction != null
            && MobileParty.MainParty?.MapFaction != null && party.MapFaction.IsAtWarWith(MobileParty.MainParty.MapFaction);

        private static void Safe(Action action)
        {
            try { action(); }
            catch (Exception ex)
            {
                if (_reportedError) return;
                _reportedError = true;
                try { BannerlordLinkModule.Log("[LordTroops] diagnostics error (game action unchanged): " + ex.GetType().Name + ": " + ex.Message); }
                catch { /* Diagnostics must never break a campaign action, including logging errors. */ }
            }
        }

        private static string Identity(MobileParty p) => "party=" + p.StringId + " lord=" + p.LeaderHero.StringId
            + " name='" + p.LeaderHero.Name + "' faction=" + p.MapFaction.StringId;
        private static string Hour() => CampaignTime.Now.ToHours.ToString("F1", CultureInfo.InvariantCulture);

        internal static int? Capture(MobileParty party)
        {
            int? count = null;
            Safe(() => { if (Eligible(party)) count = party.MemberRoster.TotalManCount; });
            return count;
        }

        internal static void Spawn(MobileParty party, string phase, bool newGame)
            => Safe(() => {
                if (Eligible(party)) BannerlordLinkModule.Log("[LordTroops] hour=" + Hour() + " source=spawn phase=" + phase
                    + " newGame=" + newGame + " " + Identity(party) + " men=" + party.MemberRoster.TotalManCount);
            });

        internal static void Changed(MobileParty party, int? before, string source, Settlement place)
            => Safe(() => {
                if (!before.HasValue || party == null) return;
                int added = party.MemberRoster.TotalManCount - before.Value;
                if (added <= 0) return;
                FlushIfDue();
                string key = party.StringId + "|" + source + "|" + place?.StringId;
                if (!Pending.TryGetValue(key, out var batch))
                {
                    if (Pending.Count >= 1024) Flush();
                    batch = new Batch { Label = Identity(party) + " source=" + source + " settlement=" + (place?.StringId ?? "none") };
                    Pending[key] = batch;
                }
                batch.Added += added; batch.Calls++; batch.LastTotal = party.MemberRoster.TotalManCount;
            });

        internal static void FlushIfDue() => Safe(() => {
            double day = Math.Floor(CampaignTime.Now.ToHours / 24);
            if (day != _day) { Flush(); _day = day; }
        });

        internal static void Flush() => Safe(() => {
            // Clear before logging so a failed writer cannot grow/replay the same batch forever.
            var batches = new List<Batch>(Pending.Values); Pending.Clear();
            foreach (var batch in batches)
                BannerlordLinkModule.Log("[LordTroops] hour=" + Hour() + " day=" + _day.ToString(CultureInfo.InvariantCulture)
                    + " " + batch.Label + " added=" + batch.Added + " calls=" + batch.Calls + " lastTotal=" + batch.LastTotal);
        });
    }

    internal sealed class LordTroopDiagnosticsBehavior : CampaignBehaviorBase
    {
        public LordTroopDiagnosticsBehavior() { LordTroopDiagnostics.Reset(); }
        public override void RegisterEvents() => CampaignEvents.HourlyTickEvent.AddNonSerializedListener(this, LordTroopDiagnostics.FlushIfDue);
        public override void SyncData(IDataStore dataStore) { } // Diagnostic batches do not belong in a save.
    }

    [HarmonyPatch(typeof(HeroSpawnCampaignBehavior), "SpawnLordParty")]
    internal static class LordSpawnBeforeLimitDiagnostics
    {
        [HarmonyPostfix, HarmonyBefore("com.nolordfreetroop.bannerlord")]
        public static void Postfix(MobileParty __result, bool isNewGame) => LordTroopDiagnostics.Spawn(__result, "before-limit", isNewGame);
    }

    [HarmonyPatch(typeof(HeroSpawnCampaignBehavior), "SpawnLordParty")]
    internal static class LordSpawnAfterLimitDiagnostics
    {
        [HarmonyPostfix, HarmonyAfter("com.nolordfreetroop.bannerlord")]
        public static void Postfix(MobileParty __result, bool isNewGame) => LordTroopDiagnostics.Spawn(__result, "after-limit", isNewGame);
    }

    [HarmonyPatch(typeof(RecruitmentCampaignBehavior), "ApplyInternal")]
    internal static class LordRecruitmentDiagnostics
    {
        [HarmonyPrefix]
        public static void Prefix(MobileParty side1Party, out int? __state) => __state = LordTroopDiagnostics.Capture(side1Party);
        [HarmonyPostfix]
        public static void Postfix(MobileParty side1Party, Settlement settlement, object detail, int? __state)
            => LordTroopDiagnostics.Changed(side1Party, __state, "recruit:" + detail, settlement);
    }

    // Native prisoner conversion bypasses ApplyInternal entirely.
    [HarmonyPatch(typeof(RecruitPrisonersCampaignBehavior), "RecruitPrisonersAi")]
    internal static class LordPrisonerRecruitmentDiagnostics
    {
        [HarmonyPrefix]
        public static void Prefix(MobileParty mobileParty, out int? __state) => __state = LordTroopDiagnostics.Capture(mobileParty);
        [HarmonyPostfix]
        public static void Postfix(MobileParty mobileParty, int? __state)
            => LordTroopDiagnostics.Changed(mobileParty, __state, "recruit:prisoner", null);
    }

    [HarmonyPatch(typeof(GarrisonTroopsCampaignBehavior), "TakeTroopsFromGarrison")]
    internal static class LordGarrisonWithdrawalDiagnostics
    {
        [HarmonyPrefix]
        public static void Prefix(MobileParty mobileParty, out int? __state) => __state = LordTroopDiagnostics.Capture(mobileParty);
        [HarmonyPostfix]
        public static void Postfix(MobileParty mobileParty, Settlement settlement, int? __state)
            => LordTroopDiagnostics.Changed(mobileParty, __state, "garrison", settlement);
    }
}
