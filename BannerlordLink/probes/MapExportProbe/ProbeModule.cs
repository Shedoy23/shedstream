using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using SandBox.View.Map;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.ModuleManager;
using TaleWorlds.MountAndBlade;
using Path = System.IO.Path;

namespace ShedLink.MapExportProbe
{
    // No renderer objects, game patches, automatic export, or network. Photo path is unsupported.
    public sealed class ProbeModule : MBSubModuleBase
    {
        private enum Phase { Idle, Requested, SamplingTerrain, Finished }
        // v4 (30.09, Claude): grid fine enough to draw a map from data instead of a photo.
        // v5: 4x denser. v4 did 7680 nodes in 1.04 s on Calradia without a hitch, so ~124k
        // nodes take ~20 s at the same 2 ms/tick budget; the map is static, one export is enough.
        // Columns fixed, rows follow the campaign aspect ratio; hard cap keeps the export bounded.
        // Checkpoint every 5 s: the JSON grows to ~2.5 MB and is rewritten on the game thread.
        private const int GridColumns = 384, MaxGridRows = 384, MaxSamplesPerTick = 256;
        private const double TimeoutSeconds = 180, BatchBudgetMs = 2, CheckpointSeconds = 5;
        private int _gridRows;
        private double _lastCheckpoint;
        private static int _used, _requested, _cancelled;
        private static string _status = "Disabled. Photo unsupported; manual data command required.";
        private readonly Stopwatch _clock = new Stopwatch();
        private Phase _phase;
        private string _folder;
        private JObject _report;
        private Campaign _campaign;
        private Scene _borrowedScene;
        private MapScreen _screen;
        private Vec2 _min, _max;
        private JArray _surface, _campaignHeight, _terrainHeight;
        private int _sampleIndex;
        private bool _hasHeightmap;

        [CommandLineFunctionality.CommandLineArgumentFunction("capture", "shedmap_probe")]
        public static string Capture(List<string> args)
        {
            // Fail closed even with the former valid confirmation. Never consume/queue an attempt.
            return "Photo export unsupported after native crash; no render/capture work queued. Data-only mode is a separate command.";
        }

        [CommandLineFunctionality.CommandLineArgumentFunction("data", "shedmap_probe")]
        public static string Data(List<string> args)
        {
            if (args == null || args.Count != 1 || args[0] != "confirm-data-only")
                return "Manual data only: shedmap_probe.data confirm-data-only";
            if (Interlocked.CompareExchange(ref _used, 1, 0) != 0)
                return "One data attempt per process; no retry or automatic export.";
            Interlocked.Exchange(ref _requested, 1);
            _status = "Data-only queued; no photograph. Close console and stay on campaign map.";
            return _status;
        }

        [CommandLineFunctionality.CommandLineArgumentFunction("status", "shedmap_probe")]
        public static string Status(List<string> args) { return _status; }

        [CommandLineFunctionality.CommandLineArgumentFunction("cancel", "shedmap_probe")]
        public static string Cancel(List<string> args)
        {
            Interlocked.Exchange(ref _cancelled, 1);
            return "Data cancellation requested; no renderer cleanup is needed.";
        }

        protected override void OnApplicationTick(float dt)
        {
            base.OnApplicationTick(dt);
            if (_phase == Phase.Idle && Interlocked.Exchange(ref _requested, 0) == 1)
                _phase = Phase.Requested;
            if (_phase == Phase.Idle || _phase == Phase.Finished) return;
            try
            {
                if (Volatile.Read(ref _cancelled) != 0) { Stop("cancelled", null); return; }
                if (_phase == Phase.Requested) { Begin(); return; }
                if (!StillOnSameReadyMap()) { Stop("map_changed_or_not_ready", null); return; }
                if (_clock.Elapsed.TotalSeconds > TimeoutSeconds) { Stop("data_timeout", null); return; }
                int total = GridColumns * _gridRows;
                if (_clock.Elapsed.TotalSeconds - _lastCheckpoint >= CheckpointSeconds)
                {
                    // Durable progress about once a second (not every tick: the grid JSON is ~100 KB).
                    _lastCheckpoint = _clock.Elapsed.TotalSeconds;
                    _report["nextSampleIndex"] = _sampleIndex;
                    WriteReport();
                }
                var batch = Stopwatch.StartNew();
                for (int count = 0; count < MaxSamplesPerTick && _sampleIndex < total; ++count)
                {
                    if (Volatile.Read(ref _cancelled) != 0) { Stop("cancelled", null); return; }
                    SampleTerrain(_sampleIndex++);
                    // Yield after a query if the small time budget expired; cannot interrupt a native call.
                    if (batch.Elapsed.TotalMilliseconds >= BatchBudgetMs) break;
                }
                if (_sampleIndex == total) Stop("data_complete_geography_unverified", null);
            }
            catch (Exception ex) { Stop("managed_exception", ex); }
        }

        private void Begin()
        {
            _clock.Restart();
            string localData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (string.IsNullOrWhiteSpace(localData) || !Path.IsPathRooted(localData))
                throw new IOException("No absolute LocalApplicationData directory; refusing relative output.");
            _folder = Path.Combine(localData, "ShedLink", "MapExportProbe",
                DateTime.UtcNow.ToString("yyyyMMddTHHmmssZ") + "-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_folder);
            _report = new JObject
            {
                ["schema"] = "shedlink.map-data-probe.v1", ["attemptUtc"] = DateTime.UtcNow.ToString("o"),
                ["status"] = "started", ["runtimeValidated"] = false, ["mode"] = "data-only",
                ["probeRevision"] = "map-data-grid.v5", ["photoSupported"] = false,
                ["rendererObjectsCreated"] = false, ["sharedSceneBorrowedForQueriesOnly"] = true,
                ["limitations"] = new JArray("Terrain samples are not a photograph or a mesh export.",
                    "Native terrain queries remain untested over the full grid and cannot be interrupted by managed timeout.",
                    "Navmesh surface does not identify every visual texture, coastline or water body.",
                    "No scene/player camera/lighting/visibility changes, native releases, save changes or network.")
            };
            WriteReport();
            _campaign = Campaign.Current;
            _screen = MapScreen.Instance;
            _borrowedScene = _screen == null ? null : _screen.MapScene;
            if (!StillOnSameReadyMap()) { Stop("campaign_map_not_ready", null); return; }
            _report["campaignId"] = _campaign.UniqueGameId;
            _report["wrapperType"] = _campaign.MapSceneWrapper.GetType().FullName;
            _report["sceneName"] = _borrowedScene.GetName();
            _report["modulePath"] = _borrowedScene.GetModulePath();
            _report["sceneXmlCrc"] = _borrowedScene.GetSceneXMLCRC();
            _report["navmeshCrc"] = _borrowedScene.GetNavigationMeshCRC();
            _report["containsTerrain"] = _borrowedScene.ContainsTerrain;
            _hasHeightmap = _borrowedScene.HasTerrainHeightmap;
            _report["hasTerrainHeightmap"] = _hasHeightmap;
            var modules = new JArray();
            foreach (var module in ModuleHelper.GetActiveModules())
                modules.Add(new JObject { ["id"] = module.Id, ["folder"] = module.FolderPath });
            _report["activeModules"] = modules;
            float markerZ;
            _campaign.MapSceneWrapper.GetMapBorders(out _min, out _max, out markerZ);
            if (!Finite(_min.x) || !Finite(_min.y) || !Finite(_max.x) || !Finite(_max.y)
                || _max.x <= _min.x || _max.y <= _min.y || !Finite(markerZ))
            { Stop("invalid_campaign_bounds", null); return; }
            _report["campaignBounds"] = new JObject { ["min"] = XY(_min), ["max"] = XY(_max), ["borderMaxMarkerZ"] = markerZ };
            Vec3 sceneMin, sceneMax;
            _borrowedScene.GetBoundingBox(out sceneMin, out sceneMax);
            _report["sceneBounds"] = new JObject { ["min"] = XYZ(sceneMin), ["max"] = XYZ(sceneMax) };
            var landmarks = new JArray();
            _report["landmarks"] = landmarks;
            if (MobileParty.MainParty != null) Sample(landmarks, "mainParty", MobileParty.MainParty.StringId, MobileParty.MainParty.Position);
            bool town = false, village = false, hideout = false;
            foreach (var settlement in Settlement.All)
            {
                string kind = null;
                if (!town && settlement.IsTown) { town = true; kind = "town"; }
                else if (!village && settlement.IsVillage) { village = true; kind = "village"; }
                else if (!hideout && settlement.IsHideout) { hideout = true; kind = "hideout"; }
                if (kind != null) Sample(landmarks, kind, settlement.StringId, settlement.Position);
                if (town && village && hideout) break;
            }
            Sample(landmarks, "boundsCenter", null, new CampaignVec2(new Vec2((_min.x + _max.x) / 2, (_min.y + _max.y) / 2), true));
            // Managed campaign objects only: no native calls, read in one pass.
            _report["factions"] = Factions();
            _report["settlements"] = Settlements();
            _gridRows = GridRows(_min.x, _max.x, _min.y, _max.y);
            _surface = new JArray(); _campaignHeight = new JArray(); _terrainHeight = new JArray();
            _report["terrainGrid"] = new JObject
            {
                ["width"] = GridColumns, ["height"] = _gridRows, ["maxSamplesPerTick"] = MaxSamplesPerTick,
                ["layout"] = "row-major flat arrays, columns increase world X, rows increase world Y",
                ["placement"] = "nodes include campaign bound endpoints; no Y flip",
                ["coordinateUnits"] = "campaign world coordinates", ["interpolation"] = "none",
                ["surfaceSource"] = "land navmesh face type, else sea navmesh face type prefixed 'sea:', else null",
                ["surface"] = _surface, ["campaignHeight"] = _campaignHeight, ["terrainHeight"] = _terrainHeight
            };
            _phase = Phase.SamplingTerrain;
            _report["phase"] = _phase.ToString();
            WriteReport();
            _status = "Sampling bounded data grid; photo remains unsupported. Output: " + _folder;
        }

        private bool StillOnSameReadyMap()
        {
            return _campaign != null && ReferenceEquals(Campaign.Current, _campaign)
                && _campaign.MapSceneWrapper != null && Mission.Current == null
                && Game.Current != null && _screen != null && ReferenceEquals(MapScreen.Instance, _screen)
                && ReferenceEquals(Game.Current.GameStateManager.ActiveState, _screen.MapState)
                && _screen.IsReady && !_screen.IsInMenu && _borrowedScene != null
                && _screen.MapScene == _borrowedScene && _borrowedScene.IsLoadingFinished();
        }

        private static bool FiniteD(double v) { return !double.IsNaN(v) && !double.IsInfinity(v); }

        private static int GridRows(double minX, double maxX, double minY, double maxY)
        {
            if (!FiniteD(minX) || !FiniteD(maxX) || !FiniteD(minY) || !FiniteD(maxY) || maxX <= minX || maxY <= minY)
                throw new ArgumentException("Invalid finite bounds.");
            double rows = Math.Round(GridColumns * (maxY - minY) / (maxX - minX));
            return (int)Math.Max(2, Math.Min(MaxGridRows, rows));
        }

        private static double GridCoordinate(double min, double max, int index, int count)
        {
            if (!FiniteD(min) || !FiniteD(max) || max <= min || count < 2 || count > MaxGridRows || index < 0 || index >= count)
                throw new ArgumentException("Invalid finite bounds or grid index.");
            return min + (max - min) * index / (count - 1);
        }

        private void SampleTerrain(int index)
        {
            int column = index % GridColumns, row = index / GridColumns;
            var xy = new Vec2((float)GridCoordinate(_min.x, _max.x, column, GridColumns),
                (float)GridCoordinate(_min.y, _max.y, row, _gridRows));
            var land = new CampaignVec2(xy, true);
            var face = _campaign.MapSceneWrapper.GetFaceIndex(in land);
            string surface = null;
            if (face.IsValid()) surface = _campaign.MapSceneWrapper.GetFaceTerrainType(face).ToString();
            else
            {
                var sea = new CampaignVec2(xy, false);
                var seaFace = _campaign.MapSceneWrapper.GetFaceIndex(in sea);
                if (seaFace.IsValid()) surface = "sea:" + _campaign.MapSceneWrapper.GetFaceTerrainType(seaFace);
            }
            _surface.Add(surface);
            // Invalid navmesh has no campaign height; don't synthesize Plain or zero.
            float height = 0;
            bool heightValid = face.IsValid() && _campaign.MapSceneWrapper.GetHeightAtPoint(in land, ref height) && Finite(height);
            _campaignHeight.Add(heightValid ? (JToken)Math.Round(height, 2) : JValue.CreateNull());
            JToken terrain = JValue.CreateNull();
            if (_hasHeightmap)
            {
                float terrainHeight;
                Vec3 normal;
                _borrowedScene.GetTerrainHeightAndNormal(xy, out terrainHeight, out normal);
                if (Finite(terrainHeight)) terrain = Math.Round(terrainHeight, 2);
            }
            _terrainHeight.Add(terrain);
        }

        private static JArray Factions()
        {
            var result = new JArray();
            foreach (var kingdom in Kingdom.All)
                result.Add(new JObject
                {
                    ["id"] = kingdom.StringId, ["name"] = kingdom.Name?.ToString(),
                    ["color"] = Hex(kingdom.Color), ["color2"] = Hex(kingdom.Color2), ["eliminated"] = kingdom.IsEliminated
                });
            return result;
        }

        private static JArray Settlements()
        {
            var result = new JArray();
            foreach (var settlement in Settlement.All)
            {
                string kind = settlement.IsTown ? "town" : settlement.IsCastle ? "castle"
                    : settlement.IsVillage ? "village" : settlement.IsHideout ? "hideout" : null;
                if (kind == null) continue;
                var faction = settlement.MapFaction;
                var clan = settlement.OwnerClan;
                result.Add(new JObject
                {
                    ["id"] = settlement.StringId, ["name"] = settlement.Name?.ToString(), ["kind"] = kind,
                    ["xy"] = XY(settlement.Position.ToVec2()),
                    ["bound"] = settlement.IsVillage ? settlement.Village?.Bound?.StringId : null,
                    ["factionId"] = faction?.StringId, ["factionName"] = faction?.Name?.ToString(),
                    ["factionColor"] = faction == null ? null : Hex(faction.Color),
                    ["clanId"] = clan?.StringId, ["clanName"] = clan?.Name?.ToString()
                });
            }
            return result;
        }

        private void Sample(JArray samples, string kind, string id, CampaignVec2 position)
        {
            var sample = new JObject { ["kind"] = kind, ["id"] = id, ["xy"] = XY(position.ToVec2()), ["isOnLand"] = position.IsOnLand };
            try
            {
                float height = 0;
                bool validHeight = _campaign.MapSceneWrapper.GetHeightAtPoint(in position, ref height);
                sample["heightValid"] = validHeight;
                sample["height"] = validHeight && Finite(height) ? (JToken)height : JValue.CreateNull();
                var land = new CampaignVec2(position.ToVec2(), true);
                var sea = new CampaignVec2(position.ToVec2(), false);
                var landFace = _campaign.MapSceneWrapper.GetFaceIndex(in land);
                var seaFace = _campaign.MapSceneWrapper.GetFaceIndex(in sea);
                sample["landFaceValid"] = landFace.IsValid();
                sample["seaFaceValid"] = seaFace.IsValid();
                if (landFace.IsValid()) sample["landTerrainType"] = _campaign.MapSceneWrapper.GetFaceTerrainType(landFace).ToString();
                if (seaFace.IsValid()) sample["seaTerrainType"] = _campaign.MapSceneWrapper.GetFaceTerrainType(seaFace).ToString();
                if (_borrowedScene.HasTerrainHeightmap)
                {
                    float terrainHeight;
                    Vec3 normal;
                    _borrowedScene.GetTerrainHeightAndNormal(position.ToVec2(), out terrainHeight, out normal);
                    sample["terrainHeight"] = Finite(terrainHeight) ? (JToken)terrainHeight : JValue.CreateNull();
                    sample["terrainNormal"] = XYZ(normal);
                }
            }
            catch (Exception ex) { sample["error"] = ex.ToString(); }
            samples.Add(sample);
        }

        private void Stop(string reason, Exception ex)
        {
            if (_phase == Phase.Finished) return;
            if (_report != null)
            {
                _report["status"] = reason;
                _report["stoppedPhase"] = _phase.ToString();
                _report["elapsedSeconds"] = _clock.Elapsed.TotalSeconds;
                _report["completedSamples"] = _surface == null ? 0 : _surface.Count;
                if (ex != null) _report["error"] = ex.ToString();
            }
            _status = reason + (ex == null ? "" : ": " + ex.Message) + "; output: " + (_folder ?? "not created");
            // Borrowed wrappers only: no native clear/release/invalidation or deferred GPU tasks.
            _borrowedScene = null; _screen = null; _campaign = null;
            _phase = Phase.Finished;
            if (_report == null || _folder == null) return;
            try { WriteReport(); } catch (Exception error) { _status += "; JSON write failed: " + error.Message; }
        }

        protected override void OnSubModuleUnloaded()
        {
            if (_phase != Phase.Idle && _phase != Phase.Finished) Stop("module_unloaded", null);
            base.OnSubModuleUnloaded();
        }

        private void WriteReport() { File.WriteAllText(Path.Combine(_folder, "probe.json"), _report.ToString(Formatting.Indented)); }
        private static bool Finite(float value) { return !float.IsNaN(value) && !float.IsInfinity(value); }
        private static string Hex(uint argb) { return "#" + (argb & 0xFFFFFF).ToString("X6"); }
        private static JArray XY(Vec2 v) { return new JArray(v.x, v.y); }
        private static JArray XYZ(Vec3 v) { return new JArray(v.x, v.y, v.z); }
    }
}
