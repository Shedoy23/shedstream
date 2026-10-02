import { TwitchAuthStore } from '../auth';
import { isRecord } from '../contracts';
import { requestJson } from '../skillgames/http';
import { actionKey, UnknownActionOutcomeError, type ActionReply, type PanelTransport } from './contracts';
const newClientActionId = () => typeof globalThis.crypto?.randomUUID === 'function'
  ? globalThis.crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
// Only these exact outer require_jwt_user refusals precede action-body parsing,
// charge and enqueue. A generic 4xx (or a mixed action/policy envelope) proves nothing.
function policyRefusal(status: number, body: unknown, channelId: string, read = false): ActionReply | null {
  if (!isRecord(body) || Object.keys(body).length !== 1 || !isRecord(body.detail)) return null;
  const detail = body.detail;
  if (typeof detail.channel_id !== 'number' || !Number.isSafeInteger(detail.channel_id) || detail.channel_id <= 0
    || String(detail.channel_id) !== channelId || typeof detail.message !== 'string' || !detail.message.trim()) return null;
  const registration = status === 403 && (detail.status === 'channel_not_registered' || detail.status === 'channel_pending_approval');
  const rate = status === 429 && detail.status === 'channel_rate_limited';
  if (!registration && !rate) return null;
  const fields = rate ? ['status', 'channel_id', 'message', 'tier', 'limit_per_min', 'scope'] : ['status', 'channel_id', 'message'];
  if (Object.keys(detail).some(key => !fields.includes(key))) return null;
  if (rate && (typeof detail.tier !== 'string' || !detail.tier.trim()
    || typeof detail.limit_per_min !== 'number' || !Number.isSafeInteger(detail.limit_per_min) || detail.limit_per_min <= 0
    || (detail.scope !== 'channel' && !(read && detail.scope === 'viewer_poll')))) return null;
  // Retry-After belongs to HTTP policy, not a game-action cooldown or retry command.
  return { success: false, message: detail.message };
}
export class HttpPanelTransport implements PanelTransport {
  private inflight = new Set<string>();
  // No automatic retry after an unknown result: the server may already have
  // accepted it. Keep this identity blocked for this transport's lifetime.
  private uncertain = new Set<string>();
  mutationBlock() { const auth = this.auth.current(); return this.uncertain.has(JSON.stringify([auth?.channelId, auth?.userId])) ? new UnknownActionOutcomeError().message : null; }
  constructor(private readonly baseUrl: string, private readonly auth: TwitchAuthStore, private readonly fetcher: typeof fetch = fetch, private readonly newId: () => string = newClientActionId) {}
  private authorization() { const value = this.auth.current(); if (!value?.token) throw new Error('Нужна авторизация Twitch'); return { ...value }; }
  async read<T>(path: string, signal?: AbortSignal): Promise<T> {
    if (!path.startsWith('/api/')) throw new Error('Недопустимый путь API');
    const authorization = this.authorization();
    const { response, body } = await requestJson(this.fetcher, this.baseUrl + path, { headers: { 'X-Twitch-JWT': authorization.token }, signal, ...((path.startsWith('/api/viewer/stats/') || path === '/api/bannerlord/config') ? { cache: 'no-store' as const } : {}) });
    const refusal = policyRefusal(response.status, body, authorization.channelId, true);
    if (refusal) throw new Error(refusal.message);
    if (!response.ok || !isRecord(body) || body.success === false) {
      throw new Error(isRecord(body) && typeof body.message === 'string' ? body.message : `Ошибка сервера (${response.status})`);
    }
    return body as T;
  }
  async action(type: string, data: Record<string, unknown>): Promise<ActionReply | null> {
    // Snapshot once. A token rotation must not change an already admitted request.
    const authorization = this.authorization();
    const identity = JSON.stringify([authorization.channelId, authorization.userId]);
    if (this.uncertain.has(identity)) throw new UnknownActionOutcomeError();
    const key = identity + ':' + actionKey(type, data);
    if (this.inflight.has(key)) return null;
    // A local ID/serialization failure happened before any request was sent.
    // It cannot be evidence of an uncertain server-side acceptance.
    const requestBody = JSON.stringify({ action_type: type, data: { ...data, client_action_id: this.newId() } });
    this.inflight.add(key);
    try {
      const { response, body } = await requestJson(this.fetcher, this.baseUrl + '/api/bannerlord/action', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authorization.token },
        body: requestBody,
      });
      if (!Number.isInteger(response.status) || response.status < 200 || response.status >= 500) throw new Error(`Ошибка ответа сервера (${response.status})`);
      const refusal = policyRefusal(response.status, body, authorization.channelId);
      if (refusal) return refusal;
      if (!isRecord(body) || 'detail' in body || typeof body.success !== 'boolean') throw new Error(`Ошибка ответа сервера (${response.status})`);
      return body as ActionReply;
    } catch {
      this.uncertain.add(identity);
      throw new UnknownActionOutcomeError();
    } finally { this.inflight.delete(key); }
  }
}
