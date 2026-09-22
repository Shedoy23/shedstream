using System;
using System.Linq;
using System.Collections.Generic;
using BannerlordLink.Patches;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Election;
var valid=new Clan();valid.Leader=new Hero{Clan=valid};
var broken=new Clan{IsEliminated=true,Leader=new Hero()};
// Живой клан, чей лидер ушёл в другой клан: ровно то, что уронило игру 22.09
// (уничтожен он был или нет — для ванили неважно, падает на Leader.Clan).
var other=new Clan{Name="other"};
var dangling=new Clan{Name="[BLink] Рой пчел",Leader=new Hero{Clan=other}};
// Клан с флагом «уничтожен», но с живым лидером-членом клана: у зрителя
// neyrahatomia 22.09 это ЖИВОЙ клан — 5 человек, отряд, 24 430 известности,
// он сам лидер. Ваниль на таком не падает (падает на Leader.Clan == null),
// значит выкидывать его из голосования нельзя: зритель теряет политику.
var eliminatedButWhole=new Clan{Name="[BLink] Рой пчёл",IsEliminated=true};
eliminatedButWhole.Leader=new Hero{Clan=eliminatedButWhole};
IEnumerable<Supporter> rows=new[]{new Supporter(valid),new Supporter(broken),new Supporter(new Clan()),new Supporter(dangling),new Supporter(eliminatedButWhole)};
ValidKingdomSupportersPatch.Postfix(ref rows);
if(rows.Count()!=2 || rows.First().Clan!=valid || !rows.Any(r=>r.Clan==eliminatedButWhole))throw new Exception("Invalid voter must not reach diplomacy model");
Console.WriteLine("Invalid kingdom supporter: PASS");
namespace HarmonyLib { public class HarmonyPatch:Attribute { public HarmonyPatch(Type t,string n){} } }
namespace TaleWorlds.CampaignSystem {public class Clan { public bool IsEliminated;public Hero Leader;public string Name; } public class Hero {public Clan Clan;} }
namespace BannerlordLink {public static class BannerlordLinkModule {public static void Log(string text) {}}}
namespace TaleWorlds.CampaignSystem.Election {public class KingdomDecision {public void DetermineSupporters(){} } public class Supporter {public Clan Clan;public Supporter(Clan c){Clan=c;}} }
