using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

internal static partial class Program
{
    // 23.09, владелец: «съёбывать в свой город/замок или просто отбегать, если
    // бежит бить армия в разы сильнее». Порог 5x (владелец 25.09: «отступление только при 5х перевесе везде», было 2x); он не пересекается
    // с охотой (нападаем, пока враг не сильнее 1,25x нас).
    static MobileParty Chaser(IFaction faction, int strength, float distance, bool targetsUs = true)
    {
        var p = HuntTarget("армия", strength, distance, faction);
        if (targetsUs) p.TargetParty = MobileParty.MainParty;
        return p;
    }

    static Settlement Fort(string name, float x, IFaction faction)
    {
        var s = new Settlement { Name = name, IsCastle = true, MapFaction = faction, Position = new CampaignVec2 { X = x } };
        Settlement.All.Add(s); return s;
    }

    static void FleeTests()
    {
        Try("армия в 5,5x идёт на нас — укрываемся в своём замке", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            var home = Fort("Свой замок", -5, MobileParty.MainParty.MapFaction);
            Chaser(enemy, 500, 8);
            b.PollState();
            Check(MobileParty.MainParty.TargetSettlement == home, "едем в свой замок: " + MobileParty.MainParty.TargetSettlement?.Name);
            Check(LogCount("ОТХОД") >= 1, "причина записана");
        });
        Try("враг 1,5x — не бежим", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            Fort("Свой замок", -5, MobileParty.MainParty.MapFaction);
            Chaser(enemy, 135, 8);
            b.PollState();
            Check(LogCount("ОТХОД") == 0, "полтора раза — не «в разы», не бежим");
        });
        Try("враг 4x — не бежим, воюем (владелец 25.09)", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            Fort("Свой замок", -5, MobileParty.MainParty.MapFaction);
            Chaser(enemy, 360, 8);
            b.PollState();
            Check(LogCount("ОТХОД") == 0, "4x — меньше порога 5x, не бежим");
        });
        Try("армия 3x идёт мимо — не бежим", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            Fort("Свой замок", -5, MobileParty.MainParty.MapFaction);
            Chaser(enemy, 300, 8, targetsUs: false);
            b.PollState();
            Check(LogCount("ОТХОД") == 0, "идёт не на нас — не дёргаемся");
        });
        Try("до своего замка враг ближе — уходим в поселение в сторону от врага", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            Fort("Замок за врагом", 15, MobileParty.MainParty.MapFaction);
            var away = new Settlement { Name = "Деревня в стороне", IsVillage = true, MapFaction = MobileParty.MainParty.MapFaction,
                Position = new CampaignVec2 { X = -20 } };
            Settlement.All.Add(away);
            Chaser(enemy, 500, 8);
            b.PollState();
            Check(MobileParty.MainParty.TargetSettlement == away, "не в замок за спиной врага, а прочь: " + MobileParty.MainParty.TargetSettlement?.Name);
        });
        Try("в укрытии сидим, пока угроза рядом", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            var home = Fort("Свой замок", -5, MobileParty.MainParty.MapFaction);
            var chaser = Chaser(enemy, 500, 8);
            b.PollState();
            ArriveTown(home); b.PollState(); b.PollState();
            var next = new Settlement { Name = "Next" };
            Scores((AiBehavior.GoToSettlement, next, 10f));
            HourlyTick(b); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == home, "армия рядом — из замка не выходим");
            chaser.Position = new CampaignVec2 { X = 60 };
            HourlyTick(b); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == null && MobileParty.MainParty.TargetSettlement == next,
                "армия ушла — возвращаемся к обычным делам");
        });
    }

    // 23.09, владелец: оборону своего замка бросаем только перед силой в 5x —
    // «мы со зрителями отбивали даже подобные осады». Лог 22.09: как защитники
    // отбили 1650 и 1685 врагов при отряде ~320 (~5,2x), проиграли от 6,4x.
    static void FleeDefenseTests()
    {
        foreach (var (force, flee) in new[] { (270, false), (540, true) })
        Try("оборона своего замка против армии x" + (force / 90), () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            var besieged = OwnSiege(x: 20);
            Fort("Запасной замок", -5, MobileParty.MainParty.MapFaction);
            Chaser(enemy, force, 8);
            b.PollState(); HourlyTick(b); b.PollState();
            Check((LogCount("ОТХОД") > 0) == flee, "отход при x" + (force / 90) + ": ждали " + flee);
            if (!flee) Check(MobileParty.MainParty.TargetSettlement == besieged, "при 3x идём защищать свой замок: "
                + MobileParty.MainParty.TargetSettlement?.Name);
        });
    }
}
