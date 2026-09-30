using System;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Conversation;
internal static partial class Program {
 static void PatrolEncounterTests() {
  foreach(var id in new[]{"patrol_talk_start_enemy_1","patrol_talk_start_attack_final","patrol_talk_start_enemy_2"})
  foreach(var guard in new[]{"valid","peace","different","not-patrol","disabled","inquiry","off"})
  Try("patrol dialogue "+id+" / "+guard,()=>{
   var b=Fresh();Enable(b);b.RandomDialogsEnabled=false;
   var ours=new TestFaction();var enemy=new TestFaction();if(guard!="peace")ours.Enemies.Add(enemy);
   MobileParty.MainParty.MapFaction=ours;
   var patrol=new MobileParty{MapFaction=enemy,IsPatrolParty=guard!="not-patrol"};
   MobileParty.MainParty.TargetParty=patrol;MobileParty.MainParty.DefaultBehavior=AiBehavior.EngageParty;
   PlayerEncounter.Current=new PlayerEncounter{Defender=id=="patrol_talk_start_enemy_2"};
   PlayerEncounter.EncounteredMobileParty=patrol;Campaign.Current.CurrentConversationContext=ConversationContext.PartyEncounter;
   var c=Campaign.Current.ConversationManager;c.ConversationParty=guard=="different"?new MobileParty():patrol;c.IsConversationInProgress=true;
   c.CurOptions.Add(new ConversationSentenceOption{Id="patrol_talk_start_ask_security",IsClickable=true});
   c.CurOptions.Add(new ConversationSentenceOption{Id=id,IsClickable=guard!="disabled"});
   if(guard=="inquiry")TaleWorlds.Library.InformationManager.TestInquiryActive=true;
   if(guard=="off")b.Disable("test");
   b.PollDialogs();Check(guard=="valid"?c.Selected.SequenceEqual(new[]{id}):c.Selected.Count==0,"patrol native reply guard "+guard);
  });
  Try("patrol attack gathers same faction lords",()=>{
   var w=LordGatherWorld();var target=PlayerEncounter.EncounteredMobileParty;target.IsLordParty=false;target.IsPatrolParty=true;
   var lord=NearbyLord("reinforcement",60,1,w.Faction);w.Pilot.PollState();
   Check(lord.MapEvent==w.Battle,"patrol gets lord reinforcement");
   Check(TaleWorlds.CampaignSystem.GameMenus.MenuContext.Invoked.Contains("attack"),"patrol battle starts after gathering");
  });
  foreach(var kind in new[]{"quest","caravan","villager","unknown"})Try("gather target excluded "+kind,()=>{
   var w=LordGatherWorld();var target=PlayerEncounter.EncounteredMobileParty;target.IsLordParty=false;
   target.IsPatrolParty=kind=="quest";target.IsCurrentlyUsedByAQuest=kind=="quest";target.IsCaravan=kind=="caravan";target.IsVillager=kind=="villager";
   var lord=NearbyLord("leave",60,1,w.Faction);w.Pilot.PollState();Check(lord.MapEvent==null,"target excluded "+kind);
  });
 }
}
