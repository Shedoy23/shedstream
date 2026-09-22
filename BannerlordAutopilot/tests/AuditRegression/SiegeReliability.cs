using System;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

internal static partial class Program
{
    static void SiegeReliabilityTests()
    {
        Try("unavailable break in leaves and does not loop", () => {
            var b=Fresh(); ConquestWorld(wounded:0); var own=OwnSiege(); Enable(b);
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=own;
            int leaves=0, breaks=0;
            var menu=Menu("join_siege_event","join_siege_event_break_in",()=>breaks++,false);
            menu.Options.Add(new GameMenuOption { IdString="join_encounter_leave", IsEnabled=true,
                Consequence=()=>{leaves++;PlayerEncounter.Finish();MobileParty.MainParty.CurrentSettlement=null;} });
            Show(menu); b.PollState();
            Check(leaves==1 && breaks==0 && b.CurrentMode==AutopilotBehavior.Mode.Apply,
                "недоступный прорыв: штатный выход без выключения");
            HourlyTick(b); b.PollState();
            Check(MobileParty.MainParty.TargetSettlement!=own && b.CurrentMode==AutopilotBehavior.Mode.Apply,
                "недоступная осада не выбирается снова сразу после выхода");
        });
        Try("defense interrupts postbattle rest", () => {
            var b=Surrender(); LootScreen(); b.PollState(); PlayerEncounter.Finish();
            PlayerEncounter.EncounteredMobileParty=null; ConquestWorld(wounded:0);
            var town=ArriveTown(new Settlement {IsTown=true,MapFaction=MobileParty.MainParty.MapFaction});
            b.PollState(); var own=OwnSiege(); HourlyTick(b); b.PollState();
            Check(MobileParty.MainParty.TargetSettlement==own && MobileParty.MainParty.CurrentSettlement==null,
                "свой феод под осадой прерывает 12 часов отдыха");
        });
        foreach(bool native in new[]{false,true}) Try("remote siege rejected "+native, () => {
            var b=Fresh(); var far=ConquestWorld(wounded:0); far.Position=new CampaignVec2 {X=500}; far.Militia=1;
            var home=OwnSiege(x:0);home.IsUnderSiege=false;
            var near=new Settlement {IsCastle=true,MapFaction=far.MapFaction,Position=new CampaignVec2 {X=35},Militia=5};
            Settlement.All.Add(far);Settlement.All.Add(near);
            MobileParty.MainParty.Position=far.Position;
            if(native) Scores((AiBehavior.BesiegeSettlement,far,999f));
            Enable(b);HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement!=far,"далёкий слабый феод не становится целью осады");
            Check(MobileParty.MainParty.TargetSettlement==near,"пограничный феод разрешён даже вдали от текущего отряда");
        });
    }
}
