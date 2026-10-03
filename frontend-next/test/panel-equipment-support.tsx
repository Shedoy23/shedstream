import gameFixtures from './panel-fixtures/game-progression-responses.json';
import { act, fireEvent, render } from '@testing-library/preact';
import { vi } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { HttpPanelTransport } from '../src/panel/transport';
import { PanelController } from '../src/panel/controller';
import { PanelApp } from '../src/panel/PanelApp';
import { EquipmentView } from '../src/panel/EquipmentView';
import fixtures from './panel-fixtures/real-responses.json';
export const f = fixtures.responses;
export const flush = async () => { for (let n = 0; n < 40; n++) await Promise.resolve(); };
export const response = (body: unknown) => new Response(JSON.stringify(body));
export const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { resolve, promise }; };
export interface Trace { method: string; path: string; body: Record<string, any> | null; rawBody: string | null; token: string; query: string; contentType: string; cache: string | null }
export function equipmentSetup(snapshot: unknown = f.equipment_inventory, actionReply: unknown = f.equipment_buy.response) {
  const trace: Trace[] = [];
  const routes: Record<string, unknown> = {
    '/api/user/resolve-twitch-token': { login: 'alice' }, '/api/bannerlord/content-catalogs': gameFixtures.responses.catalogs, '/api/bannerlord/progression': gameFixtures.responses.progression, '/api/bannerlord/config': f.config,
    '/api/bannerlord/my-hero': f.hero, '/api/bannerlord/classes': f.classes,
    '/api/bannerlord/build': f.build_ready, '/api/bannerlord/my-buffs': f.buffs,
    '/api/bannerlord/equipment-shop': snapshot, '/api/bannerlord/action': actionReply,
    '/api/viewer/stats/alice': f.stats, '/api/user/level/alice': f.level, '/api/duel/list': f.duels,
    '/api/viewer/stats/carol': { points: 200 }, '/api/user/level/carol': {},
  };
  const fetcher = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url); const method = init?.method || 'GET';
    trace.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : null, rawBody: init?.body == null ? null : String(init.body), token: new Headers(init?.headers).get('X-Twitch-JWT') || '', query: new URL(path, 'https://example.test').search, contentType: new Headers(init?.headers).get('Content-Type') || '', cache: init?.cache || null });
    if (!(path in routes)) throw new Error(`UNMATCHED ${method} ${path}`);
    const body = routes[path]; if (typeof body === 'function') return body();
    return body instanceof Promise ? body : response(body);
  }) as unknown as typeof fetch;
  const auth = new TwitchAuthStore(); let authorize!: (value: { token: string; userId: string; channelId: string }) => void;
  const identity = new IdentityBootstrap(auth, '', fetcher);
  const detach = identity.attach({ onAuthorized: callback => { authorize = callback; } });
  const controller = new PanelController(new HttpPanelTransport('', auth, fetcher, () => 'test-id'), auth, identity);
  let refresh!: () => void | Promise<unknown>;
  const register = controller.registerEquipmentRefresh.bind(controller);
  vi.spyOn(controller, 'registerEquipmentRefresh').mockImplementation(callback => { refresh = callback; return register(callback); });
  return { trace, routes, auth, identity, controller, authorize, detach,
    async start(active = true, host = false) {
      authorize({ token: 'alice-token', userId: 'opaque-alice', channelId: 'channel-a' }); await flush(); await controller.start(); await flush(); trace.length = 0;
      let ui!: ReturnType<typeof render>; await act(async () => { ui = render(host ? <PanelApp controller={controller} identity={identity} Equipment={EquipmentView} /> : <EquipmentView controller={controller} active={active} />); await flush(); });
      return ui;
    },
    async setActive(ui: ReturnType<typeof render>, active: boolean) { await act(async () => { ui.rerender(<EquipmentView controller={controller} active={active} />); await flush(); }); },
    beginRefresh() { return refresh(); },
    async refresh() { await act(async () => { await refresh(); await flush(); }); },
    async switchIdentity() { await act(async () => { routes['/api/user/resolve-twitch-token'] = { login: 'carol' }; authorize({ token: 'carol-token', userId: 'opaque-carol', channelId: 'channel-a' }); await flush(); }); },
  };
}
export async function click(root: ParentNode, selector: string) {
  const target = root.querySelector(selector); if (!target) throw new Error(`Missing control ${selector}`);
  await act(async () => { fireEvent.click(target); await flush(); });
}
export async function change(root: ParentNode, selector: string, value: string) {
  const target = root.querySelector(selector); if (!target) throw new Error(`Missing control ${selector}`);
  await act(async () => { (target as HTMLSelectElement).value = value; target.dispatchEvent(new Event('change', { bubbles: true })); await flush(); });
}
