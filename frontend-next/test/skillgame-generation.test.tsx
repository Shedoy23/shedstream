import { useEffect, useSyncExternalStore } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/preact';
import { afterEach, expect, it, vi } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import { SkillgameController } from '../src/skillgames/controller';
import { HttpSkillgameTransport } from '../src/skillgames/transport';
import { SkillgameView } from '../src/skillgames/SkillgameView';
import { parseSnapshot, type SkillgameSnapshot } from '../src/skillgames/contracts';
import { authOne, deferred } from './fixtures';
import { empty, session } from './skillgame-fixtures';

// DOM/controller/HTTP-adapter regression with controlled responses. These are
// production-shaped projections, not a claim about live browser layout or speed.
const waiting = { ...session, expires_at: null, state: { ...session.state, mine_count: 5 } };
const active = { ...waiting, status: 'active', version: 1, started_at: 20, expires_at: 620,
  state: { ...waiting.state, status: 'active', rules_version: 'minesweeper-no-guess-v1', tier: 'beginner', opened: { '0': 0, '1': 1, '6': 1, '7': 1 } } };
const response = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
const button = (name: string | RegExp) => screen.getByRole('button', { name }) as HTMLButtonElement;
function Host({ controller }: { controller: SkillgameController }) {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  useEffect(() => { controller.start(); return () => controller.stop(); }, [controller]);
  return <SkillgameView state={state} onSubmit={(endpoint, command) => { void controller.submit(endpoint, command); }} onRefresh={() => { void controller.refresh(); }} onRetry={() => { void controller.retry(); }} />;
}
function controllerFor(fetcher: typeof fetch) {
  const auth = new TwitchAuthStore(); auth.authorize(authOne);
  let request = 0;
  return new SkillgameController(new HttpSkillgameTransport('', auth, fetcher, () => `generation-test-${++request}`), auth);
}
function whenPlayable(controller: SkillgameController, status: string) {
  return new Promise<void>(resolve => {
    const stop = controller.subscribe(() => {
      if (controller.snapshot().canAct && controller.snapshot().data?.active_session?.status === status) { stop(); resolve(); }
    });
  });
}
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('first Mines click starts once, and an eight-second first-open wait stays visible and locked until the board is playable', async () => {
  let snapshot: SkillgameSnapshot = parseSnapshot(empty);
  const start = deferred<Response>(), opening = deferred<Response>();
  const commands: { endpoint: string; body: Record<string, unknown> }[] = [];
  const fetcher: typeof fetch = vi.fn((url, options) => {
    if (!options?.method) return Promise.resolve(response(snapshot));
    const endpoint = String(url).split('/').at(-1)!;
    commands.push({ endpoint, body: JSON.parse(String(options.body)) });
    return endpoint === 'start' ? start.promise : opening.promise;
  });
  const controller = controllerFor(fetcher);
  render(<Host controller={controller} />);
  await waitFor(() => expect(button('Тренировка').disabled).toBe(false));
  vi.useFakeTimers();
  fireEvent.click(button('Тренировка'));
  expect(commands).toEqual([{ endpoint: 'start', body: { game_type: 'minesweeper', mode: 'practice', difficulty: 'beginner', request_id: 'generation-test-1' } }]);
  expect(screen.getByText('Ждём ответ сервера…')).toBeTruthy();
  expect(button('Тренировка').disabled).toBe(true);
  button('Тренировка').click();
  expect(commands).toHaveLength(1);
  await act(async () => {
    const complete = whenPlayable(controller, 'awaiting_first_move');
    snapshot = parseSnapshot({ ...empty, active_session: waiting });
    start.resolve(response({ success: true, session: waiting }));
    await complete;
  });
  expect(controller.snapshot().data?.active_session?.status).toBe('awaiting_first_move');
  expect(screen.queryByText('Ждём ответ сервера…')).toBeNull();
  expect(within(screen.getByRole('table', { name: 'Поле сапёра' })).getAllByRole('button', { name: /закрыто$/ })).toHaveLength(36);
  expect(button('A1 — закрыто').disabled).toBe(false);
  fireEvent.click(button('A1 — закрыто'));
  expect(commands[1]).toEqual({ endpoint: 'action', body: { session_id: waiting.id, version: 0, action: 'open', cell: 0, request_id: 'generation-test-2' } });
  expect(screen.getByText('Ждём ответ сервера…')).toBeTruthy();
  for (const name of ['A1 — закрыто', 'B1 — закрыто', 'Обновить состояние', 'Тренировка', 'Рейтинг', 'Завершить партию', 'Сбросить попытку']) {
    expect(button(name).disabled, `${name} must be disabled while first-open is pending`).toBe(true);
    button(name).click();
  }
  await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
  expect(screen.getByText('Ждём ответ сервера…')).toBeTruthy();
  expect(button('A1 — закрыто').disabled).toBe(true);
  expect(commands).toHaveLength(2);
  await act(async () => {
    const complete = whenPlayable(controller, 'active');
    snapshot = parseSnapshot({ ...empty, active_session: active });
    opening.resolve(response({ success: true, session: active }));
    await complete;
  });
  expect(controller.snapshot().data?.active_session?.status).toBe('active');
  expect(controller.snapshot().canAct).toBe(true);
  expect(screen.queryByText('Ждём ответ сервера…')).toBeNull();
  expect(button('A1 — открыто, 0').disabled).toBe(true);
  expect(button('C1 — закрыто').disabled).toBe(false);
  expect(commands).toHaveLength(2);
});

it('a restored generating session explains the wait, blocks board taps, and becomes playable after an authoritative refresh', async () => {
  const generating = { ...waiting, status: 'generating', state: { ...waiting.state, status: 'generating' } };
  let snapshot: SkillgameSnapshot = parseSnapshot({ ...empty, active_session: generating });
  const mutation = vi.fn();
  const fetcher: typeof fetch = (url, options) => {
    if (options?.method) mutation(url, options);
    return Promise.resolve(response(snapshot));
  };
  const controller = controllerFor(fetcher);
  render(<Host controller={controller} />);
  await waitFor(() => expect(screen.getByText('Сервер подбирает поле, решаемое без угадывания…')).toBeTruthy());
  expect(controller.snapshot().canAct).toBe(true);
  expect(button('A1 — закрыто').disabled).toBe(true);
  expect(button('Тренировка').disabled).toBe(true);
  button('A1 — закрыто').click(); button('Тренировка').click();
  expect(mutation).not.toHaveBeenCalled();
  await act(async () => {
    snapshot = parseSnapshot({ ...empty, active_session: active });
    await controller.refresh();
  });
  expect(screen.queryByText('Сервер подбирает поле, решаемое без угадывания…')).toBeNull();
  expect(button('A1 — открыто, 0').disabled).toBe(true);
  expect(button('C1 — закрыто').disabled).toBe(false);
  expect(mutation).not.toHaveBeenCalled();
});
