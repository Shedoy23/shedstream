import { TwitchAuthStore } from '../auth';
import type { PanelUsage } from './usage';
import type { IdentityBootstrap } from '../skillgames/identity';
import { actionKey, hasProgressionPrices, heroContext, UnknownActionOutcomeError, type BattleReply, type ActionOptions, type ActionReply, type BuffsReply, type BuildReply, type ClassesReply, type HeroReply, type PanelConfig, type PanelState, type PanelTransport } from './contracts';
import { refundText } from './refunds';
import { combatAllowed, semanticCooldown } from './combat';
const owner = (auth: TwitchAuthStore) => JSON.stringify([auth.current()?.channelId, auth.current()?.userId]);
export class PanelController {
  private state: PanelState;
  private listeners = new Set<() => void>(); private active = false; private generation = 0; private owner = '';
  private unsubscribe: (() => void)[] = []; private issued: Record<string, number> = {}; private applied: Record<string, number> = {};
  private shownRefunds = new Set<string>(); private pendingStance: { actionId: string; revision: number } | null = null;
  private initialEquipment = false;
  private equipmentPreload: { generation: number; hero?: string; promise: Promise<unknown>; abort: AbortController } | null = null;
  private combatEnabled = false; private stanceRevision = 0;
  private cooldownRevision = 0; private buildRevision = 0; private aborts = new Set<AbortController>();
  private timers = new Set<ReturnType<typeof setTimeout>>(); private equipmentRefresh?: () => void | Promise<unknown>;
  constructor(private readonly transport: PanelTransport, private readonly auth: TwitchAuthStore, private readonly identity: Pick<IdentityBootstrap, 'snapshot' | 'subscribe'>, private readonly clock: () => number = Date.now, private readonly usage?: Pick<PanelUsage, 'start' | 'stop' | 'trackPanel' | 'trackSection' | 'trackAction'>) { this.state = this.empty(); }
  private empty(): PanelState { return { refundNotices: [], battle: null, buffs: {}, buffsReady: false, points: null, newBuild: false, buildBusy: false, buildCooldownUntil: 0, optimisticStance: null, hero: null, config: null, build: null, classes: null, loading: false, canAct: false, mutationBlocked: false, message: '', error: '', errors: {}, buildPending: false, busy: [], cooldowns: {}, now: this.clock(), generation: this.generation }; }
  snapshot = () => this.state;
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  private publish(patch: Partial<PanelState>) { this.state = { ...this.state, ...patch }; this.listeners.forEach(fn => fn()); }
  identityGeneration = () => this.generation;
  ready = () => this.active && this.identity.snapshot().status === 'ready' && !!this.identity.snapshot().login && !!this.auth.current()?.token && this.owner === owner(this.auth);
  private invalidate() { this.generation++; this.aborts.forEach(abort => abort.abort()); this.aborts.clear(); this.timers.forEach(timer => clearTimeout(timer)); this.timers.clear(); this.issued = {}; this.applied = {}; this.cooldownRevision++; this.buildRevision++; this.stanceRevision++; this.pendingStance = null; this.equipmentPreload = null; this.shownRefunds.clear(); this.state = this.empty(); }
  private mutationGate() { const message = this.transport.mutationBlock?.(); return { mutationBlocked: !!message, ...(message ? { message } : {}) }; }
  private syncIdentity = () => {
    const next = owner(this.auth); const changed = next !== this.owner;
    if (changed) { this.owner = next; this.invalidate(); }
    const previouslyReady = this.state.canAct; const canAct = this.ready(); this.publish({ canAct, ...this.mutationGate() });
    if (canAct && (changed || !previouslyReady)) void this.refresh();
  };
  enableCombat() { this.combatEnabled = true; }
  async start(options: { equipmentFirst?: boolean } = {}) {
    if (this.active) return;
    this.initialEquipment = !!options.equipmentFirst;
    this.active = true; this.owner = owner(this.auth);
    try { this.usage?.start(); } catch { /* Observability cannot block the panel. */ }
    this.unsubscribe = [this.auth.subscribe(this.syncIdentity), this.identity.subscribe(this.syncIdentity)];
    this.publish({ canAct: this.ready(), ...this.mutationGate() }); if (this.ready()) await this.refresh();
  }
  stop() { try { this.usage?.stop(); } catch { /* Best effort only. */ } this.active = false; this.unsubscribe.forEach(fn => fn()); this.unsubscribe = []; this.invalidate(); this.publish({ canAct: false }); }
  trackVisiblePanels = () => {
    if (!this.ready() || document.hidden) return;
    try { this.usage?.trackPanel('core'); this.usage?.trackPanel('bannerlord'); } catch { /* Best effort only. */ }
  };
  trackSection = (feature: string) => { if (this.ready()) { try { this.usage?.trackSection(feature); } catch { /* Best effort only. */ } } };
  registerEquipmentRefresh(callback: () => void | Promise<unknown>) { this.equipmentRefresh = callback; return () => { if (this.equipmentRefresh === callback) this.equipmentRefresh = undefined; }; }
  refreshEquipment = () => this.equipmentRefresh?.();
  discardEquipmentPreload() { this.equipmentPreload?.abort.abort(); this.equipmentPreload = null; }
  private primeEquipment() {
    const abort = new AbortController(); this.aborts.add(abort);
    const promise = this.transport.read('/api/bannerlord/equipment-shop', abort.signal).finally(() => this.aborts.delete(abort));
    // A rejected prefetch must be handled even if the viewer leaves this tab
    // before EquipmentView consumes the promise. The original error is retained.
    void promise.catch(() => {});
    this.equipmentPreload = { generation: this.generation, promise, abort };
  }
  async read<T>(path: string, signal?: AbortSignal) {
    if (!this.ready()) throw new Error('Личность Twitch пока не подтверждена');
    if (path === '/api/bannerlord/equipment-shop' && this.equipmentPreload) {
      const preload = this.equipmentPreload; this.equipmentPreload = null;
      if (preload.generation === this.generation && preload.hero !== undefined && preload.hero === heroContext(this.state.hero)) return preload.promise as Promise<T>;
      preload.abort.abort();
    }
    return this.transport.read<T>(path, signal);
  }
  private async load<T>(key: string, path: string, apply: (value: T) => Partial<PanelState>, barrier?: () => boolean) {
    if (!this.ready()) return;
    const generation = this.generation, request = this.issued[key] = (this.issued[key] || 0) + 1;
    const abort = new AbortController(); this.aborts.add(abort);
    const current = () => this.active && generation === this.generation && request > (this.applied[key] || 0) && (!barrier || barrier());
    try {
      const value = await this.transport.read<T>(path, abort.signal);
      if (!current()) return;
      this.applied[key] = request;
      const errors = { ...this.state.errors }; delete errors[key];
      this.publish({ ...apply(value), errors, error: Object.values(errors)[0] || '' });
    } catch (error) {
      if (!current() || abort.signal.aborted) return;
      this.applied[key] = request;
      const errors = { ...this.state.errors, [key]: error instanceof Error ? error.message : 'Ошибка сети' };
      // A failed config cannot leave stale prices actionable.
      this.publish({ ...(key === 'config' ? { config: null } : {}), ...(key === 'battle' ? { battle: null } : {}), ...(key === 'buffs' ? { buffsReady: false } : {}),
        ...(key === 'build' && this.state.build ? { build: { ...this.state.build, ready: false, can_manage: false, build: undefined, enabled: !!this.state.build.enabled || this.state.build.build?.version === 1, message: errors[key] } } : {}), errors, error: Object.values(errors)[0] || '' });
    } finally { this.aborts.delete(abort); }
  }
  private refundNotices(hero: HeroReply) {
    const notices = [...this.state.refundNotices], generation = this.generation;
    if (this.shownRefunds.size > 1000) this.shownRefunds.clear();
    for (const refund of hero.recent_refunds || []) {
      if (!refund.action_id || this.shownRefunds.has(refund.action_id)) continue;
      this.shownRefunds.add(refund.action_id);
      notices.push({ id: refund.action_id, message: refundText(refund.reason, refund.refunded) });
      const timer = setTimeout(() => { this.timers.delete(timer); if (generation === this.generation) this.publish({ refundNotices: this.state.refundNotices.filter(n => n.id !== refund.action_id) }); }, 6000);
      this.timers.add(timer);
    }
    return notices;
  }
  private stanceRefused(hero: HeroReply | null) { return !!this.pendingStance && this.pendingStance.revision === this.stanceRevision && !!hero?.recent_refunds?.some(r => r.action_id === this.pendingStance?.actionId && r.type === 'hero.set_combat_stance'); }
  refreshHero = () => this.load<HeroReply>('hero', '/api/bannerlord/my-hero', hero => {
    if (this.equipmentPreload) {
      if (this.equipmentPreload.hero === undefined) this.equipmentPreload.hero = heroContext(hero);
      else if (this.equipmentPreload.hero !== heroContext(hero)) this.discardEquipmentPreload();
    }
    return { hero, refundNotices: this.refundNotices(hero), optimisticStance: hero.hero?.combat_stance === this.state.optimisticStance || this.stanceRefused(hero) ? null : this.state.optimisticStance };
  });
  refreshConfig = () => this.load<PanelConfig>('config', '/api/bannerlord/config', config => ({ config }));
  refreshClasses = () => this.load<ClassesReply>('classes', '/api/bannerlord/classes', classes => ({ classes }));
  refreshBuild = () => { const revision = this.buildRevision; return this.load<BuildReply>('build', '/api/bannerlord/build', build => ({ build, buildPending: !!build.pending, newBuild: this.state.newBuild || !!build.enabled || build.build?.version === 1, buildCooldownUntil: Math.max(this.clock() + (Number.isFinite(build.cooldown_remaining_s) ? Math.max(0, build.cooldown_remaining_s!) : 0) * 1000, Number.isFinite(build.build?.weapon_power_cooldown_until) ? build.build!.weapon_power_cooldown_until! * 1000 : 0) }), () => revision === this.buildRevision); };
  refreshBuffs = () => {
    const revision = this.cooldownRevision;
    return this.load<BuffsReply>('buffs', '/api/bannerlord/my-buffs', data => ({ buffsReady: true, buffs: this.expiries(data.buffs), cooldowns: revision === this.cooldownRevision ? this.expiries(data.cooldowns) : this.state.cooldowns }));
  };
  private expiries(values: BuffsReply['buffs']) { return Object.fromEntries((values || []).filter(c => typeof c.power_key === 'string' && Number.isFinite(c.remaining_s)).map(c => [c.power_key, this.clock() + Math.max(0, c.remaining_s) * 1000])); }
  refreshBattle = () => this.load<BattleReply>('battle', '/api/bannerlord/battle-status', battle => {
    if (battle.in_battle && !this.state.battle?.in_battle) void this.refreshBuffs();
    return { battle };
  });
  async refreshDevelopment() {
    // The old explicit refresh orders mounted equipment before build; the
    // delayed successful-action tail below deliberately uses the reverse order.
    await Promise.all([this.refreshHero(), this.equipmentRefresh?.(), this.refreshBuild(),
      !hasProgressionPrices(this.state.config) ? this.refreshConfig() : undefined,
      !this.state.classes ? this.refreshClasses() : undefined]);
  }
  async refresh() {
    if (!this.ready()) return;
    const generation = this.generation;
    if (this.initialEquipment) { this.initialEquipment = false; this.primeEquipment(); }
    this.publish({ loading: true });
    await Promise.all([this.refreshConfig(), this.refreshHero(), this.refreshClasses(), this.refreshBuild(), this.refreshBuffs()]);
    if (generation === this.generation && this.combatEnabled) { await this.refreshBalance(); if (generation === this.generation) await this.refreshBattle(); }
    if (generation === this.generation) this.publish({ loading: false });
  }
  tick = () => this.publish({ now: this.clock() });
  cooldown(type: string) { return Math.max(0, ((this.state.cooldowns[type] || 0) - this.clock()) / 1000); }
  refreshBalance = () => this.balance(this.generation, this.identity.snapshot().login || '');
  private async balance(generation: number, login: string) {
    const request = this.issued.balance = (this.issued.balance || 0) + 1;
    const current = () => generation === this.generation && this.ready() && request > (this.applied.balance || 0);
    try {
      if (generation !== this.generation || !this.ready()) return;
      const data = await this.transport.read<Record<string, unknown>>('/api/viewer/stats/' + encodeURIComponent(login));
      if (!current()) return;
      this.applied.balance = request;
      if (data.status === 'unauthorized' || typeof data.points !== 'number' || !Number.isFinite(data.points)) { this.publish({ points: null, error: 'Сервер не подтвердил личность для обновления баланса' }); return; }
      this.publish({ points: data.points });
      // The old balance loader coalesces dependent shell reads when two action
      // successes request stats together. Still apply completed points
      // monotonically, so a slower newer request cannot starve the balance.
      if (request !== this.issued.balance) return;
      await Promise.all([this.transport.read('/api/user/level/' + encodeURIComponent(login)), this.transport.read('/api/duel/list')]);
    } catch (error) { if (current()) { this.applied.balance = request; this.publish({ points: null, error: error instanceof Error ? error.message : 'Не удалось обновить баланс' }); } }
  }
  async combatAction(type: string, data: Record<string, unknown>, buildFamily = false) {
    if (!combatAllowed(this.state, type, data, buildFamily, this.clock())) return null;
    const generation = this.generation, stanceRevision = type === 'hero.set_combat_stance' ? ++this.stanceRevision : this.stanceRevision;
    if (type === 'hero.set_combat_stance') { this.pendingStance = null; this.publish({ optimisticStance: String(data.stance) }); }
    const result = await this.action(type, data, { tail: 'hero', buildFamily, cooldownKey: semanticCooldown(type, data, buildFamily) });
    if (generation === this.generation && stanceRevision === this.stanceRevision && type === 'hero.set_combat_stance') {
      if (result?.success && typeof result.action_id === 'string') this.pendingStance = { actionId: result.action_id, revision: stanceRevision };
      if (!result?.success || this.stanceRefused(this.state.hero)) this.publish({ optimisticStance: null });
    }
    return result;
  }
  async action(type: string, data: Record<string, unknown>, options: ActionOptions): Promise<ActionReply | null> {
    if (!this.ready() || this.state.mutationBlocked) return null;
    const generation = this.generation, login = this.identity.snapshot().login!, token = this.auth.current()?.token, key = actionKey(type, data);
    // BnrBuilds has one synchronous family lock. Rendered disabled state alone
    // is too late for two different choices clicked before Preact commits.
    const buildFamily = !!options.buildFamily || type === 'hero.set_specialization' || type === 'hero.claim_starter' || type === 'hero.select_weapon_power';
    if (buildFamily) {
      const build = this.state.build;
      if (!build?.ready || build.pending || this.state.buildPending || this.state.buildBusy ||
        (type !== 'power.activate' && (!build.can_manage || build.build?.in_battle))) return null;
    }
    // Count dispatcher attempts, including a duplicate intent stopped by its
    // per-choice lock, but not choices blocked by the component/family guard.
    try { this.usage?.trackAction('bannerlord:' + type); } catch { /* Never affect an action. */ }
    // Match legacy per-choice single flight. Different skill/attribute choices
    // remain separate; economic authority stays on the backend.
    if (this.state.busy.includes(key)) { this.publish({ message: '⏳ Предыдущее действие ещё выполняется — секунду' }); if (options.immediateHero) void this.refreshHero(); return null; }
    this.publish({ busy: [...this.state.busy, key], ...(buildFamily ? { buildBusy: true } : {}), message: '', error: '' });
    try {
      const pending = this.transport.action(type, data);
      if (options.immediateHero) void this.refreshHero();
      const result = await pending;
      if (generation !== this.generation || !this.active || !result) return null;
      const seconds = result.success ? result.cooldown_applied_s : result.cooldown_remaining_s;
      if (token === this.auth.current()?.token && typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0) {
        this.cooldownRevision++; this.publish({ cooldowns: { ...this.state.cooldowns, [options.cooldownKey || type]: this.clock() + seconds * 1000 } });
      }
      this.publish({ message: options.quietCooldown && !result.success && typeof result.cooldown_remaining_s === 'number' && result.cooldown_remaining_s > 0 ? '' : (result.required_role && !result.success ? '🔒 ' : '') + (result.success && options.successMessage || result.message || (result.success ? 'Заявка отправлена' : 'Действие не выполнено')) });
      if (result.success) {
        void this.balance(generation, login);
        // BnrBuilds' own accepted-action continuation is viewer-owned, not
        // wrapper-JWT-owned: token refresh cannot unlock a second build choice.
        if (buildFamily) { this.buildRevision++; this.publish({ buildPending: true }); }
        // Legacy Bannerlord callbacks belong to the admitting JWT, even when
        // the refreshed token resolves to the same viewer. Generic balance reads remain current.
        if (options.tail === 'hero' && token === this.auth.current()?.token) {
          this.applied.hero = this.issued.hero = (this.issued.hero || 0) + 1;
          if (!buildFamily) this.buildRevision++;
          const timer = setTimeout(() => { this.timers.delete(timer); if (generation !== this.generation || token !== this.auth.current()?.token || !this.ready()) return; void this.refreshHero(); void this.refreshBuild(); void this.equipmentRefresh?.(); }, 3500);
          this.timers.add(timer);
        }
      }
      return result;
    } catch (error) {
      if (generation === this.generation) this.publish({ mutationBlocked: error instanceof UnknownActionOutcomeError || this.state.mutationBlocked, message: error instanceof UnknownActionOutcomeError ? error.message : 'Ошибка сети: ' + (error instanceof Error ? error.message : String(error)) });
      return null;
    } finally { if (generation === this.generation) this.publish({ busy: this.state.busy.filter(value => value !== key), ...(buildFamily ? { buildBusy: false } : {}) }); }
  }
}
