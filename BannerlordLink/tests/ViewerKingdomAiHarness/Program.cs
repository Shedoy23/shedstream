using System.Reflection;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.CampaignBehaviors.BarterBehaviors;

class Program
{
    static int Main(string[] args)
    {
        try
        {
            if (args.Length == 2)
            {
                var game = args[1];
                var dirs = new[] { Path.GetDirectoryName(Path.GetFullPath(args[0])), Path.Combine(game, "bin", "Win64_Shipping_Client"), Path.Combine(game, "Modules", "Native", "bin", "Win64_Shipping_Client"), Path.Combine(game, "Modules", "SandBox", "bin", "Win64_Shipping_Client") };
                AppDomain.CurrentDomain.AssemblyResolve += (sender, e) => {
                    var name = new AssemblyName(e.Name).Name + ".dll";
                    var file = dirs.Select(d => Path.Combine(d, name)).FirstOrDefault(File.Exists);
                    return file == null ? null : Assembly.LoadFrom(file);
                };
                var actualPatch = Assembly.LoadFrom(Path.GetFullPath(args[0])).GetType("BannerlordLink.Patches.ViewerKingdomAiPatch", true);
                var targets = ((IEnumerable<MethodBase>)actualPatch.GetMethod("TargetMethods").Invoke(null, null)).ToArray();
                if (targets.Length != 5 || targets.Any(m => m.DeclaringType.Assembly.GetName().Name != "TaleWorlds.CampaignSystem")) throw new Exception("Wrong real engine targets");
                new Harmony("test.viewer.kingdom.real.engine").CreateClassProcessor(actualPatch).Patch();
                foreach (var target in targets)
                    if (!Harmony.GetPatchInfo(target).Prefixes.Any(p => p.PatchMethod.DeclaringType == actualPatch)) throw new Exception("Missing real prefix: " + target.Name);
                Console.WriteLine("PASS: all 5 real installed engine methods resolved and patched");
                return 0;
            }
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
