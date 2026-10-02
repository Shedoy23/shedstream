import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup } from '@testing-library/preact';
import { createLegacyHarness, legacyHttpReply, type LegacyJson, type LegacyRequest } from './panel-legacy-harness';
import { equipmentSetup, f, click, change, flush, type Trace } from './panel-equipment-support';
const closers: (() => void)[] = [];
afterEach(() => { cleanup(); closers.splice(0).forEach(close => close()); vi.useRealTimers(); });
function normalized(trace: (LegacyRequest | Trace)[]) {
  return trace.map(request => { const body = structuredClone(request.body) as Record<string, any> | null;
    if (body?.data?.client_action_id) body.data.client_action_id = '<client-id>';
    return { method: request.method, path: request.path, query: request.query, body, token: request.token, contentType: request.contentType, cache: request.cache };
  });
}
async function pair(equipment: unknown = f.equipment_inventory, action: unknown = f.equipment_buy.response) {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  const old = createLegacyHarness({ equipment: equipment as LegacyJson, action: action as LegacyJson }, { scope: 'equipment' }); closers.push(old.dispose);
  await old.bootEquipment();
  const next = equipmentSetup(equipment, action); closers.push(() => next.controller.stop());
  next.routes['/api/viewer/stats/alice'] = old.fixtures.stats;
  next.routes['/api/user/level/alice'] = old.fixtures.level;
  next.routes['/api/duel/list'] = old.fixtures.duels;
  const ui = await next.start(); expect(normalized(next.trace)).toEqual(normalized(old.trace));
  return { old, next, ui,
    async click(selector: string) { await old.click(selector); await click(ui.container, selector); },
    async change(selector: string, value: string) { await old.change(selector, value); await change(ui.container, selector, value); },
    async finish() { await old.advance(3600); await act(async () => { await vi.advanceTimersByTimeAsync(3600); await flush(); });
      old.assertHealthy(); expect(normalized(next.trace), 'full unfiltered equipment method/path/query/body/token/header/cache trace').toEqual(normalized(old.trace)); },
  };
}
for (const mode of ['inventory', 'stash'] as const) for (const item of f.equipment_inventory.items) it(`old/new ${mode} buy ${item.item_id} and complete common tail, with no hero tail`, async () => {
  const p = await pair(mode === 'stash' ? f.equipment_stash : f.equipment_inventory); await p.click(`[data-bnr-eq-buy="${item.item_id}"]`); await p.finish();
  expect(p.next.trace.map(r => r.path)).toEqual(['/api/bannerlord/equipment-shop','/api/bannerlord/action','/api/viewer/stats/alice','/api/user/level/alice','/api/duel/list']);
});
for (const item of f.equipment_direct.items) for (const option of item.purchase_options) it(`old/new direct buy ${item.item_id} in ${option.slot} via real danger modal`, async () => {
  const p = await pair(f.equipment_direct, f.equipment_direct_buy.response);
  await p.change(`[data-bnr-eq-purchase-slot="${item.item_id}"]`, option.slot); await p.click(`[data-bnr-eq-buy="${item.item_id}"]`);
  expect(p.old.document.querySelector('#confirm-dyn-modal')).not.toBeNull(); expect(p.ui.container.querySelector('[role="dialog"]')).not.toBeNull();
  expect(p.next.trace.filter(r => r.method === 'POST')).toHaveLength(0);
  await p.click('#confirm-dyn-yes'); await p.finish();
});
for (const row of f.equipment_inventory.inventory.filter(row => !row.slot)) for (const slot of row.slots) it(`old/new exact owned row ${row.owned_id} equip in ${slot}`, async () => {
  const p = await pair(f.equipment_inventory, f.equipment_equip.response); await p.click('[data-bnr-eq-view="owned"]');
  await p.click(`[data-bnr-owned-slot="${slot}"]`); await p.click(`[data-bnr-eq-equip="${row.owned_id}"]`); await p.finish();
});
it('old/new unequip uses slot only', async () => {
  const p = await pair(f.equipment_inventory, f.equipment_unequip.response); await p.click('[data-bnr-eq-view="owned"]'); await p.click('[data-bnr-eq-unequip="weapon0"]'); await p.finish();
});
for (const row of f.equipment_inventory.inventory) it(`old/new discard ${row.owned_id} confirms actual modal and full tail`, async () => {
  const p = await pair(f.equipment_inventory, f.equipment_discard.response); await p.click('[data-bnr-eq-view="owned"]');
  await p.click(`[data-bnr-eq-discard="${row.owned_id}"]`); expect(p.old.document.querySelector('#confirm-dyn-modal')?.textContent).toContain('Динары не вернутся');
  await p.click('#confirm-dyn-yes'); await p.finish();
});
for (const kind of ['direct', 'discard'] as const) for (const control of ['#confirm-dyn-no', '#confirm-dyn-modal']) it(`old/new ${kind} cancellation ${control} sends nothing`, async () => {
  const p = await pair(kind === 'direct' ? f.equipment_direct : f.equipment_inventory);
  if (kind === 'discard') await p.click('[data-bnr-eq-view="owned"]');
  await p.click(kind === 'direct' ? '[data-bnr-eq-buy="sword"]' : '[data-bnr-eq-discard="party|sword|fine"]');
  await p.click(control); await p.finish(); expect(p.next.trace.filter(r => r.method === 'POST')).toHaveLength(0);
});
for (const data of [f.equipment_dead, { ...f.equipment_inventory, pending: true }, { ...f.equipment_inventory, can_manage: false }]) it(`old/new blocked state ${data.reason || (data.pending ? 'pending' : 'forbidden')} has zero POST`, async () => {
  const p = await pair(data); await p.click('[data-bnr-eq-buy="sword"]'); await p.click('[data-bnr-eq-view="owned"]');
  await p.click('[data-bnr-eq-equip="legacy-owned-1"]'); await p.click('[data-bnr-eq-unequip="weapon0"]'); await p.finish();
  expect(p.next.trace.filter(r => r.method === 'POST')).toHaveLength(0);
});
it('old/new exact server refusal remains visible without a success tail', async () => {
  const reply = { success: false, message: 'Особый отказ сервера: вещь уже недоступна' }; const p = await pair(f.equipment_inventory, reply);
  await p.click('[data-bnr-eq-buy="sword"]'); await p.finish();
  expect(p.old.document.body.textContent).toContain(reply.message); expect(p.ui.container.textContent).toContain(reply.message);
});
it('old/new equipment HTTP failure clears stale actions', async () => {
  const p = await pair(); p.old.fixtures.equipment = legacyHttpReply({ success: false, message: 'Нет каталога' }, 503);
  p.next.routes['/api/bannerlord/equipment-shop'] = Promise.resolve(new Response(JSON.stringify({ success: false, message: 'Нет каталога' }), { status: 503 }));
  await p.old.refreshEquipment(); await p.next.refresh(); await p.finish();
  expect(p.old.document.querySelector('[data-bnr-eq-buy]')).toBeNull(); expect(p.ui.container.querySelector('[data-bnr-eq-buy]')).toBeNull();
});
it('old/new negative direct quote keeps the modifier and both quoted amounts exactly', async () => {
  // Controlled variation of the real engine-shaped quote, not a live catalog dump.
  const data = structuredClone(f.equipment_direct);
  Object.assign(data.items[0].purchase_options[0], { replace_modifier_id: 'fine', trade_in_gold: 1300, net_price_gold: -300 });
  const p = await pair(data, f.equipment_direct_buy.response); await p.click('[data-bnr-eq-buy="sword"]');
  expect(p.old.document.querySelector('#confirm-dyn-modal')?.textContent).toContain('Получишь 300');
  expect(p.ui.container.querySelector('[role="dialog"]')?.textContent).toContain('Получишь 300');
  await p.click('#confirm-dyn-yes'); await p.finish();
});
for (const reason of ['insufficient_gold', 'tier_locked', 'stash_full']) it(`old/new item refusal ${reason} comes from server flags`, async () => {
  const data = { ...f.equipment_inventory, items: f.equipment_inventory.items.map(item => ({ ...item, can_buy: false, reason, message: `Сервер: ${reason}` })) };
  const p = await pair(data); await p.click('[data-bnr-eq-buy="sword"]'); await p.finish();
  expect(p.next.trace.filter(r => r.method === 'POST')).toHaveLength(0); expect(p.ui.container.textContent).toContain(`Сервер: ${reason}`);
});
it('old/new unavailable owned rows cannot be equipped, but can be discarded after confirmation', async () => {
  const data = { ...f.equipment_inventory, inventory: f.equipment_inventory.inventory.map(row => ({ ...row, unavailable: true })) };
  const p = await pair(data, f.equipment_discard.response); await p.click('[data-bnr-eq-view="owned"]'); await p.click('[data-bnr-eq-equip="party|sword|fine"]');
  expect(p.next.trace.filter(r => r.method === 'POST')).toHaveLength(0); await p.click('[data-bnr-eq-discard="party|sword|fine"]'); await p.click('#confirm-dyn-yes'); await p.finish();
});
for (const [reason, patch] of Object.entries({ no_hero: { has_hero: false, ready: false, inventory: [] }, not_ready: { ready: false }, prisoner: {}, offline: {} })) it(`old/new ${reason} context does not dispatch`, async () => {
  const data = { ...f.equipment_inventory, ...patch, can_manage: false, reason, message: `Контекст: ${reason}`, items: f.equipment_inventory.items.map(item => ({ ...item, can_buy: false, reason, message: `Контекст: ${reason}` })) };
  const p = await pair(data); await p.click('[data-bnr-eq-buy="sword"]'); await p.click('[data-bnr-eq-view="owned"]'); await p.finish();
  expect(p.next.trace.filter(r => r.method === 'POST')).toHaveLength(0); expect(p.ui.container.textContent).toContain(`Контекст: ${reason}`);
});
it('old/new selected filters, pages and input search preserve the rendered item set', async () => {
  const data = { ...f.equipment_inventory, items: Array.from({ length: 43 }, (_, i) => ({ ...f.equipment_inventory.items[0], item_id: 'sword-' + i, name: 'Sword ' + i, category: i === 42 ? 'shield' : 'one_handed' })) };
  const p = await pair(data);
  const ids = (root: ParentNode) => [...root.querySelectorAll('[data-bnr-eq-buy]')].map(node => node.getAttribute('data-bnr-eq-buy'));
  for (let page = 0; page < 2; page++) { await p.click('[data-bnr-eq-page="1"]'); expect(ids(p.ui.container)).toEqual(ids(p.old.document)); }
  await p.change('[data-bnr-eq-category]', 'shield'); expect(ids(p.ui.container)).toEqual(ids(p.old.document));
  const oldInput = p.old.document.querySelector('[data-bnr-eq-search]') as HTMLInputElement;
  const nextInput = p.ui.container.querySelector('[data-bnr-eq-search]') as HTMLInputElement;
  oldInput.value = 'missing'; oldInput.dispatchEvent(new p.old.window.Event('input', { bubbles: true })); await p.old.settle();
  await act(async () => { nextInput.value = 'missing'; nextInput.dispatchEvent(new Event('input', { bubbles: true })); await flush(); });
  expect(ids(p.ui.container)).toEqual(ids(p.old.document)); expect(p.ui.container.textContent).toContain('Ничего не найдено'); await p.finish();
});
it('old discard reproduces the cross-identity dispatch; new identical lifecycle suppresses it', async () => {
  const refusal = { success: false, message: 'Inert refusal: no external mutation' };
  const p = await pair(f.equipment_inventory, refusal); await p.click('[data-bnr-eq-view="owned"]'); await p.click('[data-bnr-eq-discard="party|sword|fine"]');
  const oldYes = p.old.document.querySelector('#confirm-dyn-yes') as HTMLButtonElement;
  const newYes = p.ui.container.querySelector('#confirm-dyn-yes') as HTMLButtonElement;
  await p.old.resetEquipment('carol', 'carol-token'); await p.next.switchIdentity();
  oldYes.click(); await p.old.settle(); await act(async () => { newYes.click(); await flush(); });
  expect(p.old.trace.filter(r => r.path === '/api/bannerlord/action')).toMatchObject([{ token: 'carol-token', body: { action_type: 'hero.discard_owned', data: { owned_id: 'party|sword|fine' } } }]);
  expect(p.next.trace.filter(r => r.path === '/api/bannerlord/action')).toEqual([]);
  // This proves the old client dispatch defect, not unauthorized server deletion.
});
