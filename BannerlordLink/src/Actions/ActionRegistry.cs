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
            Register(new SetCombatStanceHandler());  // hero.set_combat_stance — боевая стойка (2026-06-10)
            Register(new HealHeroHandler());         // player.heal — restore HP
            Register(new GiveGoldHandler());         // player.give_item (gold)
            Register(new AddSkillXpHandler());       // hero.add_skill — XP boost
            Register(new ModifyAttributeHandler());  // player.modify_attribute — points
            Register(new ActivatePowerHandler());    // power.activate — active power burst
            Register(new SummonHeroHandler());       // player.spawn — summon в Mission (5.0)
            Register(new EquipItemHandler());        // player.equip_item — equip ItemObject (5.1b)
            Register(new UpgradeGearHandler());      // hero.upgrade_gear — 6-tier progression
            Register(new ReequipGearHandler());      // hero.reequip_gear — re-roll снаряги на текущем тире (BLT ReequipInsteadOfUpgrade)
            Register(new RecruitTroopsHandler());    // hero.recruit_troops — BLT-style свита
            Register(new TrainTroopsHandler());      // hero.train_troops — bulk-upgrade свиты (BLT TrainingBehavior)
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
            Register(new SetGenderHandler());        // hero.set_gender — Sprint 5.27a (gender swap)
            Register(new MarryHandler());            // hero.marry — Sprint 5.27b (NPC marriage)
            Register(new DivorceHandler());          // hero.divorce — Sprint 5.27b (free divorce)
            Register(new MakeBabyHandler());         // hero.make_baby — Sprint 5.27c (pregnancy)
            Register(new EquipTrophyHandler());      // hero.equip_trophy — Sprint 5.29 BLT-parity #6 phase A
            Register(new ReforgeQualityHandler());   // hero.reforge_quality — 2026-06-15 «Кузница»: перековка качества надетого предмета
            Register(new ActivateHeirHandler());     // hero.activate_heir — Sprint 5.32 BLT-parity M2.1
            // Sprint 5.32 (BLT-parity Detachment) — 6 viewer commands управления agent'ом in-Mission
            Register(new DetachHandler());           // hero.detach
            Register(new AttachHandler());           // hero.attach
            Register(new HoldHandler());             // hero.detach_hold
            Register(new ChargeHandler());           // hero.detach_charge
            Register(new SkirmishHandler());         // hero.detach_skirmish — 2026-06-17 рич-приказ (standoff)
            Register(new RaidHandler());             // hero.detach_raid — 2026-06-17 рич-приказ (конная орбита)
            Register(new WallsHandler());            // hero.detach_walls (siege only)
            Register(new GateHandler());             // hero.detach_gate (siege only)
            // Sprint 5.33 (BLT-parity FAM) — viewer↔viewer семейные интеракции
            Register(new ActivateMarriageHandler());    // hero.activate_marriage
            Register(new ChildRenameHandler());         // hero.rename_child
            Register(new ChildLooksHandler());          // hero.change_child_looks
            Register(new ChildRespecSkillsHandler());   // hero.respec_child_skills
            // Sprint 5.33 (BLT-parity VAS) — vassal sub-clan management
            Register(new CreateVassalClanHandler());    // hero.create_vassal_clan
            Register(new RecruitVassalClanHandler());   // hero.recruit_vassal_clan — 2026-06-17 (ruler hires NPC vassal clan, 3M)
            Register(new RenameVassalHandler());        // hero.rename_vassal
            // Sprint 5.33 (BLT-parity SIEGE) — party strategic orders
            Register(new SetPartyOrderHandler());       // hero.party_order_set
            Register(new ReleasePartyOrderHandler());   // hero.party_order_release
            // 2026-06-14 — «Армия» MVP (kingdom army, vanilla CreateArmy)
            Register(new CreateArmyHandler());          // hero.army_create
            Register(new DisbandArmyHandler());         // hero.army_disband
            // Sprint 5.33 (BLT-parity DIPLO) — kingdom politics + ransom
            Register(new EnactPolicyHandler());         // hero.enact_policy
            Register(new MakePeaceHandler());           // hero.make_peace
            Register(new PayRansomHandler());           // hero.pay_ransom
            // 2026-06-14 — дипломатия через голосование кланов (vanilla AddDecision)
            Register(new ProposeWarHandler());          // kingdom.propose_war
            Register(new ProposePeaceHandler());        // kingdom.propose_peace
            Register(new SetKingdomTaxHandler());        // kingdom.set_tax_rate (Backlog #1)
            // Sprint 5.33 (BLT-parity SHOP) — workshops passive income
            Register(new BuyWorkshopHandler());         // hero.buy_workshop
            Register(new SellWorkshopHandler());        // hero.sell_workshop
            // Sprint 5.33 (BLT-parity CARAVAN) — mobile passive income trilogy closer
            Register(new BuyCaravanHandler());          // hero.buy_caravan
            Register(new SellCaravanHandler());         // hero.sell_caravan
            // Sprint 5.33 GAP-closure — replace EchoHandler stubs с real handlers
            Register(new BroadcastMessageHandler());    // world.broadcast_message
            Register(new TriggerWorldEventHandler());   // world.trigger_event

            // ── Echo stubs (low priority — оставлены пока stubs) ────────────
            // player.respawn — handled через hero.activate_heir (auto-heir flow)
            // hero.set_culture / hero.set_faction — LOW priority, stub OK для тестов
            string[] echoTypes =
            {
                "player.respawn",     // heir succession — auto-handled через hero.activate_heir
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
