import { policyRefusal } from './policy-refusal';
export interface ViewerIdentity { login: string; token: string; channelId: string }
export interface ViewerLevel { level?: number; exp?: number; exp_needed?: number; title?: string; bonus_pct?: number }
export class ViewerClient {
  onAuthLost?: () => void;
  onDetails?: (level: ViewerLevel, duels: Record<string, unknown>) => void;
  private active = true;
  private statsSequence = 0;
  private statsListeners = new Set<(stats: Record<string, unknown>) => void>();
  constructor(public readonly identity: ViewerIdentity, private readonly baseUrl = '', private readonly fetcher: typeof fetch = fetch, private readonly isCurrent: () => boolean = () => true, private readonly trackAction: (feature: string) => void = () => {}) {}
  dispose() { this.active = false; this.statsListeners.clear(); }
  onStats(listener: (stats: Record<string, unknown>) => void) { this.statsListeners.add(listener); return () => { this.statsListeners.delete(listener); }; }
  async read<T>(path: string, authenticated = true, cache?: RequestCache): Promise<T> {
    if (!this.active || !this.isCurrent()) throw new Error('Личность Twitch изменилась; открой раздел заново');
    const request = this.fetcher;
    const response = await request(this.baseUrl + path, { ...(authenticated ? { headers: { 'X-Twitch-JWT': this.identity.token } } : {}), ...(cache ? { cache } : {}) });
    const data = await response.json();
    const refusal = policyRefusal(response.status, data, this.identity.channelId, true);
    if (refusal) throw new Error(refusal.message);
    if (!response.ok) throw new Error(typeof data?.message === 'string' ? data.message : 'Не удалось загрузить данные');
    return data as T;
  }
  async post<T>(path: string, body?: Record<string, unknown>): Promise<T> {
    if (!this.active || !this.isCurrent()) throw new Error('Личность Twitch изменилась; открой раздел заново');
    const request = this.fetcher;
    const response = await request(this.baseUrl + path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': this.identity.token }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const data = await response.json();
    const refusal = policyRefusal(response.status, data, this.identity.channelId);
    if (refusal) return refusal as T;
    if (!response.ok) throw new Error(typeof data?.message === 'string' ? data.message : 'Сервер отказал в действии');
    return data as T;
  }
  async refreshUser() {
    const seq = ++this.statsSequence;
    if (!this.active || !this.isCurrent()) return;
    const request = this.fetcher;
    const response = await request(this.baseUrl + '/api/viewer/stats/' + encodeURIComponent(this.identity.login), { headers: { 'X-Twitch-JWT': this.identity.token }, cache: 'no-store' });
    if (!response.ok) throw new Error('Не удалось обновить баланс');
    const stats = await response.json() as Record<string, unknown>;
    if (!this.active || !this.isCurrent() || seq !== this.statsSequence) return;
    if (stats.status === 'unauthorized' || typeof stats.points !== 'number') { this.onAuthLost?.(); return; }
    this.statsListeners.forEach(listener => listener(stats));
    const [level, duels] = await Promise.all([this.read<ViewerLevel>('/api/user/level/' + encodeURIComponent(this.identity.login)), this.read<Record<string, unknown>>('/api/duel/list')]);
    if (this.active && this.isCurrent() && seq === this.statsSequence) this.onDetails?.(level, duels);
  }
  async moduleAction<T>(module: 'shedcolony', actionType: string, data: Record<string, unknown>) {
    try { this.trackAction(module + ':' + actionType); } catch { /* Telemetry must not affect gameplay. */ }
    return this.post<T>('/api/' + module + '/action', { action_type: actionType, data: { ...data, client_action_id: crypto.randomUUID() } });
  }
}
