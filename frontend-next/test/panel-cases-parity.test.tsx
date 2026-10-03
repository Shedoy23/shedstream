import { act, cleanup, render } from '@testing-library/preact';
import { afterEach, expect, it, vi } from 'vitest';
import { createLegacyHarness, legacyResponses, type LegacyRequest, type LegacyFixture } from './panel-legacy-harness';
import { CasesView } from '../src/common/CasesView';
import { ViewerClient } from '../src/common/client';
import { CommonView } from '../src/common/CommonView';
import { TwitchAuthStore } from '../src/auth';
import type { IdentityBootstrap } from '../src/skillgames/identity';
const pending: (() => void)[] = [];
afterEach(() => { cleanup(); pending.splice(0).forEach(f => f()); vi.useRealTimers(); vi.unstubAllGlobals(); });
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const list = { success: true, cases: [{ id: 71, tier: 'rare', source: 'quest', opened_at: null }], unopened_counts: { rare: 2, total: 2 }, lifetime_count: 5 };
const preview = { success: true, tiers: [{ tier: 'rare', label: 'Серверный редкий', color: '#3b82f6', reward_points: 1234 }] };
async function pair(refused = false) {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  const trace: LegacyRequest[] = [];
  const routes: Record<string, LegacyFixture> = {
    'GET /api/viewer/cases': list, 'GET /api/case/preview': preview,
    'POST /api/viewer/case/open': refused ? { success: false, message: 'Кейс уже открыт' } : { success: true, tier: 'rare', reward_points: 1234, new_balance: 8888, message: 'Открыт' },
    'POST /api/viewer/cases/open-all': { success: true, opened: 2, total_reward: 2468, left: 1, message: 'Остался 1 — нажми ещё раз.' },
    'GET /api/viewer/stats/alice': { ...legacyResponses.stats, active_module: null }, 'GET /api/user/level/alice': legacyResponses.level, 'GET /api/duel/list': legacyResponses.duels,
  };
  const old = createLegacyHarness({ stats: { ...legacyResponses.stats, active_module: null } }, { commonHost: true, extraRoutes: routes }); pending.push(old.dispose);
  const fetcher: typeof fetch = async (input, init = {}) => {
    const u = new URL(String(input), 'https://fixture.invalid'), h = new Headers(init.headers), rawBody = init.body == null ? null : String(init.body);
    trace.push({ method: init.method || 'GET', path: u.pathname, query: u.search, rawBody, body: rawBody ? JSON.parse(rawBody) : null, token: h.get('X-Twitch-JWT') || '', contentType: h.get('Content-Type') || '', cache: init.cache || null });
    const data = routes[`${init.method || 'GET'} ${u.pathname}${u.search}`]; if (data === undefined) throw new Error('Unmatched route ' + u.pathname);
    return new Response(JSON.stringify(data));
  };
  const client = new ViewerClient({ login: 'alice', token: 'alice-token', channelId: '123' }, '', fetcher);
  pending.push(() => client.dispose());
  await old.openCommon('openCasesModal');
  const ui = render(<CasesView client={client} />); await act(flush);
  return { old, ui, trace, async click(oldSelector: string, label: string) { await old.click(oldSelector); await act(async () => { ui.getByRole('button', { name: label }).click(); await flush(); }); }, async advance(ms: number) { await old.advance(ms); await act(async () => { await vi.advanceTimersByTimeAsync(ms); await flush(); }); }, check() { expect(trace).toEqual(old.trace); } };
}
it('cases opening keeps exact request body and all 400/700ms balance and list tails', async () => {
  const p = await pair(); p.check(); expect(p.ui.getByText('Серверный редкий')).toBeTruthy();
  await p.click('[data-open-case-id="71"]', 'Открыть кейс 71'); p.check();
  await p.advance(399); p.check(); await p.advance(301); p.check();
  expect(p.trace.filter(q => q.path === '/api/viewer/cases')).toHaveLength(2);
});
it('cases open-all sends no body and keeps the immediate list plus delayed balance refresh', async () => {
  const p = await pair(); await p.click('#cases-open-all-btn', 'Открыть все (2)'); await p.advance(700); p.check();
  expect(p.ui.getByRole('status').textContent).toContain('Остался 1');
});
it('cases refusal remains visible without false-success continuation', async () => {
  const p = await pair(true); await p.click('[data-open-case-id="71"]', 'Открыть кейс 71'); await p.advance(700); p.check();
  expect(p.ui.getByRole('status').textContent).toContain('Кейс уже открыт');
});
it('closing cases cancels delayed reads from that component', async () => {
  const p = await pair(); await p.click('[data-open-case-id="71"]', 'Открыть кейс 71'); const count = p.trace.length;
  p.ui.unmount(); await act(async () => { await vi.advanceTimersByTimeAsync(700); }); expect(p.trace).toHaveLength(count);
});
it('lazy cases mount retains a usable viewer client after Suspense restores the section', async () => {
  const auth = new TwitchAuthStore(); auth.authorize({ token: 'fixture-only', userId: 'u', channelId: '123' });
  const gate = { status: 'ready', login: 'alice' };
  const identity = { subscribe: () => () => {}, snapshot: () => gate } as unknown as IdentityBootstrap;
  const fetcher = vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith('/preview') ? preview : list)));
  vi.stubGlobal('fetch', fetcher);
  const ui = render(<CommonView auth={auth} identity={identity} />);
  await act(async () => { ui.getByRole('button', { name: 'Кейсы' }).click(); await import('../src/common/CasesView'); await flush(); });
  expect(await ui.findByRole('button', { name: 'Открыть кейс 71' })).toBeTruthy();
  expect(fetcher.mock.calls.map(([path]) => path)).toEqual(['/api/viewer/cases', '/api/case/preview']);
});
it('viewer client calls browser fetch without a foreign receiver and fences stale identity writes', async () => {
  let current = true, requests = 0;
  const nativeLike: typeof fetch = async function(this: unknown) { expect(this).toBeUndefined(); requests++; return new Response('{}'); };
  const client = new ViewerClient({ login: 'alice', token: 'fixture', channelId: '123' }, '', nativeLike, () => current);
  await client.read('/fixture'); await client.post('/fixture', {}); current = false;
  await expect(client.post('/fixture', {})).rejects.toThrow('Личность Twitch изменилась');
  expect(requests).toBe(2);
});
