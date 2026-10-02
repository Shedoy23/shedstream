import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent } from '@testing-library/preact';
import { click, change, deferred, equipmentSetup, f, flush, response } from './panel-equipment-support';
afterEach(() => { cleanup(); vi.useRealTimers(); });
const posts = (s: ReturnType<typeof equipmentSetup>) => s.trace.filter(r => r.method === 'POST');
const button = (root: ParentNode, selector: string) => root.querySelector(selector) as HTMLButtonElement;
it('renders complete shop and slot-based inventory from real handler data with matching owned IDs', async () => {
  const s = equipmentSetup(); const ui = await s.start();
  expect(s.trace.map(r => r.path)).toEqual(['/api/bannerlord/equipment-shop']);
  expect(ui.container.querySelectorAll('[data-bnr-eq-buy]')).toHaveLength(2);
  expect(ui.container.textContent).toContain('25');
  await click(ui.container, '[data-bnr-eq-view="owned"]');
  expect(ui.container.querySelectorAll('[data-bnr-owned-slot]')).toHaveLength(11);
  expect(ui.container.querySelector('[data-bnr-eq-equip="party|sword|fine"]')).not.toBeNull();
  expect(ui.container.querySelector('[data-bnr-eq-equip="legacy-owned-1"]')).not.toBeNull();
  expect(ui.container.querySelector('.bnr-eq-delta.better')?.textContent).toContain('+5');
  expect(s.trace).toHaveLength(1); s.controller.stop();
});
it('normal buy sends only item ID and common balance tail, never the delayed hero tail', async () => {
  vi.useFakeTimers(); const s = equipmentSetup(); const ui = await s.start();
  await click(ui.container, '[data-bnr-eq-buy="sword"]');
  expect(posts(s)[0].body).toEqual({ action_type: 'hero.buy_equipment', data: { item_id: 'sword', client_action_id: 'test-id' } });
  await act(async () => { await vi.advanceTimersByTimeAsync(3600); });
  expect(s.trace.map(r => r.path)).toEqual(['/api/bannerlord/equipment-shop', '/api/bannerlord/action','/api/viewer/stats/alice','/api/user/level/alice','/api/duel/list']);
  expect(button(ui.container, '[data-bnr-eq-buy="sword"]').disabled).toBe(true);
  await s.refresh(); expect(button(ui.container, '[data-bnr-eq-buy="sword"]').disabled).toBe(false); s.controller.stop();
});
it('direct purchase confirms actual quote and preserves empty replacement IDs for alternate empty slot', async () => {
  const s = equipmentSetup(f.equipment_direct, f.equipment_direct_buy.response); const ui = await s.start();
  await change(ui.container, '[data-bnr-eq-purchase-slot="sword"]', 'weapon1');
  await click(ui.container, '[data-bnr-eq-buy="sword"]');
  expect(posts(s)).toHaveLength(0); expect(ui.container.querySelector('[role="dialog"]')).not.toBeNull();
  await click(ui.container, '#confirm-dyn-yes');
  expect(posts(s)[0].body).toEqual({ action_type: 'hero.buy_equipment', data: {
    item_id: 'sword', equip_now: true, slot: 'weapon1', replace_owned_id: '', replace_item_id: '', replace_modifier_id: '', expected_price_gold: 1000, expected_trade_in_gold: 0, client_action_id: 'test-id',
  } }); s.controller.stop();
});
it('equips the exact owned row into selected slot and unequips by slot only', async () => {
  const s = equipmentSetup(); const ui = await s.start(); await click(ui.container, '[data-bnr-eq-view="owned"]');
  await click(ui.container, '[data-bnr-owned-slot="weapon1"]'); await click(ui.container, '[data-bnr-eq-equip="party|sword|fine"]');
  expect(posts(s)[0].body?.data).toEqual({ owned_id: 'party|sword|fine', slot: 'weapon1', client_action_id: 'test-id' });
  await s.refresh(); await click(ui.container, '[data-bnr-owned-slot="weapon0"]'); await click(ui.container, '[data-bnr-eq-unequip="weapon0"]');
  expect(posts(s)[1].body?.data).toEqual({ slot: 'weapon0', client_action_id: 'test-id' }); s.controller.stop();
});
it('allows same-identity discard confirmation and blocks stale identity confirmation', async () => {
  const s = equipmentSetup(); const ui = await s.start(); await click(ui.container, '[data-bnr-eq-view="owned"]');
  await click(ui.container, '[data-bnr-eq-discard="party|sword|fine"]'); const oldYes = button(ui.container, '#confirm-dyn-yes');
  await s.switchIdentity(); await act(async () => { oldYes.click(); await flush(); }); expect(posts(s)).toHaveLength(0);
  await click(ui.container, '[data-bnr-eq-view="owned"]'); await click(ui.container, '[data-bnr-eq-discard="party|sword|fine"]'); await click(ui.container, '#confirm-dyn-yes');
  expect(posts(s)[0]).toMatchObject({ token: 'carol-token', body: { action_type: 'hero.discard_owned', data: { owned_id: 'party|sword|fine' } } }); s.controller.stop();
});
it.each(['cancel', 'backdrop', 'Escape'])('cancels danger dialog via %s and restores opener focus', async method => {
  const s = equipmentSetup(); const ui = await s.start(); await click(ui.container, '[data-bnr-eq-view="owned"]');
  const opener = button(ui.container, '[data-bnr-eq-discard="party|sword|fine"]'); opener.focus(); await click(ui.container, '[data-bnr-eq-discard="party|sword|fine"]');
  expect(document.activeElement?.id).toBe('confirm-dyn-no');
  if (method === 'cancel') await click(ui.container, '#confirm-dyn-no');
  else if (method === 'backdrop') await click(ui.container, '#confirm-dyn-modal');
  else await act(async () => { fireEvent.keyDown(document, { key: 'Escape' }); await flush(); });
  expect(ui.container.querySelector('[role="dialog"]')).toBeNull(); expect(document.activeElement).toBe(opener); expect(posts(s)).toHaveLength(0); s.controller.stop();
});
it('blocks stale same-identity confirmation when authoritative selected ownership or quote changes', async () => {
  const s = equipmentSetup(); const ui = await s.start(); await click(ui.container, '[data-bnr-eq-view="owned"]'); await click(ui.container, '[data-bnr-eq-discard="party|sword|fine"]');
  const yes = button(ui.container, '#confirm-dyn-yes'); s.routes['/api/bannerlord/equipment-shop'] = { ...f.equipment_inventory, inventory: f.equipment_inventory.inventory.filter(i => i.owned_id !== 'party|sword|fine') };
  await s.refresh(); await act(async () => { yes.click(); await flush(); }); expect(posts(s)).toHaveLength(0); s.controller.stop();
  const d = equipmentSetup(f.equipment_direct); const du = await d.start(); await click(du.container, '[data-bnr-eq-buy="sword"]'); const dy = button(du.container, '#confirm-dyn-yes');
  const next = structuredClone(f.equipment_direct); next.items[0].price_gold += 1; d.routes['/api/bannerlord/equipment-shop'] = next;
  await d.refresh(); await act(async () => { dy.click(); await flush(); }); expect(posts(d)).toHaveLength(0); d.controller.stop();
});
it('invalidates a dialog on loss of ready context and hero iteration change without inventing session IDs', async () => {
  const s = equipmentSetup(); const ui = await s.start(); await click(ui.container, '[data-bnr-eq-view="owned"]'); await click(ui.container, '[data-bnr-eq-discard="party|sword|fine"]');
  let yes = button(ui.container, '#confirm-dyn-yes'); s.routes['/api/bannerlord/equipment-shop'] = { ...f.equipment_inventory, ready: false, can_manage: false };
  await s.refresh(); await act(async () => { yes.click(); await flush(); }); expect(posts(s)).toHaveLength(0);
  s.routes['/api/bannerlord/equipment-shop'] = f.equipment_inventory; await s.refresh(); await click(ui.container, '[data-bnr-eq-discard="party|sword|fine"]'); yes = button(ui.container, '#confirm-dyn-yes');
  s.routes['/api/bannerlord/my-hero'] = { ...f.hero, hero: { ...f.hero.hero, iteration: 2 } };
  await act(async () => { await s.controller.refreshHero(); await flush(); yes.click(); await flush(); }); expect(posts(s)).toHaveLength(0); s.controller.stop();
});
it('disables pending, forbidden, unavailable and missing party actions using server flags', async () => {
  for (const snapshot of [ { ...f.equipment_inventory, pending: true }, f.equipment_dead, { ...f.equipment_inventory, can_manage: false } ]) {
    const s = equipmentSetup(snapshot); const ui = await s.start();
    expect(button(ui.container, '[data-bnr-eq-buy="sword"]').disabled).toBe(true); await click(ui.container, '[data-bnr-eq-buy="sword"]');
    await click(ui.container, '[data-bnr-eq-view="owned"]'); expect(button(ui.container, '[data-bnr-eq-equip="legacy-owned-1"]').disabled).toBe(true);
    expect(posts(s)).toHaveLength(0); ui.unmount(); s.controller.stop();
  }
  const s = equipmentSetup(f.equipment_direct); const ui = await s.start(); await click(ui.container, '[data-bnr-eq-view="owned"]');
  expect(button(ui.container, '[data-bnr-eq-unequip="weapon0"]').disabled).toBe(true); expect(button(ui.container, '[data-bnr-eq-equip="legacy-owned-1"]').disabled).toBe(true); s.controller.stop();
});
it('preserves server refusal text and does not mark a refused request pending', async () => {
  const s = equipmentSetup(f.equipment_inventory, { success: false, message: 'Новый точный отказ от сервера' }); const ui = await s.start(); await click(ui.container, '[data-bnr-eq-buy="sword"]');
  expect(ui.container.textContent).toContain('Новый точный отказ от сервера'); expect(button(ui.container, '[data-bnr-eq-buy="sword"]').disabled).toBe(false);
  expect(s.trace.map(r => r.path)).toEqual(['/api/bannerlord/equipment-shop','/api/bannerlord/action']); s.controller.stop();
});
it('retains search input and caret across background refresh and handles out of order replies', async () => {
  const s = equipmentSetup(); const ui = await s.start(); const input = ui.container.querySelector('[data-bnr-eq-search]') as HTMLInputElement;
  input.focus(); await act(async () => { fireEvent.input(input, { target: { value: 'Sword' } }); await flush(); }); input.setSelectionRange(1, 3);
  await s.refresh(); expect(document.activeElement).toBe(input); expect(input.selectionStart).toBe(1); expect(input.selectionEnd).toBe(3);
  const a = deferred<Response>(), b = deferred<Response>(); s.routes['/api/bannerlord/equipment-shop'] = a.promise;
  const first = s.refresh(); s.routes['/api/bannerlord/equipment-shop'] = b.promise; const second = s.refresh();
  b.resolve(response({ ...f.equipment_inventory, gold: 654 })); await second; a.resolve(response({ ...f.equipment_inventory, gold: 321 })); await first;
  expect(ui.container.textContent).toContain('654'); expect(ui.container.textContent).not.toContain('321'); s.controller.stop();
});
it('never applies late equipment response or action result from a previous viewer', async () => {
  const s = equipmentSetup(); const ui = await s.start(); const pending = deferred<Response>(); s.routes['/api/bannerlord/action'] = pending.promise;
  await click(ui.container, '[data-bnr-eq-buy="sword"]'); await s.switchIdentity(); const before = s.trace.length;
  pending.resolve(response(f.equipment_buy.response)); await act(async () => { await flush(); });
  expect(s.trace.slice(before)).toEqual([]); expect(button(ui.container, '[data-bnr-eq-buy="sword"]').disabled).toBe(false); s.controller.stop();
});

it('a GET issued before purchase success cannot erase the fresh local pending barrier', async () => {
  const s = equipmentSetup(); const ui = await s.start(); const late = deferred<Response>();
  s.routes['/api/bannerlord/equipment-shop'] = late.promise; const beforePurchase = s.refresh();
  await click(ui.container, '[data-bnr-eq-buy="sword"]');
  late.resolve(response(f.equipment_inventory)); await beforePurchase;
  expect(button(ui.container, '[data-bnr-eq-buy="sword"]').disabled).toBe(true);
  s.routes['/api/bannerlord/equipment-shop'] = f.equipment_inventory; await s.refresh();
  expect(button(ui.container, '[data-bnr-eq-buy="sword"]').disabled).toBe(false); s.controller.stop();
});
it('preserves pages and filters through refresh, clamps shrinking pages and resets changed filters', async () => {
  const catalog = { ...f.equipment_inventory, items: Array.from({ length: 43 }, (_, i) => ({ ...f.equipment_inventory.items[0], item_id: 'sword-' + i, name: 'Sword ' + i, category: i === 42 ? 'shield' : 'one_handed' })) };
  const s = equipmentSetup(catalog); const ui = await s.start();
  expect(ui.container.querySelectorAll('[data-bnr-eq-buy]')).toHaveLength(20);
  expect(button(ui.container, '[data-bnr-eq-page="-1"]').disabled).toBe(true);
  await click(ui.container, '[data-bnr-eq-page="1"]'); await s.refresh();
  expect(ui.container.querySelector('[data-bnr-eq-buy="sword-20"]')).not.toBeNull();
  await click(ui.container, '[data-bnr-eq-page="1"]'); expect(button(ui.container, '[data-bnr-eq-page="1"]').disabled).toBe(true);
  s.routes['/api/bannerlord/equipment-shop'] = { ...catalog, items: catalog.items.slice(0, 22) }; await s.refresh();
  expect(ui.container.querySelector('[data-bnr-eq-pages]')?.textContent).toContain('2 / 2');
  await change(ui.container, '[data-bnr-eq-tier]', '6'); expect(ui.container.textContent).toContain('Ничего не найдено');
  await change(ui.container, '[data-bnr-eq-tier]', '4'); expect(ui.container.querySelector('[data-bnr-eq-pages]')?.textContent).toContain('1 / 2');
  s.routes['/api/bannerlord/equipment-shop'] = catalog; await s.refresh(); await change(ui.container, '[data-bnr-eq-category]', 'shield');
  expect(ui.container.querySelectorAll('[data-bnr-eq-buy]')).toHaveLength(1); s.controller.stop();
});
it('shows weight decrease as improvement and never conflates repeated item IDs with owned IDs', async () => {
  const data = structuredClone(f.equipment_inventory); data.inventory[0].stats = { ...data.inventory[0].stats, weight: 2 } as typeof data.inventory[0]['stats'];
  data.inventory[1].stats = { ...data.inventory[1].stats, weight: 1 } as typeof data.inventory[1]['stats'];
  const s = equipmentSetup(data); const ui = await s.start(); await click(ui.container, '[data-bnr-eq-view="owned"]');
  expect([...ui.container.querySelectorAll('.bnr-eq-delta.better')].map(n => n.textContent)).toContain('-1');
  await click(ui.container, '[data-bnr-eq-discard="legacy-owned-1"]'); await click(ui.container, '#confirm-dyn-yes');
  expect(posts(s)[0].body?.data).toEqual({ owned_id: 'legacy-owned-1', client_action_id: 'test-id' }); s.controller.stop();
});
it('direct negative quote preserves separate full and trade-in amounts, modifier and replacement IDs', async () => {
  const data = structuredClone(f.equipment_direct); Object.assign(data.items[0].purchase_options[0], { replace_modifier_id: 'fine', trade_in_gold: 1300, net_price_gold: -300 });
  const s = equipmentSetup(data); const ui = await s.start(); await click(ui.container, '[data-bnr-eq-buy="sword"]');
  expect(ui.container.querySelector('[role="dialog"]')?.textContent).toContain('Получишь 300'); await click(ui.container, '#confirm-dyn-yes');
  expect(posts(s)[0].body?.data).toEqual({ item_id: 'sword', equip_now: true, slot: 'weapon0', replace_owned_id: 'equipped|weapon0', replace_item_id: 'sword', replace_modifier_id: 'fine', expected_price_gold: 1000, expected_trade_in_gold: 1300, client_action_id: 'test-id' }); s.controller.stop();
});
it('inactive equipment stays idle; activation loads once and preserves editor through hide/show', async () => {
  const s = equipmentSetup(); const ui = await s.start(false); expect(s.trace).toEqual([]);
  await s.refresh(); expect(s.trace).toEqual([]);
  await s.setActive(ui, true); expect(s.trace.map(r => r.path)).toEqual(['/api/bannerlord/equipment-shop']);
  await click(ui.container, '[data-bnr-eq-view="owned"]'); await click(ui.container, '[data-bnr-owned-slot="weapon1"]');
  await s.setActive(ui, false); await s.refresh(); expect(s.trace).toHaveLength(1);
  await s.setActive(ui, true); expect(s.trace).toHaveLength(2);
  expect(ui.container.querySelector('[data-bnr-owned-slot="weapon1"]')?.getAttribute('aria-pressed')).toBe('true'); s.controller.stop();
});
