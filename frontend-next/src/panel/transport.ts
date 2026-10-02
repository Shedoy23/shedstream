import { TwitchAuthStore } from '../auth';
import { isRecord } from '../contracts';
import { requestJson } from '../skillgames/http';
import { actionKey, type ActionReply, type PanelTransport } from './contracts';
export class HttpPanelTransport implements PanelTransport {
  private inflight = new Set<string>();
  constructor(private readonly baseUrl: string, private readonly auth: TwitchAuthStore, private readonly fetcher: typeof fetch = fetch, private readonly newId: () => string = () => crypto.randomUUID()) {}
  private authorization() { const value = this.auth.current(); if (!value?.token) throw new Error('Нужна авторизация Twitch'); return { ...value }; }
  async read<T>(path: string, signal?: AbortSignal): Promise<T> {
    if (!path.startsWith('/api/')) throw new Error('Недопустимый путь API');
    const authorization = this.authorization();
    const { response, body } = await requestJson(this.fetcher, this.baseUrl + path, { headers: { 'X-Twitch-JWT': authorization.token }, signal, ...((path.startsWith('/api/viewer/stats/') || path === '/api/bannerlord/config') ? { cache: 'no-store' as const } : {}) });
    if (!response.ok || !isRecord(body) || body.success === false) {
      throw new Error(isRecord(body) && typeof body.message === 'string' ? body.message : `Ошибка сервера (${response.status})`);
    }
    return body as T;
  }
  async action(type: string, data: Record<string, unknown>): Promise<ActionReply | null> {
    // Snapshot once. A token rotation must not change an already admitted request.
    const authorization = this.authorization();
    const key = JSON.stringify([authorization.channelId, authorization.userId]) + ':' + actionKey(type, data);
    if (this.inflight.has(key)) return null;
    this.inflight.add(key);
    try {
      const { response, body } = await requestJson(this.fetcher, this.baseUrl + '/api/bannerlord/action', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authorization.token },
        body: JSON.stringify({ action_type: type, data: { ...data, client_action_id: this.newId() } }),
      });
      if (!isRecord(body) || typeof body.success !== 'boolean') throw new Error(`Ошибка ответа сервера (${response.status})`);
      return body as ActionReply;
    } finally { this.inflight.delete(key); }
  }
}
