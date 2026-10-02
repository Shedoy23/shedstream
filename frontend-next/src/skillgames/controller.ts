import { TwitchAuthStore } from '../auth';
import type { Command, Endpoint, MutationReply, SkillgameSnapshot, SkillgameTransport } from './contracts';
export interface SkillgameViewState { data: SkillgameSnapshot | null; loading: boolean; pending: boolean; uncertain: boolean; error: string | null; notice: string | null; canAct: boolean; receivedAt: number }
const initial: SkillgameViewState = { data: null, loading: false, pending: false, uncertain: false, error: null, notice: null, canAct: false, receivedAt: 0 };
const scope = (auth: TwitchAuthStore) => JSON.stringify([auth.current()?.channelId, auth.current()?.userId]);
export class SkillgameController {
  private state = initial; private listeners = new Set<() => void>(); private active = false;
  private generation = 0; private identity: string; private inFlight = false; private pending = false;
  private abort?: AbortController; private detach?: () => void; private sessionId?: string;
  constructor(private readonly transport: SkillgameTransport, private readonly auth: TwitchAuthStore) { this.identity = scope(auth); }
  snapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private publish(patch: Partial<SkillgameViewState>) {
    if (!this.active) return;
    this.state = { ...this.state, ...patch, uncertain: this.transport.hasUncertain(), pending: this.pending };
    this.state.canAct = !!this.auth.current() && !!this.state.data && !this.state.error && !this.pending && !this.state.uncertain;
    this.listeners.forEach(fn => fn());
  }
  start() {
    if (this.active) return; this.active = true;
    this.syncIdentity();
    this.detach = this.auth.subscribe(() => {
      this.generation++; this.abort?.abort(); this.inFlight = false; this.syncIdentity(); void this.refresh();
    });
    void this.refresh();
  }
  stop() { this.active = false; this.generation++; this.abort?.abort(); this.inFlight = false; this.detach?.(); }
  private syncIdentity() {
    const identity = scope(this.auth); if (this.identity === identity) return;
    this.identity = identity; this.pending = false; this.sessionId = undefined; this.state = initial;
  }
  async refresh() {
    if (!this.active || this.inFlight || this.pending) return;
    if (!this.auth.current()) { this.publish({ ...initial, error: 'Подключите Twitch: ждём авторизацию расширения' }); return; }
    const generation = this.generation; const abort = new AbortController(); this.abort = abort; this.inFlight = true;
    this.publish({ loading: true });
    try {
      const data = await this.transport.read(abort.signal, this.sessionId);
      if (!this.active || generation !== this.generation) return;
      this.publish({ data, error: null, loading: false, receivedAt: Date.now() });
    } catch (error) {
      if (!this.active || generation !== this.generation || abort.signal.aborted) return;
      this.publish({ loading: false, error: error instanceof Error ? error.message : 'Не удалось обновить состояние' });
    } finally { if (generation === this.generation) this.inFlight = false; }
  }
  async submit(endpoint: Endpoint, command: Command) {
    if (!this.active || !this.state.canAct || this.pending) return;
    await this.run(() => this.transport.mutate(endpoint, command));
  }
  async retry() { if (this.active && !this.pending && this.transport.hasUncertain()) await this.run(() => this.transport.retry()); }
  private async run(send: () => Promise<MutationReply>) {
    const identity = this.identity;
    // Establish a read barrier before mutating; a stale GET must never roll back an accepted move.
    this.generation++; this.abort?.abort(); this.inFlight = false; this.pending = true;
    this.publish({ notice: null, loading: false });
    try {
      const reply = await send(); if (identity !== scope(this.auth)) return;
      if (reply.success) {
        const session = reply.session || reply.active_session;
        if (session) this.sessionId = session.id;
        this.publish({ notice: reply.message || 'Сервер принял действие', error: null });
      } else this.publish({ notice: `${reply.message || 'Отказ сервера'}${reply.reason ? ` (${reply.reason})` : ''}` });
    } catch (error) {
      if (identity === scope(this.auth)) this.publish({ notice: error instanceof Error ? error.message : 'Результат действия неизвестен' });
    } finally {
      if (identity === scope(this.auth)) { this.pending = false; this.publish({}); await this.refresh(); }
    }
  }
}
