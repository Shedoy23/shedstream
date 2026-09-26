using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink { public static class BannerlordLinkModule { public static List<string> Lines = new(); public static bool Throws; public static void Log(string s) { if(Throws)throw new Exception("log unavailable"); Lines.Add(s); } } }
namespace TaleWorlds.CampaignSystem {
 public class Faction { public string StringId="enemy"; public string Name="Enemy"; public bool Hostile=true; public bool IsAtWarWith(Faction other)=>Hostile && this!=other; }
 public class Hero { public string StringId="lord"; public string Name="Lord"; public MobileParty PartyBelongedTo; }
 public struct CampaignTime { public static double Hour; public static CampaignTime Now=>new(); public double ToHours=>Hour; }
 public class CharacterObject { public string StringId="recruit"; }
 public interface IDataStore {}
 public abstract class CampaignBehaviorBase { public abstract void RegisterEvents(); public abstract void SyncData(IDataStore d); }
 public class TestEvent { public Action Handler; public void AddNonSerializedListener(object o,Action f) { Handler=f; } }
 public static class CampaignEvents { public static TestEvent HourlyTickEvent=new(); }
}
namespace TaleWorlds.CampaignSystem.Settlements { public class Settlement { public string StringId="town"; public string Name="Town"; } }
namespace TaleWorlds.CampaignSystem.Party {
 public class Roster { public int TotalManCount=60; }
 public class MobileParty { public static MobileParty MainParty; public bool IsLordParty=true; public Hero LeaderHero=new(); public Faction MapFaction=new(); public string StringId="party"; public Roster MemberRoster=new(); }
}
namespace TaleWorlds.CampaignSystem.CampaignBehaviors {
 public class HeroSpawnCampaignBehavior {
  [MethodImpl(MethodImplOptions.NoInlining)] public MobileParty SpawnLordParty(Hero hero,bool isNewGame) => new MobileParty { LeaderHero=hero };
 }
 public class GarrisonTroopsCampaignBehavior {
  [MethodImpl(MethodImplOptions.NoInlining)] public void TakeTroopsFromGarrison(MobileParty mobileParty,Settlement settlement,int numberOfTroopsToTake,bool archersAreHighPriority) { mobileParty.MemberRoster.TotalManCount += Math.Min(7,numberOfTroopsToTake); }
 }
 public class RecruitmentCampaignBehavior {
  public enum RecruitingDetail { VolunteerFromIndividual, MercenaryFromTavern, VolunteerFromMap }
  [MethodImpl(MethodImplOptions.NoInlining)] public void RecruitPrisonersAi(MobileParty mobileParty,CharacterObject troop,int num,int conformityCost) { mobileParty.MemberRoster.TotalManCount += num; }
  [MethodImpl(MethodImplOptions.NoInlining)] public void ApplyInternal(MobileParty side1Party,Settlement settlement,Hero individual,CharacterObject troop,int number,int bitCode,RecruitingDetail detail) { side1Party.MemberRoster.TotalManCount += number; }
 }
}
class Program {
 static int failed,passed;
 static void Check(bool b,string s) { Console.WriteLine((b?"PASS ":"FAIL ")+s); if(b)passed++;else failed++; }
 static void Limit(MobileParty __result) { __result.MemberRoster.TotalManCount=Math.Min(20,__result.MemberRoster.TotalManCount); }
 static int Main(string[] args) {
  if(args.Contains("--game-contract")) return GameContract();
  var asm=Assembly.GetExecutingAssembly();
  var audit=asm.GetType("BannerlordLink.Patches.LordTroopDiagnostics");
  Check(audit!=null,"наблюдатель источников пополнения существует"); if(audit==null)return failed;
  void Call(string method)=>audit.GetMethod(method,BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic).Invoke(null,null);
  MobileParty.MainParty=new();
  var harmony=new Harmony("test.lordtroop.observer");
  foreach(var type in asm.GetTypes().Where(t=>t.Namespace=="BannerlordLink.Patches" && t.GetCustomAttributes(typeof(HarmonyPatch),false).Length>0)) harmony.CreateClassProcessor(type).Patch();
  var spawn=typeof(TaleWorlds.CampaignSystem.CampaignBehaviors.HeroSpawnCampaignBehavior).GetMethod("SpawnLordParty");
  // Register limiter AFTER observers, as in the user's load order. Explicit dependency must still win.
  var limiter=new Harmony("com.nolordfreetroop.bannerlord");
  limiter.Patch(spawn,postfix:new HarmonyMethod(typeof(Program).GetMethod(nameof(Limit),BindingFlags.Static|BindingFlags.NonPublic)));
  Call("Reset");
  var party=new TaleWorlds.CampaignSystem.CampaignBehaviors.HeroSpawnCampaignBehavior().SpawnLordParty(new Hero(),false);
  Check(party.MemberRoster.TotalManCount==20,"наблюдение не меняет результат ограничения");
  var lines=BannerlordLink.BannerlordLinkModule.Lines;
  Check(lines.Count==2 && lines[0].Contains("phase=before-limit") && lines[0].Contains("men=60") && lines[1].Contains("phase=after-limit") && lines[1].Contains("men=20"),"реальный Harmony: 60 до чужого postfix, 20 после");
  lines.Clear();
  var recruit=new TaleWorlds.CampaignSystem.CampaignBehaviors.RecruitmentCampaignBehavior();
  for(int i=0;i<12;i++)recruit.ApplyInternal(party,new Settlement(),new Hero(),new CharacterObject(),1,0,TaleWorlds.CampaignSystem.CampaignBehaviors.RecruitmentCampaignBehavior.RecruitingDetail.VolunteerFromIndividual);
  Check(lines.Count==0,"пачка найма не спамит журнал на каждом бойце");
  new TaleWorlds.CampaignSystem.CampaignBehaviors.GarrisonTroopsCampaignBehavior().TakeTroopsFromGarrison(party,new Settlement(),100,false);
  Call("Flush");
  Check(lines.Count==2 && lines.Any(s=>s.Contains("VolunteerFromIndividual")&&s.Contains("added=12")),"12 наймов объединены с происхождением");
  Check(lines.Any(s=>s.Contains("source=garrison")&&s.Contains("added=7")),"записано реально 7, а не запрошенные 100");
  Check(party.MemberRoster.TotalManCount==39,"учёт не меняет войска");
  lines.Clear();
  recruit.RecruitPrisonersAi(party,new CharacterObject(),5,10); Call("Flush");
  Check(lines.Count==1 && lines[0].Contains("source=recruit:prisoner") && lines[0].Contains("added=5"),"обращение пленных учитывается отдельно от найма добровольцев");
  Check(party.MemberRoster.TotalManCount==44,"учёт не меняет обращение пленных");
  lines.Clear();
  recruit.ApplyInternal(MobileParty.MainParty,new Settlement(),new Hero(),new CharacterObject(),1,0,0);
  var neutral=new MobileParty(); neutral.MapFaction.Hostile=false;
  recruit.ApplyInternal(neutral,new Settlement(),new Hero(),new CharacterObject(),1,0,0);
  Call("Flush"); Check(lines.Count==0,"свои и нейтральные отряды не попадают в диагностику врага");
  recruit.ApplyInternal(party,new Settlement(),new Hero(),new CharacterObject(),0,0,0);
  Call("Flush"); Check(lines.Count==0,"тихий no-op не считается пополнением");
  var behavior=(CampaignBehaviorBase)Activator.CreateInstance(asm.GetType("BannerlordLink.Patches.LordTroopDiagnosticsBehavior"),true);
  behavior.RegisterEvents();
  recruit.ApplyInternal(party,new Settlement(),new Hero(),new CharacterObject(),3,0,0);
  CampaignTime.Hour=23; CampaignEvents.HourlyTickEvent.Handler();
  Check(lines.Count==0,"часовой обработчик не сбрасывает пачку в тот же день");
  CampaignTime.Hour=24; CampaignEvents.HourlyTickEvent.Handler();
  Check(lines.Count==1 && lines[0].Contains("added=3") && lines[0].Contains("day=0"),"новый день сам выводит пачку без следующего найма");
  lines.Clear();
  BannerlordLink.BannerlordLinkModule.Throws=true;
  try { new TaleWorlds.CampaignSystem.CampaignBehaviors.HeroSpawnCampaignBehavior().SpawnLordParty(new Hero(),false); Check(true,"ошибка записи не ломает спавн"); } catch { Check(false,"ошибка записи не ломает спавн"); }
  BannerlordLink.BannerlordLinkModule.Throws=false;
  limiter.UnpatchAll(limiter.Id); harmony.UnpatchAll(harmony.Id);
  Console.WriteLine($"{passed} ok / {failed} FAIL"); return failed;
 }

 static int GameContract() {
  string bin=@"X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\bin\Win64_Shipping_Client";
  AppDomain.CurrentDomain.AssemblyResolve += (s,e) => {
   var path=System.IO.Path.Combine(bin,new AssemblyName(e.Name).Name+".dll");
   return System.IO.File.Exists(path)?Assembly.LoadFrom(path):null;
  };
  var game=Assembly.LoadFrom(System.IO.Path.Combine(bin,"TaleWorlds.CampaignSystem.dll"));
  void Signature(string type,string name,string expected,string result) {
   var method=game.GetType("TaleWorlds.CampaignSystem.CampaignBehaviors."+type)?.GetMethod(name,BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public);
   Check(method!=null,type+"."+name+" exists");
   if(method==null)return;
   string actual=string.Join(",",method.GetParameters().Select(p=>p.Name+":"+p.ParameterType.Name));
   Check(actual==expected && method.ReturnType.Name==result,type+" native signature: "+actual);
  }
  Signature("HeroSpawnCampaignBehavior","SpawnLordParty","hero:Hero,isNewGame:Boolean","MobileParty");
  Signature("RecruitmentCampaignBehavior","ApplyInternal","side1Party:MobileParty,settlement:Settlement,individual:Hero,troop:CharacterObject,number:Int32,bitCode:Int32,detail:RecruitingDetail","Void");
  Signature("GarrisonTroopsCampaignBehavior","TakeTroopsFromGarrison","mobileParty:MobileParty,settlement:Settlement,numberOfTroopsToTake:Int32,archersAreHighPriority:Boolean","Void");
  Signature("RecruitmentCampaignBehavior","RecruitPrisonersAi","mobileParty:MobileParty,troop:CharacterObject,num:Int32,conformityCost:Int32","Void");
  Console.WriteLine($"{passed} ok / {failed} FAIL");return failed;
 }
}
