using RimLink.Components;
using Verse;

// Лог мода в этом харнесе уводим в temp: сам логгер проверяется в LogFileHarness.
RimLink.RimLinkLog.DirectoryOverride = Path.Combine(Path.GetTempPath(), "rimlink-paused-harness");
var component = new RimLinkGameComponent(Current.Game);
component.FinalizeInit();
// Paused game: frame updates continue, GameComponentTick is never called.
for (int i = 0; i < 12; i++) component.GameComponentUpdate();
if (RimLinkMod.PawnManager.Deaths != 3 || RimLinkMod.PawnManager.Snapshots != 1)
    throw new Exception($"Pause stalled sync: deaths={RimLinkMod.PawnManager.Deaths}, snapshots={RimLinkMod.PawnManager.Snapshots}");
if (RimLinkMod.CommandQueue.Flushes != 0) throw new Exception("Pause executed game commands");
Current.ProgramState = ProgramState.Entry;
component.GameComponentUpdate();
int stopped = RimLinkMod.PawnManager.Deaths;
for (int i = 0; i < 12; i++) component.GameComponentUpdate();
if (RimLinkMod.PawnManager.Deaths != stopped) throw new Exception("Sync continued after game exit");
Console.WriteLine("PASS: real component syncs deaths and snapshots without ticks; no commands on pause; stops on exit");

namespace UnityEngine {
 public static class Time { public static float unscaledDeltaTime = .25f; }
 public static class Application { public static event Action quitting { add {} remove {} } }
}
namespace RimWorld { }
namespace Verse {
 public enum ProgramState { Playing, Entry }
 public class Game { }
 public class GameComponent {
  public virtual void FinalizeInit() {} public virtual void StartedNewGame() {}
  public virtual void GameComponentTick() {} public virtual void GameComponentUpdate() {}
  public virtual void GameComponentOnGUI() {} public virtual void ExposeData() {}
 }
 public static class Current { public static Game Game = new(); public static ProgramState ProgramState; }
 public static class Find { public static List<int> Maps = new() { 1 }; }
 public static class PawnsFinder { public static List<int> AllMapsCaravansAndTravellingTransporters_Alive = new(); }
 public static class Log { public static void Message(string s) {} public static void Warning(string s) { throw new Exception(s); } public static void Error(string s) { throw new Exception(s); } }
 public static class GenFilePaths { public static string ConfigFolderPath => Path.GetTempPath(); }
}
public static class RimLinkMod {
 public static Settings Instance = new(); public static object Prices = new();
 public static bool GameSessionActive;
 public static Pawns PawnManager = new(); public static Commands CommandQueue = new();
 public static Catalog ShopManager = new(); public static Events EventManager = new(); public static Api API = new();
 public class Settings { public int SyncInterval = 2; }
 public class Pawns {
  public int Deaths, Snapshots; private readonly int main = Environment.CurrentManagedThreadId;
  public void LoadFromCurrentMap() {} public void Clear() {}
  private void CheckThread() { if (main != Environment.CurrentManagedThreadId) throw new Exception("Game state read off main thread"); }
  public void CheckAndSyncDeaths() { CheckThread(); Deaths++; }
  public void SyncAll() { CheckThread(); Snapshots++; }
 }
 public class Commands { public int Flushes; public void FlushBudget(int a,int b) { Flushes++; } public void ClearPending() {} }
 public class Catalog { public List<object> BuildCatalogWithPrices(object p) => new(); }
 public class Events { public List<object> BuildEventCatalog(object p) => new(); }
 public class Api { public void SyncShopCatalog(List<object> x) {} public void SyncEventCatalog(List<object> x) {} public void Heartbeat() {} public void SendOffline() {} }
}
