import { expect, it } from 'vitest';
import { act } from '@testing-library/preact';
import { combatPair, flush } from './panel-combat-support';
import saved from './panel-fixtures/forge-tournament-responses.json';
import type { LegacyFixtures } from './panel-legacy-harness';
const r = saved.responses;
const pair = async (overrides: Partial<LegacyFixtures> = {}) => {
  const p = await combatPair({ config: r.config, tournament: r.tournament_empty, action: r.join.response, ...overrides }, false, 'combat', false, false, { tournamentHost: true });
  // Wait for the actual lazy module; promise microtasks alone do not wait for
  // the module loader's filesystem work on the first Windows test.
  await act(async () => { await import('../src/panel/TournamentPanel'); await flush(); });
  return p;
};
function checkRaw(p: Awaited<ReturnType<typeof pair>>) {
  const raw = (trace: typeof p.trace) => trace.map(q => q.rawBody?.replace(/("(?:client_action_id|batch_id)":)"[^"\\]*"/g, '$1"<generated-id>"') ?? null);
  expect(raw(p.trace), 'raw request bytes, including property order, apart from generated IDs').toEqual(raw(p.old.trace));
}
it('tournament join preserves the complete old request traffic through its 3.5 second continuation and polling', async () => {
  const p = await pair();
  await p.click('#bnr-join-tournament-btn');
  expect(p.trace.find(q => q.path.endsWith('/action'))?.body).toMatchObject({ action_type: 'hero.join_tournament', data: { price: 0 } });
  await p.advance(30000); p.check(); checkRaw(p);
});
it('tournament prediction requires confirmation and sends the displayed participant, then keeps every tail request', async () => {
  const p = await pair({ tournament: r.tournament_running, action: r.predict.response });
  await p.click('.bnr-predict-btn[data-target="bobby"]');
  expect(p.trace.some(q => q.path.endsWith('/action'))).toBe(false);
  await p.click('#bnr-predict-confirm');
  expect(p.trace.find(q => q.path.endsWith('/action'))?.body).toMatchObject({ action_type: 'tournament.predict', data: { target: 'bobby' } });
  await p.advance(30000); p.check(); checkRaw(p);
});
it('cancelling a tournament prediction has no mutation traffic', async () => {
  const p = await pair({ tournament: r.tournament_running });
  await p.click('.bnr-predict-btn[data-target="carol"]'); await p.click('#bnr-predict-cancel');
  expect(p.trace.some(q => q.path.endsWith('/action'))).toBe(false); p.check();
});
for (const key of ['join_no_hero', 'join_running', 'join_already', 'join_pending', 'join_cooldown'] as const) it(`tournament renders exact server refusal ${key}`, async () => {
  const p = await pair({ action: r[key].response }); await p.click('#bnr-join-tournament-btn');
  expect(p.ui.container.textContent).toContain(r[key].response.message);
  await p.advance(3500); p.check();
});
it('hidden tournament stops its reads and resumes without a second timer', async () => {
  const p = await pair(); await p.hide(true); await p.advance(12000); p.check();
  await p.hide(false); await p.advance(12000); p.check();
});
it('prediction confirmation cannot submit into a visibly replaced tournament', async () => {
  const p = await pair({ tournament: r.tournament_running });
  await act(async () => { (p.ui.container.querySelector('[data-target="bobby"]') as HTMLButtonElement).click(); });
  expect(p.ui.getByRole('dialog')).toBeTruthy();
  p.fixtures.tournament = r.tournament_next_round;
  await act(async () => { await p.controller.refreshTournament(); });
  expect(p.ui.queryByRole('dialog')).toBeNull();
  expect(p.trace.some(q => q.path.endsWith('/action'))).toBe(false);
});
it('missing join quote is not replaced by the old invented fallback', async () => {
  const p = await pair({ tournament: { ...r.tournament_empty, config: {} } });
  expect((p.ui.container.querySelector('#bnr-join-tournament-btn') as HTMLButtonElement).disabled).toBe(true);
  p.check();
});
