using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

internal static partial class Program
{
    // 23.09, решение владельца: «безбашенный» автопилот — нападает на вражеский
    // отряд даже при 0,8x сил. Штатная инициатива игры нападает только при
    // перевесе (> 1x), поэтому охоту ведёт автопилот, а исполняет — игра
    // (штатный приказ EngageParty).
    // В заглушке сила отряда = число бойцов (PartyBase.EstimatedStrength).
    static (AutopilotBehavior Pilot, TestFaction Enemy) HuntWorld(int men = 90)
    {
        var b = Fresh(); Enable(b);
        var mine = new TestFaction(); var enemy = new TestFaction();
        mine.Enemies.Add(enemy); enemy.Enemies.Add(mine);
        var main = MobileParty.MainParty; main.MapFaction = mine; main.Party.MapFaction = mine;
        main.Party.PartySizeLimit = 100; main.Speed = 5f;
        main.MemberRoster.AddToCounts(new CharacterObject { Name = "Ветеран", StringId = "veteran" }, men);
        main.DefaultBehavior = AiBehavior.Hold;
        return (b, enemy);
    }

    static MobileParty HuntTarget(string name, int strength, float distance, IFaction faction, bool lord = true, float speed = 4f)
    {
        var p = new MobileParty { Name = name, IsLordParty = lord, IsBandit = !lord, MapFaction = faction,
            Position = new CampaignVec2 { X = distance }, Speed = speed, IsMoving = true };
        p.Party.MapFaction = faction;
        p.MemberRoster.AddToCounts(new CharacterObject { Name = "боец " + name, StringId = "enemy_" + name }, strength);
        MobileParty.All.Add(p);
        return p;
    }

    static void HuntTests()
    {
        Try("охота: лорд сильнее нас, но в пределах 0,8x — нападаем", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            var lord = HuntTarget("лорд", 100, 10, enemy);
            HourlyTick(b);
            Check(MobileParty.MainParty.TargetParty == lord && MobileParty.MainParty.DefaultBehavior == AiBehavior.EngageParty,
                "атакуем лорда при соотношении 0,9x: " + MobileParty.MainParty.DefaultBehavior);
            Check(LogCount("ОХОТА") >= 1, "решение записано с причиной");
        });
        Try("охота: слабее 0,8x — не нападаем", () =>
        {
            var (b, enemy) = HuntWorld(men: 70);
            HuntTarget("лорд", 100, 10, enemy);
            HourlyTick(b);
            Check(MobileParty.MainParty.DefaultBehavior != AiBehavior.EngageParty, "при 0,7x не нападаем");
        });
        Try("охота: потрёпанный отряд восстанавливается, а не лезет в бой", () =>
        {
            var (b, enemy) = HuntWorld(men: 40);
            HuntTarget("лорд", 10, 10, enemy);
            HourlyTick(b);
            Check(MobileParty.MainParty.DefaultBehavior != AiBehavior.EngageParty, "заполнение 40% — охоты нет");
        });
        Try("охота: без войны не трогаем", () =>
        {
            var (b, _) = HuntWorld();
            HuntTarget("сосед", 50, 10, new TestFaction());
            HourlyTick(b);
            Check(MobileParty.MainParty.DefaultBehavior != AiBehavior.EngageParty, "с тем, с кем нет войны, не деремся");
        });
        Try("охота: из двух целей выбираем лорда, а не бандитов", () =>
        {
            var (b, enemy) = HuntWorld(men: 100);
            HuntTarget("бандиты", 60, 8, enemy, lord: false);
            var lord = HuntTarget("лорд", 60, 12, enemy);
            HourlyTick(b);
            Check(MobileParty.MainParty.TargetParty == lord, "лорд важнее бандитов при равной силе");
        });
        Try("охота: быстрый отряд вдали не догнать — не гонимся", () =>
        {
            var (b, enemy) = HuntWorld(men: 100);
            HuntTarget("конники", 50, 25, enemy, speed: 8f);
            HourlyTick(b);
            Check(MobileParty.MainParty.DefaultBehavior != AiBehavior.EngageParty, "быстрее нас и далеко — пропускаем");
        });
        Try("охота: цель вне радиуса не трогаем", () =>
        {
            var (b, enemy) = HuntWorld(men: 100);
            HuntTarget("лорд", 50, 80, enemy);
            HourlyTick(b);
            Check(MobileParty.MainParty.DefaultBehavior != AiBehavior.EngageParty, "дальше радиуса охоты не идём");
        });
    }

    // 23.09, владелец: «на войне — осады и защита; рядом можно навалять — навалять».
    static (AutopilotBehavior Pilot, Settlement Castle, Settlement Village) SiegeVsRecruitWorld(int extraMen)
    {
        var b=Fresh(); var castle=ConquestWorld(gold:1000); castle.Militia=1; castle.Name="Замок"; Settlement.All.Add(castle);
        var party=MobileParty.MainParty; party.Party.PartySizeLimit=100;
        party.MemberRoster.AddToCounts(new CharacterObject(), extraMen);
        var village=new Settlement { Name="Деревня", IsVillage=true, MapFaction=party.MapFaction, Position=new CampaignVec2 { X=1 } };
        var notable=new Hero(); notable.VolunteerTypes[0]=new CharacterObject { TestCost=17 };
        village.Notables.Add(notable); Settlement.All.Add(village);
        Enable(b);
        return (b, castle, village);
    }

    static void SiegePriorityTests()
    {
        Try("на войне при 75% осада важнее набора до 90%", () =>
        {
            var (b, castle, _) = SiegeVsRecruitWorld(65);
            HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement==castle && SiegeTarget(b)==castle,
                "75/100 и крепость по силам — идём на осаду: " + MobileParty.MainParty.TargetSettlement?.Name);
            Check(LogCount("осада важнее набора")==1, "причина записана");
        });
        Try("при 60% сначала набор, осада подождёт", () =>
        {
            var (b, _, village) = SiegeVsRecruitWorld(50);
            HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement==village, "60/100 — едем за добровольцами");
        });
        Try("по дороге на осаду бьём врага рядом, но с маршрута далеко не сворачиваем", () =>
        {
            foreach (var (distance, expect) in new[] { (8f, true), (20f, false) })
            {
                var (b, enemy) = HuntWorld(men: 100);
                var castle = new Settlement { Name="Цель осады", IsCastle=true, MapFaction=enemy, Position=new CampaignVec2 { X=90 } };
                var main = MobileParty.MainParty; main.TargetSettlement = castle; main.DefaultBehavior = AiBehavior.BesiegeSettlement;
                var lord = HuntTarget("лорд", 60, distance, enemy);
                HourlyTick(b);
                Check((main.TargetParty == lord) == expect, "враг в " + distance + " по дороге на осаду: ждали " + expect);
            }
        });
    }
}
