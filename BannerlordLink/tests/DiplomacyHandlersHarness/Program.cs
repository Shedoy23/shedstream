using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using BannerlordLink.Actions;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
class Program {
 static int Main() {
  var hero=HeroLookup.Hero=new Hero(); var ours=new Kingdom {StringId="ours",Leader=hero}; var enemy=new Kingdom {StringId="enemy",Name="Enemy"}; hero.Clan=new Clan {Kingdom=ours,Leader=hero}; Kingdom.All.Add(enemy); ours.AtWar=true;
  new MakePeaceHandler().ExecuteAsync(new JObject{["initiated_by"]="alice",["target_kingdom_id"]="enemy"}).GetAwaiter().GetResult();
  if(ours.AtWar || !ActionFeedback.Applied) {Console.WriteLine("FAIL direct peace cannot resolve campaign kingdom absent from object registry");return 1;}
  ours.IsEliminated=true; ActionFeedback.Applied=false;
  new EnactPolicyHandler().ExecuteAsync(new JObject{["initiated_by"]="alice",["kingdom_id"]="ours",["policy_id"]="p"}).GetAwaiter().GetResult();
  if(ours.Policy || ActionFeedback.Applied) {Console.WriteLine("FAIL eliminated kingdom policy applied");return 1;}
  ours.IsEliminated=false; ActionFeedback.Applied=false;
  new EnactPolicyHandler().ExecuteAsync(new JObject{["initiated_by"]="alice",["kingdom_id"]="old",["policy_id"]="p"}).GetAwaiter().GetResult();
  if(ours.Policy || ActionFeedback.Applied) {Console.WriteLine("FAIL stale kingdom request affected current kingdom");return 1;}
  Console.WriteLine("PASS direct peace, eliminated kingdom, stale membership");return 0;
 }
}
namespace TaleWorlds.CampaignSystem {
 public class Campaign {public static Campaign Current=new();}
 public class Clan {public Kingdom Kingdom;public Hero Leader;public bool IsEliminated;}
 public class Hero {public bool IsAlive=true; public Clan Clan;}
 public class PolicyObject {}
 public class Kingdom {public static List<Kingdom> All=new(); public string StringId,Name;public Hero Leader;public bool IsEliminated,AtWar,Policy; public bool IsAtWarWith(Kingdom k)=>AtWar;public bool HasPolicy(PolicyObject p)=>Policy;public void AddPolicy(PolicyObject p)=>Policy=true;public void RemovePolicy(PolicyObject p)=>Policy=false;}
}
namespace TaleWorlds.CampaignSystem.Actions { public static class MakePeaceAction {public static void Apply(Kingdom a,Kingdom b)=>a.AtWar=false;public static void ApplyByKingdomDecision(Kingdom a,Kingdom b,int tribute,int duration)=>Apply(a,b);} }
namespace TaleWorlds.ObjectSystem { public class MBObjectManager {public static MBObjectManager Instance=new();public T GetObject<T>(string id) where T:class => typeof(T)==typeof(PolicyObject)?new PolicyObject() as T:null;} }
namespace BannerlordLink {public static class BannerlordLinkModule {public static void Log(string text) {}}public static class MainThreadDispatcher {public static void Enqueue(Action action)=>action();} }
namespace BannerlordLink.Actions { public interface IActionHandler { string ActionType{get;}Task<(bool success,string error)> ExecuteAsync(JObject data); } public static class HeroLookup {public static Hero Hero;public static Hero FindByUsername(string name)=>Hero;} }
namespace BannerlordLink.Util {public static class ActionFeedback {public static bool Applied;public static string GetActionId(JObject data)=>"action";public static void PostFailed(string id,string why)=>Applied=false;public static void PostApplied(string id)=>Applied=true;public static void PostPolicyResult(string id,string policy,bool enacted) {}}}
