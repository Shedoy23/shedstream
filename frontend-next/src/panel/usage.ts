import type { TwitchAuthStore } from '../auth';
import type { IdentityBootstrap } from '../skillgames/identity';

// Fixed semantic allowlists match the frozen collector and server manifests.
// No payload, name, target, coordinate, token or persistent identifier is an event.
const sections = new Set([
  "bannerlord:details.caravan-buy",
  "bannerlord:details.diplo-peace",
  "bannerlord:details.diplo-policy",
  "bannerlord:details.dyn-clan",
  "bannerlord:details.dyn-kingdom",
  "bannerlord:details.dyn-profile",
  "bannerlord:details.dyn-upgrades",
  "bannerlord:details.hero-gender",
  "bannerlord:details.hero-progression",
  "bannerlord:details.inv-achievements",
  "bannerlord:details.inv-forge",
  "bannerlord:details.kingdom-create",
  "bannerlord:details.kingdom-join",
  "bannerlord:details.locked-create",
  "bannerlord:details.locked-join",
  "bannerlord:details.party-order",
  "bannerlord:details.retinue",
  "bannerlord:details.vas-create",
  "bannerlord:details.ws-buy",
  "bannerlord:section.army",
  "bannerlord:section.caravans",
  "bannerlord:section.diplomacy",
  "bannerlord:section.fiefs",
  "bannerlord:section.partyorders",
  "bannerlord:section.workshops",
  "bannerlord:tab.combat",
  "bannerlord:tab.dynasty",
  "bannerlord:tab.hero",
  "bannerlord:tab.inventory",
  "core:tab.bot",
  "core:tab.integration",
  "core:tab.shop",
  "core:tab.stats"
]);
const actions = new Set([
  "bannerlord:hero.activate_heir",
  "bannerlord:hero.activate_marriage",
  "bannerlord:hero.add_attribute",
  "bannerlord:hero.add_focus",
  "bannerlord:hero.add_skill",
  "bannerlord:hero.army_create",
  "bannerlord:hero.army_disband",
  "bannerlord:hero.attach",
  "bannerlord:hero.buy_caravan",
  "bannerlord:hero.buy_clan_upgrades",
  "bannerlord:hero.buy_equipment",
  "bannerlord:hero.buy_workshop",
  "bannerlord:hero.cancel_proposal",
  "bannerlord:hero.change_child_looks",
  "bannerlord:hero.claim_starter",
  "bannerlord:hero.create",
  "bannerlord:hero.create_clan",
  "bannerlord:hero.create_kingdom",
  "bannerlord:hero.create_party",
  "bannerlord:hero.create_vassal_clan",
  "bannerlord:hero.detach",
  "bannerlord:hero.detach_charge",
  "bannerlord:hero.detach_gate",
  "bannerlord:hero.detach_hold",
  "bannerlord:hero.detach_raid",
  "bannerlord:hero.detach_skirmish",
  "bannerlord:hero.detach_walls",
  "bannerlord:hero.discard_item",
  "bannerlord:hero.discard_owned",
  "bannerlord:hero.divorce",
  "bannerlord:hero.enact_policy",
  "bannerlord:hero.equip_owned",
  "bannerlord:hero.equip_trophy",
  "bannerlord:hero.join_clan",
  "bannerlord:hero.join_kingdom",
  "bannerlord:hero.join_tournament",
  "bannerlord:hero.leave_clan",
  "bannerlord:hero.leave_kingdom",
  "bannerlord:hero.make_baby",
  "bannerlord:hero.make_peace",
  "bannerlord:hero.marry",
  "bannerlord:hero.party_order_release",
  "bannerlord:hero.party_order_set",
  "bannerlord:hero.pay_ransom",
  "bannerlord:hero.propose_marriage",
  "bannerlord:hero.recruit_troops",
  "bannerlord:hero.recruit_vassal_clan",
  "bannerlord:hero.reequip_gear",
  "bannerlord:hero.reforge_quality",
  "bannerlord:hero.rename_child",
  "bannerlord:hero.rename_vassal",
  "bannerlord:hero.respec_child_skills",
  "bannerlord:hero.respond_marriage_proposal",
  "bannerlord:hero.select_weapon_power",
  "bannerlord:hero.sell_caravan",
  "bannerlord:hero.sell_workshop",
  "bannerlord:hero.set_class",
  "bannerlord:hero.set_combat_stance",
  "bannerlord:hero.set_gender",
  "bannerlord:hero.set_specialization",
  "bannerlord:hero.smith_item",
  "bannerlord:hero.train_troops",
  "bannerlord:hero.tribute_boost",
  "bannerlord:hero.unequip_owned",
  "bannerlord:hero.upgrade_gear",
  "bannerlord:kingdom.propose_peace",
  "bannerlord:kingdom.propose_war",
  "bannerlord:player.equip_item",
  "bannerlord:player.give_item",
  "bannerlord:player.heal",
  "bannerlord:player.modify_attribute",
  "bannerlord:player.respawn",
  "bannerlord:player.spawn",
  "bannerlord:power.activate",
  "bannerlord:tournament.predict",
  "bannerlord:world.trigger_event",
  "rimworld:pawn.add_gene",
  "rimworld:pawn.add_trait",
  "rimworld:pawn.passion_reset",
  "rimworld:pawn.remove_gene",
  "rimworld:pawn.remove_trait",
  "rimworld:pawn.set_passion",
  "rimworld:pawn.set_xenotype",
  "rimworld:player.apply_effect",
  "rimworld:player.equip_item",
  "rimworld:player.give_item",
  "rimworld:player.heal",
  "rimworld:player.modify_attribute",
  "rimworld:player.respawn",
  "rimworld:player.spawn",
  "rimworld:world.trigger_event",
  "shedcolony:colonist.add_xp",
  "shedcolony:colonist.assign_home",
  "shedcolony:colonist.assign_job",
  "shedcolony:colonist.auto_work",
  "shedcolony:colonist.clear_mourn",
  "shedcolony:colonist.cure_disease",
  "shedcolony:colonist.equip_diamond",
  "shedcolony:colonist.equip_iron",
  "shedcolony:colonist.equip_leather",
  "shedcolony:colonist.equip_netherite",
  "shedcolony:colonist.equip_weapon",
  "shedcolony:colonist.feed",
  "shedcolony:colonist.fulfill_request",
  "shedcolony:colonist.give_item",
  "shedcolony:colonist.give_shield",
  "shedcolony:colonist.give_tools",
  "shedcolony:colonist.happiness_boost",
  "shedcolony:colonist.heal",
  "shedcolony:colonist.set_gender",
  "shedcolony:colonist.set_guard_retreat",
  "shedcolony:colonist.set_guard_task",
  "shedcolony:colonist.spawn",
  "shedcolony:colonist.teleport",
  "shedcolony:colony.clear_backlog",
  "shedcolony:colony.festival",
  "shedcolony:colony.finish_research",
  "shedcolony:colony.quest_unlock",
  "shedcolony:colony.set_minimum_stock",
  "shedcolony:colony.spawn_visitor",
  "shedcolony:colony.spy_boost",
  "shedcolony:colony.start_research",
  "shedcolony:colony.supply",
  "shedcolony:colony.upgrade_building"
]);
const modules = new Set(['core', 'bannerlord', 'rimworld', 'shedcolony']);
type UsageEvent = { kind: 'panel_view' | 'section_open' | 'action_attempt'; feature: string; count: number };
type Batch = { token: string; tries: number; body: string };
export interface PanelUsageDependencies {
  auth: Pick<TwitchAuthStore, 'current' | 'subscribe'>;
  identity: Pick<IdentityBootstrap, 'snapshot' | 'subscribe'>;
  baseUrl: string;
  surface: 'mobile' | 'desktop';
  fetcher?: typeof fetch;
}

/** In-memory, best-effort port of viewer-usage.js, independent of mutations.
 * Keep the legacy 30s batch / 5s timeout / two identical 60s retries contract.
 * The resolved-identity gate additionally prevents token refresh from sending
 * telemetry under an identity the current host cannot yet authorize.
 */
export class PanelUsage {
  private queue = new Map<string, UsageEvent>();
  private panels = new Set<string>();
  private seenPanels = new Set<string>();
  private panelDay = -1;
  private boundToken = '';
  private boundOwner = '';
  private flight: Batch | null = null;
  private busy = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private queued = 0;
  private active = false;
  private unsubscribe: (() => void)[] = [];
  private readonly fetcher: typeof fetch;
  constructor(private readonly deps: PanelUsageDependencies) { this.fetcher = deps.fetcher ?? fetch; }
  private clear() {
    this.queue.clear(); this.panels.clear(); this.seenPanels.clear(); this.queued = 0; this.flight = null;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }
  private context() {
    const auth = this.deps.auth.current(), token = auth?.token || '';
    const owner = JSON.stringify([auth?.channelId, auth?.userId]);
    if (token !== this.boundToken || owner !== this.boundOwner) { this.clear(); this.boundToken = token; this.boundOwner = owner; }
    const day = Math.floor(Date.now() / 86400000);
    if (day !== this.panelDay) { this.panels.clear(); this.panelDay = day; }
    const identity = this.deps.identity.snapshot();
    return this.active && identity.status === 'ready' && identity.login ? token : '';
  }
  private sync = () => {
    try {
      if (this.context()) this.schedule(this.flight ? 60000 : 30000);
      else { if (this.timer !== null) clearTimeout(this.timer); this.timer = null; }
    } catch { /* Identity/telemetry errors never reach gameplay listeners. */ }
  };
  private hidden = () => { try { if (document.hidden) void this.flush(); } catch { /* Optional statistics only. */ } };
  start() {
    if (this.active) return;
    this.active = true;
    this.unsubscribe = [this.deps.auth.subscribe(this.sync), this.deps.identity.subscribe(this.sync)];
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', this.hidden);
    this.sync();
  }
  stop() {
    this.active = false; this.unsubscribe.forEach(fn => fn()); this.unsubscribe = [];
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', this.hidden);
    this.clear();
  }
  private schedule(delay: number) {
    if (!this.active || this.timer !== null || (!this.flight && !this.queue.size)) return;
    this.timer = setTimeout(() => { this.timer = null; void this.flush(); }, delay);
  }
  private track(kind: UsageEvent['kind'], feature: string): boolean {
    try {
      if (!this.context() || this.queued >= 100) return false;
      const module = feature.split(':')[0];
      // A new-day action supplies an exposure only for explicitly seen modules.
      if (kind !== 'panel_view' && this.seenPanels.has(module) && !this.panels.has(module)) {
        if (this.track('panel_view', module + ':panel')) this.panels.add(module);
        if (this.queued >= 100) return false;
      }
      const key = kind + ':' + feature, current = this.queue.get(key);
      if (current) { if (current.count >= 20) return false; current.count++; }
      else { if (this.queue.size >= 20) return false; this.queue.set(key, { kind, feature, count: 1 }); }
      this.queued++; this.schedule(30000); return true;
    } catch { return false; }
  }
  trackPanel(module: string) {
    try {
      if (!this.context() || !modules.has(module) || this.panels.has(module)) return;
      this.seenPanels.add(module);
      if (this.track('panel_view', module + ':panel')) this.panels.add(module);
    } catch { /* Never block panel rendering. */ }
  }
  trackSection(feature: string) { if (sections.has(feature)) this.track('section_open', feature); }
  trackAction(feature: string) { if (actions.has(feature)) this.track('action_attempt', feature); }
  async flush(): Promise<void> {
    try {
      const token = this.context();
      if (!token || this.busy) return;
      if (this.timer !== null) clearTimeout(this.timer);
      this.timer = null;
      if (!this.flight && this.queue.size) {
        if (!globalThis.crypto || typeof globalThis.crypto.randomUUID !== 'function') return;
        this.flight = { token, tries: 0, body: JSON.stringify({ batch_id: globalThis.crypto.randomUUID(), surface: this.deps.surface, events: Array.from(this.queue.values()) }) };
        this.queue.clear(); this.queued = 0;
      }
      if (!this.flight) return;
      const batch = this.flight; this.busy = true; batch.tries++;
      let timeout: ReturnType<typeof setTimeout> | undefined;
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      try {
        const response = await Promise.race([
          this.fetcher(this.deps.baseUrl + '/api/viewer/ui-usage', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': batch.token }, body: batch.body, keepalive: true, signal: controller?.signal }),
          new Promise<never>((_, reject) => { timeout = setTimeout(() => { controller?.abort(); reject(new Error('usage timeout')); }, 5000); }),
        ]);
        if (response.ok || [400, 401, 403, 404, 413].includes(response.status)) { if (this.flight === batch) this.flight = null; }
      } catch { /* Retry only this batch; no toast or payload logging. */ }
      finally {
        clearTimeout(timeout); this.busy = false;
        if (this.flight === batch && batch.tries >= 3) this.flight = null;
        this.schedule(this.flight ? 60000 : 30000);
      }
    } catch { /* Fail closed without affecting the host application. */ }
  }
}
