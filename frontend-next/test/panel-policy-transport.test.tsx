import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/preact';
import { TwitchAuthStore } from '../src/auth';
import { HttpPanelTransport } from '../src/panel/transport';
import { UnknownActionOutcomeError } from '../src/panel/contracts';
import { PanelController } from '../src/panel/controller';
import { HeroDevelopmentView } from '../src/panel/HeroDevelopmentView';
import { IdentityBootstrap } from '../src/skillgames/identity';
import evidence from './panel-fixtures/policy-responses.json';
import heroEvidence from './panel-fixtures/real-responses.json';

// Captured through unchanged main.app ASGI, not an inner action-handler fixture.
const cases = evidence.cases;
const policies = ['unregistered', 'pending', 'rate_limited'] as const;
const json = (body: unknown, status = 200, headers?: HeadersInit) => new Response(JSON.stringify(body), { status, headers });
const captured = (name: keyof typeof cases) => { const r = cases[name].response; return new Response(r.raw_body, { status: r.status, headers: r.headers }); };
const authFor = (name: keyof typeof cases) => ({ ...cases[name].request.identity, token: 'synthetic-first-token' });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { resolve, promise }; };
const flush = async () => { for (let n = 0; n < 30; n++) await Promise.resolve(); };
function setup(name: keyof typeof cases = 'unregistered', reply: () => Promise<Response> = async () => captured(name)) {
  const auth = new TwitchAuthStore(); auth.authorize(authFor(name));
  const fetcher = vi.fn(async (_url: RequestInfo | URL, _options?: RequestInit) => reply());
  let id = 0; const newId = vi.fn(() => `policy-attempt-${++id}`);
  const transport = new HttpPanelTransport('', auth, fetcher, newId);
  return { auth, fetcher, newId, transport };
}
afterEach(() => { cleanup(); vi.useRealTimers(); });

for (const name of policies) {
  it(`${name}: actual policy envelope is definite, preserves exact text, allows only explicit recovered retry`, async () => {
    vi.useFakeTimers();
    let recovered = false;
    const s = setup(name, async () => recovered ? json({ success: true, message: 'Принято', action_id: 'queued-on-manual-retry' }) : captured(name));
    const data = { skill_key: 'OneHanded', amount: 1, client_action_id: 'caller-must-not-own-id' };
    const original = structuredClone(data);
    expect(await s.transport.action('hero.add_focus', data)).toEqual({ success: false, message: cases[name].response.body.detail.message });
    expect(s.transport.mutationBlock()).toBeNull(); expect(data).toEqual(original);
    expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.newId).toHaveBeenCalledTimes(1);
    const first = s.fetcher.mock.calls[0][1]!;
    expect(first.method).toBe('POST'); expect(new Headers(first.headers).get('X-Twitch-JWT')).toBe('synthetic-first-token');
    expect(JSON.parse(String(first.body))).toEqual({ action_type: 'hero.add_focus', data: { ...original, client_action_id: 'policy-attempt-1' } });
    recovered = true; s.auth.authorize({ ...authFor(name), token: 'synthetic-rotated-token' });
    await vi.advanceTimersByTimeAsync(120001);
    expect(s.fetcher).toHaveBeenCalledTimes(1); // Neither Retry-After nor JWT refresh replays a POST.
    expect(await s.transport.action('hero.add_focus', data)).toEqual({ success: true, message: 'Принято', action_id: 'queued-on-manual-retry' });
    expect(s.fetcher).toHaveBeenCalledTimes(2); expect(s.transport.mutationBlock()).toBeNull();
    const second = s.fetcher.mock.calls[1][1]!;
    expect(new Headers(second.headers).get('X-Twitch-JWT')).toBe('synthetic-rotated-token');
    expect(JSON.parse(String(second.body)).data.client_action_id).toBe('policy-attempt-2');
    expect(new Headers(first.headers).get('X-Twitch-JWT')).toBe('synthetic-first-token');
    expect(JSON.parse(String(first.body)).data).toEqual({ ...original, client_action_id: 'policy-attempt-1' });
  });
  it(`${name}: read keeps the exact known policy message without blocking mutations`, async () => {
    const s = setup(name);
    await expect(s.transport.read('/api/bannerlord/my-hero')).rejects.toThrow(cases[name].response.body.detail.message);
    expect(s.transport.mutationBlock()).toBeNull(); expect(s.fetcher).toHaveBeenCalledTimes(1);
  });
}

it('does not whitelist, trim, interpret or replace new server refusal text', async () => {
  const message = '  Новый отказ сервера: <em>не разметка</em> & другой срок 17 секунд.  ';
  const s = setup('pending', async () => json({ detail: { ...cases.pending.response.body.detail, message } }, 403));
  expect(await s.transport.action('hero.army_create', {})).toEqual({ success: false, message });
  await expect(s.transport.read('/api/bannerlord/my-hero')).rejects.toThrow(message);
});

it('uses captured authorization and frozen body while caller data, JWT, viewer and channel change in flight', async () => {
  const pending = deferred<Response>(); const s = setup('pending', () => pending.promise);
  const data = { amount: 1, nested: { target: 'original' } };
  const request = s.transport.action('hero.army_create', data);
  data.amount = 99; data.nested.target = 'changed';
  s.auth.current()!.channelId = '999'; s.auth.current()!.token = 'mutated-store-token';
  s.auth.authorize({ channelId: '333', userId: 'other-viewer', token: 'other-token' });
  pending.resolve(captured('pending'));
  expect(await request).toEqual({ success: false, message: cases.pending.response.body.detail.message });
  const options = s.fetcher.mock.calls[0][1]!;
  expect(new Headers(options.headers).get('X-Twitch-JWT')).toBe('synthetic-first-token');
  expect(JSON.parse(String(options.body))).toEqual({ action_type: 'hero.army_create', data: { amount: 1, nested: { target: 'original' }, client_action_id: 'policy-attempt-1' } });
  expect(s.transport.mutationBlock()).toBeNull();
  s.auth.authorize(authFor('pending')); expect(s.transport.mutationBlock()).toBeNull();
});

it('read classifies against its admitted channel even if the current channel switches', async () => {
  const pending = deferred<Response>(); const s = setup('pending', () => pending.promise);
  const read = s.transport.read('/api/bannerlord/my-hero'); const result = expect(read).rejects.toThrow(cases.pending.response.body.detail.message);
  s.auth.authorize({ channelId: '333', userId: 'other', token: 'other-token' });
  pending.resolve(captured('pending')); await result;
  expect(new Headers(s.fetcher.mock.calls[0][1]?.headers).get('X-Twitch-JWT')).toBe('synthetic-first-token');
});

const detail = cases.unregistered.response.body.detail;
const rate = cases.rate_limited.response.body.detail;
const invalid: { name: string; status: number; body: unknown }[] = [
  ...[200, 201, 301, 401, 404, 409, 422, 429, 500, 503].map(status => ({ name: `registration with HTTP ${status}`, status, body: { detail } })),
  ...[200, 403, 404, 500, 503].map(status => ({ name: `rate limit with HTTP ${status}`, status, body: { detail: { ...rate, channel_id: 33 } } })),
  ...[0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, '33', null, undefined, true, {}, 22].map(channel_id => ({ name: `invalid/mismatched channel ${JSON.stringify(channel_id)}`, status: 403, body: { detail: { ...detail, channel_id } } })),
  ...['', ' \n\t ', null, undefined, 22, {}, []].map(message => ({ name: `invalid message ${JSON.stringify(message)}`, status: 403, body: { detail: { ...detail, message } } })),
  ...['different_policy', '', null, 403].map(status => ({ name: `unknown policy ${JSON.stringify(status)}`, status: 403, body: { detail: { ...detail, status } } })),
  ...[null, [], 'Forbidden', { message: 'Forbidden' }, { detail: [] }, { detail: null }, { success: 'false' }].map((body, n) => ({ name: `unknown/malformed JSON ${n}`, status: 403, body })),
  ...[{ success: true }, { success: false }, { success: 'false' }, { action_id: 'accepted' }, { charged: 5 }, { message: 'contradictory top level' }].map(extra => ({ name: `mixed policy/action ${JSON.stringify(extra)}`, status: 403, body: { detail, ...extra } })),
  ...[{ success: true, action_id: 'accepted' }, { success: false, message: 'No' }].map(body => ({ name: `5xx with action envelope ${body.success}`, status: 500, body })),
  { name: 'rate quota wrong scope', status: 429, body: { detail: { ...rate, channel_id: 33, scope: 'viewer_poll' } } },
  { name: 'rate quota blank tier', status: 429, body: { detail: { ...rate, channel_id: 33, tier: '' } } },
  { name: 'rate quota invalid limit', status: 429, body: { detail: { ...rate, channel_id: 33, limit_per_min: -1 } } },
  { name: 'nested contradictory action', status: 403, body: { detail: { ...detail, action_id: 'accepted' } } },
];
for (const { name, status, body } of invalid) it(`uncertain boundary: ${name} keeps identity lock across JWT rotation and never reposts`, async () => {
  const s = setup('unregistered', async () => json(body, status));
  await expect(s.transport.action('hero.army_create', {})).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  expect(s.transport.mutationBlock()).toContain('Исход предыдущей заявки неизвестен');
  s.auth.authorize({ ...authFor('unregistered'), token: 'rotated' });
  await expect(s.transport.action('hero.add_focus', { amount: 2 })).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.newId).toHaveBeenCalledTimes(1);
});

for (const channel_id of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) it(`rejects invalid numeric response channel even when its string matches authorization: ${channel_id}`, async () => {
  const s = setup('unregistered', async () => json({ detail: { ...detail, channel_id } }, 403));
  s.auth.authorize({ ...authFor('unregistered'), channelId: String(channel_id) });
  await expect(s.transport.action('hero.army_create', {})).rejects.toBeInstanceOf(UnknownActionOutcomeError);
});
it('accepts a canonical safe-integer channel boundary without a local ID allowlist', async () => {
  const channel_id = Number.MAX_SAFE_INTEGER;
  const s = setup('unregistered', async () => json({ detail: { ...detail, channel_id } }, 403));
  s.auth.authorize({ ...authFor('unregistered'), channelId: String(channel_id) });
  expect(await s.transport.action('hero.army_create', {})).toEqual({ success: false, message: detail.message });
});
for (const extra of [{ limit_per_min: 1.5 }, { limit_per_min: '6000' }, { limit_per_min: null }, { limit_per_min: 0 }, { limit_per_min: Number.MAX_SAFE_INTEGER + 1 }, { tier: null }, { tier: 4 }, { scope: 'unknown' }]) it(`malformed rate metadata is not normalized: ${JSON.stringify(extra)}`, async () => {
  const s = setup('rate_limited', async () => json({ detail: { ...rate, ...extra } }, 429));
  await expect(s.transport.action('hero.army_create', {})).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  await expect(s.transport.read('/api/bannerlord/my-hero')).rejects.toThrow('Ошибка сервера (429)');
});
it('rate metadata may use a future nonempty server tier and an arbitrary positive quota', async () => {
  const s = setup('rate_limited', async () => json({ detail: { ...rate, tier: 'new-server-tier', limit_per_min: 7 } }, 429, { 'Retry-After': '17' }));
  expect(await s.transport.action('hero.army_create', {})).toEqual({ success: false, message: rate.message });
});

for (const channelId of ['033', ' 33', '33 ', '+33', '3.3e1', '', 'unknown']) it(`does not coerce ambiguous authorization channel ${JSON.stringify(channelId)}`, async () => {
  const s = setup(); s.auth.authorize({ ...authFor('unregistered'), channelId });
  await expect(s.transport.action('hero.army_create', {})).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  expect(s.fetcher).toHaveBeenCalledTimes(1);
});

for (const name of ['expired', 'missing'] as const) it(`${name}: existing real top-level auth refusal stays definite`, async () => {
  const s = setup(name);
  expect(await s.transport.action('hero.army_create', {})).toEqual(cases[name].response.body);
  expect(s.transport.mutationBlock()).toBeNull();
  expect(await s.transport.action('hero.army_create', {})).toEqual(cases[name].response.body);
  expect(s.fetcher).toHaveBeenCalledTimes(2);
});
it('preserves ordinary top-level success:false plus server-owned fields', async () => {
  const reply = { success: false, message: 'Новый обычный отказ', cooldown_remaining_s: 44, reason: 'new_reason' };
  const s = setup('unregistered', async () => json(reply));
  expect(await s.transport.action('hero.add_focus', {})).toEqual(reply); expect(s.transport.mutationBlock()).toBeNull();
});
it('a locally absent JWT rejects before any fetch or unknown lock', async () => {
  const s = setup(); s.auth.clear();
  await expect(s.transport.action('hero.army_create', {})).rejects.toThrow('Нужна авторизация Twitch');
  expect(s.fetcher).not.toHaveBeenCalled(); s.auth.authorize(authFor('unregistered')); expect(s.transport.mutationBlock()).toBeNull();
});
for (const status of [0, undefined, NaN, 199, 600]) it(`invalid response status ${String(status)} is uncertain even with success:false`, async () => {
  const s = setup('unregistered', async () => ({ status, json: async () => ({ success: false, message: 'No' }) }) as Response);
  await expect(s.transport.action('hero.army_create', {})).rejects.toBeInstanceOf(UnknownActionOutcomeError);
});
for (const [name, reply] of [
  ['non-JSON HTML', async () => new Response('<html>proxy</html>', { status: 403 })],
  ['fetch rejection', async () => { throw new TypeError('network lost'); }],
  ['fetch abort', async () => { throw new DOMException('aborted', 'AbortError'); }],
  ['lost JSON body', async () => ({ status: 429, json: async () => { throw new Error('lost body'); } }) as unknown as Response],
] as const) it(`${name}: retains one-POST unknown-outcome protection`, async () => {
  const s = setup('unregistered', reply);
  await expect(s.transport.action('hero.army_create', {})).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  await expect(s.transport.action('hero.add_focus', {})).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  expect(s.fetcher).toHaveBeenCalledTimes(1);
});
for (const phase of ['headers', 'body'] as const) it(`${phase} stall uses real 20-second deadline then ignores late policy reply`, async () => {
  vi.useFakeTimers(); const pending = deferred<any>();
  const s = setup('pending', () => phase === 'headers' ? pending.promise : Promise.resolve({ status: 403, json: () => pending.promise }) as Promise<Response>);
  const action = s.transport.action('hero.army_create', {}); const assertion = expect(action).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  await vi.advanceTimersByTimeAsync(20001); await assertion;
  pending.resolve(phase === 'headers' ? captured('pending') : cases.pending.response.body); await flush();
  s.auth.authorize({ ...authFor('pending'), token: 'rotated' });
  await expect(s.transport.action('hero.add_focus', {})).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
});
it('unknown lock belongs to the captured identity, allows reads and a different viewer, and survives return', async () => {
  const pending = deferred<Response>(); let n = 0;
  const s = setup('pending', async () => ++n === 1 ? pending.promise : json({ success: false, message: 'ordinary refusal' }));
  const first = s.transport.action('hero.army_create', {}); const assertion = expect(first).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  s.auth.authorize({ ...authFor('pending'), userId: 'another', token: 'another-token' });
  pending.resolve(json({ detail: 'proxy failure' }, 500)); await assertion;
  expect(s.transport.mutationBlock()).toBeNull(); expect(await s.transport.action('hero.army_create', {})).toMatchObject({ success: false });
  s.auth.authorize({ ...authFor('pending'), token: 'rotated-original' });
  expect(s.transport.mutationBlock()).not.toBeNull();
  await expect(s.transport.read('/api/bannerlord/my-hero')).rejects.toThrow('ordinary refusal');
  await expect(s.transport.action('hero.add_focus', {})).rejects.toBeInstanceOf(UnknownActionOutcomeError);
  expect(s.fetcher).toHaveBeenCalledTimes(3);
});

for (const [name, body, status] of [
  ['wrong channel', { detail: { ...detail, channel_id: 22 } }, 403],
  ['wrong code', { detail: { ...detail, status: 'other' } }, 403],
  ['blank message', { detail: { ...detail, message: ' ' } }, 403],
  ['policy-shaped 5xx', { detail }, 503],
] as const) it(`read does not adopt unverified nested text: ${name}`, async () => {
  const s = setup('unregistered', async () => json(body, status));
  await expect(s.transport.read('/api/bannerlord/my-hero')).rejects.toThrow(`Ошибка сервера (${status})`);
  expect(s.transport.mutationBlock()).toBeNull();
});
it('read preserves actual viewer_poll rate metadata boundary without inventing cooldown', async () => {
  const s = setup('rate_limited', async () => json({ detail: { ...rate, scope: 'viewer_poll' } }, 429, { 'Retry-After': '17' }));
  await expect(s.transport.read('/api/bannerlord/my-hero')).rejects.toThrow(rate.message);
  expect(s.transport.mutationBlock()).toBeNull();
});

for (const name of policies) it(`${name}: native action button displays exact server text, stays available, and does not schedule success refresh`, async () => {
  vi.useFakeTimers(); const auth = new TwitchAuthStore(); const f = heroEvidence.responses;
  const message = `  Отказ для ${name}: <b>новый серверный текст</b>  `;
  const reads: Record<string, unknown> = {
    '/api/user/resolve-twitch-token': { login: 'alice' }, '/api/bannerlord/config': f.config,
    '/api/bannerlord/my-hero': f.hero, '/api/bannerlord/classes': f.classes,
    '/api/bannerlord/build': f.build_ready, '/api/bannerlord/my-buffs': f.buffs,
    '/api/viewer/stats/alice': f.stats, '/api/user/level/alice': f.level, '/api/duel/list': f.duels,
  };
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url) === '/api/bannerlord/action' && init?.method === 'POST') return json({ detail: { ...cases[name].response.body.detail, message } }, cases[name].response.status, { 'Retry-After': '17' });
    const path = String(url); if (!(path in reads)) throw new Error('Unexpected read ' + path); return json(reads[path]);
  });
  const identity = new IdentityBootstrap(auth, '', fetcher);
  const detach = identity.attach({ onAuthorized: callback => callback(authFor(name)) });
  const transport = new HttpPanelTransport('', auth, fetcher, () => 'ui-attempt');
  const controller = new PanelController(transport, auth, identity);
  try {
    await flush(); await controller.start(); await flush();
    const ui = render(<HeroDevelopmentView controller={controller} />); fetcher.mockClear();
    const button = ui.container.querySelector('[data-attr="Vigor"]') as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    await act(async () => { button.click(); await flush(); });
    expect(controller.snapshot().message).toBe(message); expect(controller.snapshot().mutationBlocked).toBe(false);
    expect(ui.container.textContent).toContain(message); expect(ui.container.querySelector('b')).toBeNull();
    expect(button.disabled).toBe(false); expect(controller.cooldown('hero.add_attribute')).toBe(0);
    expect(fetcher.mock.calls.map(([url, init]) => [String(url), init?.method || 'GET'])).toEqual([['/api/bannerlord/action', 'POST'], ['/api/bannerlord/my-hero', 'GET']]);
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(fetcher).toHaveBeenCalledTimes(2); // Only the existing immediateHero read; no success-only tail or balance reads.
    await act(async () => { button.click(); await flush(); });
    expect(fetcher).toHaveBeenCalledTimes(4); expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2); // Explicit second click + its immediateHero read.
  } finally { controller.stop(); detach(); }
});
