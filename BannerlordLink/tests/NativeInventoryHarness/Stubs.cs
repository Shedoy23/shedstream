using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
namespace TaleWorlds.Core {
 public enum EquipmentIndex { Weapon0, Weapon1, Weapon2, Weapon3, Head, Body, Leg, Gloves, Cape, Horse, HorseHarness }
 public class ItemObject {
  public enum ItemTypeEnum { OneHandedWeapon, TwoHandedWeapon, Polearm, Bow, Crossbow, Thrown, Shield, Arrows, Bolts, HeadArmor, BodyArmor, LegArmor, HandArmor, Cape, Horse, HorseHarness, Goods }
  public string StringId, Name; public int Tier, Value; public float Weight; public bool NotMerchandise;
  public ItemTypeEnum ItemType; public HorseComponent HorseComponent; public ArmorComponent ArmorComponent;
 }
 public class HorseComponent { public bool IsRideable, IsPackAnimal; public Monster Monster; }
 public class Monster { public int FamilyType; }
 public class ArmorComponent { public int FamilyType; }
 public class ItemModifier { public string StringId; }
 public struct EquipmentElement {
  public ItemObject Item; public ItemModifier ItemModifier;
  public EquipmentElement(ItemObject item, ItemModifier modifier=null) { Item=item; ItemModifier=modifier; }
  public bool IsEmpty => Item==null; public static EquipmentElement Invalid => default;
  public int ItemValue => Item?.Value ?? 0;
 }
 public class Equipment {
  readonly Dictionary<EquipmentIndex,EquipmentElement> rows=new();
  public Equipment() {} public Equipment(Equipment other) { foreach(var x in other.rows) rows[x.Key]=x.Value; }
  public EquipmentElement this[EquipmentIndex i] { get=>rows.GetValueOrDefault(i); set=>rows[i]=value; }
 }
}
namespace TaleWorlds.CampaignSystem.Roster {
 public class ItemRoster {
  public struct Row { public TaleWorlds.Core.EquipmentElement EquipmentElement; public int Amount; }
  readonly List<Row> rows=new(); public int Count=>rows.Count;
  public Row GetElementCopyAtIndex(int i)=>rows[i];
  public int FindIndexOfElement(TaleWorlds.Core.EquipmentElement e)=>rows.FindIndex(x=>x.EquipmentElement.Item==e.Item && x.EquipmentElement.ItemModifier==e.ItemModifier && x.Amount>0);
  public int AddToCounts(TaleWorlds.Core.EquipmentElement e,int amount) {
   int i=FindIndexOfElement(e); if(i<0) { if(amount>0) rows.Add(new Row{EquipmentElement=e,Amount=amount}); return amount; }
   var r=rows[i]; r.Amount+=amount; if(r.Amount<=0) rows.RemoveAt(i); else rows[i]=r; return r.Amount;
  }
 }
}
namespace TaleWorlds.CampaignSystem {
 public class Party { public string StringId="party1",Name="Party"; public Roster.ItemRoster ItemRoster=new(); }
 public class Hero { public string StringId="hero1",Name="[BLink] alice"; public bool IsAlive=true,IsPrisoner; public int Level=30,Gold=10000; public Party PartyBelongedTo,PartyBelongedToAsPrisoner; public TaleWorlds.Core.Equipment BattleEquipment=new(); }
 public class Campaign { public static Campaign Current=new(); public string UniqueGameId="save1"; public List<Hero> AliveHeroes=new(); }
 public abstract class CampaignBehaviorBase { public abstract void RegisterEvents(); public abstract void SyncData(IDataStore store); }
 public interface IDataStore { void SyncData<T>(string key,ref T value); }
 public class TickEvent { public void AddNonSerializedListener(object owner,Action<float> tick) {} }
 public static class CampaignEvents { public static TickEvent TickEvent=new(); }
}
namespace TaleWorlds.CampaignSystem.Actions {
 public static class GiveGoldAction { public static void ApplyBetweenCharacters(TaleWorlds.CampaignSystem.Hero from,TaleWorlds.CampaignSystem.Hero to,int amount,bool notification) { if(from!=null) from.Gold-=amount; if(to!=null) to.Gold+=amount; } }
}
namespace TaleWorlds.MountAndBlade { public class Mission { public static Mission Current; } }
namespace TaleWorlds.ObjectSystem {
 public class MBObjectManager {
  public static MBObjectManager Instance=new(); public Dictionary<string,object> Objects=new();
  public T GetObject<T>(string id) where T:class=>Objects.GetValueOrDefault(id) as T;
  public List<T> GetObjectTypeList<T>()=>Objects.Values.OfType<T>().ToList();
 }
}
namespace BannerlordLink {
 public class BackendStub { public Task<bool> PostEventAsync(string module,string type,string json,long timestamp=0)=>Task.FromResult(true); }
 public static class BannerlordLinkModule { public static BackendStub Backend; public static void Log(string message) {} }
 public static class MainThreadDispatcher { public static void Enqueue(Action action)=>action(); }
}
namespace BannerlordLink.Actions {
 public interface IActionHandler { string ActionType {get;} Task<(bool success,string error)> ExecuteAsync(JObject data); }
 public static class HeroLookup { public static TaleWorlds.CampaignSystem.Hero Hero; public static TaleWorlds.CampaignSystem.Hero FindByUsername(string name)=>Hero; }
}
namespace BannerlordLink.Util {
 public class HeroBuildState {}
 public static class HeroBuildRuntime { public static JObject Snapshot(TaleWorlds.CampaignSystem.Hero hero,HeroBuildState state,bool? missionOverride=null)=>null; }
 public static class HeroNaming {
  public static bool IsAdopted(string name)=>name?.StartsWith("[BLink] ")==true;
  public static string ExtractUsername(string name)=>IsAdopted(name)?name.Substring(8).ToLowerInvariant():null;
 }
 public static class EquipmentSync {
  public static TaleWorlds.Core.EquipmentIndex? SlotFromName(string slot)=>Enum.TryParse<TaleWorlds.Core.EquipmentIndex>(slot,true,out var i)?i:null;
  public static string BuildStatsJson(TaleWorlds.Core.ItemObject item,TaleWorlds.Core.ItemModifier modifier)=>"{}";
  public static void PushAll(TaleWorlds.CampaignSystem.Hero hero) {}
 }
 public static class HeroStateSync { public static void Push(TaleWorlds.CampaignSystem.Hero hero) {} }
 public static class ActionFeedback {
  public static string Error; public static bool Applied;
  public static string GetActionId(JObject data)=>"action";
  public static void PostFailed(string id,string error) { Error=error; Applied=false; }
  public static void PostApplied(string id) { Error=null; Applied=true; }
 }
}
namespace BannerlordLink.Behaviors {
 public class HeroIdentityBehavior { public static HeroIdentityBehavior Instance=new(); public Dictionary<string,string> Users=new(); public string GetUsername(TaleWorlds.CampaignSystem.Hero hero)=>Users.GetValueOrDefault(hero.StringId); }
}
