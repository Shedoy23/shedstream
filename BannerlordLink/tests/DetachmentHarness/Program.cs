using System;
using BannerlordLink.Behaviors;
using BannerlordLink.Actions;
using BannerlordLink.Util;
using TaleWorlds.MountAndBlade;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using Newtonsoft.Json.Linq;
class Program {
 static int failed,total; static HeroDetachmentBehavior b; static Agent a; static Team foe; static Mission m;
 static void Setup(){m=Mission.Current=new Mission(); b=new();m.MissionBehaviors.Add(b);b.OnBehaviorInitialize();a=new Agent{Index=1,Team=new Team()};m.Agents.Add(a);foe=new Team();HeroLookup.Hero=new();a.Character=HeroLookup.Hero.CharacterObject;ActionFeedback.Applied=ActionFeedback.Failed=0;Agent.Main=null;}
 static void Check(bool ok,string why){if(!ok)throw new Exception(why);}
 static void Test(string name,Action test){total++;Setup();try{test();Console.WriteLine("PASS "+name);}catch(Exception e){failed++;Console.WriteLine("FAIL "+name+": "+e.Message);}}
 static Agent Enemy(int i,float x,bool human=true,bool mounted=false){var e=new Agent{Index=i,Team=foe,Position=new Vec3(x,0),IsHuman=human};if(mounted)e.MountAgent=new Agent{IsHuman=false};m.Agents.Add(e);return e;}
 static float X()=>a.Scripted?.Position.x??float.NaN;
 static void Main(){
 Test("gate chooses gate despite closer ladder",()=>{m.IsSiegeBattle=true;m.Scene.Entities.Add(new(){Name="ladder",GlobalPosition=new(5,0),ScriptType=typeof(SiegeLadder)});m.Scene.Entities.Add(new(){Name="gate",GlobalPosition=new(20,0),ScriptType=typeof(CastleGate)});Check(b.Gate(a),"gate rejected");Check(X()==20,"selected ladder instead of gate");});
 foreach(var walls in new[]{false,true}){Test((walls?"walls":"gate")+" outside siege leaves agent untouched",()=>{Check(!(walls?b.Walls(a):b.Gate(a)),"accepted invalid siege order");Check(!b.IsDetached(a)&&a.ScriptCalls==0,"invalid order detached/pinned hero");});Test((walls?"walls":"gate")+" missing target leaves agent untouched",()=>{m.IsSiegeBattle=true;Check(!(walls?b.Walls(a):b.Gate(a)),"accepted absent target");Check(!b.IsDetached(a)&&a.ScriptCalls==0,"missing target detached/pinned hero");});}
 Test("hold native failure rejected and not retained",()=>{a.ThrowScript=true;Check(!b.Hold(a),"reported success despite native exception");Check(!b.IsDetached(a),"failed hold retained state");});
 Test("attach native failure retains state",()=>{Check(b.Hold(a),"hold failed");a.ThrowDisable=true;Check(!b.Attach(a),"reported successful attach");Check(b.IsDetached(a),"lost control state after failed attach");});
 Test("attach handler refunds failure",()=>{b.Hold(a);a.ThrowDisable=true;new AttachHandler().ExecuteAsync(new JObject{{"target","viewer"}}).GetAwaiter().GetResult();Check(ActionFeedback.Applied==0&&ActionFeedback.Failed==1,"failed attach acknowledged applied");});
 Test("hold handler refunds native failure",()=>{a.ThrowScript=true;new HoldHandler().ExecuteAsync(new JObject{{"target","viewer"}}).GetAwaiter().GetResult();Check(ActionFeedback.Applied==0&&ActionFeedback.Failed==1,"failed hold acknowledged applied");});
 Test("foot charge ignores loose horse",()=>{Enemy(2,5,false);Enemy(3,15);Check(b.Charge(a),"charge rejected");Check(X()==15,"targeted horse");});
 Test("foot charge prefers infantry over cavalry",()=>{Enemy(2,7,true,true);Enemy(3,15);Check(b.Charge(a),"charge rejected");Check(X()==15,"chasing cavalry over reachable infantry");});
 Test("foot charge rejects unreachable infantry",()=>{Enemy(2,8);Enemy(3,15);m.Scene.PathExists=(from,to)=>to.Position.x!=8;Check(b.Charge(a),"charge rejected");Check(X()==15,"targeted inaccessible infantry");});
 Test("foot charge retains target through nearby switch",()=>{Enemy(2,12);var other=Enemy(3,13);b.Charge(a);other.Position=new(11,0);m.CurrentTime=.6f;b.OnMissionTick(.6f);Check(X()==12,"target switched from small distance change");});
 Test("foot charge gives up distant cavalry",()=>{Enemy(2,40,true,true);b.Charge(a);Check(X()==0,"chasing distant cavalry");});
 Test("invalid siege order preserves existing charge",()=>{Enemy(2,15);b.Charge(a);int calls=a.ScriptCalls;Check(!b.Gate(a),"accepted non siege gate");Check(X()==15&&a.ScriptCalls==calls&&b.IsDetached(a),"changed existing command");m.CurrentTime=1;b.OnMissionTick(1);Check(X()==15,"prior charge no longer running");});
 Test("charge gives up stalled nearby cavalry",()=>{Enemy(2,10,true,true);b.Charge(a);Check(X()==10,"nearby cavalry should be eligible");m.CurrentTime=5;b.OnMissionTick(5);Check(X()==0,"stalled cavalry pursuit was not abandoned");});
 Test("charge releases movement for melee contact",()=>{Enemy(2,3);b.Charge(a);Check(a.Scripted==null,"still forcing movement in melee contact");});
 Test("charge cannot engage through obstruction",()=>{Enemy(2,3);m.Scene.BlockLos=true;b.Charge(a);Check(a.Scripted!=null,"released into melee despite blocked contact");});
 Test("charge reselects dead target",()=>{var e=Enemy(2,12);Enemy(3,18);b.Charge(a);e.Active=false;m.CurrentTime=1;b.OnMissionTick(1);Check(X()==18,"dead target retained");});
 Test("mounted charge keeps original nearest target policy",()=>{a.MountAgent=new Agent{IsHuman=false};Enemy(2,8,true,true);Enemy(3,15);b.Charge(a);Check(X()==8,"mounted charge changed by infantry policy");});
 Test("gate without gate never substitutes ladder",()=>{m.IsSiegeBattle=true;m.Scene.Entities.Add(new(){Name="ladder",GlobalPosition=new(5,0),ScriptType=typeof(SiegeLadder)});Check(!b.Gate(a),"accepted ladder as gate");Check(!b.IsDetached(a)&&a.ScriptCalls==0,"failed gate changed movement");});
 Test("attach success releases control and state",()=>{b.Hold(a);Check(b.Attach(a),"attach rejected");Check(!b.IsDetached(a)&&a.Scripted==null,"attach did not release state/movement");});
 Test("hold success acknowledged once",()=>{new HoldHandler().ExecuteAsync(new JObject{{"target","viewer"}}).GetAwaiter().GetResult();Check(ActionFeedback.Applied==1&&ActionFeedback.Failed==0,"hold feedback wrong");Check(b.IsDetached(a)&&X()==0,"hold not active");});
 Test("gate native failure refunds without retained state",()=>{m.IsSiegeBattle=true;m.Scene.Entities.Add(new(){Name="gate",GlobalPosition=new(20,0),ScriptType=typeof(CastleGate)});a.ThrowScript=true;new GateHandler().ExecuteAsync(new JObject{{"target","viewer"}}).GetAwaiter().GetResult();Check(ActionFeedback.Applied==0&&ActionFeedback.Failed==1,"failed gate acknowledged applied");Check(!b.IsDetached(a),"failed gate retained state");});
 Test("charge uses ordinary movement flag",()=>{Enemy(2,15);b.Charge(a);Check(a.LastFlags==Agent.AIScriptedFrameFlags.NeverSlowDown,"unexpected movement flags");});
 Console.WriteLine($"{total-failed}/{total} passed");Environment.ExitCode=failed==0?0:1;
 }
}



