using System;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Roster;

namespace TaleWorlds.CampaignSystem { public class Hero { public bool IsPrisoner; public MobileParty PartyBelongedTo; } }
namespace TaleWorlds.CampaignSystem.Party { public class MobileParty { public Hero LeaderHero; public ItemRoster ItemRoster = new ItemRoster(); } }
namespace TaleWorlds.CampaignSystem.Roster { public class ItemRoster { } }

class Program {
 static int Main() {
  // #66: вещи зрителя уходили в инвентарь ЧУЖОГО отряда (отряд стримера после
  // боя), 22.09 так пропала булава с перековкой на 60 000💎.
  int failed = 0;
  void Check(bool ok, string t) { Console.WriteLine((ok ? "ok   " : "FAIL ") + t); if (!ok) failed++; }
  var hero = new Hero(); var own = new MobileParty { LeaderHero = hero };
  hero.PartyBelongedTo = own;
  Check(OwnPartyInventory.Of(hero) == own.ItemRoster, "свой отряд — свой инвентарь");
  var streamer = new MobileParty { LeaderHero = new Hero() };
  hero.PartyBelongedTo = streamer;
  Check(OwnPartyInventory.Of(hero) == null, "в отряде стримера — чужой инвентарь не трогаем");
  hero.PartyBelongedTo = null;
  Check(OwnPartyInventory.Of(hero) == null, "без отряда — инвентаря нет");
  hero.PartyBelongedTo = own; hero.IsPrisoner = true;
  Check(OwnPartyInventory.Of(hero) == null, "в плену — инвентаря нет");
  return failed;
 }
}
