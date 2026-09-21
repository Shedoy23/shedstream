using System.Reflection;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.CampaignBehaviors.BarterBehaviors;

class Program
{
    static int Main()
    {
        try
        {
            var patch = typeof(Program).Assembly.GetType("BannerlordLink.Patches.ViewerKingdomAiPatch");
            if (patch == null) throw new Exception("Missing viewer kingdom AI guard");
            new Harmony("test.viewer.kingdom.ai").CreateClassProcessor(patch).Patch();
            var behavior = new DiplomaticBartersBehavior();
            var viewer = new Clan { Leader = new Hero { Name = new("[BLink] viewer") } };
            var npc = new Clan { Leader = new Hero { Name = new("Derthert") } };
            var methods = new[] { "ConsiderClanJoin", "ConsiderClanJoinAsMercenary", "ConsiderClanLeaveKingdom", "ConsiderClanLeaveAsMercenary", "ConsiderDefection" };
            int checks = 0;
            foreach (var name in methods)
            {
                var method = typeof(DiplomaticBartersBehavior).GetMethod(name, BindingFlags.NonPublic | BindingFlags.Instance)!;
                foreach (var clan in new[] { viewer, npc, new Clan(), null })
                {
                    behavior.Calls = 0;
                    method.Invoke(behavior, method.GetParameters().Length == 1 ? new object[] { clan } : new object[] { clan, new Kingdom() });
                    if (behavior.Calls != (ReferenceEquals(clan, viewer) ? 0 : 1)) throw new Exception(name + " wrong decision");
                    checks++;
                }
            }
            behavior.Calls = 0;
            behavior.ConsiderPeace(viewer);
            behavior.ManualJoinOrLeave(viewer);
            if (behavior.Calls != 2) throw new Exception("Unrelated/manual actions blocked");
            Console.WriteLine($"PASS: {checks + 2} decisions; real Harmony prefixes on test engine methods");
            return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }
}
namespace TaleWorlds.Localization { public class TextObject { readonly string value; public TextObject(string s) { value = s; } public override string ToString() => value; } }
namespace TaleWorlds.CampaignSystem
{
    public class Hero { public TaleWorlds.Localization.TextObject Name { get; set; } }
    public class Clan { public Hero Leader { get; set; } }
    public class Kingdom { }
}
namespace BannerlordLink { public static class BannerlordLinkModule { public static void Log(string s) => Console.WriteLine(s); } }
namespace TaleWorlds.CampaignSystem.CampaignBehaviors.BarterBehaviors
{
    public class DiplomaticBartersBehavior
    {
        public int Calls;
        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)] private void ConsiderClanJoin(Clan clan, Kingdom kingdom) { Calls++; }
        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)] private void ConsiderClanJoinAsMercenary(Clan clan, Kingdom kingdom) { Calls++; }
        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)] private void ConsiderClanLeaveKingdom(Clan clan) { Calls++; }
        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)] private void ConsiderClanLeaveAsMercenary(Clan clan) { Calls++; }
        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)] private void ConsiderDefection(Clan clan1, Kingdom kingdom) { Calls++; }
        public void ConsiderPeace(Clan clan) { Calls++; }
        public void ManualJoinOrLeave(Clan clan) { Calls++; }
    }
}
