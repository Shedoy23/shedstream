import { act, cleanup, render } from '@testing-library/preact';
import { afterEach, expect, it } from 'vitest';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import type { TwitchAuthorization, TwitchHelper } from '../src/auth';
import { ConfigApp } from '../src/config/ConfigApp';
const { JSDOM } = createRequire(import.meta.url)('jsdom');
const legacy = (path: string) => readFileSync(new URL('../../Расширение/frontend/' + path, import.meta.url), 'utf8');
type Row = { method: string; path: string; query: string; body: string | null; token: string | null; contentType: string | null };
const drains: (() => void)[] = [];
afterEach(() => { cleanup(); drains.splice(0).forEach(f => f()); });
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
async function pair(status = 200, reply: unknown = { success: true, enabled: false }) {
  const oldTrace: Row[] = [], trace: Row[] = [];
  const fetcher = (rows: Row[]): typeof fetch => async (input, init = {}) => {
    const url = new URL(String(input), 'https://fixture.invalid'), headers = new Headers(init.headers);
    rows.push({ method: init.method || 'GET', path: url.pathname, query: url.search, body: init.body == null ? null : String(init.body), token: headers.get('X-Twitch-JWT'), contentType: headers.get('Content-Type') });
    if (url.pathname === '/api/overlay/pets') return new Response(JSON.stringify({ enabled: true }));
    if (url.pathname === '/api/streamer/pets/overlay-toggle') return new Response(JSON.stringify(reply), { status });
    throw new Error('Unmatched config route ' + url.pathname);
  };
  const dom = new JSDOM(legacy('config.html'), { url: 'https://fixture.invalid/config.html', runScripts: 'outside-only' });
  drains.push(() => dom.window.close());
  let oldAuth!: (a: TwitchAuthorization) => void, authorize!: typeof oldAuth;
  dom.window.Twitch = { ext: { onAuthorized: (cb: typeof oldAuth) => { oldAuth = cb; } } };
  dom.window.fetch = fetcher(oldTrace);
  vm.runInContext(legacy('config.js'), dom.getInternalVMContext());
  const helper: TwitchHelper = { onAuthorized: cb => { authorize = cb; } };
  const ui = render(<ConfigApp helper={helper} baseUrl="" fetcher={fetcher(trace)} />);
  const auth = { token: 'config-fixture-token', channelId: '123', userId: 'fixture-broadcaster' };
  oldAuth(auth); await act(async () => { authorize(auth); await flush(); });
  return { dom, ui, trace, oldTrace, async toggle() { dom.window.document.getElementById('pets-toggle-btn').click(); await act(async () => { ui.getByRole('button', { name: 'Выключить' }).click(); await flush(); }); }, check() { expect(trace).toEqual(oldTrace); } };
}
it('streamer config executes unchanged legacy read and exact toggle bytes', async () => {
  const p = await pair(); p.check(); await p.toggle(); p.check();
  expect(p.ui.getByText('Сохранено')).toBeTruthy(); expect(p.ui.getByRole('button', { name: 'Включить' })).toBeTruthy();
});
for (const code of [401, 403]) it(`streamer config preserves broadcaster refusal ${code}`, async () => {
  const p = await pair(code); await p.toggle(); p.check(); expect(p.ui.getByText('Открой настройки от имени бродкастера канала')).toBeTruthy();
});
it('streamer config displays an unknown server refusal verbatim', async () => {
  const p = await pair(200, { success: false, message: 'Новая причина сервера: maintenance-42' }); await p.toggle(); p.check();
  expect(p.ui.getByText('Новая причина сервера: maintenance-42')).toBeTruthy();
});
it('streamer config cannot repaint the new channel with an older public read', async () => {
  let authorize!: (a: TwitchAuthorization) => void, release!: (r: Response) => void;
  const pending = new Promise<Response>(resolve => { release = resolve; });
  const helper = { onAuthorized: (cb: typeof authorize) => { authorize = cb; } };
  const fetcher: typeof fetch = async input => String(input).endsWith('channel_id=123') ? pending : new Response(JSON.stringify({ enabled: false }));
  const ui = render(<ConfigApp helper={helper} fetcher={fetcher} />);
  await act(async () => { authorize({ token: 'a', channelId: '123', userId: 'a' }); await flush(); });
  await act(async () => { authorize({ token: 'b', channelId: '456', userId: 'b' }); await flush(); });
  await act(async () => { release(new Response(JSON.stringify({ enabled: true }))); await flush(); });
  expect(ui.getByRole('button', { name: 'Включить' })).toBeTruthy();
});
it('streamer config does not turn a malformed read into an actionable disabled setting', async () => {
  let authorize!: (a: TwitchAuthorization) => void;
  const helper = { onAuthorized: (cb: typeof authorize) => { authorize = cb; } };
  const ui = render(<ConfigApp helper={helper} fetcher={async () => new Response(JSON.stringify({ message: 'Снимок недоступен' }))} />);
  await act(async () => { authorize({ token: 'a', channelId: '123', userId: 'a' }); await flush(); });
  expect((ui.getByRole('button') as HTMLButtonElement).disabled).toBe(true);
  expect(ui.getByText('Снимок недоступен')).toBeTruthy();
});
