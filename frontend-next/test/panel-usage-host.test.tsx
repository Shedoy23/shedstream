import { act, cleanup, render } from '@testing-library/preact';
import {heroBeforeAction,nextResponseTurn} from './panel-response-order';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { PanelApp } from '../src/panel/PanelApp';
import { EquipmentView } from '../src/panel/EquipmentView';
import { PanelController } from '../src/panel/controller';
import { HttpPanelTransport } from '../src/panel/transport';
import { PanelUsage } from '../src/panel/usage';
import { createLegacyHarness, legacyResponses as f, type LegacyFixtures, type LegacyJson, type LegacyRequest, type LegacyHttpReply } from './panel-legacy-harness';

const now = Date.UTC(2026, 9, 2, 12), drains: (() => void)[] = [];
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); await nextResponseTurn(); };
beforeEach(() => { vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] }); vi.setSystemTime(now); Object.defineProperty(document, 'hidden', { configurable: true, value: false }); });
afterEach(() => { cleanup(); drains.splice(0).forEach(fn => fn()); vi.restoreAllMocks(); vi.useRealTimers(); Object.defineProperty(document, 'hidden', { configurable: true, value: false }); });
function normalized(trace: LegacyRequest[]) {
  return trace.map(({ rawBody, ...request }) => {
    let bytes=rawBody;
    const body = structuredClone(request.body);
    if (body && typeof body === 'object' && !Array.isArray(body)) {
      if ('batch_id' in body) { if(bytes)bytes=bytes.replace(JSON.stringify(body.batch_id),JSON.stringify('<generated-batch-id>')); body.batch_id = '<generated-batch-id>'; }
      if (body.data && typeof body.data === 'object' && !Array.isArray(body.data) && 'client_action_id' in body.data) { if(bytes)bytes=bytes.replace(JSON.stringify(body.data.client_action_id),JSON.stringify('<generated-action-id>')); body.data.client_action_id = '<generated-action-id>'; }
    }
    return { ...request, body, rawBody:bytes };
  });
}
const usageEvents = (trace: LegacyRequest[]) => trace.filter(row => row.path === '/api/viewer/ui-usage').flatMap(row => (row.body as { events: { kind: string; feature: string; count: number }[] }).events);
async function pair(overrides: Partial<LegacyFixtures> = {}, hidden = false) {
  Object.defineProperty(document, 'hidden', { configurable: true, value: hidden });
  const old = createLegacyHarness({ usage: f.usage_ok, ...overrides }, { panelLifecycle: true, now }); drains.push(old.dispose);
  heroBeforeAction(old.fixtures);
  if (hidden) await old.setHidden(true);
  await old.bootHero(); await old.exposeUsagePanels();
  const trace: LegacyRequest[] = [], failures: string[] = [], calls: Record<string, number> = {};
  const routes: Record<string, keyof LegacyFixtures> = {
    'GET /api/bannerlord/content-catalogs': 'catalogs', 'GET /api/bannerlord/progression': 'progression', 'GET /api/bannerlord/config': 'config', 'GET /api/bannerlord/my-hero': 'hero', 'GET /api/bannerlord/classes': 'classes',
    'GET /api/bannerlord/build': 'build', 'GET /api/bannerlord/my-buffs': 'buffs', 'POST /api/bannerlord/action': 'action',
    'GET /api/viewer/stats/alice': 'stats', 'GET /api/user/level/alice': 'level', 'GET /api/duel/list': 'duels',
    'GET /api/bannerlord/equipment-shop': 'equipment', 'POST /api/viewer/ui-usage': 'usage',
  };
  let resolver: () => Promise<Response> = async () => new Response(JSON.stringify({ login: 'alice' }));
  const fetcher: typeof fetch = async (input, init = {}) => {
    const url = new URL(String(input), 'https://example.test');
    // Resolution is real in the Preact host. Legacy bootstrap is deliberately
    // withheld by the existing selected-screen harness; compare its admitted
    // host scope only, rather than pretending its full-shell auth also ran.
    if (url.pathname === '/api/user/resolve-twitch-token') return resolver();
    const rawBody = init.body == null ? null : String(init.body), headers = new Headers(init.headers);
    const request: LegacyRequest = { method: init.method || 'GET', path: url.pathname, query: url.search, rawBody,
      body: rawBody ? JSON.parse(rawBody) as LegacyJson : null, token: headers.get('X-Twitch-JWT') || '', contentType: headers.get('Content-Type') || '', cache: init.cache || null, ...(init.keepalive === undefined ? {} : { keepalive: init.keepalive }) };
    trace.push(request);
    const key = routes[`${request.method} ${request.path}`];
    if (!key || request.query || (request.method === 'GET' && rawBody !== null)) { failures.push(`UNMATCHED ${request.method} ${request.path}${request.query}`); throw new Error(failures.at(-1)); }
    calls[key] = (calls[key] || 0) + 1;
    const fixture = old.fixtures[key], value = typeof fixture === 'function' ? await fixture(request, calls[key]) : fixture;
    const wrapped = value !== null && typeof value === 'object' && 'legacyHttpReply' in value && value.legacyHttpReply === true;
    return new Response(JSON.stringify(wrapped ? (value as LegacyHttpReply).json : value), { status: wrapped ? (value as LegacyHttpReply).status : 200 });
  };
  const auth = new TwitchAuthStore(); let authorize!: (a: { token: string; channelId: string; userId: string }) => void;
  const identity = new IdentityBootstrap(auth, '', fetcher); const detach = identity.attach({ onAuthorized: callback => { authorize = callback; } }); drains.push(detach);
  const usage = new PanelUsage({ auth, identity, baseUrl: '', surface: 'desktop', fetcher });
  const controller = new PanelController(new HttpPanelTransport('', auth, fetcher), auth, identity, Date.now, usage);
  let ui!: ReturnType<typeof render>;
  await act(async () => { authorize({ token: 'alice-token', channelId: 'channel-a', userId: 'opaque-alice' }); await flush(); ui = render(<PanelApp controller={controller} identity={identity} Equipment={EquipmentView} />); await flush(); });
  await act(async () => { await flush(); });
  const check = () => { expect(failures).toEqual([]); old.assertHealthy(); expect(normalized(trace), 'complete admitted-host request trace, including telemetry and all action/poll tails').toEqual(normalized(old.trace)); };
  check();
  return { old, trace, controller, usage, ui, authorize, identity,
    resolver: (fn: () => Promise<Response>) => { resolver = fn; }, check,
    async advance(ms: number) { await old.advance(ms); await act(async () => { await vi.advanceTimersByTimeAsync(ms); await flush(); }); },
    async click(oldSelector: string, newSelector = oldSelector, count = 1) {
      for (let i = 0; i < count; i++) (old.document.querySelector(oldSelector) as HTMLElement).click(); await old.settle();
      await act(async () => { for (let i = 0; i < count; i++) (ui.container.querySelector(newSelector) as HTMLElement).click(); await flush(); }); await act(async () => { const confirm=ui.queryByRole('button',{name:'Подтвердить',exact:true}); if(confirm) for(let i=0;i<count;i++) confirm.click(); await flush(); });
    },
    async tab(tab: 'hero' | 'inventory') { await old.click(`[data-bnr-tab="${tab}"]`); await act(async () => { ui.getByRole('button', { name: tab === 'hero' ? 'Развитие' : 'Снаряжение' }).click(); await flush(); }); await act(async () => { await flush(); }); },
    async hide(value: boolean) { await old.setHidden(value); await act(async () => { Object.defineProperty(document, 'hidden', { configurable: true, value }); document.dispatchEvent(new Event('visibilitychange')); await flush(); }); },
  };
}

it('actual PanelApp batches exposures, real transitions and action intent with complete old/new 30s request parity', async () => {
  const p = await pair();
  await p.tab('hero'); await p.tab('inventory'); await p.tab('inventory'); await p.tab('hero');
  await p.click('.bnr-prog-attr-btn[data-attr="vigor"]', '[data-attr="vigor"]');
  await p.advance(29999); expect(usageEvents(p.trace)).toEqual([]); p.check();
  await p.advance(1); p.check();
  expect(usageEvents(p.trace)).toEqual([{ kind: 'panel_view', feature: 'core:panel', count: 1 }, { kind: 'panel_view', feature: 'bannerlord:panel', count: 1 },
    { kind: 'section_open', feature: 'bannerlord:tab.inventory', count: 1 }, { kind: 'section_open', feature: 'bannerlord:tab.hero', count: 1 }, { kind: 'action_attempt', feature: 'bannerlord:hero.add_attribute', count: 1 }]);
  await p.advance(60000); p.check(); expect(p.trace.filter(row => row.path.endsWith('ui-usage'))).toHaveLength(1);
});
it('actual hidden-page event flushes once, visibility and rerenders never count additional same-day exposures', async () => {
  const p = await pair(); await p.hide(true); p.check(); expect(usageEvents(p.trace)).toHaveLength(2);
  await p.advance(40000); p.check(); await p.hide(false); await p.old.exposeUsagePanels(); await p.advance(30000); p.check();
  expect(usageEvents(p.trace)).toHaveLength(2);
});
it('an initially hidden authorized PanelApp records no exposure until it becomes visible', async () => {
  const p = await pair({}, true); await p.advance(30000); p.check(); expect(usageEvents(p.trace)).toEqual([]);
  await p.hide(false); await p.old.exposeUsagePanels(); await p.advance(30000); p.check(); expect(usageEvents(p.trace)).toHaveLength(2);
});
it('same-task exact-choice duplicate clicks count two attempts while only one action is dispatched', async () => {
  let release!: (value: LegacyJson) => void; const waiting = new Promise<LegacyJson>(resolve => { release = resolve; });
  const p = await pair({ action: () => waiting });
  await p.click('.bnr-prog-attr-btn[data-attr="vigor"]', '[data-attr="vigor"]', 2);
  expect(p.trace.filter(row => row.path.endsWith('/action'))).toHaveLength(1);
  await act(async () => { release(f.attribute_success.response); await flush(); }); await p.old.settle();
  await p.advance(30000); p.check(); expect(usageEvents(p.trace).find(event => event.kind === 'action_attempt')?.count).toBe(2);
});
it('the synchronous BnrBuilds family guard suppresses the second click before telemetry dispatch', async () => {
  let release!: (value: LegacyJson) => void; const waiting = new Promise<LegacyJson>(resolve => { release = resolve; });
  const p = await pair({ build: f.build_ready, action: () => waiting });
  // Different buttons in one event task must share the legacy family lock.
  for (const key of ['assault', 'marksman']) (p.old.document.querySelector(`[data-bnr-build-spec="${key}"]`) as HTMLElement).click(); await p.old.settle();
  await act(async () => { for (const key of ['assault', 'marksman']) (p.ui.container.querySelector(`[data-bnr-build-spec="${key}"]`) as HTMLElement).click(); await flush(); });
  await act(async () => { release(f.specialization_success.response); await flush(); }); await p.old.settle();
  await p.advance(30000); p.check(); expect(usageEvents(p.trace).find(event => event.kind === 'action_attempt')?.count).toBe(1);
  expect(p.trace.filter(row => row.path.endsWith('/action'))).toHaveLength(1);
});
it('a hung telemetry request never delays a real action, its result or its refresh tail', async () => {
  const p = await pair({ usage: () => new Promise(() => {}) }); await p.advance(30000);
  await p.click('.bnr-prog-attr-btn[data-attr="vigor"]', '[data-attr="vigor"]');
  expect(p.controller.snapshot().busy).toEqual([]); expect(p.trace.filter(row => row.path.endsWith('/action'))).toHaveLength(1);
  await p.advance(3500); p.check(); expect(p.trace.some(row => row.path === '/api/viewer/stats/alice')).toBe(true);
});
it('telemetry exceptions cannot reject or stall the controller action dispatcher', async () => {
  const p = await pair(); vi.spyOn(p.usage, 'trackAction').mockImplementation(() => { throw new Error('optional observer broke'); });
  await p.click('.bnr-prog-attr-btn[data-attr="vigor"]', '[data-attr="vigor"]');
  expect(p.controller.snapshot().busy).toEqual([]); expect(p.controller.snapshot().message).toContain('Заявка на прокачку отправлена');
  await p.advance(3500); p.check();
});
it('real Twitch token re-resolution blocks telemetry and discards the old context on authorization', async () => {
  const p = await pair();
  let resolve!: (response: Response) => void; p.resolver(() => new Promise<Response>(done => { resolve = done; }));
  await act(async () => { p.authorize({ token: 'rotated-token', channelId: 'channel-a', userId: 'opaque-alice' }); await flush(); });
  expect(p.identity.snapshot().status).toBe('resolving'); await act(async () => { await vi.advanceTimersByTimeAsync(30000); await flush(); }); await p.usage.flush();
  expect(usageEvents(p.trace)).toEqual([]);
  await act(async () => { resolve(new Response(JSON.stringify({ error: 'Identity not linked' }), { status: 403 })); await flush(); }); await p.usage.flush(); expect(usageEvents(p.trace)).toEqual([]);
  p.resolver(async () => new Response(JSON.stringify({ login: 'alice' })));
  await act(async () => { await p.identity.retry(); await flush(); }); await act(async () => { await flush(); });
  await p.usage.flush(); expect(usageEvents(p.trace)).toEqual([{ kind: 'panel_view', feature: 'core:panel', count: 1 }, { kind: 'panel_view', feature: 'bannerlord:panel', count: 1 }]);
  expect(p.trace.filter(row => row.path.endsWith('ui-usage')).map(row => row.token)).toEqual(['rotated-token']);
});
