using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
// 25.09: три скрытых правила игры против героев зрителей (роспуск клана через
// 28 дней, авто-женитьба, переодевание правителя). Заглушки повторяют имена игры.
namespace HarmonyLib {
 public class HarmonyPatch : Attribute { public HarmonyPatch(Type t,string name){} }
 public class HarmonyPrefix : Attribute {} public class HarmonyPostfix : Attribute {}
}
namespace TaleWorlds.CampaignSystem {
 public class Hero { public string Name="NPC"; public bool IsAlive=true; public Clan Clan; }
 public class Clan { public string Name="Клан"; public Hero Leader; public List<Hero> Heroes=new(); }
 public class Kingdom { public string Name="Королевство"; public Hero Leader; }
 public struct CampaignTime {}
}
namespace TaleWorlds.CampaignSystem.CampaignBehaviors {
 public class FactionDiscontinuationCampaignBehavior { private Dictionary<TaleWorlds.CampaignSystem.Clan,TaleWorlds.CampaignSystem.CampaignTime> _independentClans=new(); public int Count=>_independentClans.Count; public void Add(TaleWorlds.CampaignSystem.Clan c)=>_independentClans[c]=default; }
 public class NPCEquipmentsCampaignBehavior {}
}
namespace TaleWorlds.CampaignSystem.GameComponents { public class DefaultMarriageModel { public float NpcCoupleMarriageChance(TaleWorlds.CampaignSystem.Hero a,TaleWorlds.CampaignSystem.Hero b)=>0.002f; } }
namespace BannerlordLink { public static class BannerlordLinkModule { public static int Logged; public static void Log(string m){ Logged++; } } }
namespace BannerlordLink.Util { public static class HeroNaming { public static bool IsAdopted(TaleWorlds.CampaignSystem.Hero h)=>h?.Name?.StartsWith("[BLink] ")==true; } }
namespace BannerlordLink.Behaviors { public class VassalAutoFollowBehavior { public static VassalAutoFollowBehavior Current=new(); public HashSet<TaleWorlds.CampaignSystem.Clan> Vassals=new(); public bool IsVassal(TaleWorlds.CampaignSystem.Clan c)=>Vassals.Contains(c); } }
class Program {
 static int failed, passed;
 static void Check(bool ok,string name){ Console.WriteLine((ok?"PASS ":"FAIL ")+name); if(ok)passed++; else failed++; }
 static MethodInfo M(string type,string name)=>Assembly.GetExecutingAssembly().GetType("BannerlordLink.Patches."+type)?.GetMethod(name,BindingFlags.Static|BindingFlags.Public);
 static int Main(){
  var viewer=new TaleWorlds.CampaignSystem.Hero{Name="[BLink] fikoos418"};
  var viewerClan=new TaleWorlds.CampaignSystem.Clan{Name="Месяц Луны",Leader=viewer}; viewerClan.Heroes.Add(viewer); viewer.Clan=viewerClan;
  var npc=new TaleWorlds.CampaignSystem.Hero{Name="Лорд"}; var npcClan=new TaleWorlds.CampaignSystem.Clan{Leader=npc}; npcClan.Heroes.Add(npc); npc.Clan=npcClan;
  var vassalLeader=new TaleWorlds.CampaignSystem.Hero{Name="Вассал"}; var vassalClan=new TaleWorlds.CampaignSystem.Clan{Leader=vassalLeader}; vassalLeader.Clan=vassalClan;
  BannerlordLink.Behaviors.VassalAutoFollowBehavior.Current.Vassals.Add(vassalClan);
  var member=new TaleWorlds.CampaignSystem.Hero{Name="[BLink] dssardg"}; var hostClan=new TaleWorlds.CampaignSystem.Clan{Name="Бану Сарран",Leader=new TaleWorlds.CampaignSystem.Hero{Name="Шейх"}};
  hostClan.Heroes.Add(hostClan.Leader); hostClan.Heroes.Add(member); member.Clan=hostClan;

  // 1. Роспуск клана через 28 дней
  var disc=M("ViewerClanDiscontinuationPatch","Prefix"); var fd=new TaleWorlds.CampaignSystem.CampaignBehaviors.FactionDiscontinuationCampaignBehavior();
  fd.Add(viewerClan); fd.Add(npcClan);
  Check(!(bool)disc.Invoke(null,new object[]{fd,viewerClan}) && fd.Count==1,"клан зрителя не распускается и снят с таймера");
  Check(!(bool)disc.Invoke(null,new object[]{fd,vassalClan}),"вассальный клан зрителя не распускается");
  Check(!(bool)disc.Invoke(null,new object[]{fd,hostClan}),"чужой клан, где состоит зритель, не распускается вместе с ним");
  Check((bool)disc.Invoke(null,new object[]{fd,npcClan}),"клан NPC распускается как раньше");
  // 2. Авто-женитьба
  var marry=M("ViewerNpcMarriagePatch","Postfix");
  float Chance(TaleWorlds.CampaignSystem.Hero a,TaleWorlds.CampaignSystem.Hero b){ var args=new object[]{a,b,0.002f}; marry.Invoke(null,args); return (float)args[2]; }
  Check(Chance(member,npc)==0f && Chance(npc,member)==0f,"игра не женит зрителя сама (с любой стороны)");
  var child=new TaleWorlds.CampaignSystem.Hero{Name="Сын",Clan=viewerClan};
  Check(Chance(child,npc)==0f,"не уводит ребёнка/наследника из клана зрителя");
  var npc2=new TaleWorlds.CampaignSystem.Hero{Name="Леди",Clan=new TaleWorlds.CampaignSystem.Clan()};
  Check(Math.Abs(Chance(npc,npc2)-0.002f)<1e-7,"NPC женятся как раньше");
  // 3. Переодевание правителя
  var eq=M("ViewerRulerEquipmentPatch","Prefix");
  bool Runs(TaleWorlds.CampaignSystem.Kingdom k,TaleWorlds.CampaignSystem.Clan old)=>(bool)eq.Invoke(null,new object[]{k,old});
  Check(!Runs(new TaleWorlds.CampaignSystem.Kingdom{Leader=viewer},npcClan),"новый правитель — зритель: не переодеваем");
  Check(!Runs(new TaleWorlds.CampaignSystem.Kingdom{Leader=npc},viewerClan),"старый правитель — зритель: не переодеваем");
  Check(Runs(new TaleWorlds.CampaignSystem.Kingdom{Leader=npc},npcClan),"смена власти между NPC — как раньше");
  Check(Runs(new TaleWorlds.CampaignSystem.Kingdom{Leader=npc},null),"без старого клана — как раньше");
  Console.WriteLine($"{passed} ok / {failed} FAIL"); return failed;
 }
}
