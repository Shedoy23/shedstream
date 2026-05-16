using System;
using HarmonyLib;
using TaleWorlds.MountAndBlade;
using Debug = TaleWorlds.Library.Debug;

namespace BannerlordLink
{
    /// <summary>
    /// Entry point Bannerlord-мода. Поднимается игрой через SubModule.xml.
    ///
    /// Lifecycle:
    ///   1. OnSubModuleLoad — early init
    ///   2. OnBeforeInitialModuleScreenSetAsRoot — Harmony.PatchAll()
    ///   3. OnGameStart — load campaign behaviors (если game is Campaign)
    ///
    /// Sprint 2.1 status:
    ///   ✅ Skeleton (this file)
    ///   ⏳ Backend HTTP client (Net/BackendClient.cs) — Sprint 2.2
    ///   ⏳ Action poller (Net/ActionPoller.cs) — Sprint 2.3
    ///   ⏳ CampaignEvents handlers — Sprint 2.4
    /// </summary>
    public class BannerlordLinkModule : MBSubModuleBase
    {
        private const string MOD_NAME = "BannerlordLink";
        private const string MOD_VERSION = "0.1.0";
        private const string HARMONY_ID = "ru.shedoy23.bannerlordlink";

        private Harmony _harmony;

        protected override void OnSubModuleLoad()
        {
            base.OnSubModuleLoad();
            Debug.Print($"[{MOD_NAME}] v{MOD_VERSION} loading...");

            // TODO Sprint 2.2: load BackendConfig (token, URL) из config.json в
            //   <game>/Modules/Shedoy23.BannerlordLink/config.json. Если нет —
            //   log warning, continue без backend (mod not crash).
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
                    Debug.Print($"[{MOD_NAME}] Harmony patched (id={HARMONY_ID})");
                }
                catch (Exception ex)
                {
                    Debug.Print($"[{MOD_NAME}] Harmony patch FAILED: {ex.Message}");
                }
            }
        }

        protected override void OnSubModuleUnloaded()
        {
            base.OnSubModuleUnloaded();
            try
            {
                _harmony?.UnpatchAll(HARMONY_ID);
            }
            catch (Exception) { }
            Debug.Print($"[{MOD_NAME}] unloaded");
        }

        protected override void OnGameStart(TaleWorlds.Core.Game game, TaleWorlds.Core.IGameStarter gameStarter)
        {
            base.OnGameStart(game, gameStarter);

            // TODO Sprint 2.4: if (game.GameType is Campaign) → register
            //   MainCampaignBehavior через CampaignGameStarter
        }
    }
}
