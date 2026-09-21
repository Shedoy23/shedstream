using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using BannerlordLink.Actions;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;

static class Program
{
    static int Main()
    {
        try
        {
            TestIndependentLandlessKingdom();
            TestRebellionNeedsTwoSupporters();
            TestRebellionTransfersSupportersAndFiefs();
            Console.WriteLine("PASS kingdom founding paths: landless independent + supported rebellion");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }

    static void TestIndependentLandlessKingdom()
    {
            Reset();
            var clan = new Clan { StringId = "founder", Name = new TaleWorlds.Localization.TextObject("No fiefs") };
            var hero = new Hero {
                IsAlive = true, IsClanLeader = true, Gold = 6_000_000,
                Clan = clan, Culture = new CultureObject { StringId = "empire" },
            };
            HeroLookup.Current = hero;
            new CreateKingdomHandler().ExecuteAsync(new JObject {
                ["target"] = "endorphine13", ["kingdom_name"] = "Endorphine",
                ["action_id"] = "create-empty-kingdom",
            }).GetAwaiter().GetResult();

            Check(clan.Settlements.Count == 0, "fixture unexpectedly owns a settlement");
            Check(clan.Kingdom != null, "clan without fiefs must be allowed to create a kingdom");
            Check(ActionFeedback.Applied && ActionFeedback.Error == null,
                "successful empty kingdom must report applied");
            Check(hero.Gold == 1_000_000, "kingdom cost must still be charged");
            Check(HeroStateSync.Pushed == hero, "new kingdom state must be published");
    }

    static void TestRebellionNeedsTwoSupporters()
    {
        Reset();
        var oldKingdom = NewKingdom("old", "Old Kingdom");
        var ruler = NewClan("ruler", "Ruler", oldKingdom, 100);
        oldKingdom.RulingClan = ruler;
        var founder = NewClan("founder", "Founder", oldKingdom, 0);
        var friend = NewClan("friend", "Friend", oldKingdom, 60);
        var hero = NewHero(founder);
        friend.Leader.Relations[hero] = 60;
        HeroLookup.Current = hero;

        RunCreate("unsupported-rebellion");

        Check(founder.Kingdom == oldKingdom, "unsupported rebel must remain in old kingdom");
        Check(ActionFeedback.Error == "rebellion_support_required", "must report supporter requirement");
        Check(hero.Gold == 6_000_000, "failed rebellion must not charge gold");
    }

    static void TestRebellionTransfersSupportersAndFiefs()
    {
        Reset();
        var oldKingdom = NewKingdom("old", "Old Kingdom");
        var ruler = NewClan("ruler", "Ruler", oldKingdom, 100);
        oldKingdom.RulingClan = ruler;
        var founder = NewClan("founder", "Founder", oldKingdom, 0);
        founder.Settlements.Add(new Settlement { Id = "founder-fief" });
        var personal = NewClan("personal", "Personal Vassal", oldKingdom, -100);
        personal.Settlements.Add(new Settlement { Id = "personal-fief" });
        var friend = NewClan("friend", "Friendly Lord", oldKingdom, 55);
        friend.Settlements.Add(new Settlement { Id = "friend-fief" });
        var neutral = NewClan("neutral", "Neutral Lord", oldKingdom, 49);
        var hero = NewHero(founder);
        friend.Leader.Relations[hero] = 55;
        neutral.Leader.Relations[hero] = 49;
        BannerlordLink.Behaviors.VassalAutoFollowBehavior.Current.PersonalVassals.Add(personal);
        HeroLookup.Current = hero;

        RunCreate("supported-rebellion");

        var created = founder.Kingdom;
        Check(ActionFeedback.Applied, "supported rebellion must be applied");
        Check(created != null && created != oldKingdom, "founder must lead a new kingdom");
        Check(personal.Kingdom == created && friend.Kingdom == created,
            "personal and relation supporters must join the new kingdom");
        Check(neutral.Kingdom == oldKingdom && ruler.Kingdom == oldKingdom,
            "neutral and ruling clans must stay behind");
        Check(founder.Settlements.Count == 1 && personal.Settlements.Count == 1 && friend.Settlements.Count == 1,
            "rebellion must preserve supporter fiefs");
    }

    static void RunCreate(string actionId) => new CreateKingdomHandler().ExecuteAsync(new JObject {
        ["target"] = "endorphine13", ["kingdom_name"] = "Endorphine", ["action_id"] = actionId,
    }).GetAwaiter().GetResult();

    static Hero NewHero(Clan clan)
    {
        var hero = new Hero { IsAlive = true, IsClanLeader = true, Gold = 6_000_000,
            Clan = clan, Culture = new CultureObject { StringId = "empire" } };
        clan.Leader = hero;
        return hero;
    }

    static Clan NewClan(string id, string name, Kingdom kingdom, int relation)
    {
        var clan = new Clan { StringId = id, Name = new TaleWorlds.Localization.TextObject(name), Kingdom = kingdom };
        clan.Leader = new Hero { IsAlive = true, Clan = clan };
        kingdom.Clans.Add(clan);
        return clan;
    }

    static Kingdom NewKingdom(string id, string name)
    {
        var kingdom = new Kingdom { StringId = id, Name = new TaleWorlds.Localization.TextObject(name) };
        Kingdom.All.Add(kingdom);
        return kingdom;
    }

    static void Reset()
    {
        Kingdom.All.Clear();
        TaleWorlds.CampaignSystem.Actions.ChangeKingdomAction.Transfers.Clear();
        BannerlordLink.Behaviors.VassalAutoFollowBehavior.Current.PersonalVassals.Clear();
        ActionFeedback.Applied = false;
        ActionFeedback.Error = null;
        HeroStateSync.Pushed = null;
    }

    static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }
}

namespace BannerlordLink.Actions
{
    public interface IActionHandler
    {
        string ActionType { get; }
        Task<(bool success, string error)> ExecuteAsync(JObject data);
    }

    public static class HeroLookup
    {
        public static Hero Current;
        public static Hero FindByUsername(string username) => Current;
    }
}

namespace BannerlordLink.Util
{
    public static class MainThreadDispatcher
    {
        public static void Enqueue(Action action) => action();
    }

    public static class ActionFeedback
    {
        public static bool Applied;
        public static string Error;
        public static string GetActionId(JObject data) => data["action_id"]?.ToString();
        public static void PostApplied(string actionId) { Applied = true; Error = null; }
        public static void PostFailed(string actionId, string reason) { Applied = false; Error = reason; }
    }

    public static class HeroStateSync
    {
        public static Hero Pushed;
        public static void Push(Hero hero) => Pushed = hero;
    }
}

namespace BannerlordLink
{
    public static class BannerlordLinkModule
    {
        public static Backend Backend { get; } = new Backend();
        public static void Log(string message) { }
    }

    public sealed class Backend
    {
        public Task<bool> PostEventAsync(string module, string type, string data)
            => Task.FromResult(true);
    }
}

namespace TaleWorlds.Localization
{
    public sealed class TextObject
    {
        readonly string _value;
        public TextObject(string value) { _value = value; }
        public override string ToString() => _value;
    }
}

namespace TaleWorlds.Core
{
    public sealed class Banner { }
}

namespace TaleWorlds.CampaignSystem
{
    using TaleWorlds.Core;
    using TaleWorlds.Localization;

    public sealed class CultureObject { public string StringId; }
    public sealed class Settlement { public string Id; }
    public sealed class Hero
    {
        public bool IsAlive;
        public bool IsPrisoner;
        public bool IsClanLeader;
        public int Gold;
        public Clan Clan;
        public CultureObject Culture;
        public Dictionary<Hero, int> Relations { get; } = new Dictionary<Hero, int>();
        public int GetRelation(Hero other) => Relations.TryGetValue(other, out var value) ? value : 0;
    }
    public sealed class Clan
    {
        public TextObject Name;
        public string StringId;
        public List<Settlement> Settlements { get; } = new List<Settlement>();
        public Kingdom Kingdom;
        public float Influence;
        public Banner Banner;
        public Hero Leader;
        public bool IsEliminated;
        public bool IsUnderMercenaryService;
    }
    public sealed class Kingdom
    {
        public static List<Kingdom> All { get; } = new List<Kingdom>();
        public TextObject Name;
        public string StringId = "kingdom_test";
        public int KingdomBudgetWallet;
        public Banner Banner;
        public Clan RulingClan;
        public List<Clan> Clans { get; } = new List<Clan>();
    }
    public sealed class KingdomManager
    {
        public void CreateKingdom(TextObject name, TextObject informalName,
            CultureObject culture, Clan clan, object a, object b, object c, object d)
        {
            var kingdom = new Kingdom { Name = name };
            Kingdom.All.Add(kingdom);
            clan.Kingdom?.Clans.Remove(clan);
            clan.Kingdom = kingdom;
            kingdom.Clans.Add(clan);
            kingdom.RulingClan = clan;
        }
    }
    public sealed class Campaign
    {
        public static Campaign Current { get; } = new Campaign();
        public KingdomManager KingdomManager { get; } = new KingdomManager();
    }
}

namespace TaleWorlds.CampaignSystem.Actions
{
    using TaleWorlds.CampaignSystem;
    public static class GiveGoldAction
    {
        public static void ApplyBetweenCharacters(Hero from, Hero to, int amount, bool notify)
            => from.Gold -= amount;
    }
    public static class ChangeKingdomAction
    {
        public static List<string> Transfers { get; } = new List<string>();
        public static void ApplyByJoinToKingdomByDefection(Clan clan, Kingdom oldKingdom,
            Kingdom newKingdom, object until = null, bool showNotification = true)
        {
            oldKingdom?.Clans.Remove(clan);
            clan.Kingdom = newKingdom;
            newKingdom.Clans.Add(clan);
            Transfers.Add(clan.StringId);
        }
    }
}

namespace BannerlordLink.Behaviors
{
    using System.Collections.Generic;
    using TaleWorlds.CampaignSystem;
    public sealed class VassalAutoFollowBehavior
    {
        public static VassalAutoFollowBehavior Current { get; } = new VassalAutoFollowBehavior();
        public List<Clan> PersonalVassals { get; } = new List<Clan>();
        public List<Clan> GetVassalsOfMaster(Clan masterClan) => new List<Clan>(PersonalVassals);
    }
}
