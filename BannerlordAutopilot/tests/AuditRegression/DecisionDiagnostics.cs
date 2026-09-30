using System;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;

internal static partial class Program
{
    static void DecisionDiagnosticsTests()
    {
        Try("issued attack records live health speed distance", () => {
            var (b, enemy)=HuntWorld(men:100);
            HuntTarget("diagnostic enemy",40,10,enemy,speed:4f);
            HourlyTick(b);
            Check(AutopilotLog.Lines.Any(l=>l.Contains("ПРИКАЗ ВЫДАН:") && l.Contains("EngageParty")
                && l.Contains("герой ранен False") && l.Contains("здоровых 100/100")
                && l.Contains("наша скорость 5.00") && l.Contains("скорость цели 4.00") && l.Contains("расстояние 10.0")),
                "attack evidence is taken when order is issued");
            Check(!AutopilotLog.Lines.Any(l=>l.Contains("ДЕЙСТВИЕ ЗАВЕРШЕНО")),"movement order is not logged as completed battle");
        });
        Try("scored proposals explicitly are not issued orders", () => {
            var b=Fresh(); Enable(b,AutopilotBehavior.Mode.Observe);
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(null,AiBehavior.PatrolAroundPoint,MobileParty.NavigationType.Default,false,false,false),2f));
            HourlyTick(b);
            Check(AutopilotLog.Lines.Any(l=>l.Contains("КАНДИДАТ (не приказ):") && l.Contains("PatrolAroundPoint")),"proposal labeled as candidate");
            Check(!AutopilotLog.Lines.Any(l=>l.Contains("ПРИКАЗ ВЫДАН:")),"observe never claims issued command");
        });
    }
}
