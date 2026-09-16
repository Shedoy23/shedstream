using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using BannerlordLink.Util;

namespace TaleWorlds.Core
{
    public enum EquipmentIndex { Weapon0, Weapon1, Weapon2, Weapon3, Head, Body, Leg, Gloves, Cape, Horse, HorseHarness }
    public class ItemObject { public string StringId; public int Tier; public int Value; public string Slot = "body"; public bool Available = true; }
    public class ItemModifier { public string StringId; }
    public struct EquipmentElement
    {
        public ItemObject Item; public ItemModifier ItemModifier;
        public EquipmentElement(ItemObject item, ItemModifier modifier = null) { Item = item; ItemModifier = modifier; }
        public bool IsEmpty => Item == null;
        public static EquipmentElement Invalid => default;
    }
    public class Equipment
    {
        readonly Dictionary<EquipmentIndex, EquipmentElement> entries = new();
        public Equipment() { }
        public Equipment(Equipment other) { foreach (var x in other.entries) entries[x.Key] = x.Value; }
        public EquipmentElement this[EquipmentIndex index] { get => entries.TryGetValue(index, out var e) ? e : default; set => entries[index] = value; }
    }
}
namespace TaleWorlds.CampaignSystem
{
    public class Hero { public string StringId = "hero1"; public string Name = "alice"; public bool IsAlive = true; public int Level = 25; public int Gold = 1000; public TaleWorlds.Core.Equipment BattleEquipment = new(); }
    public class Campaign { public static Campaign Current = new(); public string UniqueGameId = "save1"; }
}
namespace TaleWorlds.CampaignSystem.Actions
{
    public static class GiveGoldAction
    {
        public static void ApplyBetweenCharacters(TaleWorlds.CampaignSystem.Hero from, TaleWorlds.CampaignSystem.Hero to, int amount, bool notification)
        { if (from != null) from.Gold -= amount; if (to != null) to.Gold += amount; }
    }
}
namespace TaleWorlds.MountAndBlade { public class Mission { public static Mission Current; } }
namespace TaleWorlds.ObjectSystem
{
    public class MBObjectManager
    {
        public static MBObjectManager Instance = new(); public Dictionary<string, object> Objects = new();
        public T GetObject<T>(string id) where T : class => Objects.TryGetValue(id, out var value) ? value as T : null;
    }
}
namespace BannerlordLink
{
    public static class BannerlordLinkModule { public static void Log(string text) { } }
    public static class MainThreadDispatcher { public static void Enqueue(Action action) => action(); }
}
namespace BannerlordLink.Actions { public interface IActionHandler { string ActionType { get; } Task<(bool success, string error)> ExecuteAsync(JObject data); } }
namespace BannerlordLink.Util
{
    public static class HeroLookup { public static TaleWorlds.CampaignSystem.Hero Hero; public static TaleWorlds.CampaignSystem.Hero FindByUsername(string username) => username == "alice" ? Hero : null; }
    public static class ActionFeedback
    {
        public static bool Applied; public static string Error;
        public static void PostFailed(string id, string error) { Error = error; Applied = false; }
        public static void PostApplied(string id) { Applied = true; Error = null; }
        public static string GetActionId(JObject data) => "test-action";
    }
    public static class EquipmentSync
    {
        public static TaleWorlds.Core.EquipmentIndex? SlotFromName(string slot)
        { return Enum.TryParse<TaleWorlds.Core.EquipmentIndex>(slot, true, out var value) && Enum.IsDefined(value) ? value : null; }
        public static void PushAll(TaleWorlds.CampaignSystem.Hero hero) { }
    }
    public static class HeroStateSync { public static void Push(TaleWorlds.CampaignSystem.Hero hero) { } }
}
namespace BannerlordLink.Behaviors
{
    public class EquipmentShopBehavior
    {
        public static EquipmentShopBehavior Instance = new();
        internal string SessionId { get; } = Guid.NewGuid().ToString("N");
        internal EquipmentLedger Saved = new(); public bool StoreFails; public bool PushFails;
        public static string[] AllSlots = { "weapon0", "weapon1", "weapon2", "weapon3", "head", "body", "leg", "gloves", "cape", "horse", "horseharness" };
        internal EquipmentLedger Read(TaleWorlds.CampaignSystem.Hero hero)
        {
            var ledger = Newtonsoft.Json.JsonConvert.DeserializeObject<EquipmentLedger>(Newtonsoft.Json.JsonConvert.SerializeObject(Saved));
            foreach (string slot in AllSlots) { var e = hero.BattleEquipment[EquipmentSync.SlotFromName(slot).Value]; ledger.Observe(slot, e.Item?.StringId, e.ItemModifier?.StringId); }
            return ledger;
        }
        internal void Store(TaleWorlds.CampaignSystem.Hero hero, EquipmentLedger ledger) { if (StoreFails) throw new Exception("disk"); Saved = ledger; }
        public static bool Sellable(TaleWorlds.Core.ItemObject item) => item?.Available == true;
        public static string[] Slots(TaleWorlds.Core.ItemObject item) => new[] { item.Slot };
        public static bool MountCompatible(TaleWorlds.CampaignSystem.Hero hero, TaleWorlds.Core.ItemObject item, string slot) => true;
        internal void Push(TaleWorlds.CampaignSystem.Hero hero, EquipmentLedger ledger) { if (PushFails) throw new Exception("network"); }
    }
}
