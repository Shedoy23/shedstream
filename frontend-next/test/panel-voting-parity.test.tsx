import { act, cleanup, fireEvent, render } from '@testing-library/preact';
import { afterEach, expect, it, vi } from 'vitest';
import { VotingView } from '../src/common/VotingView';
import { pair, flush, disposePairs } from './panel-shell-pair';
import type { LegacyFixture, LegacyJson } from './panel-legacy-harness';
export const voteConfig = { voting_min_bid: 73, voting_min_pledge: 127, voting_bid_presets: [73, 731, 7310], voting_pledge_presets: [127, 1270] };
export const activeVote = { success: true, active_event: { event_id: 51, template_name: 'Следующая игра', ends_at: '2026-10-02T12:10:00Z', total_pool: 4200, allow_proposals: true, options: [{ id: 701, label: 'Игра А', description: 'Первый вариант', pool: 1200 }, { id: 702, label: 'Игра Б', description: 'Второй вариант', pool: 3000 }] }, top_bidders: [{ username: 'bob', total: 4200 }] };
export const waitingVote = { success: true, active_event: null, pool_units: 540, threshold: 947, pool_pct: 57, has_default_template: true };
afterEach(() => { cleanup(); disposePairs(); vi.useRealTimers(); });
async function setup(status: LegacyFixture = activeVote, refused = false) {
  const p = await pair({ 'GET /api/core/config': voteConfig, 'GET /api/voting/status': status, 'POST /api/voting/bid': { success: !refused, message: refused ? 'Новая причина отказа голосования' : 'Голос учтён' }, 'POST /api/voting/propose': { success: true, message: 'На одобрении' } });
  await p.old.click('[data-action="voting"]'); document.dispatchEvent(new Event('click')); const ui = render(<VotingView runtime={p.runtime} />); await act(flush); p.check();
  return { ...p, ui, async click(old: string, label: string) { await p.old.click(old); await act(async () => { ui.getByRole('button', { name: label, exact: true }).click(); await flush(); }); }, async input(old: string, label: string, value: string) { (p.old.document.querySelector(old) as HTMLInputElement).value = value; await act(async () => { fireEvent.input(ui.getByLabelText(label), { target: { value } }); }); }, async hint(type: string, data: Record<string, LegacyJson>, seq = 1) { const envelope = { v: 1, type, seq, ts: Date.now(), data }; await p.old.realtimeMessage('broadcast', envelope); await act(async () => { p.subscriptions.get('broadcast')?.('broadcast', 'application/json', JSON.stringify(envelope)); await flush(); }); } };
}
it('voting bid preserves actual option ID, amount, refresh branches and full minute traffic', async () => {
  const p = await setup(); await p.click('[data-vote-option="701"]', 'Голосовать за Игра А'); await p.click('[data-quick="731"]', '731 💎'); await p.click('#voting-bid-confirm-btn', 'Подтвердить'); p.check();
  expect(p.ui.getByRole('status').textContent).toContain('Заявка принята'); await act(async () => { await p.advance(60000); }); p.check();
});
it('voting proposal sends trimmed label and chosen pledge with no invented immediate charge refresh', async () => {
  const p = await setup(); await p.click('#voting-propose-btn', 'Предложить свою игру'); await p.input('#voting-propose-label', 'Название игры', ' Новая игра '); await p.click('[data-qp="1270"]', '1270 💎'); await p.click('#voting-propose-confirm', 'Подтвердить'); p.check(); expect(p.ui.getByRole('status').textContent).toContain('одобрения');
});
it('voting server refusal preserves the complete trace and its unknown explanation', async () => {
  const p = await setup(activeVote, true); await p.click('[data-vote-option="702"]', 'Голосовать за Игра Б'); await p.input('#voting-bid-amount', 'Сумма голоса', '1000'); await p.click('#voting-bid-confirm-btn', 'Подтвердить'); p.check(); expect(p.ui.getByRole('status').textContent).toContain('Новая причина отказа голосования');
});
it('voting waiting state and realtime start/tick dedupe use actual protected refreshes', async () => {
  const p = await setup(waitingVote); expect(p.ui.getByText('540 / 947')).toBeTruthy(); p.routes['GET /api/voting/status'] = activeVote;
  await p.hint('vote_started', { event_id: 51 }); p.check(); await p.hint('vote_tick', { total_pool: 999999 }); p.check(); await p.hint('vote_tick', { total_pool: 999999 }); p.check(); expect(p.ui.queryByText('999999')).toBeNull();
});
it('voting finished result survives the poll, dismiss refreshes, and closing unsubscribes', async () => {
  const p = await setup(); p.routes['GET /api/voting/status'] = waitingVote; await p.hint('vote_ended', { winner: { label: 'Игра Б', pool: 3000 } });
  await act(async () => { await p.advance(30000); }); p.check(); expect(p.ui.getByRole('heading', { name: 'Игра Б', exact: true })).toBeTruthy();
  await p.click('#voting-result-dismiss', 'К копилке'); p.check(); await p.old.click('#voting-close-btn'); document.dispatchEvent(new Event('click')); p.ui.unmount();
  const before = p.trace.filter(q => q.path === '/api/voting/status').length; await p.hint('vote_tick', {}, 2); expect(p.trace.filter(q => q.path === '/api/voting/status'), 'closed realtime subscriber').toHaveLength(before); await p.advance(30000); p.check(); expect(p.trace.filter(q => q.path === '/api/voting/status')).toHaveLength(before);
});
it('voting invalidates a selected option when a later snapshot replaces its round', async () => {
  const p = await setup(); await p.click('[data-vote-option="701"]', 'Голосовать за Игра А'); p.routes['GET /api/voting/status'] = { ...activeVote, active_event: { ...activeVote.active_event, event_id: 52 } };
  await act(async () => { await p.advance(30000); }); p.check(); expect(p.ui.queryByRole('dialog')).toBeNull(); expect(p.trace.some(q => q.path === '/api/voting/bid')).toBe(false);
});
it('voting expiry keeps the legacy final status read and then stops its seconds timer', async () => {
  const p = await setup((_request, call) => call === 1 ? { ...activeVote, active_event: { ...activeVote.active_event, ends_at: '2026-10-02T12:00:02Z' } } : waitingVote);
  await act(async () => { await p.advance(5000); }); p.check(); expect(p.trace.filter(q => q.path === '/api/voting/status')).toHaveLength(2);
});
it('voting confirmation cancellation sends no payment and its keyboard loop includes the amount input', async () => {
  const p = await setup(); await p.click('[data-vote-option="701"]', 'Голосовать за Игра А');
  const cancel = p.ui.getByRole('button', { name: 'Отмена', exact: true }); cancel.focus(); fireEvent.keyDown(cancel, { key: 'Tab' }); expect(document.activeElement).toBe(p.ui.getByLabelText('Сумма голоса'));
  await p.click('#voting-bid-cancel-btn', 'Отмена'); await act(async () => { await p.advance(30000); }); p.check(); expect(p.trace.some(q => q.path === '/api/voting/bid')).toBe(false);
});
it('voting ignores a late ended hint belonging to a different active round', async () => {
  const p = await setup(); await p.hint('vote_ended', { event_id: 49, winner: { label: 'Старый результат', pool: 999 } }); p.check();
  expect(p.ui.getByRole('heading', { name: 'Следующая игра', exact: true })).toBeTruthy(); expect(p.ui.queryByRole('heading', { name: 'Старый результат', exact: true })).toBeNull();
});

