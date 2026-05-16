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

        /// <summary>Default registry — REAL handlers где есть, Echo stub'ы для остального.</summary>
        public static void RegisterDefaults()
        {
            // ── REAL handlers ──────────────────────────────────────────────
            Register(new AdoptHeroHandler());        // hero.create — adoption
            Register(new HealHeroHandler());         // player.heal — restore HP
            Register(new GiveGoldHandler());         // player.give_item (gold)
            Register(new AddSkillXpHandler());       // hero.add_skill — XP boost
            Register(new ModifyAttributeHandler());  // player.modify_attribute — points

            // ── Echo stubs (TODO Sprint 3.4+ заменить на real) ─────────────
            string[] echoTypes =
            {
                "player.spawn",       // summon в Mission — complex, Sprint 3.5
                "player.respawn",     // heir succession — complex
                "player.equip_item",  // weapon/armor — Sprint 3.4 (ItemRoster)
                "world.trigger_event",
                "world.broadcast_message",
                "hero.set_culture",
                "hero.set_faction",
                "hero.recruit_troops",
            };
            foreach (var t in echoTypes)
            {
                Register(new EchoHandler(t));
            }
        }
    }
}
