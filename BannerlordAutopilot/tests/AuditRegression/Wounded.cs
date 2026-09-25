using System;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.Party;

internal static partial class Program
{
    // 24.09: раненый герой → «Послать воинов» при любом раскладе — 22.09 армии
    // 122/312/322 → 1. Раненого героя игра в бой не пускает — только авторасчёт, поэтому для него
    // порог 0,8x, а не общие 5x (25.09: авторасчёт при 5x-правиле — 24 → 1).
    static void WoundedRetreatTests()
    {
        foreach (var (ours, theirs, options, expect) in new[]
        {
            (100f, 600f, new[] { "leave", "leave_soldiers_behind" }, "leave"),
            (100f, 600f, new[] { "leave_soldiers_behind" }, "leave_soldiers_behind"),
            (100f, 300f, new[] { "leave", "leave_soldiers_behind" }, "leave"),
            (100f, 130f, new[] { "leave" }, "leave"),
            (90f, 100f, new[] { "leave" }, "str_order_attack"),
            (100f, 300f, new string[0], "str_order_attack"),
        })
        Try("раненый герой, силы " + ours + " против " + theirs + ", есть: " + string.Join(",", options), () =>
        {
            var b = Fresh(); ConquestWorld(); Enable(b); Hero.MainHero.IsWounded = true;
            PlayerEncounter.Current = new PlayerEncounter();
            var battle = new MapEvent(); MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = battle;
            battle.StrengthOfSide[(int)TaleWorlds.Core.BattleSideEnum.Attacker] = ours;
            battle.StrengthOfSide[(int)TaleWorlds.Core.BattleSideEnum.Defender] = theirs;
            string pressed = null;
            var menu = Menu("encounter", "attack", () => {}); menu.Options[0].IsEnabled = false;
            menu.Options.Add(new GameMenuOption { IdString = "str_order_attack", IsEnabled = true, Consequence = () => pressed = pressed ?? "str_order_attack" });
            foreach (var id in options)
            {
                string captured = id;
                menu.Options.Add(new GameMenuOption { IdString = captured, IsEnabled = true, Consequence = () => pressed = pressed ?? captured });
            }
            Show(menu); b.PollState();
            Check(pressed == expect, "нажато «" + pressed + "», ждали «" + expect + "»");
        });
    }
}
