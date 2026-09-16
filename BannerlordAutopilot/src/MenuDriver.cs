using System.Text;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.Core;

namespace BannerlordAutopilot
{
    /// <summary>Пункты игрового меню — тем же путём, что кнопка.
    ///
    /// Кнопка меню в интерфейсе (GameMenuItemVM.ExecuteAction, 1.4.8) делает
    /// ровно `MenuContext.InvokeConsequence(Index)`. Мод повторяет это: находит
    /// пункт по id, спрашивает его условие, как интерфейс при обновлении меню, и
    /// вызывает то же последствие. Своих копий логики пунктов здесь нет — поэтому
    /// «Подождать» и «Перестать ждать» делают в движке всё то же, что у игрока.</summary>
    internal static class MenuDriver
    {
        internal static string CurrentMenuId => Campaign.Current?.CurrentMenuContext?.GameMenu?.StringId;

        /// <summary>Нажать пункт optionId в открытом меню. false — не нажат, причина в why.</summary>
        internal static bool TryInvoke(string optionId, out string why)
        {
            if (!FindAvailableOption(optionId, out MenuContext context, out int found, out why)) return false;
            // Repeated menu items expand the index of every following option.
            int repeats = context.GameMenu.MenuRepeatObjects.Count;
            context.InvokeConsequence(repeats == 0 || found == 0 ? found : found - 1 + repeats);
            return true;
        }

        internal static bool CanInvoke(string optionId, out string why) => FindAvailableOption(optionId, out _, out _, out why);

        private static bool FindAvailableOption(string optionId, out MenuContext context, out int found, out string why)
        {
            context = Campaign.Current?.CurrentMenuContext;
            found = -1;
            GameMenu menu = context?.GameMenu;
            if (menu == null)
            {
                why = "меню не открыто";
                return false;
            }

            int index = 0;
            foreach (GameMenuOption option in menu.MenuOptions)
            {
                if (option.IdString == optionId)
                {
                    found = index;
                    break;
                }
                index++;
            }
            if (found < 0)
            {
                why = "в меню «" + menu.StringId + "» нет пункта «" + optionId + "»";
                return false;
            }
            if (!menu.GetMenuOptionConditionsHold(Game.Current, context, found))
            {
                why = "пункт «" + optionId + "» скрыт условием";
                return false;
            }
            GameMenuOption chosen = menu.GetGameMenuOption(found);
            if (!chosen.IsEnabled)
            {
                why = "пункт «" + optionId + "» недоступен" + (chosen.Tooltip != null ? ": " + chosen.Tooltip : "");
                return false;
            }

            why = null;
            return true;
        }

        /// <summary>Для журнала: id меню и пункты с последней известной доступностью.
        /// Условия заново не спрашиваются — у них бывают побочные эффекты.</summary>
        internal static string Describe()
        {
            GameMenu menu = Campaign.Current?.CurrentMenuContext?.GameMenu;
            if (menu == null)
            {
                return "нет";
            }
            var sb = new StringBuilder(menu.StringId);
            if (menu.IsWaitMenu)
            {
                sb.Append(menu.IsWaitActive ? " (ожидание идёт)" : " (ожидание стоит)");
            }
            sb.Append(" [");
            bool first = true;
            foreach (GameMenuOption option in menu.MenuOptions)
            {
                sb.Append(first ? "" : ", ").Append(option.IdString);
                if (!option.IsEnabled)
                {
                    sb.Append(" недоступен");
                }
                first = false;
            }
            return sb.Append(']').ToString();
        }
    }
}
