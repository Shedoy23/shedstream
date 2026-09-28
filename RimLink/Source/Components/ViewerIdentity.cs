using System;
using System.Linq;
using Verse;

namespace RimLink.Components
{
    public sealed class Hediff_RimLinkViewerIdentity : HediffWithComps
    {
        public override bool Visible => false;
    }

    public sealed class HediffCompProperties_RimLinkViewer : HediffCompProperties
    {
        public HediffCompProperties_RimLinkViewer()
        {
            compClass = typeof(HediffComp_RimLinkViewer);
        }
    }

    /// <summary>
    /// Сохраняемая вместе с пешкой связь с Twitch-пользователем. В отличие от
    /// имени она переживает переименование, смену карты и большинство редакторов.
    /// </summary>
    public sealed class HediffComp_RimLinkViewer : HediffComp
    {
        public string Username = "";

        public override void CompExposeData()
        {
            base.CompExposeData();
            Scribe_Values.Look(ref Username, "rimLinkUsername", "");
        }
    }

    public static class ViewerIdentity
    {
        public const string MarkerDefName = "RimLink_ViewerIdentity";

        private static HediffDef MarkerDef =>
            DefDatabase<HediffDef>.GetNamed(MarkerDefName, errorOnFail: false);

        public static bool TryGetUsername(Pawn pawn, out string username)
        {
            username = "";
            if (pawn?.health?.hediffSet == null) return false;

            HediffDef marker = MarkerDef;
            if (marker == null) return false;
            Hediff hediff = pawn.health.hediffSet.hediffs
                .FirstOrDefault(h => h?.def == marker);
            var comp = hediff?.TryGetComp<HediffComp_RimLinkViewer>();
            if (string.IsNullOrWhiteSpace(comp?.Username)) return false;

            username = comp.Username.Trim();
            return true;
        }

        public static bool Ensure(Pawn pawn, string username)
        {
            if (pawn?.health == null || string.IsNullOrWhiteSpace(username)) return false;

            try
            {
                HediffDef marker = MarkerDef;
                if (marker == null) return false;

                Hediff hediff = pawn.health.hediffSet.hediffs
                    .FirstOrDefault(h => h?.def == marker);
                if (hediff == null)
                {
                    hediff = HediffMaker.MakeHediff(marker, pawn);
                    pawn.health.AddHediff(hediff);
                }

                var comp = hediff.TryGetComp<HediffComp_RimLinkViewer>();
                if (comp == null) return false;
                comp.Username = username.Trim();
                return true;
            }
            catch (Exception ex)
            {
                RimLinkLog.Warn($"[RimLink] Не удалось сохранить identity пешки: {ex.Message}");
                return false;
            }
        }
    }
}
