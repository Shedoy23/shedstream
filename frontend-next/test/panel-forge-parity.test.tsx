import { act } from '@testing-library/preact';
import { expect, it } from 'vitest';
import { forgePair, r, toggle, posts, flush } from './panel-forge-support';
const slots = ['weapon0', 'weapon1', 'weapon2', 'head', 'body', 'leg', 'gloves', 'cape', 'horse'];
const controls = (root: ParentNode) => [...root.querySelectorAll<HTMLButtonElement>('.bnr-reforge-btn')].map(b => ({ slot: b.dataset.slot, text: b.textContent?.replace(/\s+/g, ' ').trim(), title: b.title }));
it('full forge is the saved inventory disclosure, initially closed, with all inherited slots and qualities', async () => {
  const p = await forgePair();
  expect(p.ui.container.querySelector('[data-bnr-details="inv-forge"]')).not.toBeNull();
  expect((p.ui.container.querySelector('[data-bnr-details="inv-forge"]') as HTMLDetailsElement).open).toBe(false);
  const before = p.trace.length; await toggle(p, 'inv-forge'); expect(p.trace).toHaveLength(before);
  expect(controls(p.ui.container)).toEqual(controls(p.old.document));
  expect(controls(p.ui.container).map(b => b.slot)).toEqual(slots);
  expect(p.ui.container.querySelector('#bnr-forge-slot')?.textContent).toContain('T3★');
  expect(p.ui.container.querySelector('#bnr-forge-slot')?.textContent).toContain('✦ макс');
  expect(p.ui.container.querySelector('#bnr-forge-slot')?.textContent).not.toContain('horseharness');
  await p.advance(30000); p.check();
});
for (const slot of slots) it(`forge ${slot} real control exact wire, usage and complete successful/refused double-hero tail`, async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); const initial = p.trace.length;
  await p.click(`.bnr-reforge-btn[data-slot="${slot}"]`);
  expect(posts(p)).toHaveLength(1); expect(p.ui.queryByRole('dialog')).toBeNull();
  const data = (posts(p)[0].body as { data: Record<string, unknown> }).data;
  expect(Object.keys(data).sort()).toEqual(['client_action_id', 'expected_item_id', 'slot']); expect(data.expected_item_id).toBe((r.hero_forge.equipment as Record<string, { item_id: string }>)[slot].item_id); expect(data.slot).toBe(slot); expect(data.client_action_id).toEqual(expect.any(String));
  await p.advance(3500); p.check();
  expect(p.trace.slice(initial).filter(q => q.path.endsWith('/my-hero'))).toHaveLength(slot === 'horse' ? 1 : 2);
  await p.advance(26500); p.check();
});
for (const key of ['reforge_unsynced', 'reforge_bad_slot', 'reforge_best', 'reforge_pending_right', 'reforge_poor', 'reforge_no_hero'] as const) it(`forge real refusal ${key} preserves server text and the owned read tail`, async () => {
  const result = r[key].response; const p = await forgePair({ action: result }); await toggle(p, 'inv-forge');
  await p.click('.bnr-reforge-btn[data-slot="head"]'); expect(p.ui.container.querySelector('#bnr-equipment-shop .panel-notice[role="status"]')?.textContent).toContain(result.message);
  expect(p.ui.container.querySelector('#bnr-equipment-shop')?.closest('[hidden]')).toBeNull();
  await p.advance(3500); p.check();
});
it('forge reads its independent server quote without changing the wire or adding a prisoner restriction', async () => {
  const p = await forgePair({ config: { ...r.config, reforge_price: 23456 }, hero: r.hero_prisoner, action: r.reforge_prisoner.response }); await toggle(p, 'inv-forge');
  expect(controls(p.ui.container)).toEqual(controls(p.old.document));
  await p.click('.bnr-reforge-btn[data-slot="cape"]'); await p.advance(3500); p.check();
});
it('forge empty slots keep all ten rows and no actions', async () => {
  const p = await forgePair({ hero: { ...r.hero_forge, equipment: {} } }); await toggle(p, 'inv-forge');
  expect(p.ui.container.querySelector('#bnr-forge-slot')?.textContent?.match(/пусто/g)).toHaveLength(10);
  expect(controls(p.ui.container)).toEqual([]); p.check();
});
it('forge disclosure persists across tab changes, hero header rewrite and ordinary polls, recording only open transitions', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); await p.tab('hero'); await p.tab('inventory');
  p.fixtures.hero = { ...r.hero_forge, hero: { ...r.hero_forge.hero, level: 2 } };
  await p.old.refreshHero(); await act(async () => { await p.controller.refreshHero(); await flush(); });
  expect((p.ui.container.querySelector('[data-bnr-details="inv-forge"]') as HTMLDetailsElement).open).toBe(true);
  await toggle(p, 'inv-forge', false); await toggle(p, 'inv-forge'); await p.advance(30000); p.check();
});
it('forge numeric zero quote remains real and never invents a fallback charge', async () => {
  const p = await forgePair({ config: { ...r.config, reforge_price: 0 } }); await toggle(p, 'inv-forge');
  expect(controls(p.ui.container)).toEqual(controls(p.old.document)); await p.click('.bnr-reforge-btn[data-slot="head"]'); await p.advance(3500); p.check();
});
it('forge shield and quality presentation use the actual item, with unknown quality retaining the inherited next label', async () => {
  const p = await forgePair({ hero: { ...r.hero_forge, equipment: { ...r.hero_forge.equipment, head: { ...r.hero_forge.equipment.head, quality: 'future-quality' } } } }); await toggle(p, 'inv-forge');
  expect(controls(p.ui.container)).toEqual(controls(p.old.document));
  expect(p.ui.container.querySelector('[data-forge-slot="weapon1"]')?.textContent).toContain('🛡');
  expect(p.ui.container.querySelector('[data-forge-slot="weapon1"]')?.textContent).toContain('◆ Хорошее');
  expect(p.ui.container.querySelector('[data-forge-slot="body"]')?.textContent).toContain('▽ Низкое'); p.check();
});
