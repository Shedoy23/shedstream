import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render } from '@testing-library/preact';
import { TwitchAuthStore } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { HttpPanelTransport } from '../src/panel/transport';
import { PanelController } from '../src/panel/controller';
import { HeroDevelopmentView } from '../src/panel/HeroDevelopmentView';
import fixtures from './panel-fixtures/real-responses.json';
const f = fixtures.responses;
const authValue = { token: 'alice-token', userId: 'opaque-alice', channelId: 'channel-a' };
const flush = async () => { for (let n = 0; n < 30; n++) await Promise.resolve(); };
const response = (body: unknown) => new Response(JSON.stringify(body));
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { resolve, promise }; };
function setup(overrides: Record<string, unknown> = {}) {
  const trace: { method: string; path: string; body?: any; token: string | null }[] = [];
  const routes: Record<string, unknown> = {
    '/api/user/resolve-twitch-token': { login: 'alice' },
    '/api/bannerlord/config': f.config, '/api/bannerlord/my-hero': f.hero,
    '/api/bannerlord/classes': f.classes, '/api/bannerlord/build': f.build_ready,
    '/api/bannerlord/my-buffs': f.buffs, '/api/bannerlord/action': f.focus_success.response,
    '/api/viewer/stats/alice': f.stats, '/api/user/level/alice': f.level, '/api/duel/list': f.duels, ...overrides,
  };
  const fetcher = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url); const method = init?.method || 'GET';
    trace.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined, token: new Headers(init?.headers).get('X-Twitch-JWT') });
    if (!(path in routes)) throw new Error(`UNMATCHED ${method} ${path}`);
    const body = routes[path]; return body instanceof Promise ? (await body).clone() : response(body);
  }) as unknown as typeof fetch;
  const auth = new TwitchAuthStore(); let authorize!: (value: typeof authValue) => void;
  const identity = new IdentityBootstrap(auth, '', fetcher);
  const detach = identity.attach({ onAuthorized: callback => { authorize = callback; } });
  const transport = new HttpPanelTransport('', auth, fetcher, () => 'test-id');
  const controller = new PanelController(transport, auth, identity);
  return { trace, routes, auth, identity, controller, transport, authorize, detach,
    async start() { authorize(authValue); await flush(); await controller.start(); await flush(); trace.length = 0; },
  };
}
afterEach(() => { cleanup(); vi.useRealTimers(); });
it('keeps only the server-resolved login, clears it during refresh/switch/detach, and ignores old resolver', async () => {
  const s = setup(); await s.start(); expect(s.identity.snapshot().login).toBe('alice');
  const pending = deferred<Response>(); s.routes['/api/user/resolve-twitch-token'] = pending.promise;
  s.authorize({ ...authValue, token: 'new-token' }); expect(s.identity.snapshot().login).toBeUndefined();
  expect(s.controller.ready()).toBe(false); pending.resolve(response({ login: 'alice' })); await flush();
  expect(s.identity.snapshot().login).toBe('alice'); s.detach(); expect(s.identity.snapshot().login).toBeUndefined(); s.controller.stop();
});
it('captures JWT once, adds client_action_id once and deduplicates exact choices only', async () => {
  const s = setup(); await s.start(); const pending = deferred<Response>(); s.routes['/api/bannerlord/action'] = pending.promise;
  const first = s.transport.action('hero.add_focus', { skill_key: 'OneHanded', amount: 1 });
  const duplicate = s.transport.action('hero.add_focus', { amount: 1, skill_key: 'OneHanded' });
  const other = s.transport.action('hero.add_focus', { amount: 1, skill_key: 'TwoHanded' });
  expect(s.trace).toHaveLength(2); expect(await duplicate).toBeNull();
  expect(s.trace[0].body).toEqual({ action_type: 'hero.add_focus', data: { skill_key: 'OneHanded', amount: 1, client_action_id: 'test-id' } });
  s.auth.authorize({ ...authValue, token: 'rotated' }); expect(s.trace.every(r => r.token === 'alice-token')).toBe(true);
  pending.resolve(response(f.focus_success.response)); await Promise.all([first, other]); s.controller.stop();
});
it('renders real attributes, all 24 progression controls and server catalog choices', async () => {
  const s = setup(); await s.start(); const ui = render(<HeroDevelopmentView controller={s.controller} />);
  expect(ui.container.querySelectorAll('[data-skill]')).toHaveLength(18);
  expect(ui.container.querySelectorAll('[data-attr]')).toHaveLength(6);
  expect(ui.container.textContent).toContain('2/10'); expect(ui.container.textContent).toContain(f.hero.hero.display_name);
  expect(ui.container.querySelectorAll('[data-bnr-build-spec]')).toHaveLength(f.build_ready.build.specializations.length);
  expect(ui.container.querySelectorAll('[data-bnr-build-starter]')).toHaveLength(f.build_ready.build.starter_kits.length); s.controller.stop();
});
it('uses exact PascalCase attribute intent, immediate read and complete successful delayed tail', async () => {
  vi.useFakeTimers(); const s = setup({ '/api/bannerlord/action': f.attribute_success.response }); await s.start();
  const ui = render(<HeroDevelopmentView controller={s.controller} />);
  await act(async () => { fireEvent.click(ui.container.querySelector('[data-attr="Vigor"]')!); await flush(); });
  expect(s.trace.map(r => r.path)).toEqual(['/api/bannerlord/action','/api/bannerlord/my-hero','/api/viewer/stats/alice','/api/user/level/alice','/api/duel/list']);
  expect(s.trace[0].body.data).toEqual({ attribute_key: 'Vigor', amount: 1, client_action_id: 'test-id' });
  await act(async () => { await vi.advanceTimersByTimeAsync(3510); });
  expect(s.trace.slice(-2).map(r => r.path)).toEqual(['/api/bannerlord/my-hero','/api/bannerlord/build']); s.controller.stop();
});
it('fails closed for missing/malformed prices but preserves legitimate zero and inherited 5/10 caps', async () => {
  const s = setup({ '/api/bannerlord/config': { focus_tier_costs: [0, null, -1, '300', 500], attribute_cost: 0 } }); await s.start();
  const ui = render(<HeroDevelopmentView controller={s.controller} />);
  const attr = ui.container.querySelector('[data-attr="Vigor"]') as HTMLButtonElement; expect(attr.disabled).toBe(false);
  const firstSkill = f.hero.skills[0]; const target = ui.container.querySelector(`[data-skill="${firstSkill.skill_key}"]`) as HTMLButtonElement;
  expect(target.disabled).toBe(firstSkill.focus !== 0 && firstSkill.focus !== 4);
  s.routes['/api/bannerlord/config'] = {}; await act(async () => { await s.controller.refresh(); });
  expect([...ui.container.querySelectorAll('[data-attr],[data-skill]')].every(b => (b as HTMLButtonElement).disabled)).toBe(true);
  s.controller.stop();
});
it('preserves arbitrary refusal, applies server cooldown and stops pre-action polls erasing it', async () => {
  const s = setup({ '/api/bannerlord/action': { success: false, message: 'Новый отказ с сервера', cooldown_remaining_s: 44 } }); await s.start();
  const pending = deferred<Response>(); s.routes['/api/bannerlord/my-buffs'] = pending.promise; const poll = s.controller.refreshBuffs();
  await s.controller.action('hero.add_focus', { skill_key: 'OneHanded', amount: 1 }, { tail: 'hero' });
  expect(s.controller.snapshot().message).toContain('Новый отказ с сервера');
  pending.resolve(response(f.buffs)); await poll; expect(s.controller.cooldown('hero.add_focus')).toBeGreaterThan(43);
  s.routes['/api/bannerlord/my-buffs'] = f.buffs; await s.controller.refreshBuffs(); expect(s.controller.cooldown('hero.add_focus')).toBe(0); s.controller.stop();
});
it('does not starve slow polls or accept reverse-order state', async () => {
  const s = setup(); await s.start(); const a = deferred<Response>(); const b = deferred<Response>();
  s.routes['/api/bannerlord/my-hero'] = a.promise; const first = s.controller.refreshHero();
  s.routes['/api/bannerlord/my-hero'] = b.promise; const second = s.controller.refreshHero();
  a.resolve(response({ ...f.hero, hero: { ...f.hero.hero, gold: 321 } })); await first; expect(s.controller.snapshot().hero?.hero?.gold).toBe(321);
  b.resolve(response({ ...f.hero, hero: { ...f.hero.hero, gold: 654 } })); await second;
  expect(s.controller.snapshot().hero?.hero?.gold).toBe(654); s.controller.stop();
});
it('never applies old identity action completion or runs its balance/tail under the new viewer', async () => {
  vi.useFakeTimers(); const s = setup(); await s.start(); const pending = deferred<Response>(); s.routes['/api/bannerlord/action'] = pending.promise;
  const action = s.controller.action('hero.add_attribute', { attribute_key: 'Vigor', amount: 1 }, { tail: 'hero' });
  s.routes['/api/user/resolve-twitch-token'] = { login: 'carol' }; s.authorize({ ...authValue, userId: 'opaque-carol', token: 'carol-token' }); await flush(); s.trace.length = 0;
  pending.resolve(response(f.attribute_success.response)); await action; await vi.advanceTimersByTimeAsync(3510);
  expect(s.trace.filter(r => r.path.includes('stats') || r.path.includes('/level/') || r.path.includes('/duel/'))).toEqual([]);
  expect(s.controller.snapshot().message).not.toContain(f.attribute_success.response.message); s.controller.stop();
});
it('absent/dead hero has no mutation controls and enabled-but-syncing never falls back to classes', async () => {
  for (const hero of [f.hero_absent, f.hero_dead]) {
    const s = setup({ '/api/bannerlord/my-hero': hero }); await s.start(); const ui = render(<HeroDevelopmentView controller={s.controller} />);
    expect(ui.container.querySelector('[data-skill],[data-attr],[data-bnr-build-spec],select')).toBeNull(); ui.unmount(); s.controller.stop();
  }
  const s = setup({ '/api/bannerlord/build': f.build_syncing }); await s.start(); const ui = render(<HeroDevelopmentView controller={s.controller} />);
  expect(ui.container.querySelector('select')).toBeNull(); expect(ui.container.textContent).toContain(f.build_syncing.message); s.controller.stop();
});
it('manual refresh recovers missing prices and classes without reloading the document', async () => {
  const s = setup({ '/api/bannerlord/config': { success: false, message: 'Временный сбой цен' }, '/api/bannerlord/classes': { success: false, message: 'Временный сбой классов' } });
  await s.start(); const ui = render(<HeroDevelopmentView controller={s.controller} />);
  expect((ui.container.querySelector('[data-attr="Vigor"]') as HTMLButtonElement).disabled).toBe(true);
  s.routes['/api/bannerlord/config'] = f.config; s.routes['/api/bannerlord/classes'] = f.classes;
  await act(async () => { fireEvent.click(ui.getByRole('button', { name: 'Обновить' })); await flush(); });
  expect((ui.container.querySelector('[data-attr="Vigor"]') as HTMLButtonElement).disabled).toBe(false);
  expect(s.controller.snapshot().classes).toEqual(f.classes); expect(s.controller.snapshot().error).toBe(''); s.controller.stop();
});
it('failed new-build refresh removes stale enabled choices without exposing legacy picker', async () => {
  const s = setup(); await s.start(); const ui = render(<HeroDevelopmentView controller={s.controller} />);
  s.routes['/api/bannerlord/build'] = { success: false, message: 'Сборка недоступна' };
  await act(async () => { await s.controller.refreshBuild(); });
  const choices = [...ui.container.querySelectorAll('[data-bnr-build-spec],[data-bnr-build-starter]')];
  expect(choices.every(button => (button as HTMLButtonElement).disabled)).toBe(true);
  expect(ui.container.querySelector('select')).toBeNull();
  choices.forEach(button => fireEvent.click(button)); await flush(); expect(s.trace.filter(r => r.method === 'POST')).toEqual([]); s.controller.stop();
});
for (const costs of [[], [3], { 0: 3 }, null]) it(`manual refresh recovers malformed focus tiers ${JSON.stringify(costs)}`, async () => {
  const s = setup({ '/api/bannerlord/config': { attribute_cost: 5, focus_tier_costs: costs } }); await s.start();
  const ui = render(<HeroDevelopmentView controller={s.controller} />); s.routes['/api/bannerlord/config'] = f.config;
  await act(async () => { fireEvent.click(ui.getByRole('button', { name: 'Обновить' })); await flush(); });
  expect(s.controller.snapshot().config?.focus_tier_costs).toEqual(f.config.focus_tier_costs); s.controller.stop();
});
it('synchronously serializes different specialization and kit buttons within one render frame', async () => {
  const s = setup(); await s.start(); const pending = deferred<Response>(); s.routes['/api/bannerlord/action'] = pending.promise;
  const ui = render(<HeroDevelopmentView controller={s.controller} />);
  const spec = ui.container.querySelector('[data-bnr-build-spec="assault"]') as HTMLButtonElement;
  const kit = ui.container.querySelector('[data-bnr-build-starter="infantry"]') as HTMLButtonElement;
  await act(async () => { spec.click(); kit.click(); await flush(); });
  expect(s.trace.filter(r => r.method === 'POST')).toHaveLength(1);
  pending.resolve(response(f.specialization_success.response)); await flush(); s.controller.stop();
});
it('a build GET started before acknowledgement cannot release local pending', async () => {
  const s = setup(); await s.start(); const pending = deferred<Response>();
  s.routes['/api/bannerlord/build'] = pending.promise; const poll = s.controller.refreshBuild();
  await s.controller.action('hero.set_specialization', { specialization: 'assault' }, { tail: 'hero' });
  expect(s.controller.snapshot().buildPending).toBe(true);
  pending.resolve(response(f.build_ready)); await poll; expect(s.controller.snapshot().buildPending).toBe(true);
  s.routes['/api/bannerlord/build'] = f.build_ready; await s.controller.refreshBuild(); expect(s.controller.snapshot().buildPending).toBe(false); s.controller.stop();
});
it('a 20-second unknown action outcome blocks duplicate and different purchases while reads remain possible', async () => {
  vi.useFakeTimers(); const s = setup(); await s.start();
  s.routes['/api/bannerlord/action'] = deferred<Response>().promise;
  const action = s.controller.action('hero.buy_equipment', { item_id: 'sword' }, { tail: 'balance' });
  await vi.advanceTimersByTimeAsync(20001); await action;
  const second = s.controller.action('hero.buy_equipment', { item_id: 'sword' }, { tail: 'balance' });
  await vi.advanceTimersByTimeAsync(20001); await second;
  const third = s.controller.action('hero.buy_equipment', { item_id: 'tier5' }, { tail: 'balance' });
  await vi.advanceTimersByTimeAsync(20001); await third;
  expect(s.trace.filter(r => r.method === 'POST')).toHaveLength(1);
  expect(s.controller.snapshot().message).toContain('Исход предыдущей заявки неизвестен');
  await s.controller.refreshHero(); expect(s.trace.at(-1)?.path).toBe('/api/bannerlord/my-hero'); s.controller.stop();
});
it('ignores a genuinely reverse-ordered older hero response', async () => {
  const s = setup(); await s.start(); const a = deferred<Response>(), b = deferred<Response>();
  s.routes['/api/bannerlord/my-hero'] = a.promise; const first = s.controller.refreshHero();
  s.routes['/api/bannerlord/my-hero'] = b.promise; const second = s.controller.refreshHero();
  b.resolve(response({ ...f.hero, hero: { ...f.hero.hero, gold: 654 } })); await second;
  a.resolve(response({ ...f.hero, hero: { ...f.hero.hero, gold: 321 } })); await first;
  expect(s.controller.snapshot().hero?.hero?.gold).toBe(654); s.controller.stop();
});
it('accepted action with lost response blocks that identity across token rotation but not another viewer', async () => {
  const auth = new TwitchAuthStore(); auth.authorize(authValue); const accepted: unknown[] = [];
  const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    accepted.push(JSON.parse(String(init?.body)));
    if (accepted.length === 1) return { json: async () => { throw Error('response lost after accept'); } } as unknown as Response;
    return response(f.equipment_buy.response);
  }) as typeof fetch;
  const transport = new HttpPanelTransport('', auth, fetcher);
  await expect(transport.action('hero.buy_equipment', { item_id: 'sword' })).rejects.toThrow();
  auth.authorize({ ...authValue, token: 'rotated' });
  await expect(transport.action('hero.buy_equipment', { item_id: 'sword' })).rejects.toThrow('Исход предыдущей заявки неизвестен');
  await expect(transport.action('hero.buy_equipment', { item_id: 'tier5' })).rejects.toThrow('Исход предыдущей заявки неизвестен');
  expect(accepted).toHaveLength(1);
  auth.authorize({ ...authValue, token: 'carol-token', userId: 'opaque-carol' });
  expect((await transport.action('hero.buy_equipment', { item_id: 'sword' }))?.success).toBe(true);
  auth.authorize(authValue);
  await expect(transport.action('hero.buy_equipment', { item_id: 'sword' })).rejects.toThrow('Исход предыдущей заявки неизвестен');
  expect(accepted).toHaveLength(2);
});
it('a definite server refusal is retryable and does not create unknown-outcome blocking', async () => {
  const s = setup({ '/api/bannerlord/action': f.attribute_insufficient.response }); await s.start();
  const intent = { attribute_key: 'Vigor', amount: 1 };
  expect((await s.transport.action('hero.add_attribute', intent))?.success).toBe(false);
  s.routes['/api/bannerlord/action'] = f.attribute_success.response;
  expect((await s.transport.action('hero.add_attribute', intent))?.success).toBe(true);
  expect(s.trace.filter(r => r.method === 'POST')).toHaveLength(2); s.controller.stop();
});
it('unknown-outcome disables visible mutation controls while refresh and another identity stay usable', async () => {
  const s = setup({ '/api/bannerlord/action': {} }); await s.start(); const ui = render(<HeroDevelopmentView controller={s.controller} />);
  await act(async () => { (ui.container.querySelector('[data-attr="Vigor"]') as HTMLElement).click(); await flush(); });
  expect(s.controller.snapshot().canAct).toBe(true);
  expect([...ui.container.querySelectorAll('[data-attr],[data-skill],[data-bnr-build-spec],[data-bnr-build-starter]')].every(node => (node as HTMLButtonElement).disabled)).toBe(true);
  expect((ui.getByRole('button', { name: 'Обновить' }) as HTMLButtonElement).disabled).toBe(false);
  expect(ui.container.textContent).toContain('могла дойти до сервера');
  await act(async () => { s.authorize({ ...authValue, token: 'rotated' }); await flush(); });
  expect((ui.container.querySelector('[data-attr="Vigor"]') as HTMLButtonElement).disabled).toBe(true);
  await act(async () => { s.routes['/api/user/resolve-twitch-token'] = { login: 'carol' }; s.authorize({ ...authValue, userId: 'opaque-carol', token: 'carol' }); await flush(); });
  expect((ui.container.querySelector('[data-attr="Vigor"]') as HTMLButtonElement).disabled).toBe(false);
  await act(async () => { s.routes['/api/user/resolve-twitch-token'] = { login: 'alice' }; s.authorize(authValue); await flush(); });
  expect((ui.container.querySelector('[data-attr="Vigor"]') as HTMLButtonElement).disabled).toBe(true);
  s.controller.stop();
});
