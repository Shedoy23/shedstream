import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup } from '@testing-library/preact';
import { createLegacyHarness, legacyHttpReply, type LegacyJson, type LegacyRequest } from './panel-legacy-harness';
import { equipmentSetup, f, click, change, deferred, flush, response, type Trace } from './panel-equipment-support';
const closers: (() => void)[] = [];
afterEach(() => { cleanup(); closers.splice(0).forEach(close => close()); vi.useRealTimers(); });
function normalized(trace: (LegacyRequest | Trace)[]) {
  return trace.map(request => { const body = structuredClone(request.body) as Record<string, any> | null;
    const id=body?.data?.client_action_id;
    if (id) body.data.client_action_id = '<client-id>';
    const rawBody=id?request.rawBody!.replace(JSON.stringify(id),JSON.stringify('<client-id>')):request.rawBody;
    return { method: request.method, path: request.path, query: request.query, body, rawBody, token: request.token, contentType: request.contentType, cache: request.cache };
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
it('equipment trace retains exact raw POST bytes before random ID normalization',async()=>{const p=await pair();await p.click(`[data-bnr-eq-buy="${f.equipment_inventory.items[0].item_id}"]`);const sent=p.next.trace.find(q=>q.method==='POST') as Trace & {rawBody?:string};expect(sent.rawBody,'equipment raw request bytes must be recorded, not reconstructed from parsed JSON').toBe(JSON.stringify(sent.body));});
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
for (const [name, ui] of Object.entries({
  defaults: undefined,
  changed: { version: 1, labels: { discard: 'Убрать предмет' }, tier_colors: { '4': { text: '#112233', border: '#445566', background: '#778899' } } },
  malformed: { version: 1, labels: { discard: '\u0000unsafe' }, tier_colors: { '4': { text: 'url(https://invalid.test)', border: '#fff', background: 'red;display:none' } } },
  markup_text: { version: 1, labels: { discard: '<b>Предмет</b>' }, tier_colors: { '4': { text: '#AABBCC' } } },
  wrong_version: { version: 2, labels: { discard: 'Ignore me' }, tier_colors: { '4': { text: '#000000' } } },
})) it(`old/new equipment presentation config ${name} preserves labels and validated palette on every tier node`, async () => {
  const p = await pair(); const config = { ...f.config, ui } as unknown as LegacyJson;
  p.old.fixtures.config = config; p.next.routes['/api/bannerlord/config'] = config;
  await p.old.refreshConfig(); await act(async () => { await p.next.controller.refreshConfig(); await flush(); });
  const styles = (root: ParentNode) => [...root.querySelectorAll<HTMLElement>('[data-tier]')].map(node => ({
    tier: node.getAttribute('data-tier'), text: node.style.getPropertyValue('--tier-color'), border: node.style.getPropertyValue('--tier-border'), background: node.style.getPropertyValue('--tier-bg'),
  }));
  expect(styles(p.ui.container)).toEqual(styles(p.old.document));
  await p.click('[data-bnr-eq-view="owned"]');
  const labels = (root: ParentNode) => [...root.querySelectorAll('[data-bnr-eq-discard]')].map(node => node.textContent);
  expect(labels(p.ui.container)).toEqual(labels(p.old.document)); expect(styles(p.ui.container)).toEqual(styles(p.old.document));
  expect(p.ui.container.querySelector('[data-bnr-eq-discard] b')).toBeNull(); await p.finish();
});

it('old/new actual active inventory double click coalesces one pending equipment GET', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  const old = createLegacyHarness({}, { panelLifecycle: true }); closers.push(old.dispose); await old.bootHero();
  const next = equipmentSetup(); closers.push(() => next.controller.stop()); const ui = await next.start(true, true);
  // Both hosts are already authorized/hydrated; compare the entire tab scenario.
  old.trace.length = 0; next.trace.length = 0;
  const oldReply = deferred<LegacyJson>(), newReply = deferred<Response>();
  old.fixtures.equipment = () => oldReply.promise; next.routes['/api/bannerlord/equipment-shop'] = newReply.promise;
  const newTab = ui.getByRole('button', { name: 'Снаряжение' });
  await old.click('[data-bnr-tab="inventory"]'); await act(async () => { newTab.click(); await flush(); });
  await old.click('[data-bnr-tab="inventory"]'); await act(async () => { newTab.click(); await flush(); });
  expect(normalized(next.trace), 'no duplicate GET while same-context equipment request is pending').toEqual(normalized(old.trace));
  expect(next.trace.filter(row => row.path === '/api/bannerlord/equipment-shop')).toHaveLength(1);
  oldReply.resolve(f.equipment_inventory); newReply.resolve(response(f.equipment_inventory)); await old.settle(); await act(async () => { await flush(); });
  old.fixtures.equipment = f.equipment_inventory; next.routes['/api/bannerlord/equipment-shop'] = f.equipment_inventory;
  await old.click('[data-bnr-tab="inventory"]'); await act(async () => { newTab.click(); await flush(); });
  expect(normalized(next.trace)).toEqual(normalized(old.trace));
  expect(next.trace.filter(row => row.path === '/api/bannerlord/equipment-shop')).toHaveLength(2);
});
