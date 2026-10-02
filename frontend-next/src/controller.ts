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
  // Epoch changes with identity, not with a temporary view stop/start.
  private epoch = 0;
  private identity: string;
  private deferredSettlement?: () => void;
  private abort?: AbortController;
  private detachAuth?: () => void;
  private actionLocked = false;
  private cooldownUntil = 0;
  private accepted?: { action: TournamentAction; round: string };
  constructor(private readonly transport: TournamentTransport, private readonly auth: TwitchAuthStore) {
    this.identity = scope(auth);
  }
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
    this.syncIdentity();
    const settle = this.deferredSettlement;
    this.deferredSettlement = undefined;
    settle?.();
    this.detachAuth = this.auth.subscribe(() => {
      this.requestId++;
      this.abort?.abort();
      this.syncIdentity();
      // A token refresh cancels stale GETs, but not a POST for the same viewer.
      void this.refresh();
    });
    void this.refresh();
  }
  stop() {
    this.active = false;
    this.requestId++;
    this.abort?.abort();
    this.detachAuth?.();
  }
  private syncIdentity() {
    const nextIdentity = scope(this.auth);
    if (nextIdentity === this.identity) return;
    this.epoch++;
    this.identity = nextIdentity;
    this.actionLocked = false;
    this.accepted = undefined;
    this.cooldownUntil = 0;
    this.deferredSettlement = undefined;
    this.publish(initial);
  }
  private settleWhenActive(epoch: number, apply: () => void) {
    if (epoch !== this.epoch) return false;
    // Retain the outcome for this controller owner without notifying an unmounted
    // view. A changed identity discards it before start publishes anything.
    if (!this.active) { this.deferredSettlement = apply; return false; }
    apply();
    return true;
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
      const cooldown = reply.success ? reply.cooldown_applied_s : reply.cooldown_remaining_s;
      const deadline = typeof cooldown === 'number' && Number.isFinite(cooldown) && cooldown > 0 ? Date.now() + cooldown * 1000 : 0;
      const settled = this.settleWhenActive(epoch, () => {
        this.actionLocked = reply.success;
        if (reply.success) this.accepted = { action, round: round(data) };
        this.cooldownUntil = deadline;
        const message = reply.message || (reply.success ? 'Заявка принята.' : 'Действие отклонено сервером');
        this.publish({ pending: false, notice: reply.success ? `${message} · Подтверждение смотрим в состоянии сервера.` : message });
      });
      if (settled && reply.success) await this.refresh();
    } catch (error) {
      this.settleWhenActive(epoch, () => {
        this.publish({ pending: false, notice: error instanceof Error ? error.message : 'Результат действия неизвестен' });
      });
    }
  }
}
