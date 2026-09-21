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
            var clan = new Clan { Name = new TaleWorlds.Localization.TextObject("No fiefs") };
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
            Console.WriteLine("PASS create kingdom without fiefs: created, charged, acknowledged, synced");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
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
    public sealed class Settlement { }
    public sealed class Hero
    {
        public bool IsAlive;
        public bool IsPrisoner;
        public bool IsClanLeader;
        public int Gold;
        public Clan Clan;
        public CultureObject Culture;
    }
    public sealed class Clan
    {
        public TextObject Name;
        public List<Settlement> Settlements { get; } = new List<Settlement>();
        public Kingdom Kingdom;
        public float Influence;
        public Banner Banner;
    }
    public sealed class Kingdom
    {
        public static List<Kingdom> All { get; } = new List<Kingdom>();
        public TextObject Name;
        public string StringId = "kingdom_test";
        public int KingdomBudgetWallet;
        public Banner Banner;
    }
    public sealed class KingdomManager
    {
        public void CreateKingdom(TextObject name, TextObject informalName,
            CultureObject culture, Clan clan, object a, object b, object c, object d)
        {
            var kingdom = new Kingdom { Name = name };
            Kingdom.All.Add(kingdom);
            clan.Kingdom = kingdom;
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
}
