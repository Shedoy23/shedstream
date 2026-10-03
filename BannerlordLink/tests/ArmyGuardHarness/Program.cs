using System;
using System.Reflection;
using BannerlordLink;
using BannerlordLink.Patches;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Settlements;

// 03.10 вылет: Army.IsAnotherEnemyBesiegingTarget с пустой целью армии при лидере «осаждать».
class Program
{
    static int failed;
    static void Check(bool ok, string why) { Console.WriteLine((ok ? "PASS " : "FAIL ") + why); if (!ok) failed++; }

    static bool Run(Army a, out bool result)
    {
        var prefix = typeof(ArmyObjectiveGuardPatch).GetMethod("Prefix", BindingFlags.Static | BindingFlags.NonPublic);
        var args = new object[] { a, false };
        bool cont = (bool)prefix.Invoke(null, args);
        result = (bool)args[1];
        return cont;
    }

    static void Main()
    {
        var castle = new Settlement { Name = "Замок" };
        var ok = new Army { AiBehaviorObject = castle, LeaderParty = new MobileParty { Name = "лорд" } };
        Check(Run(ok, out _) && ok.AiBehaviorObject == castle && BannerlordLinkModule.Lines.Count == 0, "valid army goes to vanilla untouched");
        var repair = new Army { LeaderParty = new MobileParty { Name = "slopkom", TargetSettlement = castle } };
        Check(Run(repair, out _) && repair.AiBehaviorObject == castle, "empty army objective repaired from leader target, vanilla continues");
        var none = new Army { LeaderParty = new MobileParty { Name = "пустой" } };
        bool cont = Run(none, out bool res);
        Check(!cont && !res && none.AiBehaviorObject == null, "no target anywhere: vanilla skipped with false instead of NRE");
        Check(BannerlordLinkModule.Lines.Count == 2 && BannerlordLinkModule.Lines[0].Contains("slopkom"), "culprit army leader named in the log");
        // 03.10 22:30:42: роспуск королевства — вассала из того же королевства не трогаем.
        Check(!BannerlordLink.Util.VassalFollowPolicy.ShouldFollowNow(true, true), "kingdom destruction: vassal in the dying kingdom is left to the engine");
        Check(BannerlordLink.Util.VassalFollowPolicy.ShouldFollowNow(true, false), "kingdom destruction: vassal elsewhere still follows");
        Check(BannerlordLink.Util.VassalFollowPolicy.ShouldFollowNow(false, true), "ordinary kingdom change: vassal follows as before");
                Environment.Exit(failed == 0 ? 0 : 1);
    }
}
