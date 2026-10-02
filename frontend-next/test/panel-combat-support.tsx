import { act, cleanup, render } from '@testing-library/preact';
import { afterEach, beforeEach, expect, vi } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { PanelApp } from '../src/panel/PanelApp';
import { EquipmentView } from '../src/panel/EquipmentView';
import { PanelController } from '../src/panel/controller';
import { HttpPanelTransport } from '../src/panel/transport';
import { PanelUsage } from '../src/panel/usage';
import { createLegacyHarness, legacyResponses as f, combatResponses as c, type LegacyFixtures, type LegacyJson, type LegacyRequest, type LegacyHttpReply } from './panel-legacy-harness';

export const now = Date.UTC(2026, 9, 2, 12), drains: (() => void)[] = [];
export const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
beforeEach(() => { vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] }); vi.setSystemTime(now); localStorage.clear(); Object.defineProperty(document, 'hidden', { configurable: true, value: false }); });
afterEach(() => { cleanup(); drains.splice(0).forEach(fn => fn()); vi.restoreAllMocks(); vi.useRealTimers(); Object.defineProperty(document, 'hidden', { configurable: true, value: false }); });
export function normalized(trace: LegacyRequest[]) {
  return trace.map(({ rawBody: _rawBody, ...request }) => {
    const body = structuredClone(request.body);
    if (body && typeof body === 'object' && !Array.isArray(body)) {
      if ('batch_id' in body) body.batch_id = '<generated-batch-id>';
      if (body.data && typeof body.data === 'object' && !Array.isArray(body.data) && 'client_action_id' in body.data) body.data.client_action_id = '<generated-action-id>';
    }
    return { ...request, body };
  });
}
export const usageEvents = (trace: LegacyRequest[]) => trace.filter(row => row.path === '/api/viewer/ui-usage').flatMap(row => (row.body as { events: { kind: string; feature: string; count: number }[] }).events);
export async function combatPair(overrides: Partial<LegacyFixtures> = {}, hidden = false, initialTab?: 'combat' | 'hero' | 'inventory' | 'dynasty', retinueHost = false, partyHost = false) {
  if (initialTab) localStorage.setItem('bnr_active_tab', initialTab);
  Object.defineProperty(document, 'hidden', { configurable: true, value: hidden });
  const old = createLegacyHarness({ usage: f.usage_ok, build: c.build_no_session, classes: c.classes_by_key.tank, battle: c.battle_siege, buffs: c.buffs_empty, action: combatAction, ...overrides }, { panelLifecycle: true, combatHost: true, retinueHost, partyHost, initialTab, now }); drains.push(old.dispose);
  if (hidden) await old.setHidden(true);
  await old.bootCombat(); await old.exposeUsagePanels();
  const trace: LegacyRequest[] = [], failures: string[] = [], calls: Record<string, number> = {};
  const routes: Record<string, keyof LegacyFixtures> = {
    'GET /api/bannerlord/config': 'config', 'GET /api/bannerlord/my-hero': 'hero', 'GET /api/bannerlord/classes': 'classes',
    'GET /api/bannerlord/build': 'build', 'GET /api/bannerlord/my-buffs': 'buffs', 'POST /api/bannerlord/action': 'action',
    'GET /api/viewer/stats/alice': 'stats', 'GET /api/user/level/alice': 'level', 'GET /api/duel/list': 'duels',
    'GET /api/bannerlord/party-orders': 'partyOrders', 'GET /api/bannerlord/equipment-shop': 'equipment', 'GET /api/bannerlord/battle-status': 'battle', 'POST /api/viewer/ui-usage': 'usage',
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
  await act(async () => { authorize({ token: 'alice-token', channelId: 'channel-a', userId: 'opaque-alice' }); await flush(); ui = render(<PanelApp controller={controller} identity={identity} Equipment={EquipmentView} {...{ combat: true, party: partyHost }} />); await flush(); });
  await act(async () => { await flush(); });
  const check = () => { expect(failures).toEqual([]); old.assertHealthy(); expect(normalized(trace), 'complete admitted-host request trace, including telemetry and all action/poll tails').toEqual(normalized(old.trace)); };
  if (!partyHost) check();
  return { old, trace, controller, usage, ui, authorize, identity, fixtures: old.fixtures, failures,
    resolver: (fn: () => Promise<Response>) => { resolver = fn; }, check,
    async advance(ms: number) { await old.advance(ms); await act(async () => { await vi.advanceTimersByTimeAsync(ms); await flush(); }); },
    async click(oldSelector: string, newSelector = oldSelector, count = 1) {
      for (let i = 0; i < count; i++) (old.document.querySelector(oldSelector) as HTMLElement).click(); await old.settle();
      await act(async () => { for (let i = 0; i < count; i++) (ui.container.querySelector(newSelector) as HTMLElement).click(); await flush(); }); await act(async () => { await flush(); });
    },
    async tab(tab: 'hero' | 'inventory' | 'combat' | 'dynasty') { await old.click(`[data-bnr-tab="${tab}"]`); await act(async () => { ui.getByRole('button', { name: tab === 'hero' ? 'Развитие' : tab === 'combat' ? 'Боевые действия' : tab === 'dynasty' ? 'Клан, отряд и армия' : 'Снаряжение' }).click(); await flush(); }); await act(async () => { await flush(); }); },
    async hide(value: boolean) { await old.setHidden(value); await act(async () => { Object.defineProperty(document, 'hidden', { configurable: true, value }); document.dispatchEvent(new Event('visibilitychange')); await flush(); }); },
  };
}


function combatAction(request: LegacyRequest): LegacyJson {
  const body = request.body as { action_type: string; data: Record<string, string> };
  const { action_type: type, data } = body;
  const responses = c as unknown as Record<string, { response: LegacyJson }>;
  const key = type === 'hero.set_combat_stance' ? 'stance_' + data.stance
    : type === 'player.spawn' ? 'spawn_' + data.side
    : type === 'hero.select_weapon_power' ? 'select_' + data.weapon_type
    : type === 'power.activate' ? ('price' in data ? 'legacy_power_' + data.power_key : data.power_key === 'heal_burst' ? 'build_heal' : 'build_power_' + c.build_choices.build.power_options.find(p => p.power_key === data.power_key)!.weapon_type)
    : type;
  if (!responses[key]?.response) throw new Error('Unmatched combat action: ' + JSON.stringify(body));
  return responses[key].response;
}
export { c, f };
