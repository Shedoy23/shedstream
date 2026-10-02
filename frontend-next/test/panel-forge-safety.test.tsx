import { act } from '@testing-library/preact';
import { expect, it, vi } from 'vitest';
import { forgePair, r, toggle, posts, flush } from './panel-forge-support';
import { deferred } from './panel-equipment-support';
const head = '.bnr-reforge-btn[data-slot="head"]';
const click = async (p: Awaited<ReturnType<typeof forgePair>>, selector = head) => { await act(async () => { (p.ui.container.querySelector(selector) as HTMLButtonElement).click(); await flush(); }); };
it('forge repaints accepted equipment quality despite identical hero header and rejects a stale pre-render item control', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); const old = p.ui.container.querySelector(head) as HTMLButtonElement;
  p.fixtures.hero = r.hero_forge_upgraded;
  await act(async () => { await p.controller.refreshHero(); old.click(); await flush(); });
  expect(posts(p)).toHaveLength(0); expect(p.ui.container.querySelector(head)?.textContent).toContain('Шикарное');
  await click(p); expect(posts(p)).toHaveLength(1);
});
for (const [name, hero] of [['dead', r.hero_forge_dead], ['absent', r.hero_absent]] as const) it(`forge ${name} hero removes controls and rejects the prior DOM callback`, async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); const button = p.ui.container.querySelector(head) as HTMLButtonElement;
  p.fixtures.hero = hero; await act(async () => { await p.controller.refreshHero(); button.click(); await flush(); });
  expect(posts(p)).toHaveLength(0); expect(p.ui.container.querySelector('.bnr-reforge-btn')).toBeNull();
});
for (const price of [null, '20000', 'not-a-price', -1, Number.NaN]) it(`forge malformed/missing quote ${price} never admits a paid click`, async () => {
  const p = await forgePair({ config: { ...r.config, reforge_price: price } }); await toggle(p, 'inv-forge'); await click(p);
  expect(posts(p)).toHaveLength(0); expect(p.ui.container.querySelector('#bnr-forge-slot')?.textContent).toContain('Цена недоступна');
});
it('forge quote replacement invalidates a stale rendered click before Preact can commit', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); const button = p.ui.container.querySelector(head) as HTMLButtonElement;
  p.fixtures.config = { ...r.config, reforge_price: 76543 };
  await act(async () => { await p.controller.refreshConfig(); button.click(); await flush(); }); expect(posts(p)).toHaveLength(0);
  await click(p); expect(posts(p)).toHaveLength(1);
});
it('forge same-frame duplicate locks one slot but distinct slots remain independent', async () => {
  const wait = deferred<unknown>(); const p = await forgePair({ action: () => wait.promise as never }); await toggle(p, 'inv-forge');
  await act(async () => { (p.ui.container.querySelector(head) as HTMLElement).click(); (p.ui.container.querySelector(head) as HTMLElement).click(); (p.ui.container.querySelector('.bnr-reforge-btn[data-slot="body"]') as HTMLElement).click(); await flush(); });
  expect(posts(p)).toHaveLength(2); wait.resolve(r.reforge.response); await act(flush);
});
it('forge unknown write blocks new slots, survives same-viewer JWT refresh and never auto-retries', async () => {
  const p = await forgePair({ action: { unexpected: true } }); await toggle(p, 'inv-forge'); await click(p);
  expect(p.controller.snapshot().mutationBlocked).toBe(true); await click(p, '.bnr-reforge-btn[data-slot="body"]');
  await act(async () => { p.authorize({ token: 'new-token', userId: 'opaque-alice', channelId: 'channel-a' }); await flush(); });
  await click(p); await act(async () => { await vi.advanceTimersByTimeAsync(3500); await flush(); }); expect(posts(p)).toHaveLength(1);
});
for (const change of ['stop', 'identity', 'token'] as const) it(`forge successful local and generic delayed tails are fenced after ${change}`, async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); await click(p); const before = p.trace.length;
  await act(async () => {
    if (change === 'stop') p.controller.stop();
    else p.authorize({ token: 'new-token', userId: change === 'identity' ? 'opaque-other' : 'opaque-alice', channelId: 'channel-a' });
    await flush();
  });
  const afterIdentity = p.trace.length; await act(async () => { await vi.advanceTimersByTimeAsync(3500); await flush(); });
  expect(p.trace.slice(afterIdentity).filter(q => q.path.endsWith('/my-hero'))).toHaveLength(0);
  expect(posts(p)).toHaveLength(1); expect(before).toBeGreaterThan(0);
});
it('forge idle same-viewer token refresh preserves disclosure and next action uses current token', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge');
  await act(async () => { p.authorize({ token: 'current-token', userId: 'opaque-alice', channelId: 'channel-a' }); await flush(); });
  expect((p.ui.container.querySelector('[data-bnr-details="inv-forge"]') as HTMLDetailsElement).open).toBe(true);
  await click(p); expect(posts(p)[0].token).toBe('current-token');
});
it('forge hidden inventory cannot dispatch a retained control', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); await p.tab('hero'); await click(p); expect(posts(p)).toHaveLength(0);
});
