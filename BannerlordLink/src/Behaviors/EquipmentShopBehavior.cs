using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Roster;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Behaviors
{
    // Ownership follows the campaign save AND hero identity, never the backend
    // username cache. Native gear is imported before every inventory operation.
    public sealed class EquipmentShopBehavior : CampaignBehaviorBase
    {
        public static EquipmentShopBehavior Instance { get; private set; }
        // Runtime nonce intentionally excluded from SyncData: an older save
        // with the same UniqueGameId must not accept actions from before load.
        internal string SessionId { get; } = Guid.NewGuid().ToString("N");
        private Dictionary<string, string> _ledgers = new Dictionary<string, string>();
        private readonly Dictionary<string, HeroBuildState> _builds = new Dictionary<string, HeroBuildState>(StringComparer.OrdinalIgnoreCase);
        private readonly Stopwatch _refresh = Stopwatch.StartNew();
        private readonly Stopwatch _catalogRefresh = Stopwatch.StartNew();
        private volatile bool _published;
        private volatile bool _publishing;
        private EquipmentSessionHandshake _handshake;
        private readonly InventorySnapshotPublisher _snapshots = new InventorySnapshotPublisher();
        internal static readonly string[] AllSlots = { "weapon0", "weapon1", "weapon2", "weapon3", "head", "body", "leg", "gloves", "cape", "horse", "horseharness" };

        internal static ItemRoster PartyInventory(Hero hero)
            => hero == null || hero.IsPrisoner ? null : hero.PartyBelongedTo?.ItemRoster;

        private static string Username(Hero hero)
            => HeroIdentityBehavior.Instance?.GetUsername(hero)
                ?? HeroNaming.ExtractUsername(hero?.Name?.ToString());

        internal static string PartyOwnedId(ItemObject item, ItemModifier modifier)
            => "party|" + item.StringId + "|" + (modifier?.StringId ?? "");

        public override void RegisterEvents()
        {
            Instance = this;
            CampaignEvents.TickEvent.AddNonSerializedListener(this, Tick);
        }

        public override void SyncData(IDataStore store)
        {
            store.SyncData("BannerlordLink_EquipmentInventory_v1", ref _ledgers);
            _builds.Clear();
            if (_ledgers == null) _ledgers = new Dictionary<string, string>();
        }

        internal void BeginSession(string json)
        {
            if (_handshake != null) return;
            _handshake = new EquipmentSessionHandshake(json, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            var backend = BannerlordLinkModule.Backend;
            if (backend != null) Task.Run(async () => {
                try { await _handshake.EnsureAsync((payload, timestamp) => backend.PostEventAsync("bannerlord", "module.session_start", payload, timestamp)); }
                catch (Exception ex) { BannerlordLinkModule.Log("[EquipmentShop] session handshake will retry: " + ex.Message); }
            });
        }

        internal EquipmentLedger Read(Hero hero)
        {
            EquipmentLedger ledger = _ledgers.TryGetValue(hero.StringId, out string json)
                ? JsonConvert.DeserializeObject<EquipmentLedger>(json) : new EquipmentLedger();
            if (ledger?.Items == null) throw new InvalidOperationException("inventory_corrupt");
            foreach (string slot in AllSlots)
            {
                var element = hero.BattleEquipment[EquipmentSync.SlotFromName(slot).Value];
                var previous = ledger.Items.FirstOrDefault(x => x.Slot == slot);
                bool previousContentAvailable = previous == null
                    || (MBObjectManager.Instance.GetObject<ItemObject>(previous.ItemId) != null
                        && (string.IsNullOrEmpty(previous.ModifierId)
                            || MBObjectManager.Instance.GetObject<ItemModifier>(previous.ModifierId) != null));
                ledger.Observe(slot, element.Item?.StringId, element.ItemModifier?.StringId, previousContentAvailable);
            }
            return ledger;
        }

        internal void Store(Hero hero, EquipmentLedger ledger)
        {
            _ledgers[hero.StringId] = JsonConvert.SerializeObject(ledger);
            var username = Username(hero);
            if (!string.IsNullOrEmpty(username)) _builds[username] = ledger.Build;
        }

        internal HeroBuildState GetBuild(string username)
        {
            if (string.IsNullOrEmpty(username)) return null;
            if (_builds.TryGetValue(username, out var state)) return state;
            var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
            if (hero == null) return null;
            state = _ledgers.TryGetValue(hero.StringId, out var json)
                ? JsonConvert.DeserializeObject<EquipmentLedger>(json)?.Build : null;
            _builds[username] = state;
            return state;
        }

        internal void InitializeBuild(Hero hero)
        {
            var ledger = Read(hero);
            ledger.Build = new HeroBuildState();
            Store(hero, ledger);
        }

        internal static string Category(ItemObject item)
        {
            switch (item.ItemType)
            {
                case ItemObject.ItemTypeEnum.OneHandedWeapon: return "one_handed";
                case ItemObject.ItemTypeEnum.TwoHandedWeapon: return "two_handed";
                case ItemObject.ItemTypeEnum.Polearm: return "polearm";
                case ItemObject.ItemTypeEnum.Bow: return "bow";
                case ItemObject.ItemTypeEnum.Crossbow: return "crossbow";
                case ItemObject.ItemTypeEnum.Thrown: return "thrown";
                case ItemObject.ItemTypeEnum.Shield: return "shield";
                case ItemObject.ItemTypeEnum.Arrows: return "arrows";
                case ItemObject.ItemTypeEnum.Bolts: return "bolts";
                case ItemObject.ItemTypeEnum.HeadArmor: return "head";
                case ItemObject.ItemTypeEnum.BodyArmor: return "body";
                case ItemObject.ItemTypeEnum.LegArmor: return "leg";
                case ItemObject.ItemTypeEnum.HandArmor: return "gloves";
                case ItemObject.ItemTypeEnum.Cape: return "cape";
                case ItemObject.ItemTypeEnum.Horse: return "horse";
                case ItemObject.ItemTypeEnum.HorseHarness: return "horseharness";
                default: return null;
            }
        }

        internal static string[] Slots(ItemObject item)
        {
            string category = Category(item);
            if (category == null) return new string[0];
            if (AllSlots.Skip(4).Contains(category)) return new[] { category };
            return AllSlots.Take(4).ToArray();
        }

        internal static bool Sellable(ItemObject item)
        {
            return item != null && !item.NotMerchandise && Category(item) != null
                && (item.ItemType != ItemObject.ItemTypeEnum.Horse
                    || (item.HorseComponent?.IsRideable == true && !item.HorseComponent.IsPackAnimal));
        }

        internal static bool MountCompatible(Hero hero, ItemObject item, string slot)
        {
            var horse = slot == "horse" ? item : hero.BattleEquipment[EquipmentIndex.Horse].Item;
            var harness = slot == "horseharness" ? item : hero.BattleEquipment[EquipmentIndex.HorseHarness].Item;
            if (slot != "horse" && slot != "horseharness") return true;
            if (horse == null || harness == null) return true;
            return horse.HorseComponent?.Monster != null && harness.ArmorComponent != null
                && horse.HorseComponent.Monster.FamilyType == harness.ArmorComponent.FamilyType;
        }

        private static JObject Describe(ItemObject item, ItemModifier modifier)
        {
            int tier = EquipmentShopPolicy.PublicTier((int)item.Tier);
            return new JObject {
                ["id"] = item.StringId, ["item_id"] = item.StringId,
                ["name"] = item.Name?.ToString() ?? item.StringId,
                ["tier"] = tier, ["required_level"] = EquipmentShopPolicy.RequiredLevel(tier),
                ["price_gold"] = EquipmentShopPolicy.Price(item.Value),
                ["trade_in_gold"] = Math.Max(0, new EquipmentElement(item, modifier).ItemValue),
                ["category"] = Category(item), ["slots"] = new JArray(Slots(item)),
                ["stats"] = JObject.Parse(EquipmentSync.BuildStatsJson(item, modifier)),
                ["weight"] = item.Weight, ["modifier_id"] = modifier?.StringId,
                ["item_value"] = item.Value, ["quality"] = modifier?.ItemQuality.ToString().ToLowerInvariant(),
                ["quality_rank"] = ReforgeQuality.Rank(modifier), ["reforge_options"] = ReforgeQuality.Options(item),
            };
        }

        internal string Snapshot(Hero hero, EquipmentLedger ledger, bool? missionOverride = null)
        {
            ledger.Revision++;
            Store(hero, ledger);
            var items = new JArray();
            foreach (var owned in ledger.Items)
            {
                var item = MBObjectManager.Instance.GetObject<ItemObject>(owned.ItemId);
                // Keep missing modded items in the ledger; never erase ownership.
                JObject row;
                if (item == null) row = new JObject { ["item_id"] = owned.ItemId, ["name"] = owned.ItemId, ["unavailable"] = true, ["slots"] = new JArray() };
                else
                {
                    var modifier = string.IsNullOrEmpty(owned.ModifierId) ? null
                        : MBObjectManager.Instance.GetObject<ItemModifier>(owned.ModifierId);
                    row = Describe(item, modifier);
                    if (!string.IsNullOrEmpty(owned.ModifierId) && modifier == null) row["unavailable"] = true;
                }
                row["owned_id"] = owned.OwnedId;
                row["slot"] = owned.Slot;
                row["modifier_id"] = owned.ModifierId;
                row["source"] = owned.Slot == null ? "legacy" : "equipped";
                items.Add(row);
            }
            var roster = PartyInventory(hero);
            if (roster != null)
            {
                for (int i = 0; i < roster.Count; i++)
                {
                    var rosterRow = roster.GetElementCopyAtIndex(i);
                    var element = rosterRow.EquipmentElement;
                    // Ownership is not a shop eligibility rule: native unique gear
                    // remains visible even when the game forbids selling it.
                    if (rosterRow.Amount <= 0 || element.Item == null || Category(element.Item) == null) continue;
                    var row = Describe(element.Item, element.ItemModifier);
                    row["owned_id"] = PartyOwnedId(element.Item, element.ItemModifier);
                    row["slot"] = null;
                    row["source"] = "party";
                    row["count"] = rosterRow.Amount;
                    items.Add(row);
                }
            }
            return new JObject { ["username"] = Username(hero),
                ["save_id"] = Campaign.Current.UniqueGameId, ["hero_id"] = hero.StringId,
                ["equipment_session_id"] = SessionId,
                ["inventory_seq"] = ledger.Revision, ["items"] = items,
                ["inventory_state"] = new JObject {
                    ["buy_equip_available"] = true,
                    ["in_mission"] = missionOverride ?? (TaleWorlds.MountAndBlade.Mission.Current != null),
                    ["party_available"] = roster != null,
                    ["party_reason"] = hero.IsPrisoner ? "hero_prisoner" : roster == null ? "no_party_inventory" : null,
                    ["party_id"] = roster != null ? hero.PartyBelongedTo.StringId : null,
                    ["party_name"] = roster != null ? hero.PartyBelongedTo.Name?.ToString() : null },
                ["build"] = HeroBuildRuntime.Snapshot(hero, ledger.Build, missionOverride) }.ToString(Formatting.None);
        }

        internal void Push(Hero hero, EquipmentLedger ledger, bool? missionOverride = null)
        {
            string json = Snapshot(hero, ledger, missionOverride);
            var backend = BannerlordLinkModule.Backend;
            if (backend != null) _snapshots.Queue(json, payload => backend.PostEventAsync("bannerlord", "hero.inventory_snapshot", payload));
        }

        internal void PublishBuilds(bool? missionOverride = null)
        {
            if (Campaign.Current == null) return;
            foreach (var hero in Campaign.Current.AliveHeroes.Where(h => h != null && !string.IsNullOrEmpty(Username(h))))
            {
                var ledger = Read(hero);
                if (ledger.Build != null) Push(hero, ledger, missionOverride);
            }
        }

        private void Tick(float dt)
        {
            if (Campaign.Current == null || BannerlordLinkModule.Backend == null || _publishing || _handshake == null) return;
            if (_refresh.Elapsed.TotalSeconds < (_published ? 30 : 5)) return;
            _refresh.Restart();
            try
            {
                bool publishCatalog = !_published || _catalogRefresh.Elapsed.TotalMinutes >= 5;
                string catalog = null;
                if (publishCatalog)
                {
                    var rows = new JArray(MBObjectManager.Instance.GetObjectTypeList<ItemObject>()
                        .Where(Sellable).Select(item => Describe(item, null)));
                    catalog = new JObject { ["catalog"] = "equipment", ["save_id"] = Campaign.Current.UniqueGameId,
                        ["equipment_session_id"] = SessionId,
                        ["entries"] = rows }.ToString(Formatting.None);
                }
                var snapshots = new List<string>();
                foreach (var hero in Campaign.Current.AliveHeroes.Where(h => h != null && !string.IsNullOrEmpty(Username(h))))
                {
                    var ledger = Read(hero);
                    Store(hero, ledger);
                    snapshots.Add(Snapshot(hero, ledger));
                }
                var backend = BannerlordLinkModule.Backend;
                _publishing = true;
                Task.Run(async () => {
                    try
                    {
                        if (!await _handshake.EnsureAsync((payload, timestamp) => backend.PostEventAsync("bannerlord", "module.session_start", payload, timestamp))) return;
                        if (catalog != null)
                        {
                            if (!await backend.PostEventAsync("bannerlord", "module.catalog_update", catalog))
                            { _published = false; return; }
                            _catalogRefresh.Restart();
                        }
                        foreach (string json in snapshots) _snapshots.Queue(json, payload => backend.PostEventAsync("bannerlord", "hero.inventory_snapshot", payload));
                        _published = true;
                    }
                    catch (Exception ex) { BannerlordLinkModule.Log("[EquipmentShop] publish will retry: " + ex.Message); }
                    finally { _publishing = false; }
                });
            }
            catch (Exception ex) { BannerlordLinkModule.Log("[EquipmentShop] snapshot failed: " + ex.Message); }
        }
    }
}
