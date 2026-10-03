import { TwitchAuthStore, type TwitchAuthorization, type TwitchHelper } from '../auth';
import { isRecord } from '../contracts';
import { requestJson } from './http';
export interface IdentityHelper extends TwitchHelper { environment?: string; actions?: { requestIdShare?: () => void } }
export interface IdentityState { login?: string; status: 'waiting' | 'resolving' | 'ready' | 'blocked'; message: string; canShare: boolean; shareRequested: boolean }
const scope = (auth: TwitchAuthorization | null) => JSON.stringify([auth?.channelId, auth?.userId]);
// Only the server resolves identity. The full panel protocol forwards the old
// untrusted numeric JWT hint to that resolver; it never grants client authority.
export class IdentityBootstrap {
  private state: IdentityState = { status: 'waiting', message: 'Откройте расширение на Twitch. Ждём авторизацию платформы.', canShare: false, shareRequested: false };
  private listeners = new Set<() => void>(); private generation = 0; private abort?: AbortController;
  private latest: TwitchAuthorization | null = null; private helper?: IdentityHelper; private active = false;
  constructor(private readonly auth: TwitchAuthStore, private readonly baseUrl: string, private readonly fetcher: typeof fetch = fetch, private readonly options: { panelProtocol?: boolean } = {}) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private publish(patch: Partial<IdentityState>) { this.state = { ...this.state, ...patch }; this.listeners.forEach(fn => fn()); }
  attach(helper: IdentityHelper) {
    this.helper = helper; this.active = true;
    this.publish({ canShare: typeof helper.actions?.requestIdShare === 'function' });
    helper.onAuthorized(authorization => { if (this.active) void this.resolve(authorization); });
    return () => { this.active = false; this.generation++; this.abort?.abort(); this.auth.clear(); this.publish({ status: 'waiting', login: undefined }); };
  }
  async retry() { if (this.active && this.latest && this.state.status !== 'resolving') await this.resolve(this.latest); }
  requireResolution(message: string) { this.generation++; this.abort?.abort(); this.auth.clear(); this.publish({ login: undefined, status: 'blocked', message }); }
  requestShare() {
    if (!this.state.canShare || this.state.status === 'resolving' || this.state.shareRequested) return;
    // This method is wired only to a deliberate click. Twitch has no denial
    // callback; lack of a new resolved authorization never means consent.
    this.publish({ shareRequested: true, message: 'Подтвердите передачу ID в окне Twitch. Если вы отказались или закрыли окно, игры останутся недоступны.' });
    try { this.helper?.actions?.requestIdShare?.(); }
    catch { this.publish({ shareRequested: false, message: 'Разрешение Twitch не получено. Можно повторить проверку или открыть расширение заново.' }); }
  }
  private async resolve(authorization: TwitchAuthorization) {
    const generation = ++this.generation; this.abort?.abort(); const abort = new AbortController(); this.abort = abort;
    this.latest = { token: authorization.token, channelId: authorization.channelId, userId: authorization.userId, ...(authorization.clientId ? { clientId: authorization.clientId } : {}) };
    // Keep the same viewer's old token solely for already admitted mutations.
    // The host stops polling and blocks commands until this latest resolution.
    if (scope(this.auth.current()) !== scope(authorization)) this.auth.clear();
    this.publish({ login: undefined, status: 'resolving', message: 'Проверяем связь Twitch с игровым сервером…', shareRequested: false });
    try {
      if (!authorization.token || !authorization.userId || !authorization.channelId) throw new Error('Twitch не передал необходимые данные авторизации');
      let hint: string | null = null;
      if (this.options.panelProtocol) {
        try { const encoded = authorization.token.split('.')[1]; const value = JSON.parse(atob(encoded + '='.repeat((4 - encoded.length % 4) % 4))).user_id; if (value) hint = String(value).replace(/^U/, ''); } catch { /* Malformed hints never authorize. */ }
        if (!hint) { this.publish({ login: undefined, status: 'blocked', message: 'Для входа разрешите передачу Twitch ID.' }); return; }
      }
      const { response, body } = await requestJson(this.fetcher, `${this.baseUrl}/api/user/resolve-twitch-token`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: authorization.token, opaque_id: authorization.userId, ...(this.options.panelProtocol ? { user_id: hint && /^\d+$/.test(hint) ? hint : null } : {}) }), signal: abort.signal,
      });
      if (!this.active || generation !== this.generation) return;
      if (!response.ok || !isRecord(body) || typeof body.login !== 'string' || !body.login.trim()) {
        this.publish({ login: undefined, status: 'blocked', message: isRecord(body) && typeof body.error === 'string' ? body.error : 'Сервер пока не подтвердил вашу Twitch-личность. Для игры нужно разрешить передачу Twitch ID.' });
        return;
      }
      this.auth.authorize(this.latest);
      this.publish({ login: body.login, status: 'ready', message: 'Twitch-личность подтверждена сервером', shareRequested: false });
    } catch (error) {
      if (!this.active || generation !== this.generation || abort.signal.aborted) return;
      this.publish({ login: undefined, status: 'blocked', message: error instanceof Error ? error.message : 'Не удалось проверить Twitch-личность. Повторите проверку.' });
    }
  }
}
