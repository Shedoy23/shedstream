using System;
using System.Reflection;
// 26.09: отряд зрителя shedoy23 сдавал бойцов в гарнизон своего замка (100 → 30).
// Патч запрещает отдачу бойцов только отрядам героев зрителей.
namespace HarmonyLib {
 public class HarmonyPatch : Attribute { public HarmonyPatch(Type t,string name){} }
 public class HarmonyPrefix : Attribute {}
}
namespace TaleWorlds.CampaignSystem { public class Hero { public bool Adopted; public string Name="[BLink] shedoy23"; } }
namespace TaleWorlds.CampaignSystem.Roster { public class TroopRoster { public int TotalManCount=100; } }
namespace TaleWorlds.CampaignSystem.Party { public class MobileParty { public TaleWorlds.CampaignSystem.Hero LeaderHero; public TaleWorlds.CampaignSystem.Roster.TroopRoster MemberRoster=new TaleWorlds.CampaignSystem.Roster.TroopRoster(); } }
namespace TaleWorlds.CampaignSystem.Settlements { public class Settlement { public string Name="Замок Гаронтор"; } }
namespace TaleWorlds.CampaignSystem.CampaignBehaviors { public class GarrisonTroopsCampaignBehavior {} }
namespace BannerlordLink { public static class BannerlordLinkModule { public static string Last; public static int Logged; public static void Log(string m){ Logged++; Last=m; } } }
namespace BannerlordLink.Util { public static class HeroNaming { public static bool IsAdopted(TaleWorlds.CampaignSystem.Hero h)=>h?.Adopted==true; } }
class Program {
 static int Main(){
  var prefix=Assembly.GetExecutingAssembly().GetType("BannerlordLink.Patches.ViewerGarrisonDonationPatch")?.GetMethod("Prefix",BindingFlags.Static|BindingFlags.Public);
  int failed=0, passed=0;
  void Check(bool ok,string name){ Console.WriteLine((ok?"PASS ":"FAIL ")+name); if(ok)passed++; else failed++; }
  bool Runs(TaleWorlds.CampaignSystem.Party.MobileParty p)=>(bool)prefix.Invoke(null,new object[]{p,new TaleWorlds.CampaignSystem.Settlements.Settlement(),70});
  Check(!Runs(new TaleWorlds.CampaignSystem.Party.MobileParty{LeaderHero=new TaleWorlds.CampaignSystem.Hero{Adopted=true}}),"отряд зрителя не отдаёт бойцов в гарнизон");
  Check(BannerlordLink.BannerlordLinkModule.Logged==1 && BannerlordLink.BannerlordLinkModule.Last.Contains("70") && BannerlordLink.BannerlordLinkModule.Last.Contains("Гаронтор"),"отказ записан в лог с числом и крепостью");
  Check(Runs(new TaleWorlds.CampaignSystem.Party.MobileParty{LeaderHero=new TaleWorlds.CampaignSystem.Hero{Adopted=false,Name="Авдан"}}),"обычный лорд игры отдаёт как раньше");
  Check(Runs(new TaleWorlds.CampaignSystem.Party.MobileParty()),"отряд без лидера — как раньше");
  Check(Runs(null),"пустой вызов не ломается");
  Console.WriteLine($"{passed} ok / {failed} FAIL"); return failed;
 }
}
