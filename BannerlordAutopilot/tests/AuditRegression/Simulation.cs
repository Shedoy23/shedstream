namespace SandBox.GauntletUI.Map {
 public class GauntletMapBattleSimulationView : SandBox.View.Map.MapView {
  private readonly SimulationScoreboard _dataSource;
  public GauntletMapBattleSimulationView(SimulationScoreboard vm) { _dataSource=vm; }
 }
 public class SimulationScoreboard {
  private readonly TestBattleSimulation _battleSimulation = new TestBattleSimulation();
  public TestBattleSimulation Simulation => _battleSimulation;
  public bool IsOver {get;set;}
  public bool IsSimulation {get;set;} = true;
  public bool ShowScoreboard {get;set;} = true;
  public int Exits;
  public void ExecuteQuitAction() { Exits++; }
 }
 public class TestBattleSimulation { public bool IsSimulationFinished {get;set;} = true; }
}
