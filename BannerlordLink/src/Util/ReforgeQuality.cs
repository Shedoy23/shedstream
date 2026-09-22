using System;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
namespace BannerlordLink.Util
{
    internal static class ReforgeQuality
    {
        private static readonly ItemQuality[] Levels = { ItemQuality.Fine, ItemQuality.Masterwork, ItemQuality.Legendary };
        internal static int Rank(ItemModifier modifier) => modifier == null ? 0 : Math.Max(0, Array.IndexOf(Levels, modifier.ItemQuality) + 1);
        internal static JArray Options(ItemObject item)
        {
            var rows = new JArray();
            var group = item.ItemComponent?.ItemModifierGroup;
            if (group == null) return rows;
            for (int i = 0; i < Levels.Length; i++)
            {
                var mods = group.GetModifiersBasedOnQuality(Levels[i]);
                if (mods != null && mods.Count > 0)
                    rows.Add(new JObject { ["rank"] = i + 1, ["modifier_id"] = mods[0].StringId });
            }
            return rows;
        }
        internal static ItemModifier Resolve(ItemObject item, string modifierId)
        {
            var group = item?.ItemComponent?.ItemModifierGroup;
            if (group == null) return null;
            foreach (var quality in Levels)
            {
                var mods = group.GetModifiersBasedOnQuality(quality);
                if (mods != null) foreach (var mod in mods) if (mod.StringId == modifierId) return mod;
            }
            return null;
        }
        internal static bool Restore(Hero hero, JObject right, string saveId, string username)
        {
            if (Campaign.Current == null || Campaign.Current.UniqueGameId != saveId || Mission.Current != null
                || hero == null || !hero.IsAlive || hero.StringId != (string)right["hero_id"]
                || !string.Equals(username, (string)right["username"], StringComparison.OrdinalIgnoreCase)) return false;
            var slot = EquipmentSync.SlotFromName((string)right["slot"]);
            if (!slot.HasValue) return false;
            var current = hero.BattleEquipment[slot.Value];
            if (current.Item == null || current.Item.StringId != (string)right["item_id"]) return false;
            var modifier = Resolve(current.Item, (string)right["modifier_id"]);
            if (modifier == null || Rank(modifier) != (int?)right["rank"] || Rank(current.ItemModifier) >= Rank(modifier)) return false;
            hero.BattleEquipment[slot.Value] = new EquipmentElement(current.Item, modifier);
            return hero.BattleEquipment[slot.Value].ItemModifier == modifier;
        }
    }
}
