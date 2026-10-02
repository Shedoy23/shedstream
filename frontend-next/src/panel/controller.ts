import { TwitchAuthStore } from '../auth';
import type { IdentityBootstrap } from '../skillgames/identity';
import { actionKey, hasProgressionPrices, type ActionOptions, type ActionReply, type BuffsReply, type BuildReply, type ClassesReply, type HeroReply, type PanelConfig, type PanelState, type PanelTransport } from './contracts';
const owner = (auth: TwitchAuthStore) => JSON.stringify([auth.current()?.channelId, auth.current()?.userId]);
export class PanelController {
  private state: PanelState;
  private listeners = new Set<() => void>(); private active = false; private generation = 0; private owner = '';
  private unsubscribe: (() => void)[] = []; private issued: Record<string, number> = {}; private applied: Record<string, number> = {};
  private cooldownRevision = 0; private buildRevision = 0; private aborts = new Set<AbortController>();
  private timers = new Set<ReturnType<typeof setTimeout>>(); private equipmentRefresh?: () => void | Promise<unknown>;
  constructor(private readonly transport: PanelTransport, private readonly auth: TwitchAuthStore, private readonly identity: Pick<IdentityBootstrap, 'snapshot' | 'subscribe'>, private readonly clock: () => number = Date.now) { this.state = this.empty(); }
  private empty(): PanelState { return { hero: null, config: null, build: null, classes: null, loading: false, canAct: false, message: '', error: '', errors: {}, buildPending: false, busy: [], cooldowns: {}, now: this.clock(), generation: this.generation }; }
  snapshot = () => this.state;
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  private publish(patch: Partial<PanelState>) { this.state = { ...this.state, ...patch }; this.listeners.forEach(fn => fn()); }
  identityGeneration = () => this.generation;
  ready = () => this.active && this.identity.snapshot().status === 'ready' && !!this.identity.snapshot().login && !!this.auth.current()?.token && this.owner === owner(this.auth);
  private invalidate() { this.generation++; this.aborts.forEach(abort => abort.abort()); this.aborts.clear(); this.timers.forEach(timer => clearTimeout(timer)); this.timers.clear(); this.issued = {}; this.applied = {}; this.cooldownRevision++; this.buildRevision++; this.state = this.empty(); }
  private syncIdentity = () => {
    const next = owner(this.auth); const changed = next !== this.owner;
    if (changed) { this.owner = next; this.invalidate(); }
    const previouslyReady = this.state.canAct; const canAct = this.ready(); this.publish({ canAct });
    if (canAct && (changed || !previouslyReady)) void this.refresh();
  };
  async start() {
    if (this.active) return;
    this.active = true; this.owner = owner(this.auth);
    this.unsubscribe = [this.auth.subscribe(this.syncIdentity), this.identity.subscribe(this.syncIdentity)];
    this.publish({ canAct: this.ready() }); if (this.ready()) await this.refresh();
  }
  stop() { this.active = false; this.unsubscribe.forEach(fn => fn()); this.unsubscribe = []; this.invalidate(); this.publish({ canAct: false }); }
  registerEquipmentRefresh(callback: () => void | Promise<unknown>) { this.equipmentRefresh = callback; return () => { if (this.equipmentRefresh === callback) this.equipmentRefresh = undefined; }; }
  refreshEquipment = () => this.equipmentRefresh?.();
  async read<T>(path: string, signal?: AbortSignal) { if (!this.ready()) throw new Error('Личность Twitch пока не подтверждена'); return this.transport.read<T>(path, signal); }
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
      this.publish({ ...(key === 'config' ? { config: null } : {}),
        ...(key === 'build' && this.state.build ? { build: { ...this.state.build, ready: false, can_manage: false, build: undefined, enabled: !!this.state.build.enabled || this.state.build.build?.version === 1, message: errors[key] } } : {}), errors, error: Object.values(errors)[0] || '' });
    } finally { this.aborts.delete(abort); }
  }
  refreshHero = () => this.load<HeroReply>('hero', '/api/bannerlord/my-hero', hero => ({ hero }));
  refreshConfig = () => this.load<PanelConfig>('config', '/api/bannerlord/config', config => ({ config }));
  refreshClasses = () => this.load<ClassesReply>('classes', '/api/bannerlord/classes', classes => ({ classes }));
  refreshBuild = () => { const revision = this.buildRevision; return this.load<BuildReply>('build', '/api/bannerlord/build', build => ({ build, buildPending: !!build.pending }), () => revision === this.buildRevision); };
  refreshBuffs = () => {
    const revision = this.cooldownRevision;
    return this.load<BuffsReply>('buffs', '/api/bannerlord/my-buffs', data => ({ cooldowns: revision === this.cooldownRevision ? Object.fromEntries((data.cooldowns || []).map(c => [c.power_key, this.clock() + Math.max(0, c.remaining_s) * 1000])) : this.state.cooldowns }));
  };
  async refreshDevelopment() {
    await Promise.all([this.refreshHero(), this.refreshBuild(), this.equipmentRefresh?.(),
      !hasProgressionPrices(this.state.config) ? this.refreshConfig() : undefined,
      !this.state.classes ? this.refreshClasses() : undefined]);
  }
  async refresh() {
    if (!this.ready()) return;
    const generation = this.generation; this.publish({ loading: true });
    await Promise.all([this.refreshConfig(), this.refreshHero(), this.refreshClasses(), this.refreshBuild(), this.refreshBuffs()]);
    if (generation === this.generation) this.publish({ loading: false });
  }
  tick = () => this.publish({ now: this.clock() });
  cooldown(type: string) { return Math.max(0, ((this.state.cooldowns[type] || 0) - this.clock()) / 1000); }
  private async balance(generation: number, login: string) {
    try {
      if (generation !== this.generation || !this.ready()) return;
      const data = await this.transport.read<Record<string, unknown>>('/api/viewer/stats/' + encodeURIComponent(login));
      if (generation !== this.generation || !this.ready()) return;
      if (data.status === 'unauthorized' || !('points' in data)) { this.publish({ error: 'Сервер не подтвердил личность для обновления баланса' }); return; }
      await Promise.all([this.transport.read('/api/user/level/' + encodeURIComponent(login)), this.transport.read('/api/duel/list')]);
    } catch (error) { if (generation === this.generation) this.publish({ error: error instanceof Error ? error.message : 'Не удалось обновить баланс' }); }
  }
  async action(type: string, data: Record<string, unknown>, options: ActionOptions): Promise<ActionReply | null> {
    if (!this.ready()) return null;
    const generation = this.generation, login = this.identity.snapshot().login!, key = actionKey(type, data);
    // Match legacy per-choice single flight. Different skill/attribute choices
    // remain separate; economic authority stays on the backend.
    if (this.state.busy.includes(key)) { this.publish({ message: '⏳ Предыдущее действие ещё выполняется — секунду' }); if (options.immediateHero) void this.refreshHero(); return null; }
    this.publish({ busy: [...this.state.busy, key], message: '', error: '' });
    try {
      const pending = this.transport.action(type, data);
      if (options.immediateHero) void this.refreshHero();
      const result = await pending;
      if (generation !== this.generation || !this.active || !result) return null;
      const seconds = result.success ? result.cooldown_applied_s : result.cooldown_remaining_s;
      if (typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0) {
        this.cooldownRevision++; this.publish({ cooldowns: { ...this.state.cooldowns, [type]: this.clock() + seconds * 1000 } });
      }
      this.publish({ message: (result.required_role && !result.success ? '🔒 ' : '') + (result.success && options.successMessage || result.message || (result.success ? 'Заявка отправлена' : 'Действие не выполнено')) });
      if (result.success) {
        void this.balance(generation, login);
        if (options.tail === 'hero') {
          this.applied.hero = this.issued.hero = (this.issued.hero || 0) + 1;
          this.buildRevision++;
          if (type === 'hero.set_specialization' || type === 'hero.claim_starter') this.publish({ buildPending: true });
          const timer = setTimeout(() => { this.timers.delete(timer); if (generation !== this.generation || !this.ready()) return; void this.refreshHero(); void this.refreshBuild(); void this.equipmentRefresh?.(); }, 3500);
          this.timers.add(timer);
        }
      }
      return result;
    } catch (error) {
      if (generation === this.generation) this.publish({ message: 'Ошибка сети: ' + (error instanceof Error ? error.message : String(error)) });
      return null;
    } finally { if (generation === this.generation) this.publish({ busy: this.state.busy.filter(value => value !== key) }); }
  }
}
