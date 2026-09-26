using System;
using BannerlordLink.Util;
int probes=0;
bool Blocked(float x,float y){probes++;return false;}
if(SpawnPointSearch.TryFind(0,0,0,false,Blocked,out var x,out var y)||probes!=24)throw new Exception("Blocked scene must fail bounded");
if(!SpawnPointSearch.TryFind(0,0,0,false,(a,b)=>a < -1,out x,out y)||x>=-1)throw new Exception("Search must skip blocked side");
if(!SpawnPointSearch.TryFind(0,0,int.MinValue,true,(a,b)=>true,out x,out y)||Math.Sqrt(x*x+y*y)<3.9)throw new Exception("Mount clearance and signed seed");
// 26.09 (владелец): призыв на расстановке разрешён, как в новом BLT; свита тоже.
if(SummonModePolicy.Blocks("Deployment"))throw new Exception("Deployment must allow summon");
foreach(var m in new[]{"CutScene","Conversation","Replay","Barter","Duel","Tournament"}) if(!SummonModePolicy.Blocks(m))throw new Exception("still blocked: "+m);
if(SummonModePolicy.Blocks("Battle")||SummonModePolicy.Blocks("Stealth"))throw new Exception("Battle/Stealth allowed");
if(!SummonModePolicy.RetinueAllowed("Deployment")||!SummonModePolicy.RetinueAllowed("Battle")||SummonModePolicy.RetinueAllowed("Stealth"))throw new Exception("retinue modes");
if(!SummonModePolicy.IsDeployment("Deployment")||SummonModePolicy.IsDeployment("Battle"))throw new Exception("deployment flag");
Console.WriteLine("Spawn point search + summon modes: PASS");
