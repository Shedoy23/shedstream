using System;
using System.Collections.Generic;
using BannerlordAutopilot;
using TaleWorlds.Core;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

int checks=0,failures=0;
void Check(bool ok,string name){checks++;if(!ok)failures++;Console.WriteLine((ok?"PASS ":"FAIL ")+name);}
var rig=new BattleOverviewRig();
Check(rig.Pitch==40,"default angle is a gentler 40 degrees");
var points=new List<BattleOverviewRig.Point>();
for(int i=0;i<30;i++)points.Add(new BattleOverviewRig.Point(i%5,i/5,10,i%2==0));
points.Add(new BattleOverviewRig.Point(1000,1000,0,false));
rig.Focus(points);rig.Step(.016f);
Check(rig.Ready && rig.X<10 && rig.Y<10,"one fleeing cavalryman cannot pull camera away from main fight");
Check(Math.Abs(rig.CameraZ-90)<.01f,"default camera is 80m above highest local fighter");
rig.Zoom(100);Check(rig.Height==45,"minimum overview height");
rig.Zoom(-100);Check(rig.Height==180,"maximum overview height");
rig.Rotate(1,1000);Check(rig.Pitch==80,"pitch never reaches vertical singularity");
rig.Focus(new[]{new BattleOverviewRig.Point(300,0,0,true)});float before=rig.X;
rig.Step(.016f);Check(rig.X>before && rig.X<before+10,"focus follows smoothly instead of teleporting");
rig.Focus(new List<BattleOverviewRig.Point>());Check(rig.Ready,"reinforcement gap retains battlefield view");

BattleOverviewCamera Make(){AutopilotBehavior.Instance.CurrentMode=AutopilotBehavior.Mode.Apply;InformationManager.Inquiry=false;var v=new BattleOverviewCamera{Mission=new Mission{CameraIsFirstPerson=true}};v.Mission.Agents.Add(new Agent{Position=new Vec3(0,0,10)});return v;}
var view=Make();
Check(view.UpdateOverridenCamera(.016f) && !view.Mission.CameraIsFirstPerson,"overview owns rendering, disables first person");
Check(view.MissionScreen.CombatCamera.Frame.origin.z==90,"real view applies high camera geometry");
Check(view.Mission.CameraUpdates==1 && view.Mission.CameraFrame.origin.z==90,"native mission receives the rendered camera frame");
Check(view.MissionScreen.CombatCamera.Near==0.1f && view.MissionScreen.CombatCamera.Far==12500f,"overview initializes native clipping range");
Check(Math.Abs(view.MissionScreen.CombatCamera.Fov-65f*(float)Math.PI/180f)<.001f,"overview initializes field of view");
view.MissionScreen.CombatCamera.Near=1000;
view.UpdateOverridenCamera(.016f);
Check(view.Mission.CameraUpdates==2 && view.MissionScreen.CombatCamera.Near==0.1f,"each frame refreshes mission and projection");
view.Mission.MainAgent=null;
Check(view.UpdateOverridenCamera(.016f),"overview continues without main hero");
view.Mission.Scene.Ground=200;
view.UpdateOverridenCamera(.016f);Check(view.MissionScreen.CombatCamera.Frame.origin.z>=212,"camera stays above hillside beneath it");
view.Input.Toggle=true;view.OnMissionScreenTick(.016f);
Check(!view.UpdateOverridenCamera(.016f) && view.Mission.CameraIsFirstPerson,"F9 returns previous native view");
view.Input.Toggle=true;view.OnMissionScreenTick(.016f);Check(view.UpdateOverridenCamera(.016f),"F9 resumes overview");
foreach(string stop in new[]{"off","end","conversation","deployment","photo","custom","inquiry","suspended","noBehavior","finalize","deactivate"}){
 view=Make();view.UpdateOverridenCamera(.016f);
 switch(stop){
 case "off":AutopilotBehavior.Instance.CurrentMode=AutopilotBehavior.Mode.Off;break;
 case "end":view.Mission.MissionEnded=true;break;
 case "conversation":view.Mission.Mode=MissionMode.Conversation;break;
 case "deployment":view.Mission.IsDeploymentFinished=false;break;
 case "photo":view.MissionScreen.IsPhotoModeEnabled=true;break;
 case "custom":view.MissionScreen.CustomCamera=new TaleWorlds.Engine.Camera();break;
 case "inquiry":InformationManager.Inquiry=true;break;
 case "suspended":view.IsViewSuspended=true;break;
 case "noBehavior":view.Mission.HasBehavior=false;break;
 case "finalize":view.OnMissionScreenFinalize();break;
 case "deactivate":view.OnMissionScreenDeactivate();break;
 }
 if(stop!="finalize" && stop!="deactivate")Check(!view.UpdateOverridenCamera(.016f),"native view takes over: "+stop);
 Check(view.Mission.CameraIsFirstPerson,"restore saved camera flag: "+stop);
}
view=Make();view.MissionScreen.CombatCamera.Throw=true;
Check(!view.UpdateOverridenCamera(.016f) && view.Mission.CameraIsFirstPerson,"native error restores camera and falls back");
view.MissionScreen.CombatCamera.Throw=false;Check(!view.UpdateOverridenCamera(.016f),"failed view cannot loop exceptions every frame");
Console.WriteLine($"{checks} checks, {failures} failures");return failures==0?0:1;
