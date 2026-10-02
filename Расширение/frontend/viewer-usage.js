/* Semantic UI intent only. No click scraping, polling, names, payloads or storage.
 * Track calls do not await telemetry and cannot change action/ACK/charge semantics.
 * All data stays best-effort: 100 queued attempts max; 30-second batches; at most
 * two retries of the identical batch; auth-token changes discard unsent context.
 * Allowlist mirrors ui_usage.py + existing module manifests (parity tested).
 */
(function (global) {
    'use strict';
    var api = global.ShedLink || (global.ShedLink = {});
    var sections = new Set(["bannerlord:details.caravan-buy", "bannerlord:details.diplo-peace", "bannerlord:details.diplo-policy", "bannerlord:details.dyn-clan", "bannerlord:details.dyn-kingdom", "bannerlord:details.dyn-profile", "bannerlord:details.dyn-upgrades", "bannerlord:details.hero-gender", "bannerlord:details.hero-progression", "bannerlord:details.inv-achievements", "bannerlord:details.inv-forge", "bannerlord:details.kingdom-create", "bannerlord:details.kingdom-join", "bannerlord:details.locked-create", "bannerlord:details.locked-join", "bannerlord:details.party-order", "bannerlord:details.retinue", "bannerlord:details.vas-create", "bannerlord:details.ws-buy", "bannerlord:section.army", "bannerlord:section.caravans", "bannerlord:section.diplomacy", "bannerlord:section.fiefs", "bannerlord:section.partyorders", "bannerlord:section.workshops", "bannerlord:tab.combat", "bannerlord:tab.dynasty", "bannerlord:tab.hero", "bannerlord:tab.inventory", "core:tab.bot", "core:tab.integration", "core:tab.shop", "core:tab.stats"]);
    var actions = new Set(["bannerlord:hero.activate_heir", "bannerlord:hero.activate_marriage", "bannerlord:hero.add_attribute", "bannerlord:hero.add_focus", "bannerlord:hero.add_skill", "bannerlord:hero.army_create", "bannerlord:hero.army_disband", "bannerlord:hero.attach", "bannerlord:hero.buy_caravan", "bannerlord:hero.buy_clan_upgrades", "bannerlord:hero.buy_equipment", "bannerlord:hero.buy_workshop", "bannerlord:hero.cancel_proposal", "bannerlord:hero.change_child_looks", "bannerlord:hero.claim_starter", "bannerlord:hero.create", "bannerlord:hero.create_clan", "bannerlord:hero.create_kingdom", "bannerlord:hero.create_party", "bannerlord:hero.create_vassal_clan", "bannerlord:hero.detach", "bannerlord:hero.detach_charge", "bannerlord:hero.detach_gate", "bannerlord:hero.detach_hold", "bannerlord:hero.detach_raid", "bannerlord:hero.detach_skirmish", "bannerlord:hero.detach_walls", "bannerlord:hero.discard_item", "bannerlord:hero.discard_owned", "bannerlord:hero.divorce", "bannerlord:hero.enact_policy", "bannerlord:hero.equip_owned", "bannerlord:hero.equip_trophy", "bannerlord:hero.join_clan", "bannerlord:hero.join_kingdom", "bannerlord:hero.join_tournament", "bannerlord:hero.leave_clan", "bannerlord:hero.leave_kingdom", "bannerlord:hero.make_baby", "bannerlord:hero.make_peace", "bannerlord:hero.marry", "bannerlord:hero.party_order_release", "bannerlord:hero.party_order_set", "bannerlord:hero.pay_ransom", "bannerlord:hero.propose_marriage", "bannerlord:hero.recruit_troops", "bannerlord:hero.recruit_vassal_clan", "bannerlord:hero.reequip_gear", "bannerlord:hero.reforge_quality", "bannerlord:hero.rename_child", "bannerlord:hero.rename_vassal", "bannerlord:hero.respec_child_skills", "bannerlord:hero.respond_marriage_proposal", "bannerlord:hero.select_weapon_power", "bannerlord:hero.sell_caravan", "bannerlord:hero.sell_workshop", "bannerlord:hero.set_class", "bannerlord:hero.set_combat_stance", "bannerlord:hero.set_gender", "bannerlord:hero.set_specialization", "bannerlord:hero.smith_item", "bannerlord:hero.train_troops", "bannerlord:hero.tribute_boost", "bannerlord:hero.unequip_owned", "bannerlord:hero.upgrade_gear", "bannerlord:kingdom.propose_peace", "bannerlord:kingdom.propose_war", "bannerlord:player.equip_item", "bannerlord:player.give_item", "bannerlord:player.heal", "bannerlord:player.modify_attribute", "bannerlord:player.respawn", "bannerlord:player.spawn", "bannerlord:power.activate", "bannerlord:tournament.predict", "bannerlord:world.trigger_event", "rimworld:pawn.add_gene", "rimworld:pawn.add_trait", "rimworld:pawn.passion_reset", "rimworld:pawn.remove_gene", "rimworld:pawn.remove_trait", "rimworld:pawn.set_passion", "rimworld:pawn.set_xenotype", "rimworld:player.apply_effect", "rimworld:player.equip_item", "rimworld:player.give_item", "rimworld:player.heal", "rimworld:player.modify_attribute", "rimworld:player.respawn", "rimworld:player.spawn", "rimworld:world.trigger_event", "shedcolony:colonist.add_xp", "shedcolony:colonist.assign_home", "shedcolony:colonist.assign_job", "shedcolony:colonist.auto_work", "shedcolony:colonist.clear_mourn", "shedcolony:colonist.cure_disease", "shedcolony:colonist.equip_diamond", "shedcolony:colonist.equip_iron", "shedcolony:colonist.equip_leather", "shedcolony:colonist.equip_netherite", "shedcolony:colonist.equip_weapon", "shedcolony:colonist.feed", "shedcolony:colonist.fulfill_request", "shedcolony:colonist.give_item", "shedcolony:colonist.give_shield", "shedcolony:colonist.give_tools", "shedcolony:colonist.happiness_boost", "shedcolony:colonist.heal", "shedcolony:colonist.set_gender", "shedcolony:colonist.set_guard_retreat", "shedcolony:colonist.set_guard_task", "shedcolony:colonist.spawn", "shedcolony:colonist.teleport", "shedcolony:colony.clear_backlog", "shedcolony:colony.festival", "shedcolony:colony.finish_research", "shedcolony:colony.quest_unlock", "shedcolony:colony.set_minimum_stock", "shedcolony:colony.spawn_visitor", "shedcolony:colony.spy_boost", "shedcolony:colony.start_research", "shedcolony:colony.supply", "shedcolony:colony.upgrade_building"]);
    var modules = new Set(['core', 'bannerlord', 'rimworld', 'shedcolony']);
    var queue = new Map();
    var panels = new Set();
    var seenPanels = new Set();
    var panelDay = -1;
    var boundToken = '';
    var flight = null;
    var busy = false;
    var timer = null;
    var queued = 0;

    function context() {
        var token = (typeof authToken !== 'undefined' && authToken) || '';
        if (token !== boundToken) {
            queue.clear();
            panels.clear();
            seenPanels.clear();
            queued = 0;
            flight = null;
            boundToken = token;
            if (timer !== null) clearTimeout(timer);
            timer = null;
        }
        var day = Math.floor(Date.now() / 86400000);
        if (day !== panelDay) {
            panels.clear();
            panelDay = day;
        }
        return token;
    }
    function schedule(delay) {
        if (timer !== null || (!flight && !queue.size)) return;
        timer = setTimeout(function () { timer = null; flush(); }, delay);
    }
    function track(kind, feature) {
        try {
            if (!context() || queued >= 100) return false;
            var module = feature.split(':')[0];
            // A tab left open across UTC midnight still supplies a denominator
            // when the viewer next acts. Only modules explicitly seen on this
            // authenticated page qualify; polling/rendering never calls track.
            if (kind !== 'panel_view' && seenPanels.has(module) && !panels.has(module)) {
                if (track('panel_view', module + ':panel')) panels.add(module);
                if (queued >= 100) return false;
            }
            var key = kind + ':' + feature;
            var current = queue.get(key);
            if (current) {
                if (current.count >= 20) return false;
                current.count++;
            } else {
                if (queue.size >= 20) return false;
                queue.set(key, {kind: kind, feature: feature, count: 1});
            }
            queued++;
            schedule(30000);
            return true;
        } catch (_) { return false; /* telemetry must never block a user action */ }
    }
    async function flush() {
        try {
            var token = context();
            if (!token || busy || typeof API_URL === 'undefined') return;
            if (timer !== null) clearTimeout(timer);
            timer = null;
            if (!flight && queue.size) {
                // UUID is transport dedupe only, never persisted across pages.
                if (!global.crypto || typeof global.crypto.randomUUID !== 'function') return;
                flight = {token: token, tries: 0, body: JSON.stringify({
                    batch_id: global.crypto.randomUUID(),
                    surface: /mobile\.html$/.test(global.location.pathname) ? 'mobile' : 'desktop',
                    events: Array.from(queue.values())
                })};
                queue.clear();
                queued = 0;
            }
            if (!flight) return;
            var batch = flight;
            busy = true;
            batch.tries++;
            var timeout;
            var controller = typeof AbortController === 'function' ? new AbortController() : null;
            try {
                var response = await Promise.race([
                    fetch(API_URL + '/api/viewer/ui-usage', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': batch.token},
                        body: batch.body,
                        keepalive: true,
                        signal: controller ? controller.signal : undefined
                    }),
                    new Promise(function (_, reject) {
                        timeout = setTimeout(function () {
                            if (controller) controller.abort();
                            reject(new Error('usage timeout'));
                        }, 5000);
                    })
                ]);
                if (response.ok || [400, 401, 403, 404, 413].indexOf(response.status) >= 0) {
                    if (flight === batch) flight = null;
                }
            } catch (_) { /* bounded retry below; no toast or console payload */ }
            finally {
                clearTimeout(timeout);
                busy = false;
                if (flight === batch && batch.tries >= 3) flight = null;
                schedule(flight ? 60000 : 30000);
            }
        } catch (_) { /* fail closed, without affecting the host application */ }
    }
    api.usage = {
        trackSection: function (feature) {
            if (sections.has(feature)) track('section_open', feature);
        },
        trackAction: function (feature) {
            if (actions.has(feature)) track('action_attempt', feature);
        },
        trackPanel: function (module) {
            if (!context() || !modules.has(module) || panels.has(module)) return;
            seenPanels.add(module);
            if (track('panel_view', module + ':panel')) panels.add(module);
        },
        flush: flush
    };
    if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', function () {
            if (document.hidden) flush();
        });
    }
})(window);
