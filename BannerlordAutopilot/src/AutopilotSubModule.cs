using System;
using System.Collections.Generic;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.InputSystem;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

namespace BannerlordAutopilot
{
    /// <summary>Точка входа мода и управление автопилотом.
    ///
    /// Управление намеренно двойное: консольные команды (autopilot.*) для
    /// точного текста в ответ и горячие клавиши — на случай, если консоль в
    /// сборке игрока недоступна. Прототип должен включаться без танцев, иначе
    /// испытание не состоится.</summary>
    public class AutopilotSubModule : MBSubModuleBase
    {
        private const InputKey KeyObserve = InputKey.F10;
        private const InputKey KeyApply = InputKey.F11;
        private const InputKey KeyOff = InputKey.F12;

        protected override void OnSubModuleLoad()
        {
            base.OnSubModuleLoad();
            try
            {
                AutopilotLog.Session("загрузка мода");
                bool ok = EngineContract.Verify();
                AutopilotLog.Write("контракт движка: " + EngineContract.Report);
                if (!ok)
                {
                    AutopilotLog.Write("АВТОПИЛОТ НЕ БУДЕТ ВКЛЮЧАТЬСЯ: структура движка отличается от "
                                       + "той, под которую написан прототип. Игра при этом работает как "
                                       + "обычно — мод ничего не патчит и ничего не меняет.");
                }
            }
            catch (Exception ex)
            {
                AutopilotLog.Write("проверка контракта упала: " + ex);
            }
        }

        protected override void OnGameStart(Game game, IGameStarter starterObject)
        {
            base.OnGameStart(game, starterObject);
            if (game.GameType is Campaign && starterObject is CampaignGameStarter campaignStarter)
            {
                campaignStarter.AddBehavior(new AutopilotBehavior());
                AutopilotLog.Write("поведение автопилота зарегистрировано в кампании");
            }
        }

        protected override void OnApplicationTick(float dt)
        {
            base.OnApplicationTick(dt);
            AutopilotBehavior behavior = AutopilotBehavior.Instance;
            if (behavior == null || Campaign.Current == null)
            {
                return;
            }

            if (Input.IsKeyPressed(KeyObserve))
            {
                Announce(Enable(AutopilotBehavior.Mode.Observe));
            }
            else if (Input.IsKeyPressed(KeyApply))
            {
                Announce(Enable(AutopilotBehavior.Mode.Apply));
            }
            else if (Input.IsKeyPressed(KeyOff))
            {
                if (behavior.CurrentMode == AutopilotBehavior.Mode.Off)
                {
                    Announce("Автопилот и так выключен.");
                }
                else
                {
                    behavior.Disable("выключено игроком (F12)");
                    Announce("Автопилот выключен, движение остановлено, состояние AI восстановлено.");
                }
            }
        }

        private static string Enable(AutopilotBehavior.Mode mode)
        {
            AutopilotBehavior behavior = AutopilotBehavior.Instance;
            if (behavior == null)
            {
                return "Автопилот недоступен: поведение не зарегистрировано.";
            }
            if (behavior.TryEnable(mode, out string reason))
            {
                return "Автопилот включён, режим: " + AutopilotBehavior.ModeName(mode)
                       + ". Лог: " + AutopilotLog.Path;
            }
            return "Автопилот НЕ включён: " + reason;
        }

        private static void Announce(string text)
        {
            try
            {
                InformationManager.DisplayMessage(new InformationMessage(text));
            }
            catch (Exception)
            {
                // Интерфейса может не быть (например, на загрузочном экране).
            }
            AutopilotLog.Write("[UI] " + text);
        }

        // ── Консольные команды ───────────────────────────────────────────────

        [CommandLineFunctionality.CommandLineArgumentFunction("observe", "autopilot")]
        public static string CmdObserve(List<string> args)
        {
            return Enable(AutopilotBehavior.Mode.Observe);
        }

        [CommandLineFunctionality.CommandLineArgumentFunction("apply", "autopilot")]
        public static string CmdApply(List<string> args)
        {
            return Enable(AutopilotBehavior.Mode.Apply);
        }

        [CommandLineFunctionality.CommandLineArgumentFunction("off", "autopilot")]
        public static string CmdOff(List<string> args)
        {
            AutopilotBehavior behavior = AutopilotBehavior.Instance;
            if (behavior == null)
            {
                return "Автопилот недоступен.";
            }
            behavior.Disable("выключено командой autopilot.off");
            return "Автопилот выключен.";
        }

        [CommandLineFunctionality.CommandLineArgumentFunction("status", "autopilot")]
        public static string CmdStatus(List<string> args)
        {
            AutopilotBehavior behavior = AutopilotBehavior.Instance;
            if (behavior == null)
            {
                return "Автопилот недоступен: кампания не запущена. Контракт движка: " + EngineContract.Report;
            }
            return behavior.StatusLine();
        }
    }
}
