using System;
using System.Reflection;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.MapEvents;

namespace HarmonyLib {
 public class HarmonyPatch : Attribute { public HarmonyPatch(Type t, string name) {} }
 public class HarmonyPostfix : Attribute {}
}
namespace TaleWorlds.CampaignSystem.MapEvents {
 public sealed class MapEvent { public bool IsFieldBattle, IsSiegeAssault, IsHideoutBattle, IsNavalMapEvent; }
}
namespace TaleWorlds.CampaignSystem.Encounters {
 public class CampaignBattleResult { public bool PlayerVictory { get; set; } public bool PlayerDefeat { get; set; } }
 public class PlayerEncounter { public static MapEvent Battle { get; set; } }
}
namespace BannerlordLink { public static class BannerlordLinkModule { public static void Log(string s) { Console.WriteLine("LOG " + s); } } }

class Program {
 static int Main() {
  // 24.09, владелец: «если первый бой проебали, второй автоматически тоже». Игра
  // (PlayerEncounter.CheckIfBattleShouldContinueAfterBattleMissionInternal) после
  // победы в сцене продолжает бой, если у проигравших остался хоть один здоровый
  // (сбежавшие с поля) — и снова открывает «Атаковать».
  int failed = 0;
  void Check(bool ok, string t) { Console.WriteLine((ok ? "ok   " : "FAIL ") + t); if (!ok) failed++; }
  var patch = Type.GetType("BannerlordLink.Patches.BattleContinuePatch");
  var post = patch?.GetMethod("Postfix", BindingFlags.Static | BindingFlags.Public);
  bool Run(bool vanilla, bool victory, bool defeat, MapEvent ev) {
   PlayerEncounter.Battle = ev;
   object[] args = { new CampaignBattleResult { PlayerVictory = victory, PlayerDefeat = defeat }, vanilla };
   post?.Invoke(null, args);
   return (bool)args[1];
  }
  var field = new MapEvent { IsFieldBattle = true };
  Check(!Run(true, true, false, field), "победа в поле, сбежавшие живы — второго боя нет");
  Check(Run(true, false, true, field), "наш проигрыш — игра даёт второй шанс, как раньше");
  Check(Run(true, true, false, new MapEvent { IsSiegeAssault = true }), "осада — правила игры не трогаем");
  Check(Run(true, true, false, new MapEvent { IsFieldBattle = true, IsHideoutBattle = true }), "убежище — не трогаем");
  Check(Run(true, true, false, new MapEvent { IsFieldBattle = true, IsNavalMapEvent = true }), "морской бой — не трогаем");
  Check(!Run(false, true, false, field), "игра сама не продолжает — ничего не меняем");
  return failed;
 }
}
