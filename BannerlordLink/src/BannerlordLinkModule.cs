using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Actions;
using BannerlordLink.Behaviors;
using BannerlordLink.Net;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.MountAndBlade;
using Debug = TaleWorlds.Library.Debug;

namespace BannerlordLink
{
    /// <summary>
    /// Entry point Bannerlord-мода. Поднимается игрой через SubModule.xml.
    /// </summary>
    public class BannerlordLinkModule : MBSubModuleBase
    {
        private const string MOD_NAME = "BannerlordLink";
        private const string MOD_VERSION = "0.1.0";
        private const string HARMONY_ID = "ru.shedoy23.bannerlordlink";

        private static readonly string _logPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "Mount and Blade II Bannerlord", "Configs", "ModLogs",
            $"bannerlordlink_{DateTime.Now:yyyyMMdd}.txt"
        );

        private Harmony _harmony;

        // Sprint 2.2: shared между all subscribers моду. Public static чтобы
        // CampaignBehavior'ы и action handlers могли его дёргать.
        public static BackendConfig Config { get; private set; }
        public static BackendClient Backend { get; private set; }
        public static ActionPoller Poller { get; private set; }

        /// <summary>Простой file-based logger чтобы видеть load в TXT.</summary>
        public static void Log(string msg)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(_logPath));
                File.AppendAllText(
                    _logPath,
                    $"[{DateTime.Now:HH:mm:ss.fff}] {msg}{Environment.NewLine}"
                );
            }
            catch (Exception) { /* file logging fail — не критично */ }

            try { Debug.Print($"[{MOD_NAME}] {msg}"); } catch (Exception) { }
        }

        // Sprint 5.32 — verbose logging toggle.
        // Включается через env-var BANNERLORDLINK_VERBOSE=1 ИЛИ через файл-flag
        // в %MyDocs%/Mount and Blade II Bannerlord/Configs/bannerlordlink_verbose.flag
        // (создать пустой файл с таким именем — verbose on).
        //
        // При verbose=true:
        //   - DamageHookPatch логирует каждый blow с inputs/outputs
        //   - SummonHero логирует каждый retinue agent (Index, HP, equipment)
        //   - Detachment логирует formation state before/after
        //   - LeaveClan логирует reflection step-by-step
        // Это **очень шумно** — только для diagnosis crash'ей. На обычном
        // streamе оставляй OFF.
        //
        // Cached в static field — eval'им once при первом use. Если flag
        // создан/удалён mid-session — нужен restart mod'а.
        private static readonly bool _verboseLog = ResolveVerboseFlag();

        public static bool VerboseEnabled => _verboseLog;

        /// <summary>Verbose log — выводится ТОЛЬКО если VERBOSE-flag enabled.
        /// Callers оборачивают ленивым string-build чтобы не allocate'ить
        /// при disabled state: `Log.LogVerbose(() => $"detail: {hot_calc}")`.</summary>
        public static void LogVerbose(Func<string> msgFactory)
        {
            if (!_verboseLog) return;
            try { Log("[V] " + msgFactory()); }
            catch (Exception ex) { Log($"[V] factory crashed: {ex.Message}"); }
        }

        /// <summary>Plain verbose без lazy — для cheap message construction.</summary>
        public static void LogVerbose(string msg)
        {
            if (!_verboseLog) return;
            Log("[V] " + msg);
        }

        private static bool ResolveVerboseFlag()
        {
            // 2026-05-28: DEFAULT_ON revert → false. Verbose log I/O contributed
            // (likely) к FMOD resource exhaustion в long battles (crash dump
            // 2026-05-28_16.53.15 показал FMOD error 30 "invalid object handle").
            // Flag-file `bannerlordlink_verbose.flag` остаётся opt-in для debug.
            const bool DEFAULT_ON = false;
            try
            {
                // Explicit env-var override: BANNERLORDLINK_VERBOSE=0 force-disables.
                string env = Environment.GetEnvironmentVariable("BANNERLORDLINK_VERBOSE");
                if (env == "1") return true;
                if (env == "0") return false;
                var flagFile = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                    "Mount and Blade II Bannerlord", "Configs",
                    "bannerlordlink_verbose.flag");
                if (File.Exists(flagFile)) return true;
                var disableFile = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                    "Mount and Blade II Bannerlord", "Configs",
                    "bannerlordlink_verbose_OFF.flag");
                if (File.Exists(disableFile)) return false;
                return DEFAULT_ON;
            }
            catch { return DEFAULT_ON; }
        }

        protected override void OnSubModuleLoad()
        {
            base.OnSubModuleLoad();
            Log($"v{MOD_VERSION} OnSubModuleLoad");
            Log($"[VERBOSE] verbose logging = {(_verboseLog ? "ON (детальные logs включены)" : "OFF (стандартное)")}. " +
                $"Toggle via env BANNERLORDLINK_VERBOSE=1 или файл bannerlordlink_verbose.flag в Configs/");

            // Sprint 5.28: GLOBAL crash hooks. До этого спринта unhandled
            // exceptions на background thread'ах валили процесс БЕЗ логов —
            // ButterLib ловит только main-thread, AppDomain hooks никем не
            // ставились. Теперь любой fault логируется в bannerlordlink_*.txt
            // с полным stack trace, прежде чем game упадёт.
            //
            // UnobservedTaskException — для fire-and-forget Task.Run в hot
            // path (battle.stats_snapshot, HeroStateSync, BuffState). После
            // SetObserved() .NET не валит процесс (4.5+ default не-валит,
            // но явно подстраховываемся).
            try
            {
                AppDomain.CurrentDomain.UnhandledException += (sender, e) =>
                {
                    try
                    {
                        var ex = e.ExceptionObject as Exception;
                        Log($"[FATAL] AppDomain.UnhandledException terminating={e.IsTerminating}: " +
                            $"{ex?.GetType().FullName}: {ex?.Message}\n{ex?.StackTrace}\n" +
                            $"InnerException: {ex?.InnerException?.GetType().FullName}: " +
                            $"{ex?.InnerException?.Message}\n{ex?.InnerException?.StackTrace}");
                    }
                    catch { }
                };
                TaskScheduler.UnobservedTaskException += (sender, e) =>
                {
                    try
                    {
                        Log($"[WARN] UnobservedTaskException: {e.Exception?.GetType().FullName}: " +
                            $"{e.Exception?.Message}\n{e.Exception?.StackTrace}");
                        e.SetObserved();   // не валим процесс
                    }
                    catch { }
                };
                Log("Global crash hooks installed (AppDomain.UnhandledException + UnobservedTaskException)");
            }
            catch (Exception ex)
            {
                Log($"Crash hooks install FAILED: {ex.Message}");
            }

            // Sprint 2.2: load config + init backend client + async ping.
            // Если backend unreachable — log warning, мод продолжает работать
            // без backend (offline-mode, future actions просто не дойдут).
            try
            {
                Config = BackendConfig.LoadOrCreate(Log);
                Backend = new BackendClient(Config, Log);

                // Fire-and-forget: ping + module.session_start event если есть token.
                Task.Run(async () =>
                {
                    bool ok = await Backend.PingAsync();
                    Log(ok
                        ? "Backend connectivity: OK ✓"
                        : "Backend connectivity: FAILED (mod в offline-mode)");

                    // Sprint 2.3: handshake — посылаем module.session_start.
                    // Backend RimWorld-style: clear catalogs + acknowledge mod online.
                    if (ok && !string.IsNullOrEmpty(Config.ModuleToken))
                    {
                        string sessionData =
                            $"{{\"save_id\":\"boot_{DateTime.UtcNow.Ticks}\",\"mod_version\":\"{MOD_VERSION}\"}}";
                        bool acked = await Backend.PostEventAsync(
                            "bannerlord", "module.session_start", sessionData);
                        Log(acked
                            ? "Module API handshake: SUCCESS — backend знает что мы online"
                            : "Module API handshake: FAILED — проверь module_token в config.json");

                        if (acked)
                        {
                            // Sprint 2.4: start action poller после успешного handshake.
                            // ActionRegistry.RegisterDefaults() ставит EchoHandler
                            // на все manifest action types (test stub).
                            ActionRegistry.RegisterDefaults();
                            Poller = new ActionPoller(Backend, "bannerlord", Log);
                            Poller.Start();

                            // Sprint 4.2: загружаем powers + heroes class state
                            // в кэш (используется MissionLogic при agent build).
                            await PowerCache.RefreshAsync(Backend);
                        }
                    }
                });
            }
            catch (Exception ex)
            {
                Log($"Backend init FAILED: {ex.Message}");
            }
        }

        protected override void OnBeforeInitialModuleScreenSetAsRoot()
        {
            base.OnBeforeInitialModuleScreenSetAsRoot();

            if (_harmony == null)
            {
                // 2026-05-28 NAMEMARKER FIX: force-load SandBox.ViewModelCollection
                // ДО PatchAll. Этот assembly содержит MissionNameMarkerTargetVM
                // (нужен NameMarkerPatch'у). Без явной загрузки он lazy-loaded
                // только когда engine открывает первую Mission → к этому моменту
                // PatchAll уже отработал и NameMarkerPatch graceful-skip'нулся.
                //
                // Forcing reference на любой публичный тип из SandBox.ViewModelCollection
                // триггерит CLR assembly load. Используем reflection-by-name чтобы
                // не bind'нуть compile-time (defensive против rename).
                try
                {
                    string asmPath = System.IO.Path.Combine(
                        TaleWorlds.Library.BasePath.Name,
                        "Modules", "SandBox", "bin", "Win64_Shipping_Client",
                        "SandBox.ViewModelCollection.dll");
                    if (System.IO.File.Exists(asmPath))
                    {
                        var loaded = System.Reflection.Assembly.LoadFrom(asmPath);
                        Log($"[NameMarker prep] force-loaded {loaded.GetName().Name} " +
                            $"v{loaded.GetName().Version}");
                    }
                    else
                    {
                        Log($"[NameMarker prep] SandBox.ViewModelCollection.dll не найден " +
                            $"по пути: {asmPath}");
                    }
                }
                catch (Exception lex)
                {
                    Log($"[NameMarker prep] force-load failed: {lex.GetType().Name}: {lex.Message}");
                }

                _harmony = new Harmony(HARMONY_ID);
                // Sprint 5.32 CRITICAL FIX — resilient PatchAll. Раньше
                // _harmony.PatchAll() патчил все [HarmonyPatch] классы за один
                // call — если ОДИН TargetMethod бросал exception (e.g. NameMarker
                // не нашёл TaleWorlds type), вся PatchAll прерывалась → ВСЕ
                // остальные patches (включая TournamentParticipantsPatch) НЕ
                // регистрировались → турнир тащил vanilla NPC вместо viewer'ов.
                //
                // Лог 2026-05-25 показывает: `Harmony patch FAILED: Patching
                // exception in MissionNameMarkerTargetVMCtorHook::TargetMethod`,
                // и сразу tournament-patch не fires вообще.
                //
                // Решение: iterate все типы в assembly с [HarmonyPatch] и
                // patch каждый ИНДИВИДУАЛЬНО в try/catch. Broken patch скип'ает
                // с лог-warn, остальные продолжают регистрацию.
                // Sprint 5.32 — skip-list пустой. Все patches переведены на
                // resilient `TargetMethods()` (yield) pattern — gracefully skip
                // через empty enumerable если target type / method missing,
                // вместо throwing HarmonyException.
                //
                // DamageHookPatch — refactored: counter-blow для reflect теперь
                // delayed через _pendingReflects queue, drains в KillRewardBehavior
                // .OnMissionTick (fresh frame, no shared AttackCollisionData ref).
                // Раньше inline counter-blow corrupted engine state → native crash.
                //
                // Если какой-то patch снова крашит — добавь его имя сюда (typeName
                // ИЛИ outerName для nested patches типа `BannerCampaignBehaviorPatch+DailyTickHeroFinalizer`).
                var SKIP_PATCH_NAMES = new System.Collections.Generic.HashSet<string>(
                    StringComparer.Ordinal)
                {
                    // empty — все patches теперь resilient
                };
                int ok = 0, failed = 0, skipped = 0;
                var asm = typeof(BannerlordLinkModule).Assembly;
                Type[] types;
                try { types = asm.GetTypes(); }
                catch (Exception tex)
                {
                    Log($"Harmony GetTypes() crashed: {tex.Message} — fallback к PatchAll");
                    try { _harmony.PatchAll(); ok = 1; }
                    catch (Exception fex) { Log($"PatchAll fallback FAILED: {fex.Message}"); failed = 1; }
                    Log($"Harmony patched (id={HARMONY_ID}): ok={ok} failed={failed}");
                    return;
                }
                foreach (var t in types)
                {
                    // Patch только классы с [HarmonyPatch] атрибутом.
                    bool hasAttr = false;
                    try
                    {
                        var attrs = t.GetCustomAttributes(typeof(HarmonyPatch), inherit: false);
                        hasAttr = attrs != null && attrs.Length > 0;
                    }
                    catch { continue; }
                    if (!hasAttr) continue;

                    // Skip-list: high-risk patches которые могут корраптить engine.
                    // Включая nested ("DamageHookPatch+SomeNested"): startswith check
                    // плюс exact name.
                    string typeName = t.Name;
                    string outerName = t.DeclaringType?.Name ?? "";
                    if (SKIP_PATCH_NAMES.Contains(typeName) || SKIP_PATCH_NAMES.Contains(outerName))
                    {
                        Log($"Harmony patch SKIP (safe-rollback): {t.FullName}");
                        skipped++;
                        continue;
                    }

                    try
                    {
                        var processor = _harmony.CreateClassProcessor(t);
                        processor.Patch();
                        ok++;
                    }
                    catch (Exception pex)
                    {
                        Log($"Harmony patch skip: {t.FullName} — {pex.GetType().Name}: {pex.Message}");
                        failed++;
                    }
                }
                Log($"Harmony patched (id={HARMONY_ID}): ok={ok} failed={failed} skipped={skipped}");
            }
        }

        protected override void OnSubModuleUnloaded()
        {
            base.OnSubModuleUnloaded();
            try { Poller?.Stop(); } catch { }
            try { _harmony?.UnpatchAll(HARMONY_ID); } catch { }
            try { Backend?.Dispose(); } catch { }
            Log("unloaded");
        }

        protected override void OnGameStart(TaleWorlds.Core.Game game, TaleWorlds.Core.IGameStarter gameStarter)
        {
            base.OnGameStart(game, gameStarter);
            Log($"OnGameStart game={game?.GameType?.GetType().Name ?? "null"}");

            // Sprint 2.5: register CampaignBehavior если started Campaign.
            // Behavior subscribes на HeroKilledEvent / HeroLevelledUp и
            // posts соответствующие events на backend.
            if (game?.GameType is Campaign && gameStarter is CampaignGameStarter campaignStarter)
            {
                try
                {
                    campaignStarter.AddBehavior(new MainCampaignBehavior());
                    Log("MainCampaignBehavior registered (HeroKilled + HeroLevelledUp)");
                    // Sprint 5.32 (BLT-parity M9) — persistent identity dict.
                    // ДОЛЖЕН быть зарегистрирован ДО других behaviors, чтобы
                    // SyncData загрузило dict до того как OnGameLoadFinished бы
                    // сделали bootstrap-проверку existing [BLink] heroes.
                    campaignStarter.AddBehavior(new HeroIdentityBehavior());
                    Log("HeroIdentityBehavior registered (persistent username dict)");
                    // Sprint 5.26c: BLT-style clan upgrades (daily renown + influence tick).
                    campaignStarter.AddBehavior(new ClanUpgradesBehavior());
                    Log("ClanUpgradesBehavior registered (daily clan upgrades tick)");

                    // Sprint 5.33 (BLT-parity SHOP) — workshop profit sync (OnDailyTick).
                    campaignStarter.AddBehavior(new WorkshopProfitSyncBehavior());
                    Log("WorkshopProfitSyncBehavior registered (daily profit → backend payout)");

                    // Sprint 5.33 (BLT-parity FIEF) — fief tribute sync (OnDailyTick).
                    campaignStarter.AddBehavior(new FiefTributeSyncBehavior());
                    Log("FiefTributeSyncBehavior registered (daily fief tribute → backend payout)");

                    // Sprint 5.33 (BLT-parity CARAVAN) — caravan tracker (DailyTick + MobilePartyDestroyed).
                    campaignStarter.AddBehavior(new CaravanTrackerBehavior());
                    Log("CaravanTrackerBehavior registered (caravan profit + destroyed event)");

                    // Sprint 5.33 PORDER — sticky party orders (HourlyTick re-issue +
                    // completion detection). Без этого engine AI drift'ит и order
                    // через 1-2 hour'а забыт.
                    campaignStarter.AddBehavior(new PartyOrderBehavior());
                    Log("PartyOrderBehavior registered (sticky orders + auto-release on completion)");

                    // Sprint 5.26d: model replacements для статических clan-upgrade
                    // эффектов (party_size, party/army_speed, party_amount).
                    // Pattern: subclass нативной model, делегирует _previous, добавляет
                    // bonus сверху. Регистрируется через AddModel — game подменяет.
                    try
                    {
                        var prevPartySpeed = campaignStarter.Models
                            .OfType<TaleWorlds.CampaignSystem.ComponentInterfaces.PartySpeedModel>()
                            .FirstOrDefault();
                        if (prevPartySpeed != null)
                            campaignStarter.AddModel(new Models.BLPartySpeedModel(prevPartySpeed));

                        var prevPartySize = campaignStarter.Models
                            .OfType<TaleWorlds.CampaignSystem.ComponentInterfaces.PartySizeLimitModel>()
                            .FirstOrDefault();
                        if (prevPartySize != null)
                            campaignStarter.AddModel(new Models.BLPartySizeLimitModel(prevPartySize));

                        var prevClanTier = campaignStarter.Models
                            .OfType<TaleWorlds.CampaignSystem.ComponentInterfaces.ClanTierModel>()
                            .FirstOrDefault();
                        if (prevClanTier != null)
                            campaignStarter.AddModel(new Models.BLClanTierModel(prevClanTier));

                        Log("BLUpgradeModels registered (party_size/speed + clan party_amount)");
                    }
                    catch (Exception ex)
                    {
                        Log($"BLUpgradeModels register FAILED: {ex.Message}");
                    }
                }
                catch (Exception ex)
                {
                    Log($"CampaignBehavior register FAILED: {ex.Message}");
                }

                // Sprint 5.3: tournament queue + game menu options
                try
                {
                    campaignStarter.AddBehavior(new TournamentQueueBehavior());
                    Log("TournamentQueueBehavior registered (viewer tournaments)");
                }
                catch (Exception ex)
                {
                    Log($"TournamentQueueBehavior register FAILED: {ex.Message}");
                }
            }
        }

        /// <summary>Каждый frame — drain main-thread dispatcher queue.
        /// Background tasks (ActionPoller) enqueue работу сюда, мы её
        /// выполняем в безопасном main-thread контексте.</summary>
        protected override void OnApplicationTick(float dt)
        {
            base.OnApplicationTick(dt);
            MainThreadDispatcher.DrainQueue();
        }

        /// <summary>Bannerlord auto-calls на каждой новой Mission.
        /// Register MissionBehaviors которые должны быть active в battles.</summary>
        public override void OnMissionBehaviorInitialize(Mission mission)
        {
            base.OnMissionBehaviorInitialize(mission);
            try
            {
                mission.AddMissionBehavior(new PowersMissionBehavior());
                mission.AddMissionBehavior(new KillRewardBehavior());
                // Sprint 5.32 (BLT-parity Detachment) — viewer-controlled formation
                // commands. MissionBehavior — short-lived (per-mission), Instance
                // resetся через OnEndMission. Action handlers зовут Instance.X.
                mission.AddMissionBehavior(new HeroDetachmentBehavior());

                // 2026-05-29 Stage 1 (BLT-RC22 pattern) — persistent particle
                // lifecycle coordinator. Tracks все AgentPfx instances созданные
                // в PowerVisualFx.PlayActivation. Per-frame OnPreDisplayMissionTick
                // обновляет position. OnAgentDeleted auto-cleanup. OnEndMission
                // полный clear. БЕЗ этого behaviour'а AgentPfx.Register/Unregister
                // станут no-op'ами через HeroPfxBehaviour.Current → null.
                mission.AddMissionBehavior(new BannerlordLink.Behaviors.HeroPfxBehaviour());

                // 2026-05-29 Stage 6 (BLT-RC22 pattern) — track mounts of adopted
                // heroes. На OnAgentBuild: добавляет agent.MountAgent в HashSet
                // если rider — adopted hero. На Mission.OnAgentRemoved (через
                // AdoptedHeroDeathPatch) — если умирающий agent в HashSet'е →
                // Killed → Unconscious. Сохраняет saddle/harness equipment.
                mission.AddMissionBehavior(new BannerlordLink.Behaviors.AdoptedMountTrackerBehavior());

                Log("MissionBehaviors registered: Powers + KillReward + Detachment + HeroPfx + MountTracker");
            }
            catch (Exception ex)
            {
                Log($"OnMissionBehaviorInitialize FAILED: {ex.Message}");
            }
        }
    }
}
