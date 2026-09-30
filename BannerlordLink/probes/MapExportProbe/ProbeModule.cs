using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
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
using Camera = TaleWorlds.Engine.Camera;
using Path = System.IO.Path;

namespace ShedLink.MapExportProbe
{
    // Optional standalone module. No campaign behaviour, patches, network or automatic capture.
    public sealed class ProbeModule : MBSubModuleBase
    {
        private enum Phase { Idle, Requested, WaitingForView, EnabledForOneFrame, WaitingForFile, Cleanup, Finished }
        private static int _used, _requested, _cancelled;
        private static string _status = "Disabled. Manual capture required.";
        private readonly Stopwatch _clock = new Stopwatch();
        private Phase _phase;
        private int _cleanupTicks;
        private string _folder;
        private JObject _report;
        private Campaign _campaign;
        private Scene _borrowedScene;
        private MapScreen _screen;
        private SceneView _view;
        private Camera _camera;
        private Texture _target, _depth;
        private long _previousFileLength = -1;
        private bool _cleanupQueued;

        [CommandLineFunctionality.CommandLineArgumentFunction("capture", "shedmap_probe")]
        public static string Capture(List<string> args)
        {
            if (args == null || args.Count != 1 || args[0] != "confirm-after-stream")
                return "Usage AFTER STREAM: shedmap_probe.capture confirm-after-stream";
            if (Interlocked.CompareExchange(ref _used, 1, 0) != 0)
                return "One attempt per process; no retry or automatic export.";
            Interlocked.Exchange(ref _requested, 1);
            _status = "Queued; no snapshot confirmed. Close console and stay on campaign map.";
            return _status;
        }

        [CommandLineFunctionality.CommandLineArgumentFunction("status", "shedmap_probe")]
        public static string Status(List<string> args) { return _status; }

        [CommandLineFunctionality.CommandLineArgumentFunction("cancel", "shedmap_probe")]
        public static string Cancel(List<string> args)
        {
            Interlocked.Exchange(ref _cancelled, 1);
            return "Cancellation requested; cleanup runs on application thread.";
        }

        protected override void OnApplicationTick(float dt)
        {
            base.OnApplicationTick(dt);
            if (_phase == Phase.Idle && Interlocked.Exchange(ref _requested, 0) == 1)
                _phase = Phase.Requested;
            if (_phase == Phase.Idle || _phase == Phase.Finished) return;
            try
            {
                if (_phase == Phase.Cleanup)
                {
                    if (++_cleanupTicks >= 4) FinishCleanup();
                    return;
                }
                if (Volatile.Read(ref _cancelled) != 0) { Stop("cancelled", null); return; }
                if (_phase == Phase.Requested) { Begin(); return; }
                if (!StillOnSameReadyMap()) { Stop("map_changed_or_not_ready", null); return; }
                if (_clock.Elapsed.TotalSeconds > 5) { Stop("phase_timeout", null); return; }
                if (_phase == Phase.WaitingForView)
                {
                    if (!_view.CheckSceneReadyToRender()) return;
                    _report["viewReadyToRenderBeforeEnable"] = _view.ReadyToRender();
                    // Only this offscreen view is enabled, until the next application tick.
                    // Native scheduling/save semantics remain an AFTER-STREAM experiment.
                    _view.SetSaveFinalResultToDisk(true);
                    _view.SetEnable(true);
                    _phase = Phase.EnabledForOneFrame;
                    _clock.Restart();
                    return;
                }
                if (_phase == Phase.EnabledForOneFrame)
                {
                    DisableOwnView();
                    _phase = Phase.WaitingForFile;
                    _clock.Restart();
                    return;
                }
                if (_phase == Phase.WaitingForFile) CheckOutput();
            }
            catch (Exception ex) { Stop("managed_exception", ex); }
        }

        private void Begin()
        {
            string localData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (string.IsNullOrWhiteSpace(localData) || !Path.IsPathRooted(localData))
                throw new IOException("No absolute LocalApplicationData directory; refusing relative output.");
            _folder = Path.Combine(localData,
                "ShedLink", "MapExportProbe", DateTime.UtcNow.ToString("yyyyMMddTHHmmssZ") + "-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_folder);
            _report = new JObject
            {
                ["schema"] = "shedlink.map-probe.v1", ["attemptUtc"] = DateTime.UtcNow.ToString("o"),
                ["status"] = "started", ["runtimeValidated"] = false,
                ["baseCommit"] = "7e382b1ca648a2719206f5ba2bec680ca557ca4f",
                ["sharedScene"] = true, ["sceneObjectsMayAppearInImage"] = true,
                ["renderSize"] = new JArray(256, 256),
                ["limitations"] = new JArray("Native render/save/cleanup are experimental.",
                    "No shared scene visibility, entities, lighting or player camera changes.",
                    "PNG validity does not prove geographic coverage or independent culling.")
            };
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
            _report["hasTerrainHeightmap"] = _borrowedScene.HasTerrainHeightmap;
            var modules = new JArray();
            foreach (var module in ModuleHelper.GetActiveModules())
                modules.Add(new JObject { ["id"] = module.Id, ["folder"] = module.FolderPath });
            _report["activeModules"] = modules;
            Vec2 min, max;
            float borderMarkerZ;
            _campaign.MapSceneWrapper.GetMapBorders(out min, out max, out borderMarkerZ);
            if (!Finite(min.x) || !Finite(min.y) || !Finite(max.x) || !Finite(max.y)
                || max.x <= min.x || max.y <= min.y || !Finite(borderMarkerZ))
            { Stop("invalid_campaign_bounds", null); return; }
            _report["campaignBounds"] = new JObject { ["min"] = XY(min), ["max"] = XY(max), ["borderMaxMarkerZ"] = borderMarkerZ };
            Vec3 sceneMin, sceneMax;
            _borrowedScene.GetBoundingBox(out sceneMin, out sceneMax);
            _report["sceneBounds"] = new JObject { ["min"] = XYZ(sceneMin), ["max"] = XYZ(sceneMax) };
            var landmarks = new JArray();
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
            Sample(landmarks, "boundsCenter", null, new CampaignVec2(new Vec2((min.x + max.x) / 2, (min.y + max.y) / 2), true));
            _report["landmarks"] = landmarks;
            float terrainMin, terrainMax;
            terrainMin = terrainMax = 0;
            bool terrainRange = _borrowedScene.HasTerrainHeightmap && _borrowedScene.GetTerrainMinMaxHeight(out terrainMin, out terrainMax);
            float top = borderMarkerZ;
            if (Finite(sceneMax.z)) top = Math.Max(top, sceneMax.z);
            if (terrainRange && Finite(terrainMax)) top = Math.Max(top, terrainMax);
            float span = Math.Max(max.x - min.x, max.y - min.y);
            float bottom = terrainRange && Finite(terrainMin) ? terrainMin : 0;
            if (Finite(sceneMin.z)) bottom = Math.Min(bottom, sceneMin.z);
            float altitude = top + Math.Max(100, span * 0.1f);
            float far = Math.Max(200, altitude - bottom + 100);
            if (!Finite(altitude) || !Finite(far) || !Finite(span)) { Stop("invalid_camera_extent", null); return; }
            _camera = Camera.CreateCamera();
            _view = SceneView.CreateSceneView();
            if (_camera == null || _view == null) throw new InvalidOperationException("Native camera/view allocation failed.");
            _view.SetEnable(false);
            var frame = MatrixFrame.Identity; // Camera.Direction == -Frame.rotation.u: identity looks down -Z.
            frame.origin = new Vec3((min.x + max.x) / 2, (min.y + max.y) / 2, altitude);
            _camera.Frame = frame;
            _camera.SetViewVolume(false, -span / 2, span / 2, -span / 2, span / 2, 1, far);
            _report["camera"] = new JObject { ["origin"] = XYZ(frame.origin), ["orthographicSpan"] = span, ["near"] = 1, ["far"] = far };
            _target = Texture.CreateRenderTarget("shedmap_probe_" + Guid.NewGuid().ToString("N"), 256, 256, false, false);
            _depth = Texture.CreateDepthTarget("shedmap_probe_depth_" + Guid.NewGuid().ToString("N"), 256, 256);
            if (_target == null || _depth == null) throw new InvalidOperationException("Native texture allocation failed.");
            _view.SetScene(_borrowedScene);
            _view.SetCamera(_camera);
            _view.SetRenderTarget(_target);
            _view.SetDepthTarget(_depth);
            _view.SetRenderWithPostfx(false);
            _view.SetAcceptGlobalDebugRenderObjects(false);
            _view.SetResolutionScaling(false);
            _view.SetRenderOnDemand(false);
            _view.SetFilePathToSaveResult(_folder + Path.DirectorySeparatorChar);
            _view.SetFileNameToSaveResult("snapshot.png");
            _view.SetFileTypeToSave(View.TextureSaveFormat.TextureTypePng);
            WriteReport();
            _status = "Probe view waiting for readiness. Output: " + _folder;
            _phase = Phase.WaitingForView;
            _clock.Restart();
        }

        private bool StillOnSameReadyMap()
        {
            return _campaign != null && ReferenceEquals(Campaign.Current, _campaign)
                && _campaign.MapSceneWrapper != null && Mission.Current == null
                && Game.Current != null && _screen != null && ReferenceEquals(MapScreen.Instance, _screen)
                && ReferenceEquals(Game.Current.GameStateManager.ActiveState, _screen.MapState)
                && _screen.IsReady && !_screen.IsInMenu && _borrowedScene != null
                && _screen.MapScene == _borrowedScene && _borrowedScene.IsLoadingFinished()
                && _screen.SceneLayer != null && _screen.SceneLayer.SceneView.CheckSceneReadyToRender();
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

        private void CheckOutput()
        {
            string path = Path.Combine(_folder, "snapshot.png");
            // Native filename extension handling is unverified; inspect only our unique run folder.
            if (!File.Exists(path)) path += ".png";
            if (!File.Exists(path)) return;
            long length = new FileInfo(path).Length;
            if (length <= 0 || length != _previousFileLength) { _previousFileLength = length; return; }
            try
            {
                if (length > 2 * 1024 * 1024) { Stop("unexpected_png_size", null); return; }
                using (var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    var signature = new byte[8];
                    if (stream.Read(signature, 0, 8) != 8 || BitConverter.ToString(signature) != "89-50-4E-47-0D-0A-1A-0A")
                        throw new InvalidDataException("Output is not PNG.");
                    stream.Position = 0;
                    using (var image = Image.FromStream(stream, true, true))
                    {
                        if (image.Width != 256 || image.Height != 256) throw new InvalidDataException("Wrong PNG dimensions.");
                        _report["png"] = new JObject { ["path"] = path, ["bytes"] = length, ["width"] = image.Width, ["height"] = image.Height };
                    }
                }
                Stop("png_valid_geography_unverified", null);
            }
            catch (IOException) { /* Native writer may still have the file open; bounded by phase timeout. */ }
            catch (ArgumentException) { /* Incomplete PNG: wait, then timeout; never claim success. */ }
        }

        private void DisableOwnView()
        {
            if (_view == null) return;
            _view.SetEnable(false);
            _view.SetSaveFinalResultToDisk(false);
        }

        private void Stop(string reason, Exception ex)
        {
            if (_phase == Phase.Cleanup || _phase == Phase.Finished) return;
            if (_report != null) { _report["status"] = reason; if (ex != null) _report["error"] = ex.ToString(); }
            _status = reason + (ex == null ? "" : ": " + ex.Message) + "; output: " + (_folder ?? "not created");
            _phase = Phase.Cleanup;
            _cleanupTicks = 0;
            // Queue clearing of OUR view only. Never ClearAll(true,...), SceneLayer, or borrowed scene invalidation.
            TryCleanup("disableView", DisableOwnView);
            if (_view != null) TryCleanup("queueClearOwnView", delegate { _view.AddClearTask(true); _cleanupQueued = true; });
            WriteReportSafely();
        }

        private void FinishCleanup()
        {
            // Use NativeObject's ordinary reference-count lifetime, not forced native destruction/GPU release.
            // Retain all owned wrappers for four application ticks after the clear request.
            if (_view != null) TryCleanup("releaseViewReference", delegate { _view.ManualInvalidate(); });
            if (_camera != null) TryCleanup("releaseCameraReference", delegate { _camera.ManualInvalidate(); });
            ReleaseTexture("releaseColorReference", _target);
            ReleaseTexture("releaseDepthReference", _depth);
            _view = null; _camera = null; _target = null; _depth = null;
            _borrowedScene = null; _screen = null; _campaign = null;
            if (_report != null) { _report["cleanupClearQueued"] = _cleanupQueued; _report["cleanupReferenceReleaseAttempted"] = true; }
            _phase = Phase.Finished;
            WriteReportSafely();
        }

        private void ReleaseTexture(string label, Texture texture)
        {
            if (texture == null) return;
            TryCleanup(label, delegate
            {
                if (texture.RenderTargetComponent != null) texture.Release();
                else texture.ManualInvalidate();
            });
        }

        private void TryCleanup(string label, Action action)
        {
            try { action(); }
            catch (Exception ex)
            {
                if (_report != null) _report[label + "Error"] = ex.ToString();
                _status = "Cleanup error: " + label + "; inspect probe.json.";
            }
        }

        protected override void OnSubModuleUnloaded()
        {
            if (_phase != Phase.Idle && _phase != Phase.Finished)
            {
                Stop("module_unloaded", null);
                // No more ticks guaranteed: relinquish references; engine owns queued-task lifetime.
                FinishCleanup();
            }
            base.OnSubModuleUnloaded();
        }

        private void WriteReport() { File.WriteAllText(Path.Combine(_folder, "probe.json"), _report.ToString(Formatting.Indented)); }
        private void WriteReportSafely()
        {
            if (_report == null || _folder == null) return;
            try { WriteReport(); } catch (Exception ex) { _status += "; JSON write failed: " + ex.Message; }
        }
        private static bool Finite(float value) { return !float.IsNaN(value) && !float.IsInfinity(value); }
        private static JArray XY(Vec2 v) { return new JArray(v.x, v.y); }
        private static JArray XYZ(Vec3 v) { return new JArray(v.x, v.y, v.z); }
    }
}
