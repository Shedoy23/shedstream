import { requestJson } from './http';
import { TwitchAuthStore } from '../auth';
import { isRecord } from '../contracts';
import { parseCatalog, parseSession, parseSnapshot, type Command, type Endpoint, type MutationReply, type SkillgameSnapshot, type SkillgameTransport } from './contracts';
const scope = (auth: TwitchAuthStore) => JSON.stringify([auth.current()?.channelId, auth.current()?.userId]);
type Attempt = { endpoint: Endpoint; body: string; phase: 'pending' | 'uncertain'; sentAt: number; retentionMs: number | null };
export class UnknownMutationError extends Error {
  constructor() { super('Ответ потерян. Сервер мог принять действие. Обновите состояние или повторите тот же запрос, пока действует серверный срок защиты.'); }
}
function refusal(body: unknown, status: number): MutationReply | null {
  if (!isRecord(body)) return null;
  const source = isRecord(body.detail) ? body.detail : body;
  const message = typeof source.message === 'string' ? source.message : typeof body.detail === 'string' ? body.detail : undefined;
  if (source.success === false || (status >= 400 && status < 500 && message)) {
    return { ...source, success: false, message: message || 'Действие отклонено сервером', reason: typeof source.reason === 'string' ? source.reason : `HTTP_${status}` };
  }
  return null;
}
// This adapter only sends to its configured origin. No token, ship, mine, or move
// is logged or put in a URL/storage. Retries reuse the EXACT idempotent request.
export class HttpSkillgameTransport implements SkillgameTransport {
  private attempts = new Map<string, Attempt>();
  private retention = new Map<string, number | null>();
  constructor(private readonly baseUrl: string, private readonly auth: TwitchAuthStore, private readonly fetcher: typeof fetch = fetch, private readonly newId: () => string = () => crypto.randomUUID(), private readonly monotonicClock: () => number = () => performance.now()) {}
  private token() { const token = this.auth.current()?.token; if (!token) throw new Error('Нужна авторизация Twitch'); return token; }
  async config(signal: AbortSignal) {
    const { response, body } = await requestJson(this.fetcher, `${this.baseUrl}/api/skillgames/config`, { headers: { 'X-Twitch-JWT': this.token() }, signal });
    if (!response.ok || !isRecord(body) || body.success !== true) throw new Error('Не удалось загрузить правила сервера');
    return { ...body, catalog: parseCatalog(body.catalog) };
  }
  async read(signal: AbortSignal, sessionId?: string): Promise<SkillgameSnapshot> {
    const key = scope(this.auth);
    const suffix = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    const { response, body } = await requestJson(this.fetcher, `${this.baseUrl}/api/skillgames/state${suffix}`, { headers: { 'X-Twitch-JWT': this.token() }, signal });
    const rejected = refusal(body, response.status);
    if (rejected) throw new Error(`${rejected.message} (${rejected.reason})`);
    if (!response.ok) throw new Error(`Ошибка HTTP ${response.status}`);
    const data = parseSnapshot(body);
    const expired = this.expired(this.attempts.get(key));
    this.retention.set(key, data.request_retention_seconds === undefined ? null : data.request_retention_seconds * 1000);
    // Only a validated, successful state read recovers an expired uncertain
    // request. It never sends another command or invents a replacement UUID.
    if (expired && this.attempts.get(key)?.phase === 'uncertain') this.attempts.delete(key);
    return data;
  }
  private expired(attempt?: Attempt) { return !!attempt && (attempt.retentionMs === null || this.monotonicClock() - attempt.sentAt >= attempt.retentionMs); }
  retryExpired() { const attempt = this.attempts.get(scope(this.auth)); return attempt?.phase === 'uncertain' && this.expired(attempt); }
  hasUncertain() { return this.attempts.get(scope(this.auth))?.phase === 'uncertain'; }
  async mutate(endpoint: Endpoint, command: Command): Promise<MutationReply> {
    this.token();
    const key = scope(this.auth);
    if (this.attempts.has(key)) throw new Error('Предыдущее действие ещё не завершено');
    const attempt: Attempt = { endpoint, body: JSON.stringify({ ...command, request_id: this.newId() }), phase: 'pending', sentAt: this.monotonicClock(), retentionMs: this.retention.get(key) ?? null };
    this.attempts.set(key, attempt);
    return this.send(key, attempt);
  }
  async retry(): Promise<MutationReply> {
    const key = scope(this.auth); const attempt = this.attempts.get(key);
    if (!attempt || attempt.phase !== 'uncertain') throw new Error('Нет запроса для безопасного повтора');
    if (this.expired(attempt)) throw new Error('Срок безопасного повтора истёк или сервер не подтвердил срок. Обновите состояние; новое действие нужно выбрать отдельно.');
    attempt.phase = 'pending'; return this.send(key, attempt);
  }
  private async send(key: string, attempt: Attempt): Promise<MutationReply> {
    try {
      const { response, body } = await requestJson(this.fetcher, `${this.baseUrl}/api/skillgames/${attempt.endpoint === 'cancel' ? 'queue/cancel' : attempt.endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': this.token() }, body: attempt.body,
      });
      const rejected = refusal(body, response.status);
      if (rejected) { this.attempts.delete(key); return rejected; }
      if (!response.ok || !isRecord(body) || body.success !== true) throw new UnknownMutationError();
      if (body.session !== undefined) parseSession(body.session);
      if (body.active_session != null) parseSession(body.active_session);
      this.attempts.delete(key); return body as MutationReply;
    } catch { attempt.phase = 'uncertain'; throw new UnknownMutationError(); }
  }
}
