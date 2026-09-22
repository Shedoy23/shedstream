using System;
using System.Reflection;
using System.Linq;
namespace HarmonyLib {
 public class HarmonyPatch : Attribute { public HarmonyPatch(Type t,string name){} }
 public class HarmonyPostfix : Attribute {}
 public class HarmonyPriority : Attribute {public HarmonyPriority(int p){} }
 public static class Priority {public const int Last=0;}
}
namespace TaleWorlds.CampaignSystem {public class Hero {public bool Adopted;} public class CharacterObject {public Hero HeroObject;}}
namespace TaleWorlds.CampaignSystem.GameComponents {public class DefaultPartyHealingModel {}}
namespace BannerlordLink.Util { public static class HeroNaming { public static bool IsAdopted(TaleWorlds.CampaignSystem.Hero h)=>h?.Adopted==true;}}
class Program {
 static int Main(){
 var type=Assembly.GetExecutingAssembly().GetType("BannerlordLink.Patches.ViewerBattleMortalityPatch");
 int failed=0, passed=0;
 foreach(var row in new[]{(true,0f,.95f),(true,.5f,.975f),(true,.98f,.999f),(true,1f,1f),(false,.5f,.5f),(false,0f,0f)}){
  var character=new TaleWorlds.CampaignSystem.CharacterObject{HeroObject=new TaleWorlds.CampaignSystem.Hero{Adopted=row.Item1}};
  object[] args={character,row.Item2};
  type?.GetMethod("Postfix",BindingFlags.Static|BindingFlags.Public)?.Invoke(null,args);
  if(Math.Abs((float)args[1]-row.Item3)<.000001f)passed++;else failed++;
 }
 object[] regular={new TaleWorlds.CampaignSystem.CharacterObject(),.25f};
 type?.GetMethod("Postfix")?.Invoke(null,regular);
 if((float)regular[1]==.25f)passed++;else failed++;
 object[] missing={null,.3f};type?.GetMethod("Postfix")?.Invoke(null,missing);
 if((float)missing[1]==.3f)passed++;else failed++;
 Console.WriteLine($"{passed} ok / {failed} FAIL");return failed;
 }
}
