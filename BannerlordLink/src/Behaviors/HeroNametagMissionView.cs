using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordLink.Util;
using TaleWorlds.Core;
using TaleWorlds.Engine;
using TaleWorlds.Engine.GauntletUI;
using TaleWorlds.GauntletUI.Data;
using TaleWorlds.InputSystem;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;
using TaleWorlds.MountAndBlade.View;
using TaleWorlds.MountAndBlade.View.MissionViews;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.33 NAMETAG (2026-05-28) — @username markers над adopted-hero agents
    /// в Mission. Pattern adapted from BLT-Lait (Lait96/Bannerlord-Twitch-lait):
    /// <c>BLTAdoptAHero/Behaviors/BLTHeroWidgetBehavior.cs</c>.
    ///
    /// Зачем НЕ Harmony patch на engine MissionNameMarkerTargetVM:
    ///   - В Bannerlord 1.3.x тип стал GENERIC (`1 suffix) + base class
    ///     non-generic + nested namespace .Targets. Несколько iterations
    ///     fix'ов не приводили к стабильной работе — engine VM API меняется
    ///     between minor versions.
    ///   - BLT-Lait использует AUTONOMOUS Gauntlet layer без engine VM
    ///     dependency — survives любые TaleWorlds internal renames.
    ///
    /// Architecture:
    ///   - <see cref="HeroNametagMissionView"/> наследует MissionView,
    ///     auto-registered через <see cref="DefaultViewAttribute"/>.
    ///   - OnMissionScreenTick (per-frame): iterate Mission.Current.Agents,
    ///     filter agents с adopted hero ([BLink] prefix), compute screen
    ///     position через MBWindowManager.WorldToScreen, update VM positions.
    ///   - Gauntlet layer грузит prefab GUI/Prefabs/BLinkHeroNametag.xml
    ///     с DataSource binding на MBBindingList<HeroNametagVM>.
    ///   - Overlap detection — слайдит overlapping nametag'и vertically
    ///     чтобы они не сливались в кучу.
    ///   - Distance-based scaling (1.0 → 0.5 от 25m → 100m), скрытие за 350m.
    ///
    /// Team colors:
    ///   - Ally  (same team as Agent.Main / PlayerTeam) → green (#4EE04CF0)
    ///   - Enemy → red (#ED1C24F0)
    ///   - Neutral / no main → white (#FFFFFFF0)
    ///
    /// Toggle: hotkey H (default) скрывает все nametag'и до следующего press.
    /// </summary>
    [DefaultView]
    public class HeroNametagMissionView : MissionView
    {
        // ─── Tunable constants ─────────────────────────────────────────────
        private const float CONFIG_WIDTH    = 200f;
        private const float CONFIG_HEIGHT   = 28f;
        private const int   CONFIG_FONTSIZE = 24;
        private const float MAX_VISIBLE_DIST = 350f;   // hide past this distance
        private const float NEAR_SCALE_DIST  = 25f;    // scale=1 below this
        private const float FAR_SCALE_DIST   = 100f;   // scale=0.5 at this
        private const float MIN_SCALE        = 0.5f;
        private const InputKey TOGGLE_KEY    = InputKey.H;

        private static readonly string COLOR_ALLY    = "#4EE04CF0";
        private static readonly string COLOR_ENEMY   = "#ED1C24F0";
        private static readonly string COLOR_NEUTRAL = "#FFFFFFF0";

        // ─── State ─────────────────────────────────────────────────────────
        private GauntletLayer _layer;
        private HeroNametagListVM _vm;
        private GauntletMovieIdentifier _gauntletMovie;
        private Camera _camera;
        private readonly Dictionary<int, HeroNametagVM> _agentToVM
            = new Dictionary<int, HeroNametagVM>();
        private bool _initialized;
        private bool _hideAll;
        private bool _firstTickLogged;

        // 2026-05-28 POST-CRASH: kill-switch — после N consecutive errors
        // отключаем view до next mission. Защита от reproducing crash через
        // per-frame Agent enumeration во время unstable engine state.
        private int _consecutiveErrors;
        private bool _aborted;
        private const int MAX_CONSECUTIVE_ERRORS = 5;

        // ─── MissionView lifecycle ────────────────────────────────────────
        public override void OnMissionScreenTick(float dt)
        {
            // 2026-05-28 POST-CRASH: kill-switch protection. После 5
            // consecutive errors отключаем view (no-op tick) до next mission.
            if (_aborted) return;

            try
            {
                // Toggle key — H по умолчанию.
                if (Input.IsKeyReleased(TOGGLE_KEY))
                {
                    _hideAll = !_hideAll;
                }

                if (Mission.Current == null || MissionScreen == null) return;

                if (!_initialized)
                {
                    InitializeUI();
                    _initialized = true;
                    BannerlordLinkModule.Log(
                        "[NameTag] HeroNametagMissionView initialized (Gauntlet layer registered)");
                }

                UpdateNametags();
                _consecutiveErrors = 0;  // reset on successful tick
            }
            catch (Exception ex)
            {
                _consecutiveErrors++;
                if (!_firstTickLogged || _consecutiveErrors % 30 == 0)
                {
                    _firstTickLogged = true;
                    BannerlordLinkModule.Log(
                        $"[NameTag] OnMissionScreenTick error #{_consecutiveErrors}: " +
                        $"{ex.GetType().Name}: {ex.Message}");
                }
                if (_consecutiveErrors >= MAX_CONSECUTIVE_ERRORS)
                {
                    _aborted = true;
                    BannerlordLinkModule.Log(
                        $"[NameTag] ABORTED — {_consecutiveErrors} consecutive errors. " +
                        "View disabled until next mission to prevent crash cascade.");
                    try
                    {
                        _vm?.Heroes?.Clear();
                        _agentToVM.Clear();
                        if (_layer != null && MissionScreen != null)
                            MissionScreen.RemoveLayer(_layer);
                    }
                    catch { }
                }
            }
        }

        private void InitializeUI()
        {
            _vm = new HeroNametagListVM();
            _layer = new GauntletLayer("BLinkHeroNametagLayer", 15, false);
            _gauntletMovie = _layer.LoadMovie("BLinkHeroNametag", _vm);
            MissionScreen.AddLayer(_layer);
            _camera = MissionScreen.CombatCamera;
        }

        private void UpdateNametags()
        {
            if (_camera == null) return;
            var mission = Mission.Current;
            var agents = mission?.Agents;
            if (agents == null) return;

            // Collect candidates: live agents с adopted hero. Reuse VM per
            // agent.Index чтобы не плодить allocations.
            var seenIndexes = new HashSet<int>();
            var visibleEntries = new List<HeroNametagVM>();

            // 2026-05-28 POST-CRASH: per-agent try/catch — если один agent
            // в plenum'нул state и read'ы throw'ят, не лети fail на весь tick.
            foreach (var agent in agents)
            {
                try
                {
                    if (agent == null || !agent.IsActive() || !agent.IsHuman) continue;
                    var hero = (agent.Character as TaleWorlds.CampaignSystem.CharacterObject)
                        ?.HeroObject;
                    if (hero?.Name == null) continue;

                    string fullName = hero.Name.ToString();
                    if (!HeroNaming.IsAdopted(fullName)) continue;
                    string username = HeroNaming.ExtractUsername(fullName);
                    if (string.IsNullOrEmpty(username)) continue;

                    int key = agent.Index;
                    seenIndexes.Add(key);

                if (!_agentToVM.TryGetValue(key, out var vm))
                {
                    vm = new HeroNametagVM
                    {
                        HeroName = "@" + username,
                        IsVisible = false,
                        Width = CONFIG_WIDTH,
                        Height = CONFIG_HEIGHT,
                        FontSize = CONFIG_FONTSIZE,
                        Color = COLOR_NEUTRAL,
                    };
                    _vm.Heroes.Add(vm);
                    _agentToVM[key] = vm;
                }

                if (_hideAll)
                {
                    vm.IsVisible = false;
                    continue;
                }

                // Compute screen position over head.
                Vec3 worldPos = agent.Position;
                worldPos.z += agent.GetEyeGlobalHeight() + 0.15f;

                float x = 0f, y = 0f, z = 0f;
                MBWindowManager.WorldToScreen(_camera, worldPos, ref x, ref y, ref z);

                bool onScreen = z > 0f
                              && x > 0f && y > 0f
                              && x < Screen.RealScreenResolutionWidth
                              && y < Screen.RealScreenResolutionHeight;

                if (!onScreen)
                {
                    vm.IsVisible = false;
                    continue;
                }

                float dist = agent.Position.Distance(_camera.Position);
                if (dist > MAX_VISIBLE_DIST)
                {
                    vm.IsVisible = false;
                    continue;
                }

                // Lerp scale 1.0 → MIN_SCALE между NEAR/FAR distances.
                float scale = MBMath.Lerp(1f, MIN_SCALE,
                    (dist - NEAR_SCALE_DIST) / (FAR_SCALE_DIST - NEAR_SCALE_DIST),
                    0f);
                scale = MBMath.ClampFloat(scale, MIN_SCALE, 1f);

                vm.Width    = CONFIG_WIDTH * scale;
                vm.Height   = CONFIG_HEIGHT * scale;
                vm.FontSize = Math.Max(15, (int)(CONFIG_FONTSIZE * scale));
                vm.PositionX = x - vm.Width * 0.5f;
                vm.PositionY = y - vm.Height * 0.5f - 5f;
                vm.Color    = ResolveColor(agent);
                vm.IsVisible = true;
                visibleEntries.Add(vm);
                }   // end inner try (per-agent block — POST-CRASH safety)
                catch (Exception agentEx)
                {
                    // Single-agent failure не должен валить tick. Log once per session.
                    if (!_firstTickLogged)
                    {
                        _firstTickLogged = true;
                        BannerlordLinkModule.Log(
                            $"[NameTag] per-agent error (first only): " +
                            $"{agentEx.GetType().Name}: {agentEx.Message}");
                    }
                    // continue к next agent
                }
            }

            // Remove VMs for agents that died/despawned.
            var toRemove = _agentToVM.Where(kv => !seenIndexes.Contains(kv.Key))
                                     .Select(kv => kv.Key)
                                     .ToList();
            foreach (var key in toRemove)
            {
                _vm.Heroes.Remove(_agentToVM[key]);
                _agentToVM.Remove(key);
            }

            // Overlap-slide: sort by Y, push lower entries down if overlap.
            ResolveOverlaps(visibleEntries);
        }

        private static string ResolveColor(Agent agent)
        {
            try
            {
                var main = Agent.Main;
                if (main != null && agent != main)
                {
                    if (agent.IsEnemyOf(main)) return COLOR_ENEMY;
                    if (agent.IsFriendOf(main)) return COLOR_ALLY;
                }
                else if (main == null)
                {
                    var pt = Mission.Current?.PlayerTeam;
                    if (pt != null && agent.Team != null)
                    {
                        if (agent.Team == pt) return COLOR_ALLY;
                        if (agent.Team.IsEnemyOf(pt)) return COLOR_ENEMY;
                    }
                }
            }
            catch { }
            return COLOR_NEUTRAL;
        }

        private static void ResolveOverlaps(List<HeroNametagVM> visible)
        {
            if (visible.Count < 2) return;
            // Sort by Y ascending (top to bottom).
            visible.Sort((a, b) => a.PositionY.CompareTo(b.PositionY));

            const float MIN_OVERLAP_Y = 4f;
            const float PADDING_Y     = 2f;
            const float SLIDE_FACTOR  = 0.5f;
            const float MAX_LOOK_AHEAD_Y = 50f;

            for (int i = 0; i < visible.Count - 1; i++)
            {
                var anchor = visible[i];
                for (int j = i + 1; j < visible.Count; j++)
                {
                    var farther = visible[j];
                    if (!farther.IsVisible) continue;
                    if (Math.Abs(farther.PositionY - (anchor.PositionY + anchor.Height))
                        > MAX_LOOK_AHEAD_Y) break;

                    bool overlapX = farther.PositionX < anchor.PositionX + anchor.Width * 0.9f
                                 && farther.PositionX + farther.Width * 0.9f > anchor.PositionX;
                    bool overlapY = farther.PositionY < anchor.PositionY + anchor.Height
                                 && farther.PositionY + farther.Height > anchor.PositionY;

                    if (overlapX && overlapY)
                    {
                        float overlapAmtY = (anchor.PositionY + anchor.Height) - farther.PositionY;
                        if (overlapAmtY > MIN_OVERLAP_Y)
                        {
                            farther.PositionY -= overlapAmtY * SLIDE_FACTOR + PADDING_Y;
                        }
                    }
                }
            }
        }

        public override void OnRemoveBehavior()
        {
            try
            {
                _agentToVM.Clear();
                _vm?.Heroes.Clear();
                if (_layer != null && MissionScreen != null)
                    MissionScreen.RemoveLayer(_layer);
                _layer = null;
                _vm = null;
                _camera = null;
                _initialized = false;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[NameTag] OnRemoveBehavior crash: {ex.Message}");
            }
            base.OnRemoveBehavior();
        }
    }

    // ─── ViewModels (Gauntlet DataSource binding) ──────────────────────────

    public class HeroNametagListVM : ViewModel
    {
        [DataSourceProperty]
        public MBBindingList<HeroNametagVM> Heroes { get; } = new MBBindingList<HeroNametagVM>();
    }

    public class HeroNametagVM : ViewModel
    {
        private string _heroName;
        private bool   _isVisible;
        private float  _positionX;
        private float  _positionY;
        private string _color;
        private float  _width;
        private float  _height;
        private int    _fontSize;

        [DataSourceProperty]
        public string HeroName
        {
            get => _heroName;
            set { if (_heroName != value) { _heroName = value; OnPropertyChanged(nameof(HeroName)); } }
        }

        [DataSourceProperty]
        public bool IsVisible
        {
            get => _isVisible;
            set { if (_isVisible != value) { _isVisible = value; OnPropertyChanged(nameof(IsVisible)); } }
        }

        [DataSourceProperty]
        public float PositionX
        {
            get => _positionX;
            set { if (_positionX != value) { _positionX = value; OnPropertyChanged(nameof(PositionX)); } }
        }

        [DataSourceProperty]
        public float PositionY
        {
            get => _positionY;
            set { if (_positionY != value) { _positionY = value; OnPropertyChanged(nameof(PositionY)); } }
        }

        [DataSourceProperty]
        public string Color
        {
            get => _color;
            set { if (_color != value) { _color = value; OnPropertyChanged(nameof(Color)); } }
        }

        [DataSourceProperty]
        public float Width
        {
            get => _width;
            set { if (_width != value) { _width = value; OnPropertyChanged(nameof(Width)); } }
        }

        [DataSourceProperty]
        public float Height
        {
            get => _height;
            set { if (_height != value) { _height = value; OnPropertyChanged(nameof(Height)); } }
        }

        [DataSourceProperty]
        public int FontSize
        {
            get => _fontSize;
            set { if (_fontSize != value) { _fontSize = value; OnPropertyChanged(nameof(FontSize)); } }
        }
    }
}
