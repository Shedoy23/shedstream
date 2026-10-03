using System;
using System.Reflection;
namespace HarmonyLib { public class HarmonyPatch : Attribute { } public static class AccessTools { public static MethodInfo Method(Type t, string n) => t.GetMethod(n, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public); } }
namespace TaleWorlds.CampaignSystem.Settlements { public class Settlement { public string Name; } }
namespace TaleWorlds.CampaignSystem {
  using TaleWorlds.CampaignSystem.Settlements;
  public class Hero { public string Name; }
  public class MobileParty { public string Name; public Hero LeaderHero; public Settlement TargetSettlement; }
  public class Army { public object AiBehaviorObject; public MobileParty LeaderParty; private bool IsAnotherEnemyBesiegingTarget() => ((Settlement)AiBehaviorObject).Name != null; }
}
namespace BannerlordLink { public static class BannerlordLinkModule { public static System.Collections.Generic.List<string> Lines = new(); public static void Log(string s) => Lines.Add(s); } }
