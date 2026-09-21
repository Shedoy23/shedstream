using System;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.Siege;
using TaleWorlds.Core;

internal static partial class Program
{
    static Settlement OwnSiege(bool town = false, float x = 20)
    {
        var s = new Settlement { Name = town ? "Свой город" : "Свой замок", IsTown = town,
            IsCastle = !town, IsUnderSiege = true, MapFaction = MobileParty.MainParty.MapFaction,
            Position = new CampaignVec2 { X = x } };
        Clan.PlayerClan.Fiefs.Add(new Town { Settlement = s }); Settlement.All.Add(s);
        return s;
    }

    static void DefenseTests()
    {
        foreach (bool town in new[] { false, true }) Try("срочная оборона без штатной оценки", () => {
            var b = Fresh(); var enemy = ConquestWorld(food:0, gold:1000, wounded:5);
            var own = OwnSiege(town); var party = MobileParty.MainParty; party.Party.PartySizeLimit = 20;
            var village = new Settlement { IsVillage=true, MapFaction=party.MapFaction, Position=new CampaignVec2 {X=1} };
            var notable = new Hero(); notable.VolunteerTypes[0]=new CharacterObject {TestCost=17}; village.Notables.Add(notable);
            Settlement.All.Add(village); SetLimit("MinGoldReserve",0); party.TotalWage=1;
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(enemy,AiBehavior.BesiegeSettlement,MobileParty.NavigationType.Default,false,false,false),999));
            Enable(b); HourlyTick(b);
            Check(party.TargetSettlement==own && party.DefaultBehavior==AiBehavior.GoToSettlement && party.IsMoving,
                "свои город/замок: 50% заполнения и 50% здоровых идут защищать прежде найма и похода");
            Check(SetPartyAiAction.VisitCalls==1,"оборона двигает MainParty штатной поездкой, не пустым DefendSettlement");
            Check(AutopilotLog.Lines.Any(l=>l.Contains("ОБОРОНА") && l.Contains("5/10")),"журнал объясняет срочную оборону и порог");
            HourlyTick(b); Check(party.TargetSettlement==own && SetPartyAiAction.VisitCalls==1,"маршрут обороны не сбрасывается на каждом тике");
        });
        foreach (int wounded in new[]{5,6}) Try("порог обороны", () => {
            var b=Fresh(); ConquestWorld(wounded:wounded); var own=OwnSiege(); Enable(b); HourlyTick(b);
            Check((MobileParty.MainParty.TargetSettlement==own)==(wounded==5),"ровно 50% здоровых разрешено, ниже половины восстановление");
        });
        Try("снятая осада и утрата собственности", () => {
            var b=Fresh(); ConquestWorld(wounded:0); var near=OwnSiege(x:10); var far=OwnSiege(x:30); Enable(b); HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement==near,"сначала ближайший свой осаждённый феод");
            far.Position=new CampaignVec2 {X=1}; HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement==near,"на ходу не мечемся между двумя осадами");
            near.IsUnderSiege=false; HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement==far,"снятую осаду заменяет другая актуальная");
            Clan.PlayerClan.Fiefs.Clear(); HourlyTick(b);
            Check(!MobileParty.MainParty.IsMoving && MobileParty.MainParty.DefaultBehavior==AiBehavior.Hold,"утраченная своя цель не оставляет старый приказ движения");
        });
        Try("свои только, не всё королевство", () => {
            var b=Fresh(); ConquestWorld(wounded:0);
            var ally=new Settlement {IsCastle=true,IsUnderSiege=true,MapFaction=MobileParty.MainParty.MapFaction}; Settlement.All.Add(ally);
            Enable(b); HourlyTick(b); Check(MobileParty.MainParty.TargetSettlement!=ally,"чужой клан не становится срочным своим владением");
        });
        Try("F10 и следование чужой армии", () => {
            var b=Fresh(); ConquestWorld(wounded:0); var own=OwnSiege(); Enable(b,AutopilotBehavior.Mode.Observe); HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement!=own,"F10 не выдаёт срочных приказов");
            b.Disable("test"); MobileParty.MainParty.Army=new Army {LeaderParty=new MobileParty()}; Enable(b); HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement!=own,"не перехватываем управление чужой армией");
        });
        Try("выход из отдыха ради обороны", () => {
            var b=Fresh(); ConquestWorld(wounded:5); var own=OwnSiege(); Enable(b); b.PollState();
            ArriveTown(); b.PollState(); HourlyTick(b); b.PollState();
            Check(MobileParty.MainParty.TargetSettlement==own && MobileParty.MainParty.CurrentSettlement==null,
                "отдых прерывается штатным выходом ради своего феода");
        });
        Try("отмена наступательной осады ради своего феода", () => {
            var b=Fresh(); var enemy=ConquestWorld(wounded:0); Enable(b);
            var siege=new SiegeEvent {BesiegedSettlement=enemy}; siege.BesiegerCamp.LeaderParty=MobileParty.MainParty;
            MobileParty.MainParty.SiegeEvent=siege; PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=enemy;
            int cancelled=0;
            Show(Menu("menu_siege_strategies","menu_siege_strategies_leave",()=>Show(Menu("menu_siege_strategies_break_siege","menu_siege_strategies_break_siege_go_on",()=>{
                cancelled++; MobileParty.MainParty.SiegeEvent=null; PlayerEncounter.Finish();
            }))));
            var own=OwnSiege(); b.PollState(); b.PollState(); HourlyTick(b);
            Check(cancelled==1 && MobileParty.MainParty.TargetSettlement==own,"снимаем свою наступательную осаду штатными кнопками и идём спасать своё");
        });
        foreach (bool sally in new[]{false,true}) Try("помощь осаждённому феоду в наружном бою", () => {
            var b=Fresh(); ConquestWorld(wounded:0); var own=OwnSiege(); Enable(b); HourlyTick(b);
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=own; PlayerEncounter.EncounteredMobileParty=new MobileParty();
            var battle=new MapEvent {MapEventSettlement=own,IsSallyOut=sally,IsSiegeOutside=!sally,PlayerSide=sally?BattleSideEnum.Attacker:BattleSideEnum.Defender};
            PlayerEncounter.EncounteredBattle=battle;
            int attacks=0; var fight=Menu("encounter","attack",()=>attacks++);
            string option="join_encounter_help_"+(sally?"attackers":"defenders");
            Show(Menu("join_encounter",option,()=>{MobileParty.MainParty.MapEvent=battle;PlayerEncounter.Battle=battle;Show(fight);}));
            b.PollState(); b.PollState();
            Check(MenuContext.Invoked.Contains(option) && attacks==1 && b.IsOwnedOperationBattle(MobileParty.MainParty),
                "наружный бой и вылазка: присоединяемся к стороне своего замка и запускаем бой");
        });
    }
}
