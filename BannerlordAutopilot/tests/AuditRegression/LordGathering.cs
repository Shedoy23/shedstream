using System;
using System.Collections.Generic;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
internal static partial class Program {
 static (AutopilotBehavior Pilot, MapEvent Battle, TestFaction Faction) LordGatherWorld(float enemy=40) {
  var w=GatheringWorld(enemy);var target=PlayerEncounter.EncounteredMobileParty;
  target.IsBandit=false;target.IsLordParty=true;MobileParty.AllBanditParties.Remove(target);MobileParty.All.Add(target);
  return(w.Pilot,w.Battle,w.Bandits);
 }
 static MobileParty NearbyLord(string name,float power,float distance,TestFaction faction){
  var p=new MobileParty{Name=name,IsLordParty=true,MapFaction=faction,Position=new CampaignVec2{X=distance}};
  p.Party.MapFaction=faction;p.Party.TestStrength=power;MobileParty.All.Add(p);return p;
 }
 static void LordGatheringTests(){
  foreach(string change in new[]{"inquiry","menu","army","joined","attack-disabled"})
  Try("лорды: callback меняет контекст "+change,()=>{
   var w=LordGatherWorld();var first=NearbyLord("first",20,1,w.Faction);var next=NearbyLord("next",40,2,w.Faction);
   first.Party.TestAfterJoin=()=>{
    if(change=="inquiry")TaleWorlds.Library.InformationManager.TestInquiryActive=true;
    if(change=="menu")Show(new GameMenu{StringId="different_menu",Options={new GameMenuOption{IdString="attack"}}});
    if(change=="army")MobileParty.MainParty.Army=new Army{LeaderParty=new MobileParty()};
    if(change=="joined")PlayerEncounter.Current.IsJoinedBattle=true;
    if(change=="attack-disabled")Campaign.Current.CurrentMenuContext.GameMenu.Options[0].IsEnabled=false;
   };
   w.Pilot.PollState();Check(first.MapEvent==w.Battle&&next.MapEvent==null&&next.Position.X==2,"контекст "+change+": второй лорд не перемещён");
   Check(w.Pilot.CurrentMode==AutopilotBehavior.Mode.Off&&!MenuContext.Invoked.Contains("attack"),"контекст "+change+": сомнительный бой не запущен");
  });
  Try("лорды: callback меняет фракцию самого кандидата",()=>{
   var w=LordGatherWorld();var p=NearbyLord("changed",60,1,w.Faction);p.Party.TestAfterJoin=()=>{p.MapFaction=new TestFaction();p.Party.MapFaction=p.MapFaction;};
   w.Pilot.PollState();Check(p.MapEvent==w.Battle&&w.Pilot.CurrentMode==AutopilotBehavior.Mode.Off&&!MenuContext.Invoked.Contains("attack"),"эффект сменившего фракцию кандидата сохранён, автоматическая атака остановлена");
  });
  Try("лорды: повторное F11 не возобновляет недобранный бой",()=>{
   var w=LordGatherWorld();var first=NearbyLord("first",20,1,w.Faction);w.Pilot.PollState();
   w.Pilot.Disable("pause");Enable(w.Pilot);var next=NearbyLord("new",40,2,w.Faction);w.Pilot.PollState();
   Check(first.MapEvent==w.Battle&&next.MapEvent==null,"однократность сохраняется после выключения и включения");
  });

  Try("лорды: ближайшие целые отряды, потолок120%, ровно один добор",()=>{
   var w=LordGatherWorld();var huge=NearbyLord("huge",81,1,w.Faction);var a=NearbyLord("a",30,2,w.Faction);var b=NearbyLord("b",50,3,w.Faction);var rest=NearbyLord("rest",1,4,w.Faction);
   w.Pilot.PollState();w.Pilot.PollState();
   Check(a.MapEvent==w.Battle&&b.MapEvent==w.Battle,"подтянуты ближайшие подходящие лорды до120%");
   Check(huge.MapEvent==null&&rest.MapEvent==null,"целый слишком сильный отряд пропущен, после равенства добор прекращён");
   Check(a.Position.X==0&&b.Position.X==0&&huge.Position.X==1,"перемещены только принятые лорды");
   Check(a.Party.TestJoinCalls==1&&b.Party.TestJoinCalls==1,"нет повторного присоединения при повторе опроса");
   Check(MenuContext.Invoked.Contains("attack"),"после успешного добора используется штатная атака");
  });
  Try("лорды: считаем всех союзников в бою, армию не удваиваем",()=>{
   var w=LordGatherWorld();var main=MobileParty.MainParty;main.Army=new Army{LeaderParty=main};
   var ally=NearbyLord("attached",100,0,(TestFaction)main.MapFaction);ally.Army=main.Army;ally.AttachedTo=main;main.AttachedParties.Add(ally);ally.Party.MapEventSide=w.Battle.AttackerSide;
   var pending=NearbyLord("en route",1000,30,(TestFaction)main.MapFaction);pending.Army=main.Army;
   var huge=NearbyLord("too strong for actual side",201,1,w.Faction);var extra=NearbyLord("matched",160,2,w.Faction);
   w.Pilot.PollState();Check(extra.MapEvent==w.Battle,"союзник учтён:200 нашей стороны допускают добор160 к40");
   Check(huge.MapEvent==null,"не учитываем армию дважды или ещё не подошедшие1000силы");
  });
  Try("лорды: все уже вошедшие враги учитываются",()=>{
   var w=LordGatherWorld(60);var existing=NearbyLord("already",40,0,w.Faction);existing.Party.MapEventSide=w.Battle.DefenderSide;
   var extra=NearbyLord("extra",10,1,w.Faction);w.Pilot.PollState();Check(extra.MapEvent==null,"при равных сторонах дополнительного усиления нет");
  });
  Try("лорды: строго фракция атакованного, не все враги игрока",()=>{
   var w=LordGatherWorld();var other=new TestFaction();((TestFaction)MobileParty.MainParty.MapFaction).Enemies.Add(other);other.Enemies.Add(MobileParty.MainParty.MapFaction);
   var foreign=NearbyLord("other kingdom",60,1,other);var same=NearbyLord("same kingdom",60,2,w.Faction);w.Pilot.PollState();
   Check(foreign.MapEvent==null&&same.MapEvent==w.Battle,"другая воюющая фракция не подтянута");
  });
  Try("лорды: native запрет вступления соблюдается",()=>{
   var w=LordGatherWorld();var denied=NearbyLord("denied",60,1,w.Faction);w.Battle.TestDisallowed.Add(denied.Party);var accepted=NearbyLord("accepted",60,2,w.Faction);w.Pilot.PollState();
   Check(denied.MapEvent==null&&accepted.MapEvent==w.Battle,"CanPartyJoinBattle проверен для кандидата");
  });
  Try("лорды: не забираем занятые или защищённые отряды",()=>{
   var w=LordGatherWorld();var rejected=new List<MobileParty>();
   Action<Action<MobileParty>> reject=set=>{var p=NearbyLord("rejected",1,1,w.Faction);set(p);rejected.Add(p);};
   reject(p=>p.IsLordParty=false);reject(p=>p.IsActive=false);reject(p=>p.IsCurrentlyAtSea=true);reject(p=>p.IsEngaging=true);
   reject(p=>p.Army=new Army());reject(p=>p.AttachedTo=new MobileParty());reject(p=>p.AttachedParties.Add(new MobileParty()));
   reject(p=>p.MapEvent=new MapEvent());reject(p=>p.SiegeEvent=new TaleWorlds.CampaignSystem.Siege.SiegeEvent());reject(p=>p.BesiegedSettlement=new Settlement());reject(p=>p.CurrentSettlement=new Settlement());
   reject(p=>p.IsDisbanding=true);reject(p=>p.IsTransitionInProgress=true);reject(p=>p.IsCurrentlyUsedByAQuest=true);reject(p=>p.Ai.DoNotMakeNewDecisions=true);reject(p=>p.Ai.IsDisabled=true);
   reject(p=>p.Party.NumberOfHealthyMembers=0);reject(p=>p.Party.TestStrength=float.NaN);reject(p=>p.Party.TestStrength=float.PositiveInfinity);reject(p=>p.Party.TestStrength=-1);reject(p=>p.Position=new CampaignVec2{X=120.01f});
   var allowed=NearbyLord("boundary",60,120,w.Faction);w.Pilot.PollState();
   Check(rejected.TrueForAll(p=>p.Position.X!=0&&p.Party.TestJoinCalls==0),"все занятые/защищённые/внерадиуса остались на месте");
   Check(allowed.MapEvent==w.Battle,"граница радиуса120 включена");
  });
  foreach(string block in new[]{"observe","off","inquiry","attack-disabled","defending","sea","siege","raid","sally","target-quest","not-lord","our-power-nan","ally-battle","subordinate-army","joined-battle"})
  Try("лорды: запрещённый контекст "+block,()=>{
   var w=LordGatherWorld();var extra=NearbyLord("extra",60,1,w.Faction);
   if(block=="observe")w.Pilot.TryEnable(AutopilotBehavior.Mode.Observe,out _);
   if(block=="off")w.Pilot.Disable("test");
   if(block=="inquiry")TaleWorlds.Library.InformationManager.TestInquiryActive=true;
   if(block=="attack-disabled")Campaign.Current.CurrentMenuContext.GameMenu.Options[0].IsEnabled=false;
   if(block=="defending")w.Battle.PlayerSide=BattleSideEnum.Defender;
   if(block=="sea")w.Battle.IsNavalMapEvent=true;
   if(block=="siege")w.Battle.IsSiegeAssault=true;
   if(block=="raid")w.Battle.IsRaid=true;
   if(block=="sally")w.Battle.IsSallyOut=true;
   if(block=="target-quest")PlayerEncounter.EncounteredMobileParty.IsCurrentlyUsedByAQuest=true;
   if(block=="not-lord")PlayerEncounter.EncounteredMobileParty.IsLordParty=false;
   if(block=="our-power-nan")MobileParty.MainParty.Party.TestStrength=float.NaN;
   if(block=="ally-battle")w.Battle.AttackerSide.LeaderParty=new MobileParty().Party;
   if(block=="subordinate-army")MobileParty.MainParty.Army=new Army{LeaderParty=new MobileParty()};
   if(block=="joined-battle")PlayerEncounter.Current.IsJoinedBattle=true;
   w.Pilot.PollState();Check(extra.MapEvent==null&&extra.Position.X==1,"контекст "+block+" не телепортирует лордов");
  });
  Try("лорды: остановка при100%, а не обязательные120%",()=>{
   var w=LordGatherWorld();var a=NearbyLord("equal",60,1,w.Faction);var b=NearbyLord("spare",20,2,w.Faction);w.Pilot.PollState();Check(a.MapEvent==w.Battle&&b.MapEvent==null,"равной силы достаточно");
  });
  Try("лорды: изменение силы из callback не превышает лимит",()=>{
   var w=LordGatherWorld();var a=NearbyLord("a",20,1,w.Faction);var b=NearbyLord("b",50,2,w.Faction);a.Party.TestAfterJoin=()=>w.Battle.DefenderSide.LeaderParty.TestStrength=75;
   w.Pilot.PollState();Check(a.MapEvent==w.Battle&&b.MapEvent==null,"силы перечитаны перед вторым отрядом");
  });
  Try("лорды: callback уменьшил нашу сторону — атаку не нажимать",()=>{
   var w=LordGatherWorld();var p=NearbyLord("callback",60,1,w.Faction);p.Party.TestAfterJoin=()=>MobileParty.MainParty.Party.TestStrength=50;w.Pilot.PollState();
   Check(p.MapEvent==w.Battle&&w.Pilot.CurrentMode==AutopilotBehavior.Mode.Off&&!MenuContext.Invoked.Contains("attack"),"подтверждённый join сохранён, превышение останавливает автопилот");
  });
  Try("лорды: no-op join откатывает только позицию",()=>{
   var w=LordGatherWorld();var p=NearbyLord("noop",60,1,w.Faction);p.Party.TestIgnoreJoin=true;w.Pilot.PollState();
   Check(p.MapEvent==null&&p.Position.X==1&&w.Pilot.CurrentMode==AutopilotBehavior.Mode.Off&&!MenuContext.Invoked.Contains("attack"),"нет потерянного отряда после неподтверждённого join");
  });
  Try("лорды: исключение после join сохраняет эффект без повтора",()=>{
   var w=LordGatherWorld();var p=NearbyLord("throw",60,1,w.Faction);p.Party.TestAfterJoin=()=>throw new Exception("after join");w.Pilot.PollState();w.Pilot.PollState();
   Check(p.MapEvent==w.Battle&&p.Party.TestJoinCalls==1&&p.Position.X==0,"не повторяем join после исключения callback");
   Check(w.Pilot.CurrentMode==AutopilotBehavior.Mode.Off&&!MenuContext.Invoked.Contains("attack"),"ошибка обработчика не запускает бой автоматически");
  });
  Try("лорды: смена фракции исходной цели во время join останавливает",()=>{
   var w=LordGatherWorld();var target=PlayerEncounter.EncounteredMobileParty;var p=NearbyLord("callback",60,1,w.Faction);p.Party.TestAfterJoin=()=>target.MapFaction=new TestFaction();w.Pilot.PollState();
   Check(p.MapEvent==w.Battle&&w.Pilot.CurrentMode==AutopilotBehavior.Mode.Off&&!MenuContext.Invoked.Contains("attack"),"изменившаяся принадлежность цели не игнорируется");
  });
 }
}
