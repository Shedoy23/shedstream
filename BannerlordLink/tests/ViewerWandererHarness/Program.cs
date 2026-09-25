using System;
using System.Reflection;
// 25.09: герой зрителя без клана исчезал на дневном тике (ваниль убирает
// ненанятых странников). Патч блокирует только это; остальное — как было.
namespace HarmonyLib {
 public class HarmonyPatch : Attribute { public HarmonyPatch(Type t,string name){} }
 public class HarmonyPrefix : Attribute {}
}
namespace TaleWorlds.CampaignSystem {
 public class Clan {}
 public class Hero { public bool Adopted; public Clan Clan; public bool IsAlive=true; public string Name="[BLink] kuro_gothic"; }
}
namespace TaleWorlds.CampaignSystem.Actions { public static class KillCharacterAction { public static void ApplyByRemove(TaleWorlds.CampaignSystem.Hero victim,bool showNotification=false,bool isForced=true){} } }
namespace BannerlordLink { public static class BannerlordLinkModule { public static int Logged; public static void Log(string m){ Logged++; } } }
namespace BannerlordLink.Util { public static class HeroNaming { public static bool IsAdopted(TaleWorlds.CampaignSystem.Hero h)=>h?.Adopted==true; } }
class Program {
 static int Main(){
  var prefix=Assembly.GetExecutingAssembly().GetType("BannerlordLink.Patches.ViewerWandererRemovalPatch")?.GetMethod("Prefix",BindingFlags.Static|BindingFlags.Public);
  int failed=0, passed=0;
  void Check(bool ok,string name){ Console.WriteLine((ok?"PASS ":"FAIL ")+name); if(ok)passed++; else failed++; }
  bool Runs(TaleWorlds.CampaignSystem.Hero h)=>(bool)prefix.Invoke(null,new object[]{h});
  var clan=new TaleWorlds.CampaignSystem.Clan();
  Check(!Runs(new TaleWorlds.CampaignSystem.Hero{Adopted=true}),"зритель без клана: игра не может убрать как странника");
  Check(BannerlordLink.BannerlordLinkModule.Logged==1,"блокировка записана в лог");
  Check(Runs(new TaleWorlds.CampaignSystem.Hero{Adopted=true,Clan=clan}),"зритель в клане: уход с уничтоженным кланом как раньше");
  Check(Runs(new TaleWorlds.CampaignSystem.Hero{Adopted=false}),"обычный странник игры убирается как раньше");
  Check(Runs(new TaleWorlds.CampaignSystem.Hero{Adopted=true,IsAlive=false}),"мёртвого не трогаем");
  Check(Runs(null),"пустой вызов не ломается");
  Console.WriteLine($"{passed} ok / {failed} FAIL"); return failed;
 }
}
