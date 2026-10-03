import type { TwitchAuthStore } from '../auth';
import type { IdentityBootstrap, IdentityHelper } from '../skillgames/identity';
import { PanelUsage } from '../panel/usage';
import { ViewerClient, type ViewerLevel } from './client';
import { ViewerRealtime, type RealtimeHelper } from './realtime';
export interface ViewerHelper extends IdentityHelper, RealtimeHelper { chat?: { onMessage(callback: (channel: string, user: string, message: string, id: string) => void): void } }
export interface ViewerNotice { id: number; text: string }
export interface ViewerStatistics { stats: Record<string, number>; achievements: { key?: string; emoji?: string; name: string; description?: string; reward?: number; unlocked?: boolean }[]; streak: { current_streak?: number; max_streak?: number } }
export interface ViewerState { panelVisible: boolean; client: ViewerClient | null; stats: Record<string, unknown> | null; level: ViewerLevel | null; config: Record<string, unknown> | null; perks: Record<string, unknown> | null; online: string[]; notices: ViewerNotice[]; statistics: ViewerStatistics | null; error: string }
export class ViewerRuntime {
  private state: ViewerState = { panelVisible: true, client: null, stats: null, level: null, config: null, perks: null, online: [], notices: [], statistics: null, error: '' };
  private listeners = new Set<() => void>(); private stops: (() => void)[] = []; private timers: ReturnType<typeof setInterval>[] = [];
  private active = false; private owner = ''; private initialized = false; private noticesBusy = false; private minutes = 0;
  private authRecoveries = 0;
  private modules = new Set<(client: ViewerClient | null, module: unknown) => void>();
  private visibilityListeners = new Set<(visible: boolean) => void>();
  bindPanelVisibility(listener: (visible: boolean) => void) { this.visibilityListeners.add(listener); listener(this.state.panelVisible); return () => { this.visibilityListeners.delete(listener); }; }
  setPanelVisible(panelVisible: boolean) { this.publish({ panelVisible }); this.visibilityListeners.forEach(fn => fn(panelVisible)); }
  private tabListeners = new Set<(tab: 'bot'|'integration'|'shop'|'stats') => void>();
  bindTab(listener: (tab: 'bot'|'integration'|'shop'|'stats') => void) { this.tabListeners.add(listener); return () => { this.tabListeners.delete(listener); }; }
  bindModule(listener: (client: ViewerClient | null, module: unknown) => void) { this.modules.add(listener); listener(this.state.client, this.state.stats?.active_module); return () => { this.modules.delete(listener); }; }
  private started = 0; private reported = 0; private clicks = 0; private moves = 0; private lastMove = 0;
  readonly realtime = new ViewerRealtime(); readonly usage: PanelUsage;
  constructor(private readonly auth: TwitchAuthStore, private readonly identity: IdentityBootstrap, private readonly options: { fetcher?: typeof fetch; baseUrl: string; surface: 'mobile' | 'desktop' }) { this.usage = new PanelUsage({ auth, identity, ...options }); }
  snapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private publish(patch: Partial<ViewerState>) { this.state = { ...this.state, ...patch }; this.listeners.forEach(fn => fn()); }
  private interval(fn: () => void, ms: number) { this.timers.push(setInterval(fn, ms)); }
  private run(work: Promise<unknown>) { void work.catch(error => { if (this.active) this.publish({ error: error instanceof Error ? error.message : 'Сервер недоступен' }); }); }
  start() {
    if (this.active) return; this.active = true; this.started = this.reported = Date.now(); this.usage.start();
    const request = this.options.fetcher || fetch;
    this.run(request(this.options.baseUrl + '/api/core/config').then(r => { if (!r.ok) throw new Error('Цены сервера недоступны'); return r.json(); }).then(config => { if (this.active) this.publish({ config }); }));
    document.addEventListener('click', this.click); document.addEventListener('mousemove', this.move); document.addEventListener('visibilitychange', this.visibility); window.addEventListener('beforeunload', this.unload);
    this.interval(() => this.reportActivity(false), 60000); this.stops.push(this.identity.subscribe(this.sync)); this.sync();
  }
  attach(helper: ViewerHelper) {
    helper.onAuthorized(auth => { if (this.active) this.realtime.bind(helper, auth); });
    try { helper.chat?.onMessage((_channel, _user, message) => { const client = this.state.client; if (client) this.run(client.post('/api/viewer/chat-message', { username: client.identity.login, message_length: message ? message.length : 0, message_text: message || '' })); }); } catch { /* Chat is optional on Twitch surfaces. */ }
  }
  private sync = () => {
    const gate = this.identity.snapshot(), auth = this.auth.current();
    if (gate.status !== 'ready' || !gate.login || !auth) { this.publish({ client: null }); return; }
    const owner = JSON.stringify([auth.channelId, auth.userId, gate.login]);
    if (this.state.client?.identity.token === auth.token && owner === this.owner) return;
    if (owner !== this.owner) { this.minutes = this.clicks = this.moves = this.authRecoveries = 0; this.initialized = false; this.publish({ stats: null, level: null, perks: null, online: [], notices: [], statistics: null }); }
    this.owner = owner;
    const client = new ViewerClient({ ...auth, login: gate.login }, this.options.baseUrl, this.options.fetcher || fetch, () => this.active && this.state.client === client && this.identity.snapshot().status === 'ready', feature => this.usage.trackAction(feature));
    client.onAuthLost = () => { if (this.state.client !== client) return; this.publish({ stats: null, level: null, perks: null }); if (this.authRecoveries++ < 3) this.run(this.identity.retry()); else this.identity.requireResolution('Сервер не подтвердил вход. Повторите проверку Twitch ID.'); };
    client.onDetails = level => { if (this.state.client === client) this.publish({ level }); };
    client.onStats(stats => { if (this.state.client === client) { this.publish({ stats, error: '' }); this.modules.forEach(fn => fn(client, stats.active_module)); this.usage.trackPanel('core'); } }); this.publish({ client });
    if (this.initialized) { this.run(client.refreshUser()); this.perks(); return; }
    this.initialized = true; this.online();
    if (!this.servicesStarted) this.interval(() => this.online(), 30000);
    // Historical wire field is extension clientId; server derives real channel from JWT.
    this.run(client.post('/api/viewer/online', { username: gate.login, channel_id: auth.clientId || 'unknown' }));
    this.run(client.refreshUser()); this.perks(); this.notices();
    if (!this.servicesStarted) {
      this.interval(() => this.notices(), 20000); this.interval(() => this.perks(), 300000);
      this.interval(() => { if (this.state.client) this.run(this.state.client.refreshUser()); if (this.tab === 'stats') this.run(this.loadStatistics()); }, 60000);
      this.interval(() => { if (this.state.client && this.state.client.identity.login !== 'testuser') this.minutes++; }, 60000);
      this.interval(() => this.attendance(), 300000); this.servicesStarted = true;
    }
  };
  private servicesStarted = false;
  private tab: 'bot' | 'integration' | 'shop' | 'stats' = 'bot';
  selectTab(tab: typeof this.tab) { if (tab !== this.tab) this.usage.trackSection('core:tab.' + tab); this.tab = tab; this.usage.trackPanel('core'); if (tab === 'integration' && typeof this.state.stats?.active_module === 'string') this.usage.trackPanel(this.state.stats.active_module); this.tabListeners.forEach(fn => fn(tab)); if (tab === 'stats') this.run(this.loadStatistics()); }
  async loadStatistics() {
    const client = this.state.client; if (!client) return; const name = encodeURIComponent(client.identity.login);
    const [data, achievements, streak] = await Promise.all([client.read<{ stats?: Record<string, number> }>('/api/viewer/stats/' + name, true, 'no-store'), client.read<{ achievements?: ViewerStatistics['achievements'] }>('/api/viewer/achievements/' + name, true, 'no-store'), client.read<ViewerStatistics['streak']>('/api/viewer/streak/' + name, true, 'no-store')]);
    if (this.state.client === client) this.publish({ statistics: { stats: data.stats || {}, achievements: achievements.achievements || [], streak } });
  }
  private online() { const client = this.state.client; if (client) this.run(client.read<{ users?: string[] }>('/api/viewer/online-list').then(data => { if (this.state.client === client) this.publish({ online: (data.users || []).filter(user => user !== client.identity.login) }); })); }
  private perks() { const client = this.state.client; if (client) this.run(client.read<Record<string, unknown>>('/api/viewer/perks', true, 'no-store').then(data => { if (this.state.client === client) this.publish({ perks: data.success ? data : null }); })); }
  private notices() {
    const client = this.state.client; if (!client || this.noticesBusy || document.hidden) return; this.noticesBusy = true;
    this.run(client.read<{ notices?: { id: number; text: string; amount?: number }[] }>('/api/notices').then(data => {
      if (this.state.client !== client) return; const items = (data.notices || []).slice(0, 3); if (!items.length) return;
      // Show the complete acknowledged batch immediately; legacy could lose its delayed toasts on close.
      this.publish({ notices: items.map(item => ({ id: item.id, text: item.text + (Number(item.amount) > 0 ? ` Крустики вернулись: +${item.amount}💎` : '') })) });
      if (items.some(item => Number(item.amount) > 0)) this.run(client.refreshUser());
      return client.post('/api/notices/ack', { ids: items.map(item => item.id) });
    }).finally(() => { this.noticesBusy = false; }));
  }
  dismissNotice(id: number) { this.publish({ notices: this.state.notices.filter(item => item.id !== id) }); }
  private attendance() {
    const client = this.state.client; if (!client || client.identity.login === 'testuser' || this.minutes < 1) return;
    this.run(client.post<{ rewarded?: boolean; current_streak?: number; reward?: number }>('/api/viewer/attendance', { username: client.identity.login, minutes: this.minutes }).then(data => {
      if (this.state.client !== client || !data.rewarded) return; this.publish({ notices: [...this.state.notices, { id: -Date.now(), text: `Стрик ${data.current_streak} стримов подряд! +${data.reward}💎` }] }); this.run(client.refreshUser()); this.run(this.loadStatistics());
    }));
  }
  private click = () => { this.clicks++; };
  private move = () => { const now = Date.now(); if (now - this.lastMove > 2000) { this.moves++; this.lastMove = now; } };
  private visibility = () => { if (document.hidden) this.reportActivity(true); else this.started = this.reported = Date.now(); };
  private unload = () => { this.reportActivity(true); this.stop(); };
  private reportActivity(final: boolean) {
    const now = Date.now(), watch = Math.floor((now - this.reported) / 1000), client = this.state.client;
    if ((!final && watch < 5) || !client || client.identity.login === 'testuser' || client.identity.login.includes('U')) return;
    this.run(client.post<{ status?: string }>('/api/viewer/activity', { username: client.identity.login, watch_time: watch, total_time: Math.floor((now - this.started) / 1000), active_clicks: this.clicks, active_moves: this.moves }).then(data => { if (data.status === 'ok' && this.state.client === client) { this.clicks = this.moves = 0; this.reported = now; } }));
  }
  stop() { this.active = false; this.modules.forEach(fn => fn(null, null)); this.timers.forEach(clearInterval); this.timers = []; this.stops.splice(0).forEach(fn => fn()); this.state.client?.dispose(); this.usage.stop(); this.realtime.stop(); this.servicesStarted = this.initialized = false; document.removeEventListener('click', this.click); document.removeEventListener('mousemove', this.move); document.removeEventListener('visibilitychange', this.visibility); window.removeEventListener('beforeunload', this.unload); }
}
