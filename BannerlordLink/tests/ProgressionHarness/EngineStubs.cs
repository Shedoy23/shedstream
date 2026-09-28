using System;
using System.Collections.Generic;
namespace TaleWorlds.Core {
 public class SkillObject { public string StringId; public string Name=>StringId; }
 public class CharacterAttribute { public string StringId; public string Name=>StringId; }
}
namespace TaleWorlds.ObjectSystem {
 public class MBObjectManager {
  public static MBObjectManager Instance=new MBObjectManager();
  public List<TaleWorlds.Core.SkillObject> Skills=new List<TaleWorlds.Core.SkillObject>();
  public List<TaleWorlds.Core.CharacterAttribute> Attributes=new List<TaleWorlds.Core.CharacterAttribute>();
  public List<T> GetObjectTypeList<T>() => typeof(T)==typeof(TaleWorlds.Core.SkillObject)?(List<T>)(object)Skills:(List<T>)(object)Attributes;
 }
}
namespace TaleWorlds.MountAndBlade { public class Mission { public static Mission Current; } }
namespace TaleWorlds.CampaignSystem {
 public class Campaign { public static Campaign Current=new Campaign(); public string UniqueGameId="save"; public Models Models=new Models(); }
 public class Models { public DevelopmentModel CharacterDevelopmentModel=new DevelopmentModel(); public GenericXpModel GenericXpModel=new GenericXpModel(); }
 public class DevelopmentModel { public int MaxFocusPerSkill=5,MaxAttribute=10; }
 public class GenericXpModel { public float Rate=1; public float GetXpMultiplier(Hero hero)=>Rate; }
 public class Hero { public string StringId="hero"; public bool IsAlive=true; public int Gold=100000; public Developer HeroDeveloper=new Developer(); public int AttributeValue=2; public int Level=100; public int GetAttributeValue(TaleWorlds.Core.CharacterAttribute a)=>AttributeValue; public int GetSkillValue(TaleWorlds.Core.SkillObject s) {if(HeroDeveloper.XpMutated&&HeroDeveloper.UnreadableXp)throw new Exception(); return Level;} }
 public class Developer {
  private int totalXp; public bool XpMutated,UnreadableXp,ReadableRaw; public int TotalXp { get {if(XpMutated&&UnreadableXp&&!ReadableRaw)throw new Exception(); return totalXp;} set {totalXp=value;} } public float SkillXp; public bool RawXpOnly; public float LastGrant; public int Focus=2; public float Rate=1; public bool NoOp,ThrowBefore,ThrowAfter,UnreadableAfter; private bool mutated; public Hero Owner;
  public float GetSkillXpProgress(TaleWorlds.Core.SkillObject s) {if(XpMutated&&UnreadableXp)throw new Exception();return SkillXp;}
  public void AddSkillXp(TaleWorlds.Core.SkillObject s,float xp,bool isAffectedByFocusFactor) { LastGrant=xp; if(ThrowBefore)throw new Exception(); if(!NoOp) {TotalXp+=(int)xp; if(!RawXpOnly)SkillXp+=xp;} XpMutated=true; if(ThrowAfter)throw new Exception(); }
  public void DevelopCharacterStats(){}
  public void SetInitialSkillLevel(TaleWorlds.Core.SkillObject s,int level){Owner.Level=level;}
  public int GetFocus(TaleWorlds.Core.SkillObject s) { if(mutated && UnreadableAfter)throw new Exception(); return Focus; }
  public float GetFocusFactor(TaleWorlds.Core.SkillObject s)=>Rate;
  public void AddFocus(TaleWorlds.Core.SkillObject s,int amount,bool checkUnspentFocusPoints) { if(ThrowBefore)throw new Exception(); if(!NoOp){Focus+=amount;mutated=true;} if(ThrowAfter)throw new Exception(); }
  public void AddAttribute(TaleWorlds.Core.CharacterAttribute a,int amount,bool checkUnspentPoints) { if(ThrowBefore)throw new Exception(); if(!NoOp)Owner.AttributeValue+=amount; if(ThrowAfter)throw new Exception(); }
 }
}
namespace TaleWorlds.CampaignSystem.Actions {
 public static class GiveGoldAction { public static bool NoOp,ThrowAfter; public static void ApplyBetweenCharacters(TaleWorlds.CampaignSystem.Hero from,TaleWorlds.CampaignSystem.Hero to,int amount,bool notify) { if(NoOp)return; if(from!=null)from.Gold-=amount; if(to!=null)to.Gold+=amount; if(ThrowAfter)throw new Exception(); } }
}
namespace BannerlordLink.Actions { public static class HeroLookup { public static TaleWorlds.CampaignSystem.Hero Hero; public static TaleWorlds.CampaignSystem.Hero FindByUsername(string name)=>Hero; } }
namespace BannerlordLink.Behaviors {
 public class EquipmentShopBehavior {
  public static EquipmentShopBehavior Instance=new EquipmentShopBehavior(); public string SessionId="session"; public int Pushes;
  public object Read(TaleWorlds.CampaignSystem.Hero h)=>null; public void Store(TaleWorlds.CampaignSystem.Hero h,object ledger){} public void Push(TaleWorlds.CampaignSystem.Hero h,object ledger){Pushes++;}
 }
}
namespace BannerlordLink { public static class BannerlordLinkModule { public static void Log(string text){} public static FakeBackend Backend=new FakeBackend(); } }
namespace BannerlordLink.Util {
 public static class HeroStateSync { public static void Push(TaleWorlds.CampaignSystem.Hero h){} }
 public static class ActionFeedback {
  public static string Failure; public static int Applied;
  public static string GetActionId(Newtonsoft.Json.Linq.JObject o)=>"action";
  public static void PostFailed(string id,string reason){Failure=reason;}
  public static void PostApplied(string id){Applied++;}
 }
 public static class HeroGoldCharge { public static bool NoOp,ReportFailure; public static int Calls; public static bool Refund(TaleWorlds.CampaignSystem.Hero h,int amount,string tag){Calls++;if(!NoOp)h.Gold+=amount;return !ReportFailure;} }
}

namespace BannerlordLink { public class FakeBackend { public System.Threading.Tasks.Task<bool> PostEventAsync(string game,string type,string json)=>System.Threading.Tasks.Task.FromResult(true); } }
namespace BannerlordLink.Net { public static class PowerCache { public static (string classKey,int level)? GetHeroClass(string user)=>null; } }
namespace BannerlordLink.Actions {
 public interface IActionHandler { string ActionType{get;} System.Threading.Tasks.Task<(bool success,string error)> ExecuteAsync(Newtonsoft.Json.Linq.JObject data); }
 public static class MainThreadDispatcher { public static void Enqueue(System.Action action)=>action(); }
}
