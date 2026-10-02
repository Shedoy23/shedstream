import { describe, expect, it, vi } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import { HttpTournamentTransport } from '../src/transport';
import { authOne, deferred, idle } from './fixtures';

function setup() {
  const auth = new TwitchAuthStore();
  auth.authorize(authOne);
  const fetcher = vi.fn<typeof fetch>();
  const transport = new HttpTournamentTransport('/test-ebs', auth, fetcher, () => 'fixed-client-id');
  return { auth, fetcher, transport };
}
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe('verified EBS boundary', () => {
  it('reads the latest Twitch token for every request, including after rotation', async () => {
    const { auth, fetcher, transport } = setup();
    fetcher.mockResolvedValue(response(idle));
    await transport.read(new AbortController().signal);
    auth.authorize({ ...authOne, token: 'rotated-token' });
    fetcher.mockResolvedValue(response(idle));
    await transport.read(new AbortController().signal);
    expect(fetcher.mock.calls[0][1]?.headers).toEqual({ 'X-Twitch-JWT': 'first-token' });
    expect(fetcher.mock.calls[1][1]?.headers).toEqual({ 'X-Twitch-JWT': 'rotated-token' });
  });
  it('forwards cancellation and uses the exact existing GET route', async () => {
    const { transport, fetcher } = setup();
    fetcher.mockResolvedValue(response(idle));
    const signal = new AbortController().signal;
    await expect(transport.read(signal)).resolves.toEqual(idle);
    expect(fetcher).toHaveBeenCalledWith('/test-ebs/api/bannerlord/tournament', expect.objectContaining({ signal }));
  });
  it('does not send any request without authorization', async () => {
    const { auth, transport, fetcher } = setup();
    auth.clear();
    await expect(transport.read(new AbortController().signal)).rejects.toThrow('Twitch');
    await expect(transport.act({ action_type: 'hero.join_tournament', data: { price: 0 } })).rejects.toThrow('Twitch');
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('sends exact action contract with client_action_id and the fresh token', async () => {
    const { auth, transport, fetcher } = setup();
    auth.authorize({ ...authOne, token: 'fresh-token' });
    fetcher.mockResolvedValue(response({ success: true, message: 'Принято сервером', action_id: '0123456789abcdef0123456789abcdef' }));
    await transport.act({ action_type: 'tournament.predict', data: { target: 'viewer_one' } });
    expect(fetcher).toHaveBeenCalledWith('/test-ebs/api/bannerlord/action', expect.objectContaining({
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': 'fresh-token' },
      body: JSON.stringify({ action_type: 'tournament.predict', data: { target: 'viewer_one', client_action_id: 'fixed-client-id' } }),
    }));
  });
  it('suppresses simultaneous duplicate and alternate-target submissions', async () => {
    const { transport, fetcher } = setup();
    const pending = deferred<Response>();
    fetcher.mockReturnValue(pending.promise);
    const first = transport.act({ action_type: 'tournament.predict', data: { target: 'viewer_one' } });
    await expect(transport.act({ action_type: 'tournament.predict', data: { target: 'someone_else' } })).rejects.toThrow('выполняется');
    expect(fetcher).toHaveBeenCalledTimes(1);
    pending.resolve(response({ success: true }));
    await first;
  });
  it('preserves an unknown outcome and never automatically retries a POST', async () => {
    const { transport, fetcher } = setup();
    fetcher.mockRejectedValue(new TypeError('connection lost after server commit'));
    const action = { action_type: 'hero.join_tournament' as const, data: { price: 0 as const } };
    await expect(transport.act(action)).rejects.toThrow('неизвестен');
    await expect(transport.act(action)).rejects.toThrow('неизвестен');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('retains an uncertain lock when Twitch rotates the same viewer token', async () => {
    const { auth, transport, fetcher } = setup();
    fetcher.mockRejectedValue(new TypeError('lost'));
    const action = { action_type: 'hero.join_tournament' as const, data: { price: 0 as const } };
    await expect(transport.act(action)).rejects.toThrow();
    auth.authorize({ ...authOne, token: 'rotated-token' });
    await expect(transport.act(action)).rejects.toThrow('неизвестен');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('preserves unfamiliar server refusal text and metadata, including HTTP errors', async () => {
    const { transport, fetcher } = setup();
    const refusal = { success: false, message: 'Новая причина от сервера <script>', reason: 'future_rule', cooldown_remaining_s: 9, required_role: 'moderator' };
    fetcher.mockResolvedValue(response(refusal, 403));
    await expect(transport.act({ action_type: 'hero.join_tournament', data: { price: 0 } })).resolves.toEqual(refusal);
    fetcher.mockResolvedValue(response(refusal, 403));
    await expect(transport.read(new AbortController().signal)).rejects.toThrow(refusal.message);
  });
  it('preserves nested FastAPI auth/rate-limit messages without inventing a result', async () => {
    const { transport, fetcher } = setup();
    const refusal = { detail: { status: 'rate_limited', message: 'Подождите, слишком много запросов', channel_id: 123 } };
    fetcher.mockResolvedValue(response(refusal, 429));
    await expect(transport.read(new AbortController().signal)).rejects.toThrow(refusal.detail.message);
    fetcher.mockResolvedValue(response(refusal, 429));
    await expect(transport.act({ action_type: 'hero.join_tournament', data: { price: 0 } })).resolves.toEqual({ success: false, message: refusal.detail.message, detail: refusal.detail });
  });
  it('rejects malformed read bodies rather than displaying plausible empty state', async () => {
    const { transport, fetcher } = setup();
    fetcher.mockResolvedValue(response({ success: true, state: {}, queue: 'not-a-list' }));
    await expect(transport.read(new AbortController().signal)).rejects.toThrow('формат');
  });
  it('treats a non-JSON POST response as uncertain and keeps the lock', async () => {
    const { transport, fetcher } = setup();
    fetcher.mockResolvedValue(new Response('<html>proxy error</html>', { status: 502 }));
    const action = { action_type: 'hero.join_tournament' as const, data: { price: 0 as const } };
    await expect(transport.act(action)).rejects.toThrow('неизвестен');
    await expect(transport.act(action)).rejects.toThrow('неизвестен');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe('Twitch helper lifecycle', () => {
  it('updates each authorization callback and ignores callbacks after detach', () => {
    let callback!: (auth: typeof authOne) => void;
    const store = new TwitchAuthStore();
    const detach = store.attach({ onAuthorized: fn => { callback = fn; } });
    callback(authOne);
    expect(store.current()?.token).toBe('first-token');
    callback({ ...authOne, token: 'second-token' });
    expect(store.current()?.token).toBe('second-token');
    detach();
    callback({ ...authOne, token: 'obsolete' });
    expect(store.current()).toBeNull();
  });
});
