import { act, cleanup, fireEvent, render } from '@testing-library/preact';
import { afterEach, expect, it, vi } from 'vitest';
import { createLegacyHarness, type LegacyRequest, type LegacyFixture } from './panel-legacy-harness';
import { PetsView } from '../src/common/PetsView';
import { ViewerClient } from '../src/common/client';
const pending: (() => void)[] = [];
afterEach(() => { cleanup(); pending.splice(0).forEach(f => f()); vi.useRealTimers(); });
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const hat = { item_id: 'fixture_hat', name: 'Шапка', slot: 'head', rarity: 'rare', emoji: '🎩', svg_path: '', png_path: '' };
const skin = { item_id: 'skin_fixture', name: 'Лягушка', slot: 'body', rarity: 'rare', emoji: '', svg_path: '', png_path: '/pet-assets/v2/frog_samurai/south.png' };
const gem = { item_id: 'fixture_gem', name: 'Огонёк', slot: 'aura', rarity: 'epic', emoji: '', svg_path: '<circle cx="90" cy="90" r="20"/>', png_path: '', price_crustics: 12345, owned: false };
async function pair(refused = false, missingPrice = false, unknownSlot = false) {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  const trace: LegacyRequest[] = [];
  const routes: Record<string, LegacyFixture> = {
    'GET /api/pet/my': { success: true, username: 'alice', pet: { pet_type: 'creature', name: 'Друг' }, inventory: [hat, skin, { ...hat, item_id: 'fixture_spare', name: 'Запасная шапка' }], equipped: { head: hat, body: skin, ...(unknownSlot ? { future_slot: { ...hat, name: 'Будущий аксессуар' } } : {}) } },
    'GET /api/pet/catalog': { success: true, items: [{ ...hat, owned: true, price_crustics: 7890 }, { ...skin, owned: false, price_crustics: 9999 }, { ...gem, ...(missingPrice ? { price_crustics: null } : {}) }] },
    'POST /api/pet/name': { success: true, updated: true, name: 'Звезда' },
    'POST /api/pet/equip': { success: true, message: 'Готово' },
    'POST /api/pet/purchase': refused ? { success: false, message: 'Новая причина сервера' } : { success: true, price: 12345, hatched: true, message: 'Питомец вылупился' },
  };
  const old = createLegacyHarness({}, { commonHost: true, extraRoutes: routes }); pending.push(old.dispose);
  const fetcher: typeof fetch = async (input, init = {}) => {
    const u = new URL(String(input), 'https://fixture.invalid'), h = new Headers(init.headers), rawBody = init.body == null ? null : String(init.body);
    trace.push({ method: init.method || 'GET', path: u.pathname, query: u.search, rawBody, body: rawBody ? JSON.parse(rawBody) : null, token: h.get('X-Twitch-JWT') || '', contentType: h.get('Content-Type') || '', cache: init.cache || null });
    const data = routes[`${init.method || 'GET'} ${u.pathname}${u.search}`]; if (data === undefined) throw new Error('Unmatched pet route ' + u.pathname);
    return new Response(JSON.stringify(data));
  };
  const client = new ViewerClient({ login: 'alice', token: 'alice-token', channelId: '123' }, '', fetcher); pending.push(() => client.dispose());
  await old.openCommon('openPetsModal'); const ui = render(<PetsView client={client} />); await act(flush);
  return { old, ui, trace, routes, async click(oldSelector: string, label: string) { await old.click(oldSelector); await act(async () => { ui.getByRole('button', { name: label, exact: true }).click(); await flush(); }); }, async advance(ms: number) { await old.advance(ms); await act(async () => { await vi.advanceTimersByTimeAsync(ms); await flush(); }); }, check() { expect(trace).toEqual(old.trace); } };
}
it('pets load both server catalogs and unequip the displayed slot with exact legacy bytes and refreshes', async () => {
  const p = await pair(); p.check(); await p.click('[data-pet-action="unequip"][data-slot="head"]', 'Снять Шапка'); await p.advance(600); p.check();
});
it('pets rename preserves trimmed name body and both refresh requests', async () => {
  const p = await pair(); p.old.window.prompt = () => '  Звезда  ';
  await p.old.click('[data-pet-action="rename"]');
  await act(async () => { fireEvent.input(p.ui.getByLabelText('Имя питомца'), { target: { value: '  Звезда  ' } }); });
  await act(async () => { p.ui.getByRole('button', { name: 'Сохранить имя' }).click(); await flush(); }); p.check();
});
it('pets purchase confirms server price before the exact legacy item and hatch refreshes', async () => {
  const p = await pair(); await p.click('#pets-tab-catalog', 'Магазин питомцев');
  await act(async () => { p.ui.getByRole('button', { name: 'Купить Огонёк' }).click(); });
  expect(p.trace.some(q => q.method === 'POST')).toBe(false); expect(p.ui.getByRole('dialog').textContent).toContain('12 345');
  await p.old.click('[data-pet-action="buy"][data-item-id="fixture_gem"]');
  await act(async () => { p.ui.getByRole('button', { name: 'Подтвердить' }).click(); await flush(); }); await p.advance(1800); p.check();
  expect(p.ui.getByRole('status').textContent).toContain('Питомец вылупился');
});
it('pet purchase cancellation never sends a write', async () => {
  const p = await pair(); await p.click('#pets-tab-catalog', 'Магазин питомцев');
  await act(async () => { p.ui.getByRole('button', { name: 'Купить Огонёк' }).click(); });
  await act(async () => { p.ui.getByRole('button', { name: 'Отмена' }).click(); }); p.check();
});
it('pets preserve unknown server purchase refusal without success refreshes', async () => {
  const p = await pair(true); await p.click('#pets-tab-catalog', 'Магазин питомцев');
  await p.old.click('[data-pet-action="buy"][data-item-id="fixture_gem"]');
  await act(async () => { p.ui.getByRole('button', { name: 'Купить Огонёк' }).click(); });
  await act(async () => { p.ui.getByRole('button', { name: 'Подтвердить' }).click(); await flush(); }); await p.advance(400); p.check();
  expect(p.ui.getByRole('status').textContent).toContain('Новая причина сервера');
});
it('pet stage uses server skin asset and shows every occupied slot, including unknown slots', async () => {
  const p = await pair(false, false, true); expect((p.ui.getByAltText('Питомец') as HTMLImageElement).getAttribute('src')).toBe(skin.png_path);
  expect(p.ui.getByRole('button', { name: 'Снять Будущий аксессуар' })).toBeTruthy();
});
it('pets equip keeps exact owned item and the two legacy refreshes', async () => {
  const p = await pair(); await p.click('[data-pet-action="equip"][data-item-id="fixture_spare"]', 'Надеть Запасная шапка'); await p.advance(600); p.check();
});
it('pets never replace a missing server price with an invented free purchase', async () => {
  const p = await pair(false, true); await p.click('#pets-tab-catalog', 'Магазин питомцев');
  expect((p.ui.getByRole('button', { name: 'Купить Огонёк' }) as HTMLButtonElement).disabled).toBe(true); p.check();
});
