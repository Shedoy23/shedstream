import { describe, expect, it, vi } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import { HttpSkillgameTransport, UnknownMutationError } from '../src/skillgames/transport';
import { SkillgameController } from '../src/skillgames/controller';
import { parseSnapshot } from '../src/skillgames/contracts';
import { authOne, deferred } from './fixtures';

import { catalog, empty, resumed, session } from './skillgame-fixtures';
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const auth = () => { const store = new TwitchAuthStore(); store.authorize(authOne); return store; };
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

describe('skillgame HTTP contract', () => {
  it('uses latest JWT; sends server version and one request ID without identity or score', async () => {
    const store = auth(); const fetcher = vi.fn().mockResolvedValue(response({ success: true, session }));
    const transport = new HttpSkillgameTransport('', store, fetcher, () => 'request-one');
    store.authorize({ ...authOne, token: 'rotated' });
    await transport.mutate('action', { session_id: 'one', version: 0, action: 'open', cell: 8 });
    const [, options] = fetcher.mock.calls[0];
    expect(options.headers['X-Twitch-JWT']).toBe('rotated');
    expect(JSON.parse(options.body)).toEqual({ session_id: 'one', version: 0, action: 'open', cell: 8, request_id: 'request-one' });
  });
  it('blocks duplicate clicks; uncertain retries keep exact body and request ID', async () => {
    const request = deferred<Response>(); const fetcher = vi.fn().mockReturnValueOnce(request.promise).mockResolvedValue(response({ success: true, session }));
    const transport = new HttpSkillgameTransport('', auth(), fetcher, () => 'same-id');
    const pending = transport.mutate('action', { session_id: 'one', version: 0, action: 'open', cell: 8 });
    await expect(transport.mutate('action', { session_id: 'one', version: 0, action: 'open', cell: 9 })).rejects.toThrow();
    request.reject(new Error('lost response'));
    await expect(pending).rejects.toBeInstanceOf(UnknownMutationError);
    await expect(transport.mutate('start', { game_type: 'minesweeper', mode: 'ranked', difficulty: 'beginner' })).rejects.toThrow();
    await transport.retry();
    expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body);
  });
  it('preserves unfamiliar refusal code and text without replaying stale moves', async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ success: false, reason: 'new_future_reason', message: 'Сервер объяснил отказ' }, 409));
    const transport = new HttpSkillgameTransport('', auth(), fetcher);
    expect(await transport.mutate('action', { session_id: 'one', version: 0, action: 'open', cell: 8 })).toMatchObject({ reason: 'new_future_reason', message: 'Сервер объяснил отказ' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('rejects malformed state instead of enabling moves with missing rules or board', () => {
    expect(() => parseSnapshot({ ...resumed, active_session: { ...session, state: { rows: -1, cols: 6 } } })).toThrow();
    expect(() => parseSnapshot({ ...empty, catalog: [{ ...catalog[0], board: { rows: 0, cols: 6 } }] })).toThrow();
    expect(parseSnapshot({ ...empty, catalog: [...catalog, { ...catalog[0], game_type: 'future-game' }] }).catalog).toHaveLength(2);
  });
});

describe('skillgame controller lifecycle', () => {
  it('restores authoritative active session on initial load and never cancels on panel close', async () => {
    const transport = { read: vi.fn().mockResolvedValue(resumed), mutate: vi.fn(), retry: vi.fn(), hasUncertain: () => false };
    const controller = new SkillgameController(transport, auth()); controller.start(); await flush();
    expect(controller.snapshot().data?.active_session?.id).toBe('one');
    controller.stop(); expect(transport.mutate).not.toHaveBeenCalled();
  });
  it('suppresses old identity reads and settles a slow poll without aborting it every cadence', async () => {
    const old = deferred<typeof resumed>(); const next = deferred<typeof empty>(); const store = auth();
    const transport = { read: vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise), mutate: vi.fn(), retry: vi.fn(), hasUncertain: () => false };
    const controller = new SkillgameController(transport, store); controller.start();
    await controller.refresh(); await controller.refresh(); expect(transport.read).toHaveBeenCalledTimes(1);
    store.authorize({ ...authOne, userId: 'other-viewer' });
    old.resolve(resumed); next.resolve(empty); await flush();
    expect(controller.snapshot().data?.active_session).toBeNull();
    controller.stop();
  });
  it('double submit creates one command and stale refusal triggers a state read', async () => {
    const pending = deferred<{ success: false; reason: string; message: string }>();
    const transport = { read: vi.fn().mockResolvedValue(resumed), mutate: vi.fn().mockReturnValue(pending.promise), retry: vi.fn(), hasUncertain: () => false };
    const controller = new SkillgameController(transport, auth()); controller.start(); await flush();
    const first = controller.submit('action', { session_id: 'one', version: 0, action: 'open', cell: 8 });
    await controller.submit('action', { session_id: 'one', version: 0, action: 'open', cell: 9 });
    pending.resolve({ success: false, reason: 'stale_version', message: 'Обновите поле' }); await first;
    expect(transport.mutate).toHaveBeenCalledTimes(1); expect(transport.read.mock.calls.length).toBeGreaterThan(1);
    expect(controller.snapshot().notice).toContain('stale_version'); controller.stop();
  });
});
