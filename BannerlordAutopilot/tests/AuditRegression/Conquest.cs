using System;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.Siege;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.Core;

internal static partial class Program
{
    static Settlement SiegeTarget(AutopilotBehavior b) => (Settlement)typeof(AutopilotBehavior)
        .GetField("_offensiveSiege", System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic)
        .GetValue(b);

    static Settlement ConquestWorld(int food = 35, int gold = 350, int wounded = 3)
    {
        var party = MobileParty.MainParty; var ours = new TestFaction(); var enemy = new TestFaction(); ours.Enemies.Add(enemy);
        party.MapFaction = ours; party.FoodChange = -5; party.TotalWage = 50; Hero.MainHero.Gold = gold;
        party.MemberRoster.AddToCounts(new CharacterObject(), 10, woundedCount: wounded);
        party.ItemRoster.TestAdd(new ItemObject { IsFood = true }, food);
        return new Settlement { IsCastle = true, MapFaction = enemy };
    }
    static void ConquestTests()
    {
        Try("пополнение до 90% идёт раньше осады и меняет поселение после посещения", () => {
            var b=Fresh(); var castle=ConquestWorld(gold:1000); castle.Militia=1; Settlement.All.Add(castle);
            var party=MobileParty.MainParty; party.Party.PartySizeLimit=100;
            var first=new Settlement { Name="Первая деревня", IsVillage=true, MapFaction=party.MapFaction,
                Position=new CampaignVec2 { X=1 } };
            var second=new Settlement { Name="Вторая деревня", IsVillage=true, MapFaction=party.MapFaction,
                Position=new CampaignVec2 { X=20 } };
            foreach(var place in new[] { first, second }) {
                var notable=new Hero(); notable.VolunteerTypes[0]=new CharacterObject { TestCost=17 };
                place.Notables.Add(notable); Settlement.All.Add(place);
            }
            Enable(b); HourlyTick(b);
            Check(party.TargetSettlement==first && party.DefaultBehavior==AiBehavior.GoToSettlement,
                "при 10/100 набираем бойцов раньше доступной осады");
            var services=(SettlementServices)typeof(AutopilotBehavior)
                .GetField("_services",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic).GetValue(b);
            services.LoadPasses(first.StringId+"="+CampaignTime.Now.ToHours);
            for(int hour=0; hour<6; hour++) HourlyTick(b);
            Check(party.TargetSettlement==second,
                "после посещения первой деревни выбираем другую, а не повторяем круг");
            services.LoadPasses(first.StringId+"="+CampaignTime.Now.ToHours+";"
                +second.StringId+"="+CampaignTime.Now.ToHours);
            HourlyTick(b);
            Check(party.TargetSettlement!=first,
                "после обхода доступных мест не начинаем круг заново до истечения срока");
            party.MemberRoster.AddToCounts(new CharacterObject(),80);
            HourlyTick(b);
            Check(party.TargetSettlement==castle && SiegeTarget(b)==castle,
                "на 90/100 приоритет набора закончился и вернулся поход");
        });
        Try("самостоятельно выбираем слабую крепость без предложения движка", () => {
            var b=Fresh(); var weak=ConquestWorld(); weak.Name="Слабый замок"; weak.Militia=10;
            weak.Town.GarrisonParty=new MobileParty();
            var strong=new Settlement { IsTown=true, Name="Сильный город", MapFaction=weak.MapFaction, Militia=20 };
            Settlement.All.Add(weak); Settlement.All.Add(strong);
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(strong, AiBehavior.PatrolAroundPoint,
                MobileParty.NavigationType.Default, false, false, false), 9f));
            Enable(b); HourlyTick(b);
            Check(SiegeTarget(b)==weak && MobileParty.MainParty.TargetSettlement==weak,
                "цель осады создана модом, город свыше 1.5x отвергнут");
        });
        Try("отказ от осады записывает точный предел сил", () => {
            var b=Fresh(); var castle=ConquestWorld(); castle.Name="Пограничный замок";
            castle.Militia=10; Settlement.All.Add(castle);
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(castle, AiBehavior.PatrolAroundPoint,
                MobileParty.NavigationType.Default, false, false, false), 2f));
            Enable(b); HourlyTick(b);
            Check(SiegeTarget(b)==castle && MobileParty.MainParty.TargetSettlement==castle,
                "слабый замок сначала выбран");
            castle.Militia=16; for(int hour=0; hour<6; hour++) HourlyTick(b);
            Check(AutopilotLog.Lines.Any(l => l.Contains("ПОХОД: прекращаем цель «Пограничный замок»")
                && l.Contains("защитники 16.0 > предел 15.0")
                && l.Contains("далее PatrolAroundPoint")),
                "после роста обороны записаны обе силы и следующий приказ");
        });
        Try("близкий вражеский отряд входит в риск осады", () => {
            var b=Fresh(); var castle=ConquestWorld(); castle.Militia=10; Settlement.All.Add(castle);
            var relief=new MobileParty { MapFaction=castle.MapFaction, Position=castle.Position };
            relief.MemberRoster.AddToCounts(new CharacterObject(), 6); MobileParty.All.Add(relief);
            Enable(b); HourlyTick(b);
            Check(SiegeTarget(b)==null && MobileParty.MainParty.TargetSettlement!=castle,
                "подкрепление делает защиту сильнее 1.5x");
        });
        Try("для допустимой осады сначала собираем доступную армию", () => {
            var b=Fresh(); var castle=ConquestWorld(); castle.Militia=20; Settlement.All.Add(castle);
            var kingdom=new Kingdom(); kingdom.Enemies.Add(castle.MapFaction);
            MobileParty.MainParty.MapFaction=kingdom; Clan.PlayerClan.Kingdom=kingdom; Clan.PlayerClan.Influence=10;
            var ally=new MobileParty { MapFaction=kingdom }; ally.MemberRoster.AddToCounts(new CharacterObject(), 10);
            MobileParty.MainParty.ThinkParamsCache.PossibleArmyMembersUponArmyCreation.Add(ally);
            Enable(b); HourlyTick(b);
            Check(MobileParty.MainParty.Army!=null && ally.Army==MobileParty.MainParty.Army
                && Clan.PlayerClan.Influence==0,
                "20 защитников превышают 1.5x отряда из 10, армия из 20 допустима");
        });
        Try("истощённый отряд не начинает самостоятельную осаду", () => {
            var b=Fresh(); var castle=ConquestWorld(food:1); castle.Militia=1; Settlement.All.Add(castle);
            Enable(b); HourlyTick(b);
            Check(SiegeTarget(b)==null && MobileParty.MainParty.TargetSettlement!=castle,
                "семидневный запас остаётся обязательным");
        });
        Try("стратегический аудит пишет риск, но не меняет приказ", () => {
            var b=Fresh(); var castle=ConquestWorld(); castle.Militia=24;
            var garrison=new MobileParty(); garrison.MemberRoster.AddToCounts(new CharacterObject(), 30);
            castle.Town.GarrisonParty=garrison;
            var enemy=new MobileParty { MapFaction=castle.MapFaction, Position=castle.Position };
            enemy.MemberRoster.AddToCounts(new CharacterObject(), 45);
            MobileParty.All.Add(enemy);
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(castle, AiBehavior.BesiegeSettlement,
                MobileParty.NavigationType.Default, false, false, false), 3f));
            Enable(b, AutopilotBehavior.Mode.Observe); HourlyTick(b);
            Check(AutopilotLog.Lines.Any(l => l.Contains("СТРАТЕГИЯ [только наблюдение]")
                && l.Contains("гарнизон 30") && l.Contains("ополчение 24")
                && l.Contains("вражеских партий рядом 1 (сила 45)")),
                "в журнале раздельно видны гарнизон, ополчение и видимый враг");
            Check(SiegeTarget(b) == null && MobileParty.MainParty.TargetSettlement != castle,
                "наблюдение не отдаёт приказ осады");
        });
        Try("scoreboard result precedes actual simulation finish", () => {
            var b=Fresh(); ConquestWorld(); Enable(b); Hero.MainHero.IsWounded=true;
            PlayerEncounter.Current=new PlayerEncounter(); MobileParty.MainParty.MapEvent=PlayerEncounter.Battle=new MapEvent();
            var screen=(SandBox.View.Map.MapScreen)((MapState)Game.Current.GameStateManager.ActiveState).Handler;
            var vm=new SandBox.GauntletUI.Map.SimulationScoreboard { IsOver=true }; vm.Simulation.IsSimulationFinished=false;
            screen.SimulationView=new SandBox.GauntletUI.Map.GauntletMapBattleSimulationView(vm);
            var menu=Menu("encounter","attack",()=>{}); menu.Options[0].IsEnabled=false;
            menu.Options.Add(new GameMenuOption { IdString="str_order_attack", IsEnabled=true, Consequence=()=>screen.IsInBattleSimulation=true });
            Show(menu); b.PollState(); b.PollState();
            Check(vm.Exits==0,"do not press Done while native simulation is still finishing");
            vm.Simulation.IsSimulationFinished=true; b.PollState(); b.PollState();
            Check(vm.Exits==1,"press Done once after native simulation completion");
        });
        foreach(string boundary in new[] { "forced", "escape", "healthy", "modal", "observe" })
        Try("unavoidable surrender " + boundary, () => {
            var b=Fresh(); Enable(b,boundary=="observe" ? AutopilotBehavior.Mode.Observe : AutopilotBehavior.Mode.Apply);
            Hero.MainHero.IsWounded=true;
            MobileParty.MainParty.Party.NumberOfHealthyMembers=boundary=="healthy" ? 1 : 0;
            if(boundary=="healthy") MobileParty.MainParty.MemberRoster.AddToCounts(new CharacterObject(),1);
            PlayerEncounter.Current=new PlayerEncounter(); MobileParty.MainParty.MapEvent=PlayerEncounter.Battle=new MapEvent();
            int surrendered=0;
            var menu=Menu("encounter","attack",()=>{}); menu.Options[0].IsEnabled=false;
            menu.Options.Add(new GameMenuOption { IdString="surrender", IsEnabled=true, Consequence=()=> { surrendered++; Hero.MainHero.IsPrisoner=true; } });
            if(boundary=="escape") menu.Options.Add(new GameMenuOption { IdString="leave_soldiers_behind", IsEnabled=true, Consequence=()=>{} });
            Show(menu); TaleWorlds.Library.InformationManager.TestInquiryActive=boundary=="modal"; b.PollState();
            Check(surrendered==(boundary=="forced" ? 1 : 0),"surrender only as sole option: " + boundary);
            if(boundary=="forced") Check(b.CurrentMode==AutopilotBehavior.Mode.Apply,"captivity keeps autopilot active");
        });
        foreach (string boundary in new[] { "apply", "observe", "inquiry", "disabled" })
        Try("raid warning continue " + boundary, () => {
            var b=Fresh(); var w=MakeWorld(prisoners:false);
            Enable(b, boundary=="observe" ? AutopilotBehavior.Mode.Observe : AutopilotBehavior.Mode.Apply);
            PlayerEncounter.Current=new PlayerEncounter();
            MobileParty.MainParty.CurrentSettlement=w.Place;
            PlayerEncounter.EncounterSettlement=w.Place;
            int clicks=0;
            var menu=Menu("encounter_interrupted_raid_started", "encounter_interrupted_raid_started_leave", () => {
                clicks++; Show(Menu("join_encounter", "leave", () => {}));
            });
            menu.Options[0].IsEnabled=boundary!="disabled";
            Show(menu); TaleWorlds.Library.InformationManager.TestInquiryActive=boundary=="inquiry";
            b.PollState();
            Check(clicks==(boundary=="apply" ? 1 : 0), "raid notice respects " + boundary);
            if (boundary=="apply") Check(b.CurrentMode==AutopilotBehavior.Mode.Apply && MenuDriver.CurrentMenuId=="join_encounter", "raid notice reaches native encounter without disabling");
        });
        foreach (bool wounded in new[] { true, false })
        Try("wounded hero sends troops through native option", () => {
            var b = Fresh(); ConquestWorld(); Enable(b);
            Hero.MainHero.IsWounded = wounded;
            PlayerEncounter.Current = new PlayerEncounter();
            MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = new MapEvent();
            var screen = (SandBox.View.Map.MapScreen)((MapState)Game.Current.GameStateManager.ActiveState).Handler;
            var vm = new SandBox.GauntletUI.Map.SimulationScoreboard();
            screen.SimulationView = new SandBox.GauntletUI.Map.GauntletMapBattleSimulationView(vm);
            int sends = 0;
            var menu = Menu("encounter", "attack", () => {}); menu.Options[0].IsEnabled = false;
            menu.Options.Add(new GameMenuOption { IdString = "str_order_attack", IsEnabled = true, Consequence = () => { sends++; screen.IsInBattleSimulation = true; } });
            Show(menu); b.PollState();
            Check(sends == (wounded ? 1 : 0), "simulation fallback only for wounded hero");
            if (wounded) {
                b.PollState(); Check(vm.Exits == 0, "ongoing simulation is not closed");
                vm.IsOver = true;
                TaleWorlds.Library.InformationManager.TestInquiryActive = true;
                b.PollState(); Check(vm.Exits == 0, "modal window blocks simulation confirmation");
                TaleWorlds.Library.InformationManager.TestInquiryActive = false;
                b.PollState(); b.PollState();
                Check(vm.Exits == 1, "finished owned simulation confirmed exactly once");
            }
        });
        Try("native send troops refusal is respected", () => {
            var b = Fresh(); ConquestWorld(); Enable(b); Hero.MainHero.IsWounded = true;
            PlayerEncounter.Current = new PlayerEncounter(); MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = new MapEvent();
            int sends = 0; var menu = Menu("encounter", "attack", () => {}); menu.Options[0].IsEnabled = false;
            menu.Options.Add(new GameMenuOption { IdString = "str_order_attack", IsEnabled = false, Consequence = () => sends++ });
            Show(menu); b.PollState(); Check(sends == 0, "cannot bypass low morale or no healthy troops");
        });
        Try("startup hiring preserves seven days of future wages", () => {
            var b = Fresh(); var w = MakeWorld(gold: 1000, prisoners: false);
            SetLimit("MinGoldReserve", 0); MobileParty.MainParty.TotalWage = 0;
            MobileParty.MainParty.ItemRoster.TestAdd(w.Grain, 200); w.Recruit.TestCost = 100;
            int initial = MobileParty.MainParty.MemberRoster.TotalManCount;
            Campaign.Current.Models.PartyWageModel.TestTotalWage = (party, roster) => (roster.TotalManCount - initial) * 50;
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(CampaignEventDispatcher.Recruited.Count == 2 && Hero.MainHero.Gold == 800,
                "1000 gold hires two, but not third: remaining gold covers new wages for seven days");
        });
        foreach (string terminal in new[] { "village_player_raid_ended", "village_raid_ended_leaded_by_someone_else", "village_raid_diplomatically_ended", "village_looted" })
        Try("raid terminal after encounter teardown: " + terminal, () => {
            var b = Fresh(); var village = ConquestWorld(); village.IsCastle = false; village.IsVillage = true;
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(village, AiBehavior.RaidSettlement, MobileParty.NavigationType.Default, false, false, false), 9f));
            Enable(b); HourlyTick(b);
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = village;
            Show(Menu("village", "hostile_action", () => {})); b.PollState();
            PlayerEncounter.Finish(); MobileParty.MainParty.CurrentSettlement = null;
            MobileParty.MainParty.DefaultBehavior = AiBehavior.Hold;
            string option = terminal.Contains("diplomatically") || terminal == "village_looted" ? "leave" : "continue";
            int clicks = 0; Show(Menu(terminal, option, () => clicks++)); b.PollState();
            Check(clicks == 1 && b.CurrentMode == AutopilotBehavior.Mode.Apply, "cleared encounter still closes " + terminal);
        });
        foreach (string kind in new[] { "village", "naval", "raid", "castle" })
        Try("field battle location classification: " + kind, () => {
            var b = Fresh(); var place = ConquestWorld(); Enable(b);
            place.IsCastle = kind == "castle"; place.IsVillage = !place.IsCastle;
            var battle = new MapEvent { MapEventSettlement = place, IsFieldBattle = kind != "raid", IsRaid = kind == "raid", IsNavalMapEvent = kind == "naval" };
            MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = battle; PlayerEncounter.Current = new PlayerEncounter();
            Check(AutopilotBehavior.IsSupportedFieldBattleEncounter(MobileParty.MainParty) == (kind == "village"), "only land field battle at village is supported: " + kind);
            if (kind == "village") Check(b.TryEnable(AutopilotBehavior.Mode.Apply, out _), "F11 can resume a village field battle");
        });
        Try("lord dialogue at village uses combat rules", () => {
            var b = Fresh(); var village = ConquestWorld(); village.IsCastle = false; village.IsVillage = true; Enable(b);
            var lord = new MobileParty { MapFaction = village.MapFaction };
            PlayerEncounter.Current = new PlayerEncounter { Defender = true }; PlayerEncounter.EncounteredMobileParty = lord;
            PlayerEncounter.EncounterSettlement = village;
            MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = new MapEvent { MapEventSettlement = village, IsFieldBattle = true };
            var c = Campaign.Current.ConversationManager; c.ConversationParty = lord; c.IsConversationInProgress = true;
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = "545", IsClickable = true });
            b.PollDialogs();
            Check(c.Selected.SequenceEqual(new[] { "545" }) && !AutopilotLog.Lines.Any(l => l.Contains("случайно выбрана")), "lord at village goes through fixed combat conversation");
        });
        Try("истощились по пути к крепости — уход к снабжению", () => {
            var b = Fresh(); var castle = ConquestWorld(food: 1); Enable(b);
            MobileParty.MainParty.TargetSettlement = castle; MobileParty.MainParty.DefaultBehavior = AiBehavior.BesiegeSettlement;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = castle;
            Show(Menu("castle_outside", "town_outside_leave", () => PlayerEncounter.Finish())); b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[] { "town_outside_leave" }) && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                "у ворот ушли штатно, автопилот продолжает снабжение");
        });
        Try("нельзя исполнить армейскую цель без приглашений", () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            typeof(AutopilotBehavior).GetMethod("ApplyDecision", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                .Invoke(b, new object[] { MobileParty.MainParty, new AIBehaviorData(castle, AiBehavior.BesiegeSettlement, MobileParty.NavigationType.Default, true, false, false), 9f });
            Check(MobileParty.MainParty.DefaultBehavior != AiBehavior.BesiegeSettlement, "не превращаем армейскую цель в одиночный поход после отказа сбора");
        });
        Try("пустая армия после изменения доступности распускается", () => {
            var b = Fresh(); var castle = ConquestWorld(); var kingdom = new Kingdom(); kingdom.Enemies.Add(castle.MapFaction);
            MobileParty.MainParty.MapFaction = kingdom; Clan.PlayerClan.Influence = 10;
            var ally = new MobileParty { MapFaction = kingdom }; MobileParty.MainParty.ThinkParamsCache.PossibleArmyMembersUponArmyCreation.Add(ally);
            kingdom.AfterCreate = () => ally.Army = new Army { LeaderParty = ally };
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(castle, AiBehavior.BesiegeSettlement, MobileParty.NavigationType.Default, true, false, false), 9f));
            Enable(b); HourlyTick(b);
            Check(MobileParty.MainParty.Army == null && Clan.PlayerClan.Influence == 10, "не ведём пустую армию и не платим за чужую");
        });
        foreach (bool bandit in new[] { false, true })
        Try("нападающий противник открывает бой вместо случайного разговора", () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            var attacker = new MobileParty { MapFaction = castle.MapFaction, IsBandit = bandit };
            PlayerEncounter.Current = new PlayerEncounter { Defender = true }; PlayerEncounter.EncounteredMobileParty = attacker;
            var c = Campaign.Current.ConversationManager; c.ConversationParty = attacker; c.IsConversationInProgress = true;
            string id = bandit ? "bandit_start_defender_1" : "545";
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = id, IsClickable = true });
            b.PollDialogs(); Check(c.Selected.SequenceEqual(new[] { id }), "защита от нападающего, бандит " + bandit);
        });
        Try("полевая миссия внутри союзной армии поддержана", () => {
            var b = Fresh(); ConquestWorld(); Enable(b);
            MobileParty.MainParty.Army = new Army { LeaderParty = new MobileParty() };
            var battle = new MapEvent(); MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = battle;
            PlayerEncounter.Current = new PlayerEncounter();
            Check(AutopilotBehavior.IsSupportedFieldBattleEncounter(MobileParty.MainParty), "реальный бой участника армии разрешён");
        });
        foreach (bool supplied in new[] { true, false })
        Try("цель завоевания выше патруля, снабжение выше истощённого похода", () => {
            var b = Fresh(); var castle = ConquestWorld(food: supplied ? 35 : 1);
            var town = new Settlement { IsTown = true, MapFaction = MobileParty.MainParty.MapFaction };
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(castle, AiBehavior.BesiegeSettlement, MobileParty.NavigationType.Default, false, false, false), 2f));
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(town, AiBehavior.PatrolAroundPoint, MobileParty.NavigationType.Default, false, false, false), 9f));
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(town, AiBehavior.GoToSettlement, MobileParty.NavigationType.Default, false, false, false), 1f));
            Enable(b); HourlyTick(b);
            Check(supplied ? (SiegeTarget(b) == castle && MobileParty.MainParty.TargetSettlement == castle)
                           : (SiegeTarget(b) == null && MobileParty.MainParty.TargetSettlement == town),
                "приоритет поход/снабжение, обеспечены " + supplied);
            var ai = Campaign.Current.Models.MobilePartyAIModel; ai.NextBehavior = AiBehavior.EngageParty;
            ai.NextTarget = new MobileParty { IsBandit = true }; ai.NextScore = 5;
            HourlyTick(b);
            Check(supplied ? (SiegeTarget(b) == castle && MobileParty.MainParty.TargetSettlement == castle)
                           : (SiegeTarget(b) == null && MobileParty.MainParty.TargetSettlement == town),
                "до следующего пересчёта бандиты не перехватывают поход или снабжение");
        });
        Try("сплочённость своей армии поддерживается штатным расчётом", () => {
            var b = Fresh(); ConquestWorld(); Enable(b);
            var army = new Army { LeaderParty = MobileParty.MainParty, Cohesion = 40 }; MobileParty.MainParty.Army = army;
            HourlyTick(b); Check(army.BoostChecks == 1, "при низкой сплочённости вызван штатный ThinkAboutCohesionBoost");
        });
        Try("рейд штатной цели проходит через меню и ожидание", () => {
            var b = Fresh(); var village = ConquestWorld(); village.IsCastle = false; village.IsVillage = true;
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(village, AiBehavior.RaidSettlement, MobileParty.NavigationType.Default, false, false, false), 9f));
            Enable(b); HourlyTick(b);
            Check(MobileParty.MainParty.DefaultBehavior == AiBehavior.RaidSettlement, "штатная цель рейда исполнена");
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = village;
            var wait = new GameMenu { StringId = "raiding_village", IsWaitMenu = true };
            Show(Menu("village", "hostile_action", () => Show(Menu("village_hostile_action", "raid_village", () => Show(wait)))));
            b.PollState(); b.PollState(); b.PollState();
            Check(wait.IsWaitActive && b.CurrentMode == AutopilotBehavior.Mode.Apply, "рейд запущен через штатные кнопки, время идёт");
            Show(Menu("village_player_raid_ended", "continue", () => {})); b.PollState();
            Check(MenuContext.Invoked.LastOrDefault() == "continue", "завершение рейда подтверждено");
        });
        Try("встреча в собственной армии не выключает поход", () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            MobileParty.MainParty.Army = new Army { LeaderParty = MobileParty.MainParty };
            var lord = new MobileParty { MapFaction = castle.MapFaction };
            MobileParty.MainParty.TargetParty = lord; MobileParty.MainParty.DefaultBehavior = AiBehavior.EngageParty;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty = lord;
            b.PollState(); Check(b.CurrentMode == AutopilotBehavior.Mode.Apply, "армия ждёт разговора с целью");
        });
        foreach (float influence in new[] { 10f, 9f })
        Try("сбор армии: влияние " + influence, () => {
            var b = Fresh(); var castle = ConquestWorld(); var kingdom = new Kingdom(); kingdom.Enemies.Add(castle.MapFaction);
            MobileParty.MainParty.MapFaction = kingdom; Clan.PlayerClan.Influence = influence; Clan.PlayerClan.Kingdom = kingdom;
            var ally = new MobileParty { MapFaction = kingdom };
            MobileParty.MainParty.ThinkParamsCache.PossibleArmyMembersUponArmyCreation.Add(ally);
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(castle, AiBehavior.BesiegeSettlement, MobileParty.NavigationType.Default, true, false, false), 9f));
            Enable(b); HourlyTick(b);
            if (influence >= 10)
            {
                Check(MobileParty.MainParty.Army != null && ally.Army == MobileParty.MainParty.Army && Clan.PlayerClan.Influence == 0,
                    "армия создана с приглашённым союзником и оплатой влиянием");
                ally.AttachedTo = MobileParty.MainParty; b.PollState();
                Check(MobileParty.MainParty.TargetSettlement == castle && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                    "собранная армия продолжает наступление");
            }
            else Check(MobileParty.MainParty.Army == null && Clan.PlayerClan.Influence == influence, "нельзя создать неоплаченную армию");
        });
        Try("партия в армии союзника продолжает следование", () => {
            var b = Fresh(); ConquestWorld(); Enable(b);
            MobileParty.MainParty.Army = new Army { LeaderParty = new MobileParty() };
            MobileParty.MainParty.AttachedTo = MobileParty.MainParty.Army.LeaderParty;
            b.PollState();
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply && Campaign.Current.TimeControlMode != CampaignTimeControlMode.Stop,
                "следование лидеру не выключает автопилот и продвигает время");
        });
        foreach (bool mercy in new[] { true, false })
        Try("после захвата: милость либо разграбление", () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            MobileParty.MainParty.TargetSettlement = castle; MobileParty.MainParty.DefaultBehavior = AiBehavior.BesiegeSettlement;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = castle;
            Show(Menu("castle_outside", "town_besiege", () => {})); b.PollState(); MenuContext.Invoked.Clear();
            var aftermath = new GameMenu { StringId = "menu_settlement_taken_player_leader" };
            aftermath.Options.Add(new GameMenuOption { IdString = "menu_settlement_taken_show_mercy", IsEnabled = mercy });
            aftermath.Options.Add(new GameMenuOption { IdString = "menu_settlement_taken_pillage" });
            Show(aftermath); b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[] { mercy ? "menu_settlement_taken_show_mercy" : "menu_settlement_taken_pillage" }), "последствия захвата по решению владельца, милость " + mercy);
        });
        Try("бандиты не отвлекают от готового наступления", () => {
            var b = Fresh(); var castle = ConquestWorld();
            var ai = Campaign.Current.Models.MobilePartyAIModel;
            ai.NextBehavior = AiBehavior.EngageParty; ai.NextTarget = new MobileParty { IsBandit = true }; ai.NextScore = 9f;
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(castle, AiBehavior.BesiegeSettlement, MobileParty.NavigationType.Default, false, false, false), 3f));
            Enable(b); HourlyTick(b);
            Check(SiegeTarget(b) == castle && MobileParty.MainParty.TargetSettlement == castle,
                "доступная военная цель выбрана прежде погони");
        });
        Try("истощение осады вызывает штатный отход", () => {
            var b = Fresh(); var castle = ConquestWorld(food: 1); Enable(b);
            var siege = new SiegeEvent { BesiegedSettlement = castle }; siege.BesiegerCamp.LeaderParty = MobileParty.MainParty;
            siege.BesiegerCamp.IsReadyToBesiege = true; MobileParty.MainParty.SiegeEvent = siege;
            var wait = new GameMenu { StringId = "menu_siege_strategies", IsWaitMenu = true };
            wait.Options.Add(new GameMenuOption { IdString = "menu_siege_strategies_lead_assault" });
            wait.Options.Add(new GameMenuOption { IdString = "menu_siege_strategies_leave" }); Show(wait); b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[] { "menu_siege_strategies_leave" }), "при нехватке еды уходим пополняться вместо штурма");
        });
        foreach (int shortage in new[] { 0, 1, 2, 3 })
        Try("готовность к наступлению " + shortage, () => {
            var b = Fresh(); var castle = ConquestWorld(shortage == 1 ? 34 : 35, shortage == 2 ? 349 : 350, shortage == 3 ? 4 : 3);
            var town = new Settlement { IsTown = true, MapFaction = MobileParty.MainParty.MapFaction };
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(castle, AiBehavior.BesiegeSettlement, MobileParty.NavigationType.Default, false, false, false), 9f));
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(town, AiBehavior.GoToSettlement, MobileParty.NavigationType.Default, false, false, false), 2f));
            Enable(b); HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement == (shortage == 0 ? castle : town), "порог 7/7/70, нехватка " + shortage);
        });
        // 18.09, живой прогон 19:27:57: сторож движения поймал застревание и записал
        // состояние — IsDisabled=False, DoNotMakeNewDecisions=False, поведение
        // BesiegeSettlement, ни армии, ни встречи, ни поселения. То есть движку ничто
        // не мешало, и смена поведения Hold → BesiegeSettlement движения тоже не дала.
        // Причина в самом ванильном приказе: SetMoveBesiegeSettlement (104002-104012)
        // НЕ ставит ни TargetPosition, ни MoveTargetPoint, тогда как рейд (103994-103999),
        // поездка (103923-103931), патруль и погоня — ставят. NPC-партию под осадным
        // приказом ведёт тик ИИ, партия игрока просто стоит. Отсюда и «любит грабить
        // деревни»: рейд уезжает, осада — нет. Едем к крепости обычным приказом, а
        // осаду начинает меню у ворот, как это делает человек.
        Try("к крепости едем обычным приказом, а не осадным", () => {
            var b=Fresh(); var castle=ConquestWorld(gold:1000); castle.Militia=1; Settlement.All.Add(castle);
            var party=MobileParty.MainParty; party.Party.PartySizeLimit=10;
            Enable(b); HourlyTick(b);
            Check(party.TargetSettlement==castle && party.DefaultBehavior==AiBehavior.GoToSettlement,
                "приказ, который реально двигает партию игрока");
            int visits=TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.VisitCalls;
            HourlyTick(b); HourlyTick(b);
            Check(TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.VisitCalls==visits,
                "цель считается прежней: приказ не перевыдаётся каждый час");
            Check(!AutopilotLog.Lines.Any(l => l.Contains("ЗАСТРЯЛИ")),
                "пока едем, сторож движения не срабатывает");
        });
        Try("доехали до крепости — жмём осаду штатным пунктом", () => {
            var b=Fresh(); var castle=ConquestWorld(gold:1000); castle.Name="Замок Аб Комер";
            castle.Militia=1; Settlement.All.Add(castle);
            MobileParty.MainParty.Party.PartySizeLimit=10;
            Enable(b); HourlyTick(b);
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=castle;
            bool besieged=false;
            Show(Menu("castle_outside", "town_besiege", () => besieged=true));
            b.PollState();
            Check(besieged, "у ворот вражеской крепости осада начинается штатным пунктом меню");
        });

        // Стояние на месте 18.09 (журнал 14:43 и 18:38). Движок принимает приказ
        // осады и ставит DefaultBehavior, но движение задаёт только сеттер
        // DefaultBehavior — и только когда значение СМЕНИЛОСЬ (MobileParty 100723);
        // сам SetMoveBesiegeSettlement (104002-104012) сбрасывает параметры движения
        // и ни TargetPosition, ни MoveTargetPoint не выставляет, в отличие от
        // SetMoveGoToSettlement (103923-103931). Мод же, увидев «цель та же»,
        // приказ не перевыдавал — и партия стояла часами при живом времени.
        Try("приказ выдан, а партия стоит: мод замечает и перевыдаёт", () => {
            var b=Fresh(); var castle=ConquestWorld(gold:1000); castle.Militia=1; Settlement.All.Add(castle);
            var party=MobileParty.MainParty; party.Party.PartySizeLimit=10;
            Enable(b); HourlyTick(b);
            Check(SiegeTarget(b)==castle && party.TargetSettlement==castle,
                "поход к крепости назначен");
            int holds=party.HoldCalls;
            for(int i=0;i<8;i++) HourlyTick(b);
            Check(AutopilotLog.Lines.Any(l => l.Contains("ЗАСТРЯЛИ")),
                "шесть часов без движения при живом времени замечены и записаны");
            Check(party.HoldCalls>holds,
                "поведение сброшено в Hold — иначе движок примет приказ за уже выданный и движение не вернёт");
        });
        Try("недостижимая цель снимается, а не держится вечно", () => {
            var b=Fresh(); var castle=ConquestWorld(gold:1000); castle.Militia=1; Settlement.All.Add(castle);
            var party=MobileParty.MainParty; party.Party.PartySizeLimit=10;
            Enable(b); HourlyTick(b);
            for(int i=0;i<24;i++) HourlyTick(b);
            Check(AutopilotLog.Lines.Any(l => l.Contains("ЗАСТРЯЛИ") && l.Contains("снята")),
                "после двух безуспешных перевыдач цель снята с записью в журнал");
            Check(party.TargetSettlement!=castle || party.DefaultBehavior!=AiBehavior.BesiegeSettlement,
                "мод больше не держится за цель, до которой не доехал");
        });
        Try("партия едет — сторож молчит", () => {
            var b=Fresh(); var castle=ConquestWorld(gold:1000); castle.Militia=1; Settlement.All.Add(castle);
            var party=MobileParty.MainParty; party.Party.PartySizeLimit=10;
            Enable(b); HourlyTick(b);
            for(int i=1;i<=12;i++){ party.Position=new CampaignVec2 { X=i*3f }; HourlyTick(b); }
            Check(!AutopilotLog.Lines.Any(l => l.Contains("ЗАСТРЯЛИ")),
                "пока партия двигается, сторож не вмешивается");
        });
        // 18.09 19:54:27, живой прогон: во время осады Замка Астер выпало событие
        // «Подкоп» (IncidentTrigger.DuringSiege), и автопилот встал на 22 секунды,
        // пока владелец не нажал сам. Причина не в разборе события, а в порядке
        // опроса: осадный обработчик стоит РАНЬШЕ и при окне поверх карты возвращает
        // «занято», поэтому до разбора события очередь не доходила.
        Try("событие во время осады разбирается, а не ждёт человека", () => {
            var b=Fresh(); var castle=ConquestWorld(); castle.Name="Замок Астер"; Enable(b);
            var party=MobileParty.MainParty;
            party.TargetSettlement=castle; party.DefaultBehavior=AiBehavior.BesiegeSettlement;
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=castle;
            var siege=new SiegeEvent { BesiegedSettlement=castle }; siege.BesiegerCamp.LeaderParty=party;
            party.SiegeEvent=siege;
            Show(new GameMenu { StringId="menu_siege_strategies", IsWaitMenu=true, IsWaitActive=true });
            var incident=new TaleWorlds.CampaignSystem.Incidents.Incident {
                StringId="incident_siege_tunnel", Title=new TaleWorlds.Localization.TextObject("Подкоп")
            };
            int selected=-1;
            incident.Options.Add((new TaleWorlds.Localization.TextObject("Удвоить плату"),
                new System.Collections.Generic.List<TaleWorlds.Localization.TextObject>{new("Дорого")}, () => selected=0));
            incident.Options.Add((new TaleWorlds.Localization.TextObject("Обычными методами"),
                new System.Collections.Generic.List<TaleWorlds.Localization.TextObject>{new("Ничего")}, () => selected=1));
            Screen.IncidentView=new SandBox.View.Map.MapIncidentView(incident); Screen.IsMapIncidentActive=true;
            b.PollState();
            Check(selected>=0 && !Screen.IsMapIncidentActive,
                "окно события во время осады разобрано модом, а не оставлено человеку");
        });
        Try("осада: штатная стратегия, ожидание готовности и штурм", () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            MobileParty.MainParty.TargetSettlement = castle; MobileParty.MainParty.DefaultBehavior = AiBehavior.BesiegeSettlement;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = castle;
            var siege = new SiegeEvent { BesiegedSettlement = castle }; siege.BesiegerCamp.LeaderParty = MobileParty.MainParty;
            int assaults = 0;
            var wait = new GameMenu { StringId = "menu_siege_strategies", IsWaitMenu = true };
            wait.Options.Add(new GameMenuOption { IdString = "menu_siege_strategies_lead_assault", Consequence = () => assaults++ });
            Show(Menu("castle_outside", "town_besiege", () => { MobileParty.MainParty.SiegeEvent = siege; Show(wait); }));
            b.PollState(); b.PollState();
            Check(siege.BesiegerCamp.SiegeStrategy == DefaultSiegeStrategies.PrepareAssault && wait.IsWaitActive && assaults == 0,
                "осада начата, машины отданы штатной стратегии, раннего штурма нет");
            siege.BesiegerCamp.SetSiegeStrategy(DefaultSiegeStrategies.Custom);
            b.PollState();
            Check(siege.BesiegerCamp.SiegeStrategy == DefaultSiegeStrategies.PrepareAssault,
                "ручная стратегия после повторного открытия осады не оставляет автопилот без строительства");
            siege.BesiegerCamp.IsReadyToBesiege = true; b.PollState();
            Check(assaults == 1 && b.CurrentMode == AutopilotBehavior.Mode.Apply, "готовность AI запускает полноценный штурм");
            var battle = new MapEvent { MapEventSettlement = castle, IsSiegeAssault = true, PlayerSide = BattleSideEnum.Attacker };
            MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = battle;
            Check(b.IsOwnedOperationBattle(MobileParty.MainParty), "наша наступательная осада поддержана боевой миссией");
        });
        Try("осада: армия деблокирования получает автоматическую атаку, затем осада продолжается", () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            var party = MobileParty.MainParty;
            party.TargetSettlement = castle; party.DefaultBehavior = AiBehavior.BesiegeSettlement;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = castle;
            var siege = new SiegeEvent { BesiegedSettlement = castle }; siege.BesiegerCamp.LeaderParty = party;
            var wait = new GameMenu { StringId="menu_siege_strategies", IsWaitMenu=true };
            Show(Menu("castle_outside", "town_besiege", () => { party.SiegeEvent=siege; Show(wait); }));
            b.PollState(); b.PollState();

            // Live 20.09: during the attack on the besieger camp the engine had
            // already exposed EncounteredBattle, while Battle was still null.
            int attacks = 0;
            var relief = new MapEvent { MapEventSettlement=castle, IsSiegeOutside=true, PlayerSide=BattleSideEnum.Defender };
            party.MapEvent = relief; PlayerEncounter.Battle = null; PlayerEncounter.EncounteredBattle = relief;
            Show(Menu("encounter", "attack", () => attacks++));
            b.PollState();
            Check(attacks==1 && b.CurrentMode==AutopilotBehavior.Mode.Apply,
                "деблокирующая армия атакована штатной кнопкой, автопилот не выключен");

            party.MapEvent=null; PlayerEncounter.Current=null; PlayerEncounter.Battle=null; PlayerEncounter.EncounteredBattle=null;
            party.SiegeEvent=siege; PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=castle;
            Show(wait); b.PollState();
            Check(wait.IsWaitActive && b.CurrentMode==AutopilotBehavior.Mode.Apply,
                "после полевого боя ожидание строительства осады возобновлено");
        });
        foreach (bool wounded in new[] { false, true })
        Try("после победы у стен: восстановление=" + wounded, () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            var party = MobileParty.MainParty;
            var siege = new SiegeEvent { BesiegedSettlement=castle }; siege.BesiegerCamp.LeaderParty=party;
            party.SiegeEvent=siege;
            PlayerEncounter.Current=null; PlayerEncounter.Battle=null; PlayerEncounter.EncounteredBattle=null;
            Hero.MainHero.IsWounded=wounded;
            int continued=0, left=0;
            var menu=Menu("continue_siege_after_attack", "continue_siege", () => continued++);
            menu.Options.Add(new GameMenuOption { IdString="leave_siege", Consequence=() => left++ });
            Show(menu); b.PollState();
            Check(b.CurrentMode==AutopilotBehavior.Mode.Apply && continued==(wounded ? 0 : 1) && left==(wounded ? 1 : 0),
                "после добычи без PlayerEncounter выбран штатный исход осады по готовности");
        });
        foreach (string location in new[] { "none", "village", "castle" })
        Try("осада: атакующий патруль после разговора: " + location, () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            var party = MobileParty.MainParty;
            party.TargetSettlement = castle; party.DefaultBehavior = AiBehavior.BesiegeSettlement;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = castle;
            var siege = new SiegeEvent { BesiegedSettlement = castle }; siege.BesiegerCamp.LeaderParty = party;
            party.SiegeEvent = siege;
            var field = new MapEvent { MapEventSettlement=location == "castle" ? castle : location == "village" ? new Settlement { IsVillage=true } : null, IsFieldBattle=true, PlayerSide=BattleSideEnum.Defender };
            party.MapEvent=field; PlayerEncounter.Battle=field; PlayerEncounter.EncounteredBattle=field;
            int attacks=0; Show(Menu("encounter", "attack", () => attacks++));
            b.PollState();
            Check(attacks==1 && b.CurrentMode==AutopilotBehavior.Mode.Apply,
                "патруль, атаковавший наш осадный лагерь, принят как принадлежащий операции бой");
            field.MapEventSettlement = new Settlement { IsCastle=true };
            Check(!b.IsOwnedOperationBattle(party), "бой у другой крепости не присваивается осаде");
            field.MapEventSettlement = null; field.IsNavalMapEvent = true;
            Check(!b.IsOwnedOperationBattle(party), "морской бой не присваивается сухопутной осаде");
            field.IsNavalMapEvent = false; party.SiegeEvent = null;
            Check(!b.IsOwnedOperationBattle(party), "без действующего осадного лагеря произвольный бой не присваивается");
        });
    }
}
namespace TaleWorlds.CampaignSystem.Siege
{
    public class SiegeStrategy { }
    public static class DefaultSiegeStrategies
    {
        public static SiegeStrategy PrepareAssault { get; } = new();
        public static SiegeStrategy Custom { get; } = new();
        public static System.Collections.Generic.IEnumerable<SiegeStrategy> AllAttackerStrategies => new[] { PrepareAssault, Custom };
    }
    public class BesiegerCamp
    {
        public MobileParty LeaderParty { get; set; }
        public bool IsReadyToBesiege { get; set; }
        public SiegeStrategy SiegeStrategy { get; private set; } = DefaultSiegeStrategies.Custom;
        public void SetSiegeStrategy(SiegeStrategy strategy) { SiegeStrategy = strategy; }
    }
    public class SiegeEvent
    {
        public Settlement BesiegedSettlement { get; set; }
        public BesiegerCamp BesiegerCamp { get; } = new();
        public BesiegerCamp GetSiegeEventSide(BattleSideEnum side) => BesiegerCamp;
    }
}
namespace TaleWorlds.CampaignSystem.ComponentInterfaces
{
    // Native player-led siege: Custom scores 9000, automatic strategies score 0..1.
    public class SiegeEventModel { public float GetSiegeStrategyScore(SiegeEvent siege, BattleSideEnum side, SiegeStrategy strategy) => strategy == DefaultSiegeStrategies.Custom ? 9000f : 1f; }
    public class ArmyManagementCalculationModel
    {
        public bool CanPlayerCreateArmy(out TaleWorlds.Localization.TextObject why) { why = null; return true; }
        public bool CheckPartyEligibility(MobileParty party, out TaleWorlds.Localization.TextObject why) { why = null; return party.Army == null; }
        public int CalculatePartyInfluenceCost(MobileParty leader, MobileParty party) => 10;
    }
}
namespace TaleWorlds.CampaignSystem
{
    public partial class MapEvent { public bool IsRaid { get; set; } public bool IsSallyOut { get; set; } public bool IsSiegeOutside { get; set; } }
    public class Army
    {
        public enum ArmyTypes { Besieger, Raider, Defender }
        public MobileParty LeaderParty { get; set; }
        public float Cohesion { get; set; } = 100;
        public int BoostChecks;
        private void ThinkAboutCohesionBoost() { BoostChecks++; }
    }
    public partial class Kingdom
    {
        public Action AfterCreate;
        public TaleWorlds.Library.MBReadOnlyList<Town> Fiefs { get; } = new();
        public void CreateArmy(Hero leader, Settlement target, Army.ArmyTypes type, TaleWorlds.Library.MBReadOnlyList<MobileParty> members = null)
        { MobileParty.MainParty.Army = new Army { LeaderParty = MobileParty.MainParty }; AfterCreate?.Invoke(); }
    }
}
namespace TaleWorlds.CampaignSystem.Actions
{
    public static class DisbandArmyAction { public static void ApplyByUnknownReason(Army army) { army.LeaderParty.Army = null; } }
    public static class ChangeClanInfluenceAction { public static void Apply(Clan clan, float amount) { clan.Influence += amount; } }
}
