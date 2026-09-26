using System;
using System.Collections.Generic;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.MapEvents;
using TaleWorlds.CampaignSystem.Party;
// 26.09 20:58 краш: зритель вышел из Вландии, пока вландийцы штурмовали Усанк в бою стримера.
namespace TaleWorlds.CampaignSystem { public interface IFaction {} public class Clan : IFaction {} public class Kingdom : IFaction {} public class Hero { public Clan Clan; } }
namespace TaleWorlds.CampaignSystem.Party {
 public class MobileParty { public Clan ActualClan; }
 public class PartyBase { public MobileParty MobileParty; public Hero Owner; public IFaction MapFaction; }
}
namespace TaleWorlds.CampaignSystem.MapEvents {
 public class MapEvent { public static MapEvent PlayerMapEvent; public bool Throw; public List<PartyBase> Parties = new();
  public IEnumerable<PartyBase> InvolvedParties { get { if (Throw) throw new Exception("движок"); return Parties; } } }
}
class Program {
 static int Main(){
  int failed=0; void Check(bool ok,string t){Console.WriteLine((ok?"ok   ":"FAIL ")+t); if(!ok) failed++;}
  var vlandia=new Kingdom(); var shedlink=new Kingdom(); var stepuha=new Clan(); var lord=new Clan(); var other=new Clan();
  PartyBase Party(Clan c, IFaction k)=>new PartyBase{MobileParty=new MobileParty{ActualClan=c}, MapFaction=k};
  MapEvent.PlayerMapEvent=null;
  Check(!FactionChangeGuard.TouchesPlayerBattle(stepuha, vlandia), "боя стримера нет — выходить можно");
  MapEvent.PlayerMapEvent=new MapEvent(); MapEvent.PlayerMapEvent.Parties.Add(Party(lord, vlandia)); MapEvent.PlayerMapEvent.Parties.Add(Party(null, shedlink));
  Check(FactionChangeGuard.TouchesPlayerBattle(stepuha, vlandia), "вландийцы в бою стримера — выйти из Вландии нельзя (случай 26.09)");
  MapEvent.PlayerMapEvent.Parties.Add(Party(stepuha, vlandia));
  Check(FactionChangeGuard.TouchesPlayerBattle(stepuha, null), "отряд самого клана в бою — нельзя");
  Check(!FactionChangeGuard.TouchesPlayerBattle(other, new Kingdom()), "в бою нет ни клана, ни королевства — можно");
  Check(FactionChangeGuard.TouchesPlayerBattle(shedlink, vlandia), "мир между сторонами идущего боя — нельзя");
  MapEvent.PlayerMapEvent.Throw=true;
  Check(FactionChangeGuard.TouchesPlayerBattle(other), "движок не отдал участников — отказ, а не риск вылета");
  Check(!FactionChangeGuard.Blocks(true, new List<object[]>{ new object[]{ lord, vlandia } }, new object[]{ null }), "пустой список затронутых — не блокируем зря");
  Console.WriteLine(failed==0?"ВСЕ ОК":"ПРОВАЛОВ: "+failed); return failed;
 }
}
