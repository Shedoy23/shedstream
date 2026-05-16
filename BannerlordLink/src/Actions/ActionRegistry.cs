using System.Collections.Generic;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Простой registry handler'ов by action_type.
    ///
    /// Sprint 2.4: все known action types из manifest регистрируются как
    /// EchoHandler (test stub). Sprint 3+ — replace на реальные.
    /// </summary>
    public static class ActionRegistry
    {
        private static readonly Dictionary<string, IActionHandler> _handlers =
            new Dictionary<string, IActionHandler>();

        /// <summary>Регистрирует handler. Replace если type уже зарегистрирован.</summary>
        public static void Register(IActionHandler handler)
        {
            _handlers[handler.ActionType] = handler;
        }

        /// <summary>Возвращает handler для type или null если не зарегистрирован.</summary>
        public static IActionHandler Get(string actionType)
        {
            return _handlers.TryGetValue(actionType ?? "", out var h) ? h : null;
        }

        /// <summary>Sprint 2.4 default — все manifest action types как Echo.</summary>
        public static void RegisterDefaults()
        {
            string[] knownTypes =
            {
                // Standard actions из manifest.yaml
                "player.spawn",
                "player.heal",
                "player.respawn",
                "player.give_item",
                "player.equip_item",
                "player.modify_attribute",
                "world.trigger_event",
                "world.broadcast_message",
                // Bannerlord extensions
                "hero.add_skill",
                "hero.set_culture",
                "hero.set_faction",
                "hero.recruit_troops",
            };
            foreach (var t in knownTypes)
            {
                Register(new EchoHandler(t));
            }
        }
    }
}
