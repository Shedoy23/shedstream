using System;
using System.Collections.Generic;
using TaleWorlds.Engine;
using TaleWorlds.Core;
using TaleWorlds.InputSystem;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;
using TaleWorlds.MountAndBlade.View;
using TaleWorlds.MountAndBlade.View.MissionViews;

namespace BannerlordAutopilot
{
    // Registered by the native view creator; rendering stays on the mission UI thread.
    [DefaultView]
    public sealed class BattleOverviewCamera : MissionView
    {
        private readonly BattleOverviewRig _rig = new BattleOverviewRig();
        private readonly List<BattleOverviewRig.Point> _fighters = new List<BattleOverviewRig.Point>();
        private bool _enabled = true, _owned, _previousFirstPerson, _failed;
        private float _refresh;

        private bool Eligible => !_failed && MissionScreen != null && Mission != null
            && AutopilotBehavior.Instance?.CurrentMode == AutopilotBehavior.Mode.Apply
            && Mission.GetMissionBehavior<BattleAutopilotMission>() != null
            && Mission.IsDeploymentFinished && Mission.Mode == MissionMode.Battle
            && !Mission.MissionEnded && !IsViewSuspended && !MissionScreen.IsPhotoModeEnabled
            && MissionScreen.CustomCamera == null && !InformationManager.IsAnyInquiryActive();

        public override void OnMissionScreenTick(float dt)
        {
            if (!Eligible) { Release(); return; }
            if (Input.IsKeyPressed(InputKey.F9))
            {
                _enabled = !_enabled;
                if (!_enabled) Release();
                AutopilotLog.Write("КАМЕРА: " + (_enabled ? "высокий обзор (F9)" : "обычная камера (F9)"));
            }
            if (!_enabled) return;
            _rig.Zoom(Input.GetDeltaMouseScroll() / 120f);
            if (Input.IsKeyDown(InputKey.MiddleMouseButton))
                _rig.Rotate(Input.GetMouseMoveX(), Input.GetMouseMoveY());
        }

        public override bool UpdateOverridenCamera(float dt)
        {
            if (!_enabled || !Eligible) { Release(); return false; }
            try
            {
                _refresh -= dt;
                if (_refresh <= 0f || !_rig.Ready)
                {
                    _refresh = 0.5f;
                    _fighters.Clear();
                    foreach (var agent in Mission.Agents)
                    {
                        if (!agent.IsActive() || !agent.IsHuman || agent.Team == null) continue;
                        var p = agent.Position;
                        _fighters.Add(new BattleOverviewRig.Point(p.x, p.y, p.z,
                            Mission.PlayerTeam != null && agent.Team.IsEnemyOf(Mission.PlayerTeam)));
                    }
                    _rig.Focus(_fighters);
                }
                if (!_rig.Ready) return false;
                if (!_owned)
                {
                    _previousFirstPerson = Mission.CameraIsFirstPerson;
                    Mission.CameraIsFirstPerson = false;
                    _owned = true;
                    AutopilotLog.Write("КАМЕРА: обзор сверху, высота 80 м; колесо — высота, средняя кнопка — поворот, F9 — герой");
                }
                _rig.Step(dt);
                var target = new Vec3(_rig.X, _rig.Y, _rig.Z);
                var location = new Vec3(_rig.CameraX, _rig.CameraY, _rig.CameraZ);
                // A hillside behind the fight must not swallow the camera.
                location.z = Math.Max(location.z, Mission.Scene.GetGroundHeightAtPosition(location) + 12f);
                // Returning true skips MissionScreen.UpdateCamera completely, including
                // projection and the native mission camera used for visual updates.
                MissionScreen.CombatCamera.SetFovVertical(65f * (float)Math.PI / 180f,
                    TaleWorlds.Engine.Screen.AspectRatio, 0.1f, 12500f);
                MissionScreen.CombatCamera.LookAt(location, target, Vec3.Up);
                var frame = MissionScreen.CombatCamera.Frame;
                Mission.SetCameraFrame(ref frame, 1f, ref location);
                MissionScreen.SceneView.SetCamera(MissionScreen.CombatCamera);
                SoundManager.SetListenerFrame(MissionScreen.CombatCamera.Frame);
                return true;
            }
            catch (Exception ex)
            {
                _failed = true;
                Release();
                AutopilotLog.Write("КАМЕРА: обзор отключён после ошибки; штатная камера сохранена: " + ex.Message);
                return false;
            }
        }

        private void Release()
        {
            if (_owned && Mission != null) Mission.CameraIsFirstPerson = _previousFirstPerson;
            _owned = false;
            _refresh = 0;
            _rig.ResetPosition();
        }
        public override void OnMissionScreenFinalize() { Release(); base.OnMissionScreenFinalize(); }
        public override void OnMissionScreenDeactivate() { Release(); base.OnMissionScreenDeactivate(); }
    }
}
