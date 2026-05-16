using System;
using System.IO;
using System.Threading.Tasks;
using BannerlordLink.Actions;
using BannerlordLink.Net;
using HarmonyLib;
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

        protected override void OnSubModuleLoad()
        {
            base.OnSubModuleLoad();
            Log($"v{MOD_VERSION} OnSubModuleLoad");

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
                try
                {
                    _harmony = new Harmony(HARMONY_ID);
                    _harmony.PatchAll();
                    Log($"Harmony patched (id={HARMONY_ID})");
                }
                catch (Exception ex)
                {
                    Log($"Harmony patch FAILED: {ex.Message}");
                }
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
        }
    }
}
