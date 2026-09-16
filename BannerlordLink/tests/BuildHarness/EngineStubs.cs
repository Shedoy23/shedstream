using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using BannerlordLink.Util;

namespace TaleWorlds.Core {
    public enum EquipmentIndex { Weapon0, Weapon1, Weapon2, Weapon3, Head, Body, Leg, Gloves, Cape, Horse, HorseHarness }
    public enum WeaponClass { Undefined, Arrow, Bolt, SmallShield, LargeShield, OneHandedSword }
    public class SkillObject { public string Id; public SkillObject(string id) { Id = id; } }
    public static class DefaultSkills {
        public static SkillObject OneHanded=new("OneHanded"), TwoHanded=new("TwoHanded"), Polearm=new("Polearm"), Bow=new("Bow"), Crossbow=new("Crossbow"), Throwing=new("Throwing");
    }
    public class WeaponComponentData { public SkillObject RelevantSkill; public WeaponClass WeaponClass,AmmoClass; }
    public class ItemObject { public string StringId, Name, Category; public int Tier, Value, Difficulty; public bool Sellable=true; public WeaponComponentData PrimaryWeapon; }
    public class ItemModifier { public string StringId; }
    public struct EquipmentElement {
        public ItemObject Item; public ItemModifier ItemModifier;
        public EquipmentElement(ItemObject item, ItemModifier modifier=null) { Item=item; ItemModifier=modifier; }
        public bool IsEmpty=>Item==null; public static EquipmentElement Invalid=>default;
    }
    public class Equipment {
        readonly Dictionary<EquipmentIndex,EquipmentElement> entries=new();
        public Equipment() { } public Equipment(Equipment other) { foreach(var kv in other.entries) entries[kv.Key]=kv.Value; }
        public EquipmentElement this[EquipmentIndex i] { get=>entries.TryGetValue(i,out var e)?e:default; set=>entries[i]=value; }
    }
}
namespace TaleWorlds.CampaignSystem {
    public class Hero {
        public string Name="alice",StringId="hero1"; public bool IsAlive=true,IsPrisoner;
        public TaleWorlds.Core.Equipment BattleEquipment=new();
        public Dictionary<string,int> Skills=new();
        public int GetSkillValue(TaleWorlds.Core.SkillObject skill)=>Skills.TryGetValue(skill.Id,out int v)?v:25;
    }
    public class Campaign { public static Campaign Current=new(); public string UniqueGameId="save1"; }
}
namespace TaleWorlds.MountAndBlade {
    public class Mission { public static Mission Current; }
    public enum FormationClass { Infantry,Ranged,Cavalry,HorseArcher }
    public struct MissionWeapon { public TaleWorlds.Core.ItemObject Item; public TaleWorlds.Core.WeaponComponentData CurrentUsageItem; public bool IsEmpty=>Item==null; }
    public class Agent { public MissionWeapon WieldedWeapon,WieldedOffhandWeapon; public bool Active=true; public bool IsActive()=>Active; }
}
namespace TaleWorlds.ObjectSystem {
    public class MBObjectManager {
        public static MBObjectManager Instance=new(); public Dictionary<string,object> Objects=new();
        public IEnumerable<T> GetObjectTypeList<T>()=>Objects.Values.OfType<T>();
        public T GetObject<T>(string id) where T:class=>Objects.TryGetValue(id,out var item)?item as T:null;
    }
}
namespace BannerlordLink {
    public static class MainThreadDispatcher { public static void Enqueue(Action action)=>action(); }
    public static class BannerlordLinkModule { public static void Log(string message) { } }
}
namespace BannerlordLink.Actions {
    public interface IActionHandler { string ActionType {get;} Task<(bool success,string error)> ExecuteAsync(JObject data); }
    public static class HeroLookup { public static TaleWorlds.CampaignSystem.Hero Hero; public static TaleWorlds.CampaignSystem.Hero FindByUsername(string user)=>user=="alice"?Hero:null; }
}
namespace BannerlordLink.Net { public class BackendClient { public Task<string> GetAsync(string url)=>Task.FromResult<string>(null); } }
namespace BannerlordLink.Util {
    public static class HeroNaming { public static string ExtractUsername(string name)=>name; }
    public static class ActionFeedback {
        public static bool Applied; public static string Error;
        public static void PostFailed(string id,string error) { Applied=false; Error=error; }
        public static void PostApplied(string id) { Applied=true; Error=null; }
        public static string GetActionId(JObject data)=>"test";
    }
    public static class EquipmentSync {
        public static TaleWorlds.Core.EquipmentIndex? SlotFromName(string slot)=>Enum.TryParse<TaleWorlds.Core.EquipmentIndex>(slot,true,out var e)?e:null;
        public static void PushAll(TaleWorlds.CampaignSystem.Hero hero) { }
    }
    public static class HeroStateSync { public static void Push(TaleWorlds.CampaignSystem.Hero hero) { } }
}
namespace BannerlordLink.Behaviors {
    public class EquipmentShopBehavior {
        public static EquipmentShopBehavior Instance=new(); public string SessionId="session1";
        internal EquipmentLedger Saved=new(); public bool StoreFails,PushFails;
        public static string[] AllSlots={"weapon0","weapon1","weapon2","weapon3","head","body","leg","gloves","cape","horse","horseharness"};
        internal EquipmentLedger Read(TaleWorlds.CampaignSystem.Hero hero) {
            var copy=JsonConvert.DeserializeObject<EquipmentLedger>(JsonConvert.SerializeObject(Saved));
            foreach(var slot in AllSlots) { var e=hero.BattleEquipment[EquipmentSync.SlotFromName(slot).Value]; copy.Observe(slot,e.Item?.StringId,e.ItemModifier?.StringId); }
            return copy;
        }
        internal void Store(TaleWorlds.CampaignSystem.Hero hero,EquipmentLedger ledger) { if(StoreFails)throw new Exception("store");Saved=JsonConvert.DeserializeObject<EquipmentLedger>(JsonConvert.SerializeObject(ledger)); }
        internal HeroBuildState GetBuild(string username)=>username=="alice"?Saved.Build:null;
        internal void Push(TaleWorlds.CampaignSystem.Hero hero,EquipmentLedger ledger) { if(PushFails)throw new Exception("network"); }
        internal static bool Sellable(TaleWorlds.Core.ItemObject item)=>item.Sellable;
        internal static string Category(TaleWorlds.Core.ItemObject item)=>item.Category;
    }
}
