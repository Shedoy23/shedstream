using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using BannerlordLink.Actions;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;

// 24.09, багрепорт #62: «выйдя из мёртвого клана могу влиять на политику».
// EnactPolicy/MakePeace отказывают уничтоженному клану/королевству, а
// ProposeWar/ProposePeace — нет. Тест берёт НАСТОЯЩИЕ обработчики из исходника.
class Program {
 static int failed;
 static void Check(bool ok,string t){Console.WriteLine((ok?"ok   ":"FAIL ")+t);if(!ok)failed++;}
 static int Main() {
  foreach (var (clanDead, kingdomDead, war) in new[]{(true,false,true),(false,true,true),(true,false,false),(false,true,false),(false,false,true),(false,false,false)}) {
   var hero=HeroLookup.Hero=new Hero(); var ours=new Kingdom{StringId="ours",Name="Ours",IsEliminated=kingdomDead,AtWar=!war};
   var enemy=new Kingdom{StringId="enemy",Name="Enemy"}; Kingdom.All.Clear(); Kingdom.All.Add(ours); Kingdom.All.Add(enemy);
   hero.Clan=new Clan{Kingdom=ours,Leader=hero,IsEliminated=clanDead};
   ActionFeedback.Applied=false; ActionFeedback.Why=null;
   var data=new JObject{["initiated_by"]="alice",["target_kingdom_id"]="enemy"};
   if (war) new ProposeWarHandler().ExecuteAsync(data).GetAwaiter().GetResult();
   else new ProposePeaceHandler().ExecuteAsync(data).GetAwaiter().GetResult();
   bool shouldPass = !clanDead && !kingdomDead;
   Check(ActionFeedback.Applied==shouldPass && ours.Decisions==(shouldPass?1:0),
    (war?"война":"мир")+": клан уничтожен="+clanDead+", королевство уничтожено="+kingdomDead+" → подано="+ActionFeedback.Applied+" ("+ActionFeedback.Why+")");
  }
  return failed;
 }
}
namespace TaleWorlds.CampaignSystem {
 public class Campaign {public static Campaign Current=new();}
 public interface IFaction {}
 public class Clan {public static Clan PlayerClan; public Kingdom Kingdom;public Hero Leader;public bool IsEliminated;}
 public class Hero {public bool IsAlive=true; public Clan Clan;}
 public class Kingdom : IFaction {public static List<Kingdom> All=new(); public string StringId,Name;public bool IsEliminated,AtWar; public int Decisions;
  public List<Election.KingdomDecision> UnresolvedDecisions=new(); public bool IsAtWarWith(IFaction k)=>AtWar;
  public void AddDecision(Election.KingdomDecision d,bool ignoreInfluenceCost=false){Decisions++;UnresolvedDecisions.Add(d);} }
}
namespace TaleWorlds.CampaignSystem.Election {
 public class KingdomDecision {public bool ShouldBeCancelled()=>false;}
 public class DeclareWarDecision : KingdomDecision {public IFaction FactionToDeclareWarOn;}
 public class MakePeaceKingdomDecision : KingdomDecision {public IFaction FactionToMakePeaceWith;}
}
namespace BannerlordLink.Actions {
 public interface IActionHandler { string ActionType{get;}Task<(bool success,string error)> ExecuteAsync(JObject data); }
 public static class HeroLookup {public static Hero Hero;public static Hero FindByUsername(string name)=>Hero;}
 internal sealed class ViewerDeclareWarDecision : TaleWorlds.CampaignSystem.Election.DeclareWarDecision { public ViewerDeclareWarDecision(Clan c, IFaction t){FactionToDeclareWarOn=t;} }
 internal sealed class ViewerMakePeaceDecision : TaleWorlds.CampaignSystem.Election.MakePeaceKingdomDecision { public ViewerMakePeaceDecision(Clan c, IFaction t){FactionToMakePeaceWith=t;} }
}
namespace TaleWorlds.ObjectSystem { public class MBObjectManager {public static MBObjectManager Instance=new();public T GetObject<T>(string id) where T:class => null;} }
namespace BannerlordLink {public static class BannerlordLinkModule {public static void Log(string text) {}}public static class MainThreadDispatcher {public static void Enqueue(Action action)=>action();} }
namespace BannerlordLink.Util {public static class ActionFeedback {public static bool Applied;public static string Why;public static string GetActionId(JObject data)=>"action";public static void PostFailed(string id,string why){Applied=false;Why=why;}public static void PostApplied(string id)=>Applied=true;}}
