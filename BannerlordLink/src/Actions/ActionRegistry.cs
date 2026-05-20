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
            Register(new SetClassHandler());         // hero.set_class — class + equipment
            Register(new HealHeroHandler());         // player.heal — restore HP
            Register(new GiveGoldHandler());         // player.give_item (gold)
            Register(new AddSkillXpHandler());       // hero.add_skill — XP boost
            Register(new ModifyAttributeHandler());  // player.modify_attribute — points
            Register(new ActivatePowerHandler());    // power.activate — active power burst
            Register(new SummonHeroHandler());       // player.spawn — summon в Mission (5.0)
            Register(new EquipItemHandler());        // player.equip_item — equip ItemObject (5.1b)
            Register(new UpgradeGearHandler());      // hero.upgrade_gear — 6-tier progression
            Register(new RecruitTroopsHandler());    // hero.recruit_troops — BLT-style свита
            Register(new JoinTournamentHandler());   // hero.join_tournament — Sprint 5.3
            Register(new AddFocusHandler());         // hero.add_focus — Sprint 5.8 (Hero.Gold tier-based)
            Register(new AddAttributeHandler());     // hero.add_attribute — Sprint 5.8 (Hero.Gold flat)
            Register(new CreateClanHandler());       // hero.create_clan — Sprint 5.9 (BLT-style clan creation)
            Register(new CreateKingdomHandler());    // hero.create_kingdom — Sprint 5.12 (5M)
            Register(new LeaveClanHandler());        // hero.leave_clan — Sprint 5.12
            Register(new LeaveKingdomHandler());     // hero.leave_kingdom — Sprint 5.12
            Register(new JoinClanHandler());         // hero.join_clan — Sprint 5.12
            Register(new JoinKingdomHandler());      // hero.join_kingdom — Sprint 5.12
            Register(new CreatePartyHandler());      // hero.create_party — Sprint 5.13 (BLT-style)

            // ── Echo stubs (TODO Sprint 5.2+ заменить на real) ─────────────
            string[] echoTypes =
            {
                "player.respawn",     // heir succession — complex
                "world.trigger_event",
                "world.broadcast_message",
                "hero.set_culture",
                "hero.set_faction",
            };
            foreach (var t in echoTypes)
            {
                Register(new EchoHandler(t));
            }
        }
    }
}
