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
it('forge stale hero read cannot restore older equipment after a newer accepted response', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); const first = deferred<unknown>(), second = deferred<unknown>(); let call = 0;
  p.fixtures.hero = () => (++call === 1 ? first.promise : second.promise) as never;
  let a!: Promise<unknown>, b!: Promise<unknown>; await act(async () => { a = p.controller.refreshHero(); b = p.controller.refreshHero(); await flush(); });
  await act(async () => { second.resolve(r.hero_forge_upgraded); await b; await flush(); });
  await act(async () => { first.resolve(r.hero_forge); await a; await flush(); });
  expect(p.ui.container.querySelector(head)?.textContent).toContain('Шикарное');
});
it('forge failed hero read quarantines the retained equipment until a successful fresh snapshot', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); p.fixtures.hero = { success: false, message: 'fixture hero unavailable' };
  await act(async () => { await p.controller.refreshHero(); await flush(); }); await click(p); expect(posts(p)).toHaveLength(0);
  expect(p.ui.container.textContent).toContain('fixture hero unavailable'); p.fixtures.hero = r.hero_forge;
  await act(async () => { await p.controller.refreshHero(); await flush(); }); await click(p); expect(posts(p)).toHaveLength(1);
});
it('forge failed config read removes its actionable quote and a fresh config restores it', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); p.fixtures.config = { success: false, message: 'fixture quote unavailable' };
  await act(async () => { await p.controller.refreshConfig(); await flush(); }); await click(p); expect(posts(p)).toHaveLength(0);
  expect(p.ui.container.querySelector('#bnr-forge-slot')?.textContent).toContain('Цена недоступна'); p.fixtures.config = r.config;
  await act(async () => { await p.controller.refreshConfig(); await flush(); }); await click(p); expect(posts(p)).toHaveLength(1);
});
for (const change of ['stop', 'identity', 'token'] as const) it(`forge pending POST completion after ${change} owns no delayed hero continuation`, async () => {
  const waiting = deferred<unknown>(); const p = await forgePair({ action: () => waiting.promise as never }); await toggle(p, 'inv-forge'); await click(p);
  await act(async () => { if (change === 'stop') p.controller.stop(); else p.authorize({ token: 'changed-token', userId: change === 'identity' ? 'other' : 'opaque-alice', channelId: 'channel-a' }); await flush(); });
  const before = p.trace.length;
  await act(async () => { waiting.resolve(r.reforge.response); await flush(); await vi.advanceTimersByTimeAsync(3500); await flush(); });
  expect(p.trace.slice(before).filter(q => q.path.endsWith('/my-hero'))).toHaveLength(0); expect(posts(p)).toHaveLength(1);
});
for (const login of ['testuser', 'U123456789']) it(`forge rejected viewer login ${login} has sign-in text and no purchase controls`, async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); p.resolver(async () => new Response(JSON.stringify({ login })));
  await act(async () => { p.authorize({ token: 'anonymous-token', userId: 'opaque-alice', channelId: 'channel-a' }); await flush(); });
  expect(p.ui.container.querySelector('.bnr-reforge-btn')).toBeNull(); expect(p.ui.container.querySelector('#bnr-forge-slot')?.textContent).toContain('Войдите через Twitch'); expect(posts(p)).toHaveLength(0);
});
it('forge real item removal invalidates a saved callback and displays its empty slot', async () => {
  const p = await forgePair(); await toggle(p, 'inv-forge'); const button = p.ui.container.querySelector(head) as HTMLButtonElement;
  const equipment = { ...r.hero_forge.equipment }; delete (equipment as Partial<typeof equipment>).head; p.fixtures.hero = { ...r.hero_forge, equipment };
  await act(async () => { await p.controller.refreshHero(); button.click(); await flush(); }); expect(posts(p)).toHaveLength(0);
  expect(p.ui.container.querySelector('[data-forge-slot="head"]')?.textContent).toContain('пусто');
});
it('forge unavailable quote has an explicit recovery control that preserves disclosure and then uses the recovered server price', async () => {
  const p = await forgePair({ config: { ...r.config, reforge_price: 'missing-quote' } }); await toggle(p, 'inv-forge');
  expect(p.controller.snapshot().config?.attribute_cost).toBe(r.config.attribute_cost);
  const retry = p.ui.container.querySelector('#bnr-forge-price-retry') as HTMLButtonElement | null; expect(retry).not.toBeNull();
  const before = p.trace.length; p.fixtures.config = { ...r.config, reforge_price: 24680 };
  await act(async () => { retry!.click(); await flush(); });
  expect(p.trace.slice(before).map(q => q.path)).toEqual(['/api/bannerlord/config']);
  expect((p.ui.container.querySelector('[data-bnr-details="inv-forge"]') as HTMLDetailsElement).open).toBe(true);
  expect((p.ui.container.querySelector(head) as HTMLButtonElement)?.title).toContain('24680'); await click(p); expect(posts(p)).toHaveLength(1);
});
