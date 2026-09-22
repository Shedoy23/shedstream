using System;
using System.Linq;
using System.Collections.Generic;
using BannerlordLink.Patches;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Election;
var valid=new Clan();valid.Leader=new Hero{Clan=valid};
var broken=new Clan{IsEliminated=true,Leader=new Hero()};
IEnumerable<Supporter> rows=new[]{new Supporter(valid),new Supporter(broken),new Supporter(new Clan())};
ValidKingdomSupportersPatch.Postfix(ref rows);
if(rows.Count()!=1 || rows.First().Clan!=valid)throw new Exception("Invalid voter must not reach diplomacy model");
Console.WriteLine("Invalid kingdom supporter: PASS");
namespace HarmonyLib { public class HarmonyPatch:Attribute { public HarmonyPatch(Type t,string n){} } }
namespace TaleWorlds.CampaignSystem {public class Clan { public bool IsEliminated;public Hero Leader; } public class Hero {public Clan Clan;} }
namespace TaleWorlds.CampaignSystem.Election {public class KingdomDecision {public void DetermineSupporters(){} } public class Supporter {public Clan Clan;public Supporter(Clan c){Clan=c;}} }
