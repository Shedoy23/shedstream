import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render } from '@testing-library/preact';
import { TwitchAuthStore } from '../src/auth';
import { PanelController } from '../src/panel/controller';
import { HttpPanelTransport } from '../src/panel/transport';
import { HeroDevelopmentView } from '../src/panel/HeroDevelopmentView';
import { createLegacyHarness, legacyResponses as f, legacySelectors as oldSelect, type LegacyFixtures, type LegacyJson, type LegacyRequest, type LegacyHttpReply } from './panel-legacy-harness';
const now = Date.UTC(2026, 9, 2, 12);
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const all: (() => void)[] = [];
beforeEach(() => { vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] }); vi.setSystemTime(now); });
afterEach(() => { cleanup(); all.splice(0).forEach(close => close()); vi.useRealTimers(); });
function normalized(trace: LegacyRequest[]) {
  return trace.map(({ rawBody: _rawBody, ...request }) => {
    const body = structuredClone(request.body);
    if (body && typeof body === 'object' && !Array.isArray(body) && body.data && typeof body.data === 'object' && !Array.isArray(body.data) && 'client_action_id' in body.data) body.data.client_action_id = '<random-client-id>';
    return { ...request, body };
  });
}
async function pair(overrides: Partial<LegacyFixtures> = {}) {
  const old = createLegacyHarness(overrides, { now }); all.push(old.dispose);
  await old.bootHero();
  const trace: LegacyRequest[] = []; const failures: string[] = []; const calls: Record<string, number> = {};
  const fixtures = old.fixtures;
  const routes: Record<string, keyof LegacyFixtures> = {
    'GET /api/bannerlord/config': 'config', 'GET /api/bannerlord/my-hero': 'hero', 'GET /api/bannerlord/classes': 'classes',
    'GET /api/bannerlord/build': 'build', 'GET /api/bannerlord/my-buffs': 'buffs', 'POST /api/bannerlord/action': 'action',
    'GET /api/viewer/stats/alice': 'stats', 'GET /api/user/level/alice': 'level', 'GET /api/duel/list': 'duels',
  };
  const fetcher = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'https://example.test'); const rawBody = init.body == null ? null : String(init.body);
    const headers = new Headers(init.headers);
    const request = { method: init.method || 'GET', path: url.pathname, query: url.search, rawBody, body: rawBody ? JSON.parse(rawBody) as LegacyJson : null, token: headers.get('X-Twitch-JWT') || '', contentType: headers.get('Content-Type') || '', cache: init.cache || null };
    trace.push(request);
    const key = routes[`${request.method} ${request.path}`];
    if (!key || request.query || (request.method === 'GET' && rawBody !== null)) { failures.push(`UNMATCHED ${request.method} ${request.path}${request.query}`); throw new Error(failures.at(-1)); }
    calls[key] = (calls[key] || 0) + 1; const fixture = fixtures[key];
    const value = typeof fixture === 'function' ? await fixture(request, calls[key]) : fixture;
    const wrapped = value !== null && typeof value === 'object' && 'legacyHttpReply' in value && value.legacyHttpReply === true;
    return new Response(JSON.stringify(wrapped ? (value as LegacyHttpReply).json : value), { status: wrapped ? (value as LegacyHttpReply).status : 200 });
  };
  const auth = new TwitchAuthStore(); auth.authorize({ channelId: 'channel-a', userId: 'opaque-alice', token: 'alice-token' });
  const identity = { snapshot: () => ({ status: 'ready' as const, login: 'alice', message: '', canShare: false, shareRequested: false }), subscribe: () => () => {} };
  const controller = new PanelController(new HttpPanelTransport('', auth, fetcher), auth, identity);
  all.push(() => controller.stop()); await controller.start(); await flush();
  const ui = render(<HeroDevelopmentView controller={controller} />);
  expect(normalized(trace), 'entire selected-scope startup').toEqual(normalized(old.trace));
  trace.length = 0; old.trace.length = 0;
  return { old, controller, ui, trace, fixtures,
    async click(oldSelector: string, newSelector = oldSelector) { await old.click(oldSelector); await act(async () => { const button = ui.container.querySelector(newSelector) as HTMLElement; expect(button, newSelector).toBeTruthy(); button.click(); await flush(); }); },
    async finish(ms = 3510) { await old.advance(ms); await act(async () => { await vi.advanceTimersByTimeAsync(ms); await flush(); }); expect(failures).toEqual([]); expect(normalized(trace), 'full method/path/query/body/JWT/header/cache trace').toEqual(normalized(old.trace)); },
  };
}
const attrs = Object.keys(f.hero.attributes);
const skills = f.hero.skills.map(skill => skill.skill_key);
describe('real old rendered progression vs new Preact request parity', () => {
  for (const key of attrs) it(`attribute ${key}: exact PascalCase+amount and complete success tail`, async () => {
    const p = await pair(); await p.click(oldSelect.attribute(key), `[data-attr="${key}"]`); await p.finish();
    expect(p.trace[0].body).toMatchObject({ action_type: 'hero.add_attribute', data: { attribute_key: key, amount: 1 } });
  });
  for (const key of skills) it(`focus ${key}: exact key+amount and complete success tail`, async () => {
    const p = await pair(); await p.click(oldSelect.focus(key), `[data-skill="${key}"]`); await p.finish();
    expect(p.trace[0].body).toMatchObject({ action_type: 'hero.add_focus', data: { skill_key: key, amount: 1 } });
  });
});
describe('actual emitted catalogs vs new Preact request parity', () => {
  for (const option of f.classes.classes) it(`legacy class ${option.class_key}`, async () => {
    const current = option.class_key === f.classes.current.class_key ? { ...f.classes.current, class_key: f.classes.classes[0].class_key } : f.classes.current;
    const p = await pair({ build: f.build_no_session, classes: { ...f.classes, current } });
    await p.old.change(oldSelect.class, option.class_key);
    await act(async () => { const select = p.ui.container.querySelector('#panel-class-select') as HTMLSelectElement; select.value = option.class_key; select.dispatchEvent(new Event('change', { bubbles: true })); await flush(); });
    await p.finish(); expect(p.trace[0].body).toMatchObject({ action_type: 'hero.set_class', data: { class_key: option.class_key, price: 0 } });
  });
  for (const option of f.build_ready.build.specializations) it(`specialization ${option.id}`, async () => {
    const current = option.id === f.build_ready.build.specialization ? 'assault' : f.build_ready.build.specialization;
    const p = await pair({ build: { ...f.build_ready, build: { ...f.build_ready.build, specialization: current } } });
    await p.click(oldSelect.specialization(option.id)); await p.finish(); expect(p.trace[0].body).toMatchObject({ action_type: 'hero.set_specialization', data: { specialization: option.id } });
  });
  for (const option of f.build_ready.build.starter_kits) it(`starter ${option.id}`, async () => {
    const p = await pair({ build: f.build_ready }); await p.click(oldSelect.starter(option.id)); await p.finish();
    expect(p.trace[0].body).toMatchObject({ action_type: 'hero.claim_starter', data: { starter_kit: option.id } });
  });
});
it('same-current catalog selections and unavailable kits produce no mutation', async () => {
  const build = { ...f.build_ready, build: { ...f.build_ready.build, starter_kits: f.build_ready.build.starter_kits.map(kit => ({ ...kit, available: false, reason: 'Предмет временно недоступен' })) } };
  const p = await pair({ build }); await p.click(oldSelect.specialization(build.build.specialization));
  for (const kit of build.build.starter_kits) await p.click(oldSelect.starter(kit.id));
  await p.finish(); expect(p.trace).toEqual([]); expect(p.ui.container.textContent).toContain('Предмет временно недоступен');
});
for (const [name, build] of Object.entries({ pending: f.build_pending, battle: f.build_battle, syncing: f.build_syncing })) it(`${name} new-build state never exposes selectable legacy controls`, async () => {
  const p = await pair({ build });
  expect(p.old.document.querySelector('select')).toBeNull(); expect(p.ui.container.querySelector('select')).toBeNull();
  const oldButtons = [...p.old.document.querySelectorAll('[data-bnr-build-spec],[data-bnr-build-starter]')];
  const newButtons = [...p.ui.container.querySelectorAll('[data-bnr-build-spec],[data-bnr-build-starter]')];
  expect(newButtons.map(button => (button as HTMLButtonElement).disabled)).toEqual(oldButtons.map(button => (button as HTMLButtonElement).disabled));
  for (const button of newButtons) (button as HTMLButtonElement).click(); await p.finish(); expect(p.trace).toEqual([]);
});
for (const [name, reply] of Object.entries({ money: f.attribute_insufficient.response, role: f.role_refusal, unknown: { success: false, message: 'Новый отказ, которого клиент не знает' }, cooldown: f.focus_cooldown.response })) it(`preserves ${name} server refusal and exact full request tail`, async () => {
  const p = await pair({ action: reply }); await p.click(oldSelect.attribute('Vigor'), '[data-attr="Vigor"]'); await p.finish();
  expect(p.controller.snapshot().message).toContain(reply.message);
  // Old cooldown rejection suppresses its toast when a cooldown button exists;
  // new screen keeps the supplied message visible in addition to countdown.
  if (name !== 'cooldown') expect(p.old.document.querySelector(oldSelect.notice)?.textContent).toContain(reply.message);
});
it('shows changed server prices and legitimate zero without copying economics', async () => {
  const p = await pair({ config: { ...f.config, attribute_cost: 0, focus_tier_costs: [1, 2, 3, 4, 5] } });
  expect(p.old.document.querySelector(oldSelect.attribute('Vigor'))?.getAttribute('title')).toContain('0');
  expect(p.ui.container.querySelector('[data-attr="Vigor"]')?.getAttribute('title')).toContain('0');
  await p.click(oldSelect.attribute('Vigor'), '[data-attr="Vigor"]'); await p.finish();
});
it('preserves inherited 5/10 cap gating', async () => {
  const hero = { ...f.hero, attributes: Object.fromEntries(attrs.map(key => [key, 10])), skills: f.hero.skills.map(skill => ({ ...skill, focus: 5 })) };
  const p = await pair({ hero });
  for (const key of attrs) await p.click(oldSelect.attribute(key), `[data-attr="${key}"]`);
  for (const key of skills) await p.click(oldSelect.focus(key), `[data-skill="${key}"]`);
  await p.finish(); expect(p.trace).toEqual([]);
});
it('manual refresh uses actual old refresh control and entire selected-host reads', async () => {
  const p = await pair();
  // The scope header lacks full-shell controls, so add only the old delegated
  // refresh button; the original document click handler remains unchanged.
  const button = p.old.document.createElement('button'); button.id = 'refresh-hero-btn'; p.old.document.body.append(button);
  await p.old.click('#refresh-hero-btn'); await act(async () => { fireEvent.click(p.ui.getByRole('button', { name: 'Обновить' })); await flush(); }); await p.finish(0);
});
for (const [first, second] of [
  [oldSelect.specialization('assault'), oldSelect.specialization('marksman')],
  [oldSelect.specialization('assault'), oldSelect.starter('infantry')],
  [oldSelect.starter('infantry'), oldSelect.specialization('assault')],
]) it(`same-frame build-family clicks ${first} then ${second} preserve the actual old single flight`, async () => {
  let resolve!: (reply: LegacyJson) => void;
  const pending = new Promise<LegacyJson>(r => { resolve = r; });
  const p = await pair({ build: f.build_ready, action: () => pending });
  for (const selector of [first, second]) (p.old.document.querySelector(selector) as HTMLElement).click();
  await p.old.settle();
  await act(async () => { for (const selector of [first, second]) (p.ui.container.querySelector(selector) as HTMLElement).click(); await flush(); });
  expect(p.old.trace.filter(r => r.method === 'POST')).toHaveLength(1);
  expect(p.trace.filter(r => r.method === 'POST')).toHaveLength(1);
  resolve(f.specialization_success.response); await p.finish();
});
for (const [name, hero] of Object.entries({ absent: f.hero_absent, dead: f.hero_dead })) it(`${name} hero has no old or new progression controls`, async () => {
  const p = await pair({ hero });
  expect(p.old.document.querySelector('[data-skill],[data-attr]')).toBeNull();
  expect(p.ui.container.querySelector('[data-skill],[data-attr]')).toBeNull(); await p.finish(); expect(p.trace).toEqual([]);
});
it('claimed starter preserves the old information-only state', async () => {
  const p = await pair({ build: f.build_claimed });
  expect(p.old.document.querySelector('[data-bnr-build-starter]')).toBeNull(); expect(p.ui.container.querySelector('[data-bnr-build-starter]')).toBeNull();
  expect(p.ui.container.textContent).toContain('Стартовый набор получен'); await p.finish();
});
it('same-frame duplicate progression clicks have the exact old single POST and immediate reads', async () => {
  let resolve!: (reply: LegacyJson) => void; const pending = new Promise<LegacyJson>(r => { resolve = r; });
  const p = await pair({ action: () => pending });
  const old = p.old.document.querySelector(oldSelect.attribute('Vigor')) as HTMLElement;
  old.click(); old.click(); await p.old.settle();
  await act(async () => { const next = p.ui.container.querySelector('[data-attr="Vigor"]') as HTMLElement; next.click(); next.click(); await flush(); });
  expect(p.trace.filter(row => row.method === 'POST')).toHaveLength(1); expect(p.old.trace.filter(row => row.method === 'POST')).toHaveLength(1);
  resolve(f.attribute_success.response); await p.finish();
});
it('missing config deliberately fails closed instead of buying at inherited legacy fallback prices', async () => {
  const p = await pair({ config: {} });
  await p.click(oldSelect.attribute('Vigor'), '[data-attr="Vigor"]');
  expect(p.old.trace.filter(row => row.method === 'POST')).toHaveLength(1);
  expect(p.trace).toEqual([]); expect((p.ui.container.querySelector('[data-attr="Vigor"]') as HTMLButtonElement).disabled).toBe(true);
});
