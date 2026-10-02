import type { TournamentAction, TournamentSnapshot, TournamentTransport } from './contracts';
import { TwitchAuthStore } from './auth';
export interface TournamentViewState {
  data: TournamentSnapshot | null;
  loading: boolean;
  error: string | null;
  notice: string | null;
  pending: boolean;
  canAct: boolean;
}
const initial: TournamentViewState = { data: null, loading: false, error: null, notice: null, pending: false, canAct: false };
const scope = (auth: TwitchAuthStore) => JSON.stringify([auth.current()?.channelId, auth.current()?.userId]);
const round = (data: TournamentSnapshot) => JSON.stringify([data.state.status, data.state.started_at, data.state.current_round]);

// Owns asynchronous state, independent of React and DOM. All writes are fenced.
export class TournamentController {
  private state: TournamentViewState = initial;
  private listeners = new Set<() => void>();
  private active = false;
  private requestId = 0;
  private epoch = 0;
  private abort?: AbortController;
  private detachAuth?: () => void;
  private actionLocked = false;
  private cooldownUntil = 0;
  private accepted?: { action: TournamentAction; round: string };
  constructor(private readonly transport: TournamentTransport, private readonly auth: TwitchAuthStore) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private publish(patch: Partial<TournamentViewState>) {
    this.state = { ...this.state, ...patch };
    this.state.canAct = !!this.state.data && !this.state.error && !this.actionLocked && Date.now() >= this.cooldownUntil && !!this.auth.current();
    this.listeners.forEach(listener => listener());
  }
  start() {
    if (this.active) return;
    this.active = true;
    let identity = scope(this.auth);
    this.detachAuth = this.auth.subscribe(() => {
      this.requestId++;
      this.abort?.abort();
      const nextIdentity = scope(this.auth);
      if (nextIdentity !== identity) {
        this.epoch++;
        this.actionLocked = false;
        this.accepted = undefined;
        this.cooldownUntil = 0;
        identity = nextIdentity;
        this.publish(initial);
      }
      // A token refresh cancels stale GETs, but not a POST for the same viewer.
      void this.refresh();
    });
    void this.refresh();
  }
  stop() {
    this.active = false;
    this.epoch++;
    this.requestId++;
    this.abort?.abort();
    this.detachAuth?.();
  }
  async refresh() {
    if (!this.active) return;
    const requestId = ++this.requestId;
    this.abort?.abort();
    if (!this.auth.current()) { this.publish({ ...initial, error: 'Нужна авторизация Twitch' }); return; }
    const abort = new AbortController();
    this.abort = abort;
    this.publish({ loading: true });
    try {
      const data = await this.transport.read(abort.signal);
      if (!this.active || requestId !== this.requestId) return;
      if (this.accepted) {
        const action = this.accepted.action;
        const confirmed = action.action_type === 'hero.join_tournament' ? (data.in_queue || (data.state.status === 'running' && data.state.participants.includes(data.my_username))) : data.my_prediction?.target === action.data.target;
        if (confirmed || (action.action_type === 'tournament.predict' && round(data) !== this.accepted.round)) {
          this.actionLocked = false;
          this.accepted = undefined;
        }
      }
      this.publish({ data, loading: false, error: null });
    } catch (error) {
      if (!this.active || requestId !== this.requestId || abort.signal.aborted) return;
      this.publish({ loading: false, error: error instanceof Error ? error.message : 'Ошибка загрузки' });
    }
  }
  async submit(action: TournamentAction) {
    if (!this.active || !this.state.canAct || this.actionLocked) return;
    const data = this.state.data!;
    // Display guards only. The server remains authoritative for all game rules.
    if (action.action_type === 'hero.join_tournament' && (data.state.status !== 'idle' || data.in_queue || data.config.join_price !== 0)) return;
    if (action.action_type === 'tournament.predict' && (data.state.status !== 'running' || !!data.my_prediction || !data.state.participants.includes(action.data.target))) return;
    this.actionLocked = true;
    const epoch = this.epoch;
    this.publish({ pending: true, notice: null });
    try {
      const reply = await this.transport.act(action);
      if (!this.active || epoch !== this.epoch) return;
      this.actionLocked = reply.success;
      if (reply.success) this.accepted = { action, round: round(data) };
      const cooldown = reply.success ? reply.cooldown_applied_s : reply.cooldown_remaining_s;
      if (typeof cooldown === 'number' && Number.isFinite(cooldown) && cooldown > 0) this.cooldownUntil = Date.now() + cooldown * 1000;
      const message = reply.message || (reply.success ? 'Заявка принята.' : 'Действие отклонено сервером');
      this.publish({ pending: false, notice: reply.success ? `${message} · Подтверждение смотрим в состоянии сервера.` : message });
      if (reply.success) await this.refresh();
    } catch (error) {
      if (!this.active || epoch !== this.epoch) return;
      this.publish({ pending: false, notice: error instanceof Error ? error.message : 'Результат действия неизвестен' });
    }
  }
}
