import { TwitchAuthStore } from '../auth';
import { isRecord } from '../contracts';
import { parseCatalog, parseSession, parseSnapshot, type Command, type Endpoint, type MutationReply, type SkillgameSnapshot, type SkillgameTransport } from './contracts';
const scope = (auth: TwitchAuthStore) => JSON.stringify([auth.current()?.channelId, auth.current()?.userId]);
type Attempt = { endpoint: Endpoint; body: string; phase: 'pending' | 'uncertain' };
export class UnknownMutationError extends Error {
  constructor() { super('Ответ потерян. Сервер мог принять действие. Обновите состояние или повторите тот же запрос безопасно.'); }
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
  constructor(private readonly baseUrl: string, private readonly auth: TwitchAuthStore, private readonly fetcher: typeof fetch = fetch, private readonly newId: () => string = () => crypto.randomUUID()) {}
  private token() { const token = this.auth.current()?.token; if (!token) throw new Error('Нужна авторизация Twitch'); return token; }
  private async request(url: string, options: RequestInit) {
    const abort = new AbortController();
    let rejectDeadline!: (error: Error) => void;
    const interrupted = new Promise<never>((_, reject) => { rejectDeadline = reject; });
    const onAbort = () => { abort.abort(); rejectDeadline(new Error('Запрос отменён')); };
    options.signal?.addEventListener('abort', onAbort, { once: true });
    const timer = setTimeout(() => { abort.abort(); rejectDeadline(new Error('Сервер не ответил за 20 секунд. Обновите состояние.')); }, 20000);
    if (options.signal?.aborted) onAbort();
    try {
      return await Promise.race([
        this.fetcher(url, { ...options, signal: abort.signal }).then(async response => ({ response, body: await response.json() as unknown })),
        interrupted,
      ]);
    } finally { clearTimeout(timer); options.signal?.removeEventListener('abort', onAbort); }
  }
  async config(signal: AbortSignal) {
    const { response, body } = await this.request(`${this.baseUrl}/api/skillgames/config`, { headers: { 'X-Twitch-JWT': this.token() }, signal });
    if (!response.ok || !isRecord(body) || body.success !== true) throw new Error('Не удалось загрузить правила сервера');
    return { ...body, catalog: parseCatalog(body.catalog) };
  }
  async read(signal: AbortSignal, sessionId?: string): Promise<SkillgameSnapshot> {
    const suffix = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    const { response, body } = await this.request(`${this.baseUrl}/api/skillgames/state${suffix}`, { headers: { 'X-Twitch-JWT': this.token() }, signal });
    const rejected = refusal(body, response.status);
    if (rejected) throw new Error(`${rejected.message} (${rejected.reason})`);
    if (!response.ok) throw new Error(`Ошибка HTTP ${response.status}`);
    return parseSnapshot(body);
  }
  hasUncertain() { return this.attempts.get(scope(this.auth))?.phase === 'uncertain'; }
  async mutate(endpoint: Endpoint, command: Command): Promise<MutationReply> {
    this.token();
    const key = scope(this.auth);
    if (this.attempts.has(key)) throw new Error('Предыдущее действие ещё не завершено');
    const attempt: Attempt = { endpoint, body: JSON.stringify({ ...command, request_id: this.newId() }), phase: 'pending' };
    this.attempts.set(key, attempt);
    return this.send(key, attempt);
  }
  async retry(): Promise<MutationReply> {
    const key = scope(this.auth); const attempt = this.attempts.get(key);
    if (!attempt || attempt.phase !== 'uncertain') throw new Error('Нет запроса для безопасного повтора');
    attempt.phase = 'pending'; return this.send(key, attempt);
  }
  private async send(key: string, attempt: Attempt): Promise<MutationReply> {
    try {
      const { response, body } = await this.request(`${this.baseUrl}/api/skillgames/${attempt.endpoint === 'cancel' ? 'queue/cancel' : attempt.endpoint}`, {
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
