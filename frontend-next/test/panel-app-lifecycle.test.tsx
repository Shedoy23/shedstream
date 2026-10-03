import gameFixtures from './panel-fixtures/game-progression-responses.json';
import { useEffect, useState } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/preact';
import { TwitchAuthStore } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { PanelApp } from '../src/panel/PanelApp';
import { EquipmentView } from '../src/panel/EquipmentView';
import { PanelController } from '../src/panel/controller';
import { HttpPanelTransport } from '../src/panel/transport';
import { createLegacyHarness, legacyResponses as f, type LegacyRequest } from './panel-legacy-harness';
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
afterEach(() => { cleanup(); Object.defineProperty(document, 'hidden', { configurable: true, value: false }); vi.useRealTimers(); });
async function setup(realEquipment = false) {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] }); const trace: string[] = []; const requests: LegacyRequest[] = [];
  const routes: Record<string, unknown> = { '/api/user/resolve-twitch-token': { login: 'alice' }, '/api/bannerlord/content-catalogs': gameFixtures.responses.catalogs, '/api/bannerlord/progression': gameFixtures.responses.progression, '/api/bannerlord/config': f.config,
    '/api/bannerlord/my-hero': f.hero, '/api/bannerlord/classes': f.classes, '/api/bannerlord/build': f.build_ready,
    '/api/bannerlord/my-buffs': f.buffs, '/api/bannerlord/equipment-shop': f.equipment_inventory,
    '/api/bannerlord/action': f.attribute_success.response, '/api/viewer/stats/alice': f.stats, '/api/user/level/alice': f.level, '/api/duel/list': f.duels };
  const fetcher = (async (url: string, init: RequestInit = {}) => { trace.push(url); const headers = new Headers(init.headers); const rawBody = init.body == null ? null : String(init.body); requests.push({ method: init.method || 'GET', path: url, query: '', rawBody, body: rawBody ? JSON.parse(rawBody) : null, token: headers.get('X-Twitch-JWT') || '', contentType: headers.get('Content-Type') || '', cache: init.cache || null }); if (!(url in routes)) throw Error('UNMATCHED ' + url); return new Response(JSON.stringify(routes[url])); }) as typeof fetch;
  const auth = new TwitchAuthStore(); let authorize!: (a: { token: string; userId: string; channelId: string }) => void;
  const identity = new IdentityBootstrap(auth, '', fetcher); const detach = identity.attach({ onAuthorized: callback => { authorize = callback; } });
  const controller = new PanelController(new HttpPanelTransport('', auth, fetcher), auth, identity);
  function Equipment({ controller, active = true }: { controller: PanelController; active?: boolean }) {
    const [value, setValue] = useState('');
    useEffect(() => { const refresh = () => active ? controller.read('/api/bannerlord/equipment-shop') : undefined;
      const unregister = controller.registerEquipmentRefresh(refresh); if (active && controller.ready()) void refresh(); return unregister;
    }, [controller, active]);
    return <input aria-label="Equipment editor" value={value} onInput={e => setValue(e.currentTarget.value)} />;
  }
  let ui!: ReturnType<typeof render>;
  await act(async () => { authorize({ token: 'alice-token', userId: 'opaque-alice', channelId: 'channel-a' }); await flush(); trace.length = 0; requests.length = 0; ui = render(<PanelApp controller={controller} identity={identity} Equipment={realEquipment ? EquipmentView : Equipment} />); await flush(); });
  await act(async () => { await flush(); });
  return { ui, trace, requests, routes, authorize, controller, detach, async click(name: string) { await act(async () => { ui.getByRole('button', { name }).click(); await flush(); }); await act(async () => { await flush(); }); } };
}
it('equipment loads on tab entry and polls only while that actual tab is active', async () => {
  const s = await setup(); expect(s.trace.filter(p => p.endsWith('equipment-shop'))).toHaveLength(0);
  await act(async () => { await vi.advanceTimersByTimeAsync(8000); await flush(); });
  expect(s.trace.filter(p => p.endsWith('equipment-shop'))).toHaveLength(0);
  await s.click('Снаряжение'); expect(s.trace.filter(p => p.endsWith('equipment-shop'))).toHaveLength(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(8000); await flush(); });
  expect(s.trace.filter(p => p.endsWith('equipment-shop'))).toHaveLength(2);
  await s.click('Развитие'); await act(async () => { await vi.advanceTimersByTimeAsync(8000); await flush(); });
  expect(s.trace.filter(p => p.endsWith('equipment-shop'))).toHaveLength(2);
  await s.click('Снаряжение'); expect(s.trace.filter(p => p.endsWith('equipment-shop'))).toHaveLength(3); s.detach();
});
it('preserves editor DOM through tab switches and same-user token refresh, clears it across identities', async () => {
  const s = await setup(); await s.click('Снаряжение');
  const input = s.ui.getByRole('textbox', { name: 'Equipment editor' }) as HTMLInputElement;
  await act(async () => { input.value = 'Sword'; input.dispatchEvent(new Event('input', { bubbles: true })); await flush(); });
  await s.click('Развитие'); await s.click('Снаряжение'); expect(s.ui.getByRole('textbox')).toBe(input); expect(input.value).toBe('Sword');
  await act(async () => { s.authorize({ token: 'rotated', userId: 'opaque-alice', channelId: 'channel-a' }); await flush(); });
  expect(s.ui.getByRole('textbox')).toBe(input); expect(input.value).toBe('Sword');
  await act(async () => { s.routes['/api/user/resolve-twitch-token'] = { login: 'carol' }; s.authorize({ token: 'carol', userId: 'opaque-carol', channelId: 'channel-a' }); await flush(); });
  expect(s.ui.getByRole('textbox')).not.toBe(input); expect((s.ui.getByRole('textbox') as HTMLInputElement).value).toBe(''); s.detach();
});
it('changing tabs midway through a polling period does not restart the shared clock', async () => {
  const s = await setup(); await act(async () => { await vi.advanceTimersByTimeAsync(3000); await flush(); });
  await s.click('Снаряжение'); expect(s.trace.filter(p => p.endsWith('equipment-shop'))).toHaveLength(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); await flush(); });
  expect(s.trace.filter(p => p.endsWith('equipment-shop'))).toHaveLength(2);
  expect(s.trace.filter(p => p.endsWith('my-buffs'))).toHaveLength(4); s.detach();
});

it('actual PanelApp tab/timer requests match unchanged old tab handlers with the same selected-host lifecycle', async () => {
  const s = await setup(true); const old = createLegacyHarness({}, { panelLifecycle: true });
  try {
    await old.bootHero(); expect(s.requests).toEqual(old.trace);
    async function advance(ms: number) { await old.advance(ms); await act(async () => { await vi.advanceTimersByTimeAsync(ms); await flush(); }); expect(s.requests).toEqual(old.trace); }
    async function tab(oldTab: string, name: string) { await old.click(`[data-bnr-tab="${oldTab}"]`); await s.click(name); expect(s.requests).toEqual(old.trace); }
    await advance(3000); await tab('inventory', 'Снаряжение'); await advance(5000);
    await tab('hero', 'Развитие'); await advance(8000); await tab('inventory', 'Снаряжение');
    await advance(1500); await tab('hero', 'Развитие'); await advance(6500);
    expect(old.sourceFiles).toHaveLength(23);
  } finally { old.dispose(); s.detach(); }
});

it('the actual equipment search editor survives auth refresh and is cleared for the next viewer', async () => {
  const s = await setup(true); await s.click('Снаряжение');
  const input = s.ui.getByRole('searchbox', { name: 'Найти вещь' }) as HTMLInputElement;
  await act(async () => { input.focus(); input.value = 'Sword'; input.dispatchEvent(new Event('input', { bubbles: true })); input.setSelectionRange(1, 3); await flush(); });
  await act(async () => { s.authorize({ token: 'rotated', userId: 'opaque-alice', channelId: 'channel-a' }); await flush(); });
  expect(s.ui.getByRole('searchbox')).toBe(input); expect(input.value).toBe('Sword');
  expect(document.activeElement).toBe(input); expect([input.selectionStart, input.selectionEnd]).toEqual([1, 3]);
  await act(async () => { s.routes['/api/user/resolve-twitch-token'] = { login: 'carol' }; s.authorize({ token: 'carol', userId: 'opaque-carol', channelId: 'channel-a' }); await flush(); });
  await act(async () => { await flush(); });
  expect(s.ui.getByRole('searchbox')).not.toBe(input); expect((s.ui.getByRole('searchbox') as HTMLInputElement).value).toBe(''); s.detach();
});

for (const action of ['purchase', 'refresh'] as const) it(`both mounted screens preserve hidden equipment reads on hero ${action}`, async () => {
  const s = await setup(true), old = createLegacyHarness({}, { panelLifecycle: true });
  const normalize = (rows: LegacyRequest[]) => rows.map(({ rawBody, ...row }) => {
    const body = structuredClone(row.body) as { data?: { client_action_id?: string } } | null;
    if (body?.data?.client_action_id) { rawBody=rawBody!.replace(JSON.stringify(body.data.client_action_id),JSON.stringify('<random-id>')); body.data.client_action_id = '<random-id>'; }
    return { ...row, body, rawBody };
  });
  try {
    await old.bootHero(); expect(normalize(s.requests)).toEqual(normalize(old.trace));
    if (action === 'purchase') {
      await old.click('.bnr-prog-attr-btn[data-attr="vigor"]');
      await act(async () => { (s.ui.container.querySelector('[data-attr="vigor"]') as HTMLElement).click(); await flush(); });
      await s.click('Подтвердить');
      await old.advance(3500); await act(async () => { await vi.advanceTimersByTimeAsync(3500); await flush(); });
    } else {
      const button = old.document.createElement('button'); button.id = 'refresh-hero-btn'; old.document.body.append(button);
      await old.click('#refresh-hero-btn'); await s.click('Обновить');
    }
    expect(normalize(s.requests), 'all requests with hidden but mounted equipment host').toEqual(normalize(old.trace));
    expect(s.requests.filter(row => row.path.endsWith('equipment-shop'))).toHaveLength(1);
    expect(s.ui.getByRole('button', { name: 'Развитие' }).getAttribute('aria-pressed')).toBe('true');
  } finally { old.dispose(); s.detach(); }
});

it('hidden document suspends selected-host reads and visibility resumes the existing polling phase', async () => {
  const s = await setup(true), old = createLegacyHarness({}, { panelLifecycle: true });
  const visible = async (hidden: boolean) => { await old.setHidden(hidden); await act(async () => { Object.defineProperty(document, 'hidden', { configurable: true, value: hidden }); document.dispatchEvent(new Event('visibilitychange')); await flush(); }); };
  try {
    await old.bootHero(); expect(s.requests).toEqual(old.trace);
    await visible(true); await old.advance(8000); await act(async () => { await vi.advanceTimersByTimeAsync(8000); await flush(); });
    expect(s.requests).toEqual(old.trace);
    await visible(false); expect(s.requests).toEqual(old.trace);
    await old.advance(8000); await act(async () => { await vi.advanceTimersByTimeAsync(8000); await flush(); }); expect(s.requests).toEqual(old.trace);
  } finally { old.dispose(); s.detach(); }
});
