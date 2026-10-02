import { type ActionReply, type TournamentAction, type TournamentSnapshot, type TournamentTransport, isRecord, isSnapshot } from './contracts';
import { TwitchAuthStore } from './auth';

function messageOf(body: unknown): string | undefined {
  if (!isRecord(body)) return undefined;
  if (typeof body.message === 'string') return body.message;
  if (isRecord(body.detail) && typeof body.detail.message === 'string') return body.detail.message;
  return typeof body.detail === 'string' ? body.detail : undefined;
}

const unknownMessage = 'Результат запроса неизвестен. Повторная отправка заблокирована; проверьте состояние турнира.';

// Separate from React and legacy ShedLink.buyAction. Not mounted in the preview.
// A future host must keep one instance per view owner, never run both dispatchers.
export class HttpTournamentTransport implements TournamentTransport {
  private locks = new Map<string, 'pending' | 'unknown'>();
  constructor(
    private readonly baseUrl: string,
    private readonly auth: TwitchAuthStore,
    private readonly fetcher: typeof fetch = fetch,
    private readonly newId: () => string = () => crypto.randomUUID(),
  ) {}
  private authorization() {
    const current = this.auth.current();
    if (!current?.token) throw new Error('Нужна авторизация Twitch');
    return current;
  }
  async read(signal: AbortSignal): Promise<TournamentSnapshot> {
    const token = this.authorization().token;
    const response = await this.fetcher(`${this.baseUrl}/api/bannerlord/tournament`, {
      headers: { 'X-Twitch-JWT': token }, signal,
    });
    const body: unknown = await response.json();
    if (!response.ok || (isRecord(body) && body.success === false)) {
      throw new Error(messageOf(body) || `Ошибка HTTP ${response.status}`);
    }
    if (!isSnapshot(body)) throw new Error('Неизвестный формат ответа турнира');
    return body;
  }
  async act(action: TournamentAction): Promise<ActionReply> {
    const current = this.authorization(); // Read at call time, never capture initial token.
    const key = JSON.stringify([current.channelId, current.userId]);
    const lock = this.locks.get(key);
    if (lock) throw new Error(lock === 'unknown' ? unknownMessage : 'Предыдущее действие ещё выполняется');
    // One tournament mutation per identity, including different prediction targets.
    // Allocate UUID before acquiring a lock: local crypto failure means nothing sent.
    const clientActionId = this.newId();
    this.locks.set(key, 'pending');
    try {
      const response = await this.fetcher(`${this.baseUrl}/api/bannerlord/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': current.token },
        body: JSON.stringify({ action_type: action.action_type, data: { ...action.data, client_action_id: clientActionId } }),
      });
      const body: unknown = await response.json();
      // FastAPI auth/rate-limit rejection happens before the action handler.
      if (!response.ok && response.status < 500 && isRecord(body) && body.detail && messageOf(body)) {
        this.locks.delete(key);
        return { ...body, success: false, message: messageOf(body) };
      }
      if (!isRecord(body) || typeof body.success !== 'boolean' || (!response.ok && body.success)) throw new Error(unknownMessage);
      this.locks.delete(key);
      return body as ActionReply; // Keep unfamiliar refusal text and server metadata intact.
    } catch {
      // A timeout, abort or malformed response cannot prove that no action happened.
      // No retry, no new UUID, no lock release on token rotation. A read is safe.
      this.locks.set(key, 'unknown');
      throw new Error(unknownMessage);
    }
  }
}
