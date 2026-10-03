import { afterEach, expect, it, vi } from 'vitest';
import { h } from 'preact';
import { act, cleanup, fireEvent, render } from '@testing-library/preact';
import { ProfileView } from '../src/common/ProfileView';
import { legacyResponses } from './panel-legacy-harness';
import type { ViewerRuntime } from '../src/common/runtime';
import { pair, flush, token, authorization, disposePairs } from './panel-shell-pair';
afterEach(() => { cleanup(); disposePairs(); vi.useRealTimers(); });
it('whole old shell boot matches resolver, presence, all five-minute polls and telemetry', async () => {
  const p = await pair(); p.check(); await p.advance(300000); p.check();
  expect(p.runtime.snapshot().online).toEqual(['bob']); expect(p.runtime.snapshot().perks?.role).toBe('moderator');
  expect(p.trace.find(q => q.path.endsWith('/attendance'))?.body).toEqual({ username: 'alice', minutes: 4 });
});
it('whole shell refund notices preserve refresh-before-ack traffic and explain returned currency', async () => {
  const p = await pair(); p.routes['GET /api/notices'] = { success: true, notices: [{ id: 51, text: 'Цель исчезла', amount: 2300 }, { id: 52, text: 'Нет места', amount: 0 }] };
  await p.advance(20000); p.check(); expect(p.runtime.snapshot().notices[0].text).toContain('2300');
  expect(p.trace.find(q => q.path === '/api/notices/ack')?.body).toEqual({ ids: [51, 52] });
});
it('whole shell chat sends the exact message length and text', async () => { const p = await pair(); await p.message('Привет 🐸'); p.check(); });
it('shell realtime deduplicates hints and changes private subscription with identity', async () => {
  const p = await pair(); const received: unknown[] = []; p.runtime.realtime.subscribe('vote_tick', data => received.push(data));
  const callback = p.subscriptions.get('broadcast')!;
  const message = JSON.stringify({ v: 1, type: 'vote_tick', seq: 7, ts: 1, data: { points: 12 } }); callback('broadcast', 'application/json', message); callback('broadcast', 'application/json', message);
  expect(received).toEqual([{ points: 12 }]); expect(p.old.realtimeTargets()).toEqual([...p.subscriptions.keys()]);
  p.callbacks.forEach(cb => cb({ ...authorization, userId: 'Unew123', channelId: '321' })); await flush();
  expect([...p.subscriptions.keys()]).toEqual(['broadcast', 'whisper-Unew123']); callback('broadcast', 'application/json', JSON.stringify({ v: 1, type: 'vote_tick', seq: 8, data: { points: 999 } })); expect(received).toHaveLength(1);
});
it('shell hidden page stops notices but retains presence, activity and balance polls', async () => {
  const p = await pair(); await p.advance(17000); await p.old.setHidden(true);
  Object.defineProperty(document, 'hidden', { configurable: true, value: true }); document.dispatchEvent(new Event('visibilitychange')); await flush();
  try { await p.advance(60000); p.check(); } finally { Object.defineProperty(document, 'hidden', { configurable: true, value: false }); }
});
it('shell token refresh keeps timer phase without sending a second online announcement', async () => {
  const p = await pair(); await p.advance(17000); const next = { ...authorization, token: token.replace(/fixture$/, 'refreshed') };
  await p.old.authorizeShell(next); p.callbacks.forEach(cb => cb(next)); await flush(); await p.advance(45000); p.check();
  expect(p.trace.filter(q => q.path === '/api/viewer/online')).toHaveLength(1);
});
it('statistics tab, manual refresh and minute polling preserve all full-shell traffic', async () => {
  const p = await pair(); await p.old.click('.tab[data-tab="stats"]'); document.dispatchEvent(new Event('click')); p.runtime.selectTab('stats'); await flush(); p.check();
  await p.old.click('#stats-refresh-btn'); document.dispatchEvent(new Event('click')); await p.runtime.loadStatistics(); p.check();
  await p.advance(61000); p.check(); expect(p.runtime.snapshot().statistics?.streak.current_streak).toBe(3);
});
it('attendance reward refreshes balance and statistics even while the statistics tab is closed', async () => {
  const p = await pair(); p.routes['POST /api/viewer/attendance'] = { rewarded: true, current_streak: 4, reward: 9234 }; await p.advance(300000); p.check();
  expect(p.runtime.snapshot().notices.at(-1)?.text).toContain('9234');
});
it('shell recovers an HTTP-200 unauthorized snapshot through the same resolver without inventing zero balance', async () => {
  const p = await pair(); p.routes['GET /api/viewer/stats/alice'] = (_request, call) => call === 2 ? { status: 'unauthorized' } : { ...legacyResponses.stats, active_module: null };
  await p.advance(60000); p.check(); expect(p.runtime.snapshot().stats?.points).toBe(legacyResponses.stats.points);
});
it('profile promo preserves uppercase payload and the complete balance tail', async () => {
  const p = await pair(); const ui = render(h(ProfileView, { runtime: p.runtime, openGame: () => {} }));
  await p.old.click('[data-action="promo"]'); await act(async () => { ui.getByRole('button', { name: 'Промокод', exact: true }).click(); });
  (p.old.document.querySelector('#promo-input') as HTMLInputElement).value = ' autumn ';
  await act(async () => { fireEvent.input(ui.getByLabelText('Промокод'), { target: { value: ' autumn ' } }); });
  await p.old.click('#promo-activate-btn'); await act(async () => { ui.getByRole('button', { name: 'Активировать' }).click(); await flush(); }); p.check();
  expect(ui.getByRole('status').textContent).toContain('Промокод принят');
});
it('profile paid TTS confirms the shown text and server quote before exact legacy POST', async () => {
  const p = await pair(); const ui = render(h(ProfileView, { runtime: p.runtime, openGame: () => {} }));
  await p.old.click('[data-action="tts"]'); await act(async () => { ui.getByRole('button', { name: 'Озвучить сообщение', exact: true }).click(); });
  (p.old.document.querySelector('#tts-input') as HTMLTextAreaElement).value = ' Привет, стрим! ';
  await act(async () => { fireEvent.input(ui.getByLabelText('Текст для озвучки'), { target: { value: ' Привет, стрим! ' } }); });
  await act(async () => { ui.getByRole('button', { name: 'Озвучить за 7700 💎' }).click(); }); expect(ui.getByRole('dialog').textContent).toContain('Привет, стрим!');
  expect(p.trace.some(q => q.path === '/api/tts/submit')).toBe(false);
  await p.old.click('#tts-submit-btn'); await act(async () => { ui.getByRole('button', { name: 'Подтвердить' }).click(); await flush(); }); p.check(); expect(ui.getByRole('status').textContent).toContain('Заявка принята');
  await act(async () => { await p.advance(60000); }); p.check({ extraConfirmationClicks: 1 });
});
it('profile bug report retains its exact message without a balance refresh', async () => {
  const p = await pair(); const ui = render(h(ProfileView, { runtime: p.runtime, openGame: () => {} }));
  await p.old.click('[data-action="bug_report"]'); await act(async () => { ui.getByRole('button', { name: 'Сообщить о баге' }).click(); });
  (p.old.document.querySelector('#bug-text') as HTMLTextAreaElement).value = ' Пропала кнопка ';
  await act(async () => { fireEvent.input(ui.getByLabelText('Что сломалось?'), { target: { value: ' Пропала кнопка ' } }); });
  await p.old.click('#bug-send'); await act(async () => { ui.getByRole('button', { name: 'Отправить' }).click(); await flush(); }); p.check();
});
it('profile quests use the server snapshot without an extra read and escape server text', async () => {
  const p = await pair(); p.routes['GET /api/viewer/stats/alice'] = { ...legacyResponses.stats, active_module: null, quests: [{ name: '<img src=x>', current: 2, target: 5, reward: 731, completed: false }] };
  await p.advance(60000); const ui = render(h(ProfileView, { runtime: p.runtime, openGame: () => {} }));
  await p.old.click('[data-action="quests"]'); await act(async () => { ui.getByRole('button', { name: 'Квесты', exact: true }).click(); }); p.check(); expect(ui.getByText('<img src=x>')).toBeTruthy(); expect(ui.container.querySelector('img')).toBeNull(); expect(ui.getByText('Награда: +731 💎')).toBeTruthy();
});
it('profile TTS cancellation sends nothing and unknown server refusal stays visible', async () => {
  const p = await pair(); const ui = render(h(ProfileView, { runtime: p.runtime, openGame: () => {} }));
  await p.old.click('[data-action="tts"]'); await act(async () => { ui.getByRole('button', { name: 'Озвучить сообщение', exact: true }).click(); });
  (p.old.document.querySelector('#tts-input') as HTMLTextAreaElement).value = 'Проверка отказа';
  await act(async () => { fireEvent.input(ui.getByLabelText('Текст для озвучки'), { target: { value: 'Проверка отказа' } }); });
  await act(async () => { ui.getByRole('button', { name: 'Озвучить за 7700 💎' }).click(); }); await act(async () => { ui.getByRole('button', { name: 'Отмена' }).click(); }); p.check();
  p.routes['POST /api/tts/submit'] = { success: false, message: 'Серверная новая причина отказа' };
  await act(async () => { ui.getByRole('button', { name: 'Озвучить за 7700 💎' }).click(); }); await p.old.click('#tts-submit-btn'); await act(async () => { ui.getByRole('button', { name: 'Подтвердить' }).click(); await flush(); }); p.check(); expect(ui.getByRole('status').textContent).toContain('Серверная новая причина отказа');
});
it('profile refuses to invent a TTS price when core config omits it', async () => {
  const p = await pair(); const state = { ...p.runtime.snapshot(), config: {} }; const fake = { subscribe: () => () => {}, snapshot: () => state } as unknown as ViewerRuntime;
  const ui = render(h(ProfileView, { runtime: fake, openGame: () => {} })); await act(async () => { ui.getByRole('button', { name: 'Озвучить сообщение', exact: true }).click(); }); expect(ui.getByText('Цена или лимит озвучки ещё не получены от сервера.')).toBeTruthy(); expect(ui.queryByRole('button', { name: /Озвучить за/ })).toBeNull();
});

