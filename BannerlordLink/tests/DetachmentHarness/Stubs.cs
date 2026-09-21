using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
namespace TaleWorlds.Core { public class BasicCharacterObject {} }
namespace TaleWorlds.Library {
 public struct Vec2 { public float x,y; public Vec2(float x,float y){this.x=x;this.y=y;} public float LengthSquared=>x*x+y*y; public float Length=>(float)Math.Sqrt(LengthSquared); public static Vec2 operator +(Vec2 a,Vec2 b)=>new(a.x+b.x,a.y+b.y); public static Vec2 operator -(Vec2 a,Vec2 b)=>new(a.x-b.x,a.y-b.y); public static Vec2 operator *(Vec2 a,float b)=>new(a.x*b,a.y*b); }
 public struct Vec3 { public float x,y,z; public Vec3(float x,float y,float z=0){this.x=x;this.y=y;this.z=z;} public Vec2 AsVec2=>new(x,y); public float LengthSquared=>x*x+y*y+z*z; public float Length=>(float)Math.Sqrt(LengthSquared); public float Distance(Vec3 b)=>(this-b).Length; public static Vec3 operator -(Vec3 a,Vec3 b)=>new(a.x-b.x,a.y-b.y,a.z-b.z); }
}
namespace TaleWorlds.Engine {
 using TaleWorlds.Library;
 public struct WorldPosition { public Vec3 Position; public bool IsValid; public Vec2 AsVec2=>Position.AsVec2; public static WorldPosition Invalid=>default; public WorldPosition(Scene s,UIntPtr n,Vec3 p,bool b){Position=p;IsValid=s!=null;} public void SetVec2(Vec2 p){Position.x=p.x;Position.y=p.y;} public UIntPtr GetNavMesh()=>new(1); }
 public class GameEntity { public string Name; public Vec3 GlobalPosition; public Type ScriptType; }
 public class Scene { public List<GameEntity> Entities=new(); public bool BlockLos; public Func<WorldPosition,WorldPosition,bool> PathExists=(a,b)=>true; public bool DoesPathExistBetweenPositions(WorldPosition a,WorldPosition b)=>PathExists(a,b); public Func<Vec3,bool> Navigable=_=>true; public void GetAllEntitiesWithScriptComponent<T>(ref List<GameEntity> list)=>list.AddRange(Entities.Where(x=>x.ScriptType==typeof(T))); public void GetEntities(ref List<GameEntity> list)=>list.AddRange(Entities); public UIntPtr GetNavigationMeshForPosition(Vec3 p)=>Navigable(p)?new(1):UIntPtr.Zero; public UIntPtr GetNearestNavigationMeshForPosition(Vec3 p,float f,bool b)=>GetNavigationMeshForPosition(p); public bool RayCastForClosestEntityOrTerrain(Vec3 a,Vec3 b,out float d){d=1;return BlockLos;} }
}
namespace TaleWorlds.CampaignSystem { public class CharacterObject:TaleWorlds.Core.BasicCharacterObject { public Hero HeroObject; } public class Hero { public CharacterObject CharacterObject=new(); public object Name; } }
namespace TaleWorlds.MountAndBlade {
 using TaleWorlds.Library; using TaleWorlds.Engine; using TaleWorlds.Core;
 public enum MissionBehaviorType { Other }
 public class MissionBehavior { public Mission Mission=>Mission.Current; public virtual MissionBehaviorType BehaviorType=>MissionBehaviorType.Other; public virtual void OnBehaviorInitialize(){} protected virtual void OnEndMission(){} public virtual void OnAgentDeleted(Agent a){} public virtual void OnMissionTick(float dt){} }
 public class Mission { public static Mission Current; public float CurrentTime; public bool IsSiegeBattle; public Scene Scene=new(); public List<Agent> Agents=new(); public List<MissionBehavior> MissionBehaviors=new(); public T GetMissionBehavior<T>() where T:class=>MissionBehaviors.OfType<T>().FirstOrDefault(); }
 public class Team { public int Side; }
 public class Formation { public int Index; }
 public class SiegeLadder {} public class CastleGate {}
 public class Agent {
  public enum ControllerType { AI,Player,None } public enum AIScriptedFrameFlags { None=0,NeverSlowDown=1 } public static Agent Main;
  public int Index; public bool Active=true,IsHuman=true,IsRangedCached; public Agent MountAgent; public Vec3 Position; public Team Team; public Formation Formation; public ControllerType Controller=ControllerType.AI; public BasicCharacterObject Character; public float MaximumMissileRange=40;
  public bool ThrowScript,ThrowDisable,ThrowCombat,ThrowTarget; public int ScriptCalls,DisableCalls; public WorldPosition? Scripted; public AIScriptedFrameFlags LastFlags; public Func<Vec3,float> Path;
  public bool IsActive()=>Active; public bool IsEnemyOf(Agent a)=>Team!=a.Team; public WorldPosition GetWorldPosition()=>new(Mission.Current.Scene,new UIntPtr(1),Position,false); public float GetPathDistanceToPoint(ref Vec3 p)=>Path?.Invoke(p)??Position.Distance(p);
  public void SetScriptedPosition(ref WorldPosition p,bool b,AIScriptedFrameFlags f){if(ThrowScript)throw new Exception("script failure");ScriptCalls++;Scripted=p;LastFlags=f;} public void DisableScriptedMovement(){if(ThrowDisable)throw new Exception("disable failure");DisableCalls++;Scripted=null;} public void DisableScriptedCombatMovement(){if(ThrowCombat)throw new Exception("combat failure");} public void SetAutomaticTargetSelection(bool b){if(ThrowTarget)throw new Exception("target failure");} public void SetTargetFormationIndex(int i){}
 }
}
namespace BannerlordLink { public static class BannerlordLinkModule { public static void Log(string s){} } }
namespace BannerlordLink.Behaviors { public class HeroIdentityBehavior { public static HeroIdentityBehavior Instance; public string GetUsername(TaleWorlds.CampaignSystem.Hero h)=>"viewer"; } }
namespace BannerlordLink.Util {
 public static class HeroNaming { public static string ExtractUsername(string s)=>s; }
 public static class HeroLookup { public static TaleWorlds.CampaignSystem.Hero Hero; public static TaleWorlds.CampaignSystem.Hero FindByUsername(string s)=>Hero; }
 public static class MainThreadDispatcher { public static void Enqueue(Action a)=>a(); }
 public static class ActionFeedback { public static int Applied,Failed; public static string GetActionId(JObject d)=>"action"; public static void PostFailed(string a,string r)=>Failed++; public static void PostApplied(string a)=>Applied++; }
}
namespace BannerlordLink.Actions { public interface IActionHandler { string ActionType{get;} System.Threading.Tasks.Task<(bool success,string error)> ExecuteAsync(JObject data); } }

