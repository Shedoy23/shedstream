using System;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
var p=new Hero();p.Clan=new Clan{Leader=p};
var c=new Hero{Father=p,Clan=p.Clan};
void Check(bool ok){if(!ok)throw new Exception("Eligibility regression");}
Check(HeirEligibility.CanCreateVassal(p,c));
c.IsChild=true;Check(!HeirEligibility.CanCreateVassal(p,c));c.IsChild=false;
c.IsPrisoner=true;Check(!HeirEligibility.CanCreateVassal(p,c));c.IsPrisoner=false;
c.IsAlive=false;Check(!HeirEligibility.CanCreateVassal(p,c));c.IsAlive=true;
c.Clan=new Clan();Check(!HeirEligibility.CanCreateVassal(p,c));c.Clan=p.Clan;
c.Father=null;Check(!HeirEligibility.CanCreateVassal(p,c));c.Mother=p;Check(HeirEligibility.CanCreateVassal(p,c));
c.Name="[BLink] viewer";Check(!HeirEligibility.CanCreateVassal(p,c));c.Name="Child";
p.Clan.IsEliminated=true;Check(!HeirEligibility.CanCreateVassal(p,c));p.Clan.IsEliminated=false;
p.Clan.Leader=c;Check(!HeirEligibility.CanCreateVassal(p,c));
Console.WriteLine("Native heir eligibility: 10 passed");
namespace TaleWorlds.CampaignSystem {
 public class Hero { public bool IsAlive=true,IsChild,IsPrisoner;public Hero Father,Mother;public Clan Clan;public string Name="Child"; }
 public class Clan { public Hero Leader;public bool IsEliminated; }
}
namespace BannerlordLink.Util { public static class HeroNaming { public static bool IsAdopted(string name)=>name.StartsWith("[BLink]"); } }
