import { act } from '@testing-library/preact';
import { expect, it } from 'vitest';
import { forgePair, r, toggle, posts, flush } from './panel-forge-support';
import { deferred } from './panel-equipment-support';
const selector = '.bnr-reforge-btn[data-slot="head"]';
const click = async (p: Awaited<ReturnType<typeof forgePair>>, q = selector) => { await act(async () => { (p.ui.container.querySelector(q) as HTMLElement).click(); await flush(); }); };
const changed = (patch: object) => ({ ...r.equipment_forge, inventory: r.equipment_forge.inventory.map(item => item.slot === 'head' ? { ...item, ...patch } : item) });
for (const [label, patch] of [['item', { item_id: 'replacement_head', name: 'Replacement helmet' }], ['quality', { quality: 'fine', modifier_id: 'fixture_rank1' }]] as const) it(`forge newer equipped ${label} disagreement blocks only its stale slot until accepted sources reconcile`, async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); p.fixtures.equipment = changed(patch);
  await act(async () => { await p.controller.refreshEquipment(); await flush(); });
  await click(p); expect(posts(p)).toHaveLength(0);
  expect(p.ui.container.querySelector('[data-forge-slot="head"]')?.textContent).toContain('Данные вещи обновляются');
  expect((p.ui.container.querySelector('.bnr-reforge-btn[data-slot="body"]') as HTMLButtonElement).disabled).toBe(false);
  expect((p.ui.container.querySelector('[data-bnr-eq-view="owned"]') as HTMLButtonElement).disabled).toBe(false);
  // Re-reading the same hero cannot discard a newer contradictory observation.
  await act(async () => { await p.controller.refreshHero(); await flush(); }); await click(p); expect(posts(p)).toHaveLength(0);
  p.fixtures.hero = { ...r.hero_forge, equipment: { ...r.hero_forge.equipment, head: { ...r.hero_forge.equipment.head, ...(label === 'item' ? { item_id: 'replacement_head', item_name: 'Replacement helmet' } : { quality: 'fine' }) } } };
  await act(async () => { await p.controller.refreshHero(); await flush(); }); await click(p); expect(posts(p)).toHaveLength(1);
});
it('forge missing equipped slot is a contradiction, while the one-based equipment tier does not conflict', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); expect((p.ui.container.querySelector(selector) as HTMLButtonElement).disabled).toBe(false);
  p.fixtures.equipment = { ...r.equipment_forge, inventory: r.equipment_forge.inventory.filter(item => item.slot !== 'head') };
  await act(async () => { await p.controller.refreshEquipment(); await flush(); }); await click(p); expect(posts(p)).toHaveLength(0);
});
it('forge accepted equipped disagreement invalidates a saved button before Preact commits', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); const button = p.ui.container.querySelector(selector) as HTMLButtonElement;
  p.fixtures.equipment = changed({ item_id: 'replacement_head' });
  await act(async () => { await p.controller.refreshEquipment(); button.click(); await flush(); }); expect(posts(p)).toHaveLength(0);
});
it('forge stale equipment request from a replaced hero cannot clear the current observed disagreement', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); const stale = deferred<unknown>(); p.fixtures.equipment = () => stale.promise as never;
  let pending!: unknown; await act(async () => { pending = p.controller.refreshEquipment(); await flush(); });
  const hero = { ...r.hero_forge, hero: { ...r.hero_forge.hero, hero_id: 'new-hero', iteration: 2 } };
  p.fixtures.hero = hero; p.fixtures.equipment = changed({ item_id: 'replacement_head' });
  await act(async () => { await p.controller.refreshHero(); await flush(); });
  await act(async () => { await flush(); });
  await act(async () => { stale.resolve(r.equipment_forge); await pending; await flush(); }); await click(p); expect(posts(p)).toHaveLength(0);
  expect(p.ui.container.querySelector('[data-forge-slot="head"]')?.textContent).toContain('Данные вещи обновляются');
});
it('forge a previous viewer equipment observation cannot quarantine the next viewer', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); p.fixtures.equipment = changed({ item_id: 'replacement_head' });
  await act(async () => { await p.controller.refreshEquipment(); await flush(); }); await click(p); expect(posts(p)).toHaveLength(0);
  p.fixtures.equipment = r.equipment_forge;
  await act(async () => { p.authorize({ token: 'other-viewer', userId: 'other-viewer', channelId: 'channel-a' }); await flush(); }); await act(flush);
  const details = p.ui.container.querySelector('[data-bnr-details="inv-forge"]') as HTMLDetailsElement;
  await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')); await flush(); });
  await click(p); expect(posts(p)).toHaveLength(1); expect(posts(p)[0].token).toBe('other-viewer');
});
