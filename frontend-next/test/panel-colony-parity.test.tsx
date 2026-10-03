import { act, cleanup, render, fireEvent } from '@testing-library/preact';
import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createLegacyHarness, legacyResponses, type LegacyRequest, type LegacyFixture } from './panel-legacy-harness';
import { ColonyView } from '../src/colony/ColonyView';
import { ViewerClient } from '../src/common/client';
import { PanelUsage } from '../src/panel/usage';
import { TwitchAuthStore } from '../src/auth';
import type { IdentityBootstrap } from '../src/skillgames/identity';
const source = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../Расширение/frontend/viewer-shedcolony.js'), 'utf8');
// Independent action enumeration comes from the frozen legacy source, not new UI.
const actions = [...source.matchAll(/^\s+(\w+):\s*\{ type: '([^']+)',\s*price: \d+ \},/gm)].map(m => ({ kind: m[1], type: m[2] }));
const pending: (() => void)[] = [];
afterEach(() => { cleanup(); pending.splice(0).forEach(f => f()); vi.useRealTimers(); });
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
export const colonyConfig = { action_prices: Object.fromEntries(actions.map((a, i) => [a.type, 1200 + i * 37])), item_catalog: { give_item: [['minecraft:bread', 'Хлеб']], supply: [['minecraft:oak_log', 'Брёвна']], min_stock: [['minecraft:torch', 'Факелы']] } };
export const colonistFixture = { success: true, linked: true, citizen_id: 41, name: 'Алиса', job: 'knight', hp: 12, skills: { Athletics: 5, Strength: 8 }, status: 'working', state: { job: 'knight', hp: 12, max_hp: 20, saturation: 30, sick: true, happiness: 5, has_home: false, requests: [{ id: 'req-A', text: 'Нужен хлеб', deliverable: true }] } };
export const capacityFixture = { success: true, jobs: [{ job: 'farmer', free: 2, total: 3 }], free_beds: 3, stale: false, data_age_sec: 1, targets: { researches: [{ branch: 'technology', id: 'mining/one', name: 'Копка', state: 'available' }, { branch: 'civilian', id: 'farm/two', name: 'Ферма', state: 'in_progress' }], buildings: [{ pos: '1,2,3', type: 'builder', backlog: 2 }], min_stock: { warehouse: true }, can_build: true, upgradable: [{ pos: '4,5,6', type: 'warehouse', level: 1, in_progress: false }] } };
async function pair(kind = 'heal', refused = false) {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] }); vi.setSystemTime(Date.UTC(2026, 9, 2, 12));
  const trace: LegacyRequest[] = [];
  const citizen = kind === 'spawn' ? { success: true, linked: false } : kind === 'auto_work' ? { ...colonistFixture, job: 'farmer', state: { ...colonistFixture.state, job: 'farmer' } } : colonistFixture;
  const stats = { ...legacyResponses.stats, active_module: 'shedcolony' };
  const routes: Record<string, LegacyFixture> = {
    'GET /api/shedcolony/config': colonyConfig, 'GET /api/shedcolony/my-colonist': citizen, 'GET /api/shedcolony/capacity': capacityFixture,
    'POST /api/shedcolony/action': refused ? { success: false, message: 'Причина отказа сервера' } : { success: true, action_id: 'fixture-queued', message: 'Принято', charged: 1200 },
    'GET /api/viewer/stats/alice': stats, 'GET /api/user/level/alice': legacyResponses.level, 'GET /api/duel/list': legacyResponses.duels, 'POST /api/viewer/ui-usage': legacyResponses.usage_ok,
  };
  const old = createLegacyHarness({ stats, usage: legacyResponses.usage_ok }, { gameHost: 'shedcolony', extraRoutes: routes }); pending.push(old.dispose);
  const fetcher: typeof fetch = async (input, init = {}) => {
    const u = new URL(String(input), 'https://fixture.invalid'), h = new Headers(init.headers), rawBody = init.body == null ? null : String(init.body);
    trace.push({ method: init.method || 'GET', path: u.pathname, query: u.search, rawBody, body: rawBody ? JSON.parse(rawBody) : null, token: h.get('X-Twitch-JWT') || '', contentType: h.get('Content-Type') || '', cache: init.cache || null, ...(init.keepalive === undefined ? {} : { keepalive: init.keepalive }) });
    const data = routes[`${init.method || 'GET'} ${u.pathname}${u.search}`]; if (data === undefined) throw new Error('Unmatched colony route ' + u.pathname);
    return new Response(JSON.stringify(data));
  };
  const auth = new TwitchAuthStore(); auth.authorize({ token: 'alice-token', channelId: '123', userId: 'alice' });
  const gate = { status: 'ready', login: 'alice' }; const identity = { subscribe: () => () => {}, snapshot: () => gate } as unknown as IdentityBootstrap;
  const usage = new PanelUsage({ auth, identity, baseUrl: '', surface: 'desktop', fetcher }); usage.start(); pending.push(() => usage.stop());
  const client = new ViewerClient({ login: 'alice', token: 'alice-token', channelId: '123' }, '', fetcher, () => true, feature => usage.trackAction(feature)); pending.push(() => client.dispose());
  await old.bootGame(); usage.trackPanel('core'); const ui = render(<ColonyView client={client} />); await act(flush);
  const normalize = (rows: LegacyRequest[]) => rows.map(q => ({ ...q, body: JSON.stringify(q.body).replace(/("(?:client_action_id|batch_id)":)"[^"\\]*"/g, '$1"<generated>"'), rawBody: q.rawBody?.replace(/("(?:client_action_id|batch_id)":)"[^"\\]*"/g, '$1"<generated>"') ?? null }));
  return { old, ui, trace, routes, async choose(selector: string, value: string) { await old.change(selector, value); await act(async () => { fireEvent.input(ui.container.querySelector(selector)!, { target: { value } }); }); }, async advance(ms: number) { await old.advance(ms); await act(async () => { await vi.advanceTimersByTimeAsync(ms); await flush(); }); }, async buy() { await act(async () => { (ui.container.querySelector(`[data-sc="${kind}"]`) as HTMLButtonElement).click(); }); expect(ui.getByRole('dialog')).toBeTruthy(); await old.click(`[data-sc="${kind}"]`); await act(async () => { ui.getByRole('button', { name: 'Подтвердить' }).click(); await flush(); }); }, check() { expect(normalize(trace)).toEqual(normalize(old.trace)); } };
}
for (const action of actions) it(`colony ${action.kind}: exact legacy POST plus all startup, balance, polling and telemetry traffic`, async () => {
  const p = await pair(action.kind); p.check(); await p.buy(); await p.advance(30000); p.check();
  expect(p.ui.getByRole('status').textContent).toContain('Заявка принята');
});
it('colony server refusal remains visible with no success refresh', async () => {
  const p = await pair('heal', true); await p.buy(); await p.advance(30000); p.check(); expect(p.ui.getByRole('status').textContent).toContain('Причина отказа сервера');
});
it('colony keeps selected skill through a snapshot poll', async () => {
  const p = await pair('xp'); await p.choose('#sc-skill-select', 'Strength'); await p.advance(5000); await p.buy(); p.check();
});
it('colony invalidates confirmation when its building disappears from a newer snapshot', async () => {
  const p = await pair('upgrade_building');
  await act(async () => { (p.ui.container.querySelector('[data-sc="upgrade_building"]') as HTMLButtonElement).click(); });
  p.routes['GET /api/shedcolony/capacity'] = { ...capacityFixture, targets: { ...capacityFixture.targets, upgradable: [] } };
  await p.advance(5000); expect(p.ui.queryByRole('dialog')).toBeNull(); expect(p.trace.some(q => q.path === '/api/shedcolony/action')).toBe(false); p.check();
});
