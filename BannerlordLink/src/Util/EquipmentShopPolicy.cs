using System;
using System.Collections.Generic;
using System.Linq;

namespace BannerlordLink.Util
{
    internal static class EquipmentShopPolicy
    {
        internal static int PublicTier(int nativeTier) => Math.Max(1, Math.Min(6, nativeTier + 1));
        internal static int RequiredLevel(int publicTier)
        {
            switch (publicTier)
            {
                case 1: return 1;
                case 2: return 10;
                case 3: return 15;
                case 4: return 25;
                case 5: return 30;
                case 6: return 35;
                default: throw new ArgumentOutOfRangeException(nameof(publicTier));
            }
        }
        internal const int PriceMultiplier = 10;
        /// <summary>Мест в личном сундуке героя без своего отряда (владелец 25.09):
        /// бездонный бесплатный склад обесценил бы клан с обозом.</summary>
        internal const int StashCapacity = 10;
        internal static int Price(int itemValue)
            => (int)Math.Min(int.MaxValue, Math.Max(1L, (long)itemValue) * PriceMultiplier);
    }

    internal sealed class OwnedEquipment
    {
        public string OwnedId;
        public string ItemId;
        public string ModifierId;
        public string Slot;
    }

    // Engine-independent ownership ledger. Slots describe equipped instances;
    // every displaced item remains owned, including its exact modifier.
    internal sealed class EquipmentLedger
    {
        public HeroBuildState Build;
        public List<OwnedEquipment> Items = new List<OwnedEquipment>();
        public long Revision = 0;

        public OwnedEquipment Add(string itemId, string modifierId = null)
        {
            var row = new OwnedEquipment { OwnedId = Guid.NewGuid().ToString("N"),
                ItemId = itemId, ModifierId = modifierId };
            Items.Add(row);
            return row;
        }

        public void Observe(string slot, string itemId, string modifierId, bool previousContentAvailable = true)
        {
            var previous = Items.FirstOrDefault(x => x.Slot == slot);
            if (previous != null && !previousContentAvailable)
            {
                // Unloaded mod content is not a voluntary discard. Preserve its
                // identity and quality in storage, unavailable until restored.
                previous.Slot = null;
                previous = null;
            }
            if (previous != null && previous.ItemId == itemId && previous.ModifierId == modifierId) return;
            // External game mutations are authoritative: discard destroys an
            // instance, reforging modifies that instance. Only explicit shop
            // Equip/Unequip operations preserve displaced gear in storage.
            if (previous != null && previous.ItemId == itemId)
            {
                previous.ModifierId = modifierId;
                return;
            }
            if (previous != null) Items.Remove(previous);
            if (itemId != null) Add(itemId, modifierId).Slot = slot;
        }

        /// <summary>Личный сундук героя — вещи в учёте без слота (бывшее «старое
        /// хранилище»). Метод, а не свойство: учёт сериализуется в сейв.</summary>
        public int StashCount() => Items.Count(x => x.Slot == null);

        public void Equip(OwnedEquipment row, string slot)
        {
            foreach (var old in Items.Where(x => x.Slot == slot)) old.Slot = null;
            row.Slot = slot;
        }

        public void Unequip(string slot)
        {
            foreach (var row in Items.Where(x => x.Slot == slot)) row.Slot = null;
        }
    }
}
