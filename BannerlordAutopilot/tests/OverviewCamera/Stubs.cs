using System;
using System.Collections.Generic;
namespace TaleWorlds.Engine { public static class Screen { public static float AspectRatio=16f/9f; } }
namespace TaleWorlds.Core { public enum MissionMode { Battle,Deployment,Conversation } }
namespace TaleWorlds.Library {
 public struct Vec3 { public float x,y,z; public Vec3(float a,float b,float c){x=a;y=b;z=c;} public static Vec3 Up=>new Vec3(0,0,1); }
 public struct MatrixFrame { public Vec3 origin; }
 public static class InformationManager { public static bool Inquiry; public static bool IsAnyInquiryActive()=>Inquiry; }
}
namespace TaleWorlds.InputSystem {
 public enum InputKey { F9,MiddleMouseButton }
 public class FakeInput {
  public bool Toggle,Middle; public float Scroll,DX,DY;
  public bool IsKeyPressed(InputKey k) {bool v=Toggle;Toggle=false;return v;}
  public bool IsKeyDown(InputKey k)=>Middle;
  public float GetDeltaMouseScroll()=>Scroll;
  public float GetMouseMoveX()=>DX; public float GetMouseMoveY()=>DY;
 }
}
namespace TaleWorlds.Engine {
 public class Camera {
  public float Fov,Aspect,Near,Far;
  public void SetFovVertical(float f,float a,float n,float z){Fov=f;Aspect=a;Near=n;Far=z;}
  public bool Throw; public TaleWorlds.Library.MatrixFrame Frame; public TaleWorlds.Library.Vec3 Target;
  public void LookAt(TaleWorlds.Library.Vec3 p,TaleWorlds.Library.Vec3 t,TaleWorlds.Library.Vec3 up) {if(Throw)throw new Exception("native test");Frame.origin=p;Target=t;}
 }
 public class Scene { public float Ground; public float GetGroundHeightAtPosition(TaleWorlds.Library.Vec3 p)=>Ground; }
 public class SceneView { public Camera Camera; public void SetCamera(Camera c){Camera=c;} }
 public static class SoundManager { public static void SetListenerFrame(TaleWorlds.Library.MatrixFrame f){} }
}
namespace TaleWorlds.MountAndBlade {
 public class Team { public bool Enemy; public bool IsEnemyOf(Team other)=>Enemy; }
 public class Agent { public bool Active=true,IsHuman=true; public Team Team=new Team(); public TaleWorlds.Library.Vec3 Position; public bool IsActive()=>Active; }
 public class Mission {
  public bool IsDeploymentFinished=true,MissionEnded,CameraIsFirstPerson,HasBehavior=true;
  public TaleWorlds.Core.MissionMode Mode=TaleWorlds.Core.MissionMode.Battle;
  public List<Agent> Agents=new List<Agent>(); public Team PlayerTeam=new Team(); public Agent MainAgent;
  public TaleWorlds.Engine.Scene Scene=new TaleWorlds.Engine.Scene();
  public int CameraUpdates; public TaleWorlds.Library.MatrixFrame CameraFrame; public TaleWorlds.Library.Vec3 Listener;
  public void SetCameraFrame(ref TaleWorlds.Library.MatrixFrame frame,float zoom,ref TaleWorlds.Library.Vec3 listener){CameraUpdates++;CameraFrame=frame;Listener=listener;}
  public T GetMissionBehavior<T>() where T:class,new()=>HasBehavior?new T():null;
 }
}
namespace TaleWorlds.MountAndBlade.View { public class DefaultViewAttribute:Attribute{} }
namespace TaleWorlds.MountAndBlade.View.MissionViews {
 public class Screen {
  public bool IsPhotoModeEnabled; public TaleWorlds.Engine.Camera CustomCamera,CombatCamera=new TaleWorlds.Engine.Camera();
  public TaleWorlds.Engine.SceneView SceneView=new TaleWorlds.Engine.SceneView();
 }
 public class MissionView {
  public TaleWorlds.MountAndBlade.Mission Mission; public Screen MissionScreen=new Screen(); public bool IsViewSuspended;
  public TaleWorlds.InputSystem.FakeInput Input=new TaleWorlds.InputSystem.FakeInput();
  public virtual void OnMissionScreenTick(float dt){} public virtual bool UpdateOverridenCamera(float dt)=>false;
  public virtual void OnMissionScreenFinalize(){} public virtual void OnMissionScreenDeactivate(){}
 }
}
namespace BannerlordAutopilot {
 public class BattleAutopilotMission{}
 public class AutopilotBehavior { public enum Mode{Apply,Off} public static AutopilotBehavior Instance=new AutopilotBehavior();public Mode CurrentMode=Mode.Apply; }
 public static class AutopilotLog { public static void Write(string msg){} }
}
