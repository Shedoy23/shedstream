import { useEffect, useState } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/preact';
import { TwitchAuthStore } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { PanelApp } from '../src/panel/PanelApp';
import { PanelController } from '../src/panel/controller';
import { HttpPanelTransport } from '../src/panel/transport';
import { legacyResponses as f } from './panel-legacy-harness';
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
afterEach(() => { cleanup(); vi.useRealTimers(); });
async function setup() {
  vi.useFakeTimers(); const trace: string[] = [];
  const routes: Record<string, unknown> = { '/api/user/resolve-twitch-token': { login: 'alice' }, '/api/bannerlord/config': f.config,
    '/api/bannerlord/my-hero': f.hero, '/api/bannerlord/classes': f.classes, '/api/bannerlord/build': f.build_ready,
    '/api/bannerlord/my-buffs': f.buffs, '/api/bannerlord/equipment-shop': f.equipment_inventory };
  const fetcher = (async (url: string) => { trace.push(url); if (!(url in routes)) throw Error('UNMATCHED ' + url); return new Response(JSON.stringify(routes[url])); }) as typeof fetch;
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
  await act(async () => { authorize({ token: 'alice-token', userId: 'opaque-alice', channelId: 'channel-a' }); await flush(); ui = render(<PanelApp controller={controller} identity={identity} Equipment={Equipment} />); await flush(); });
  return { ui, trace, routes, authorize, controller, detach, async click(name: string) { await act(async () => { ui.getByRole('button', { name }).click(); await flush(); }); } };
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
