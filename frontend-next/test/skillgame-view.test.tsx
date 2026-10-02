import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { SkillgameView } from '../src/skillgames/SkillgameView';
import type { SkillgameViewState } from '../src/skillgames/controller';
import { parseSnapshot } from '../src/skillgames/contracts';
import { catalog, empty, resumed, session } from './skillgame-fixtures';
const battle = { ...session, game_type: 'battleship', status: 'active', difficulty: null, state: { rows: 6, cols: 6, fleet_sizes: [3, 2, 2, 1], phase: 'placement', own_ships: [], ready: false, opponent_ready: false, opponent: 'opponent', shots: [], incoming: [], sunk_count: 0, your_turn: false, turn_started_at: null, winner: null } };
const state = (data: unknown): SkillgameViewState => ({ data: parseSnapshot(data), loading: false, pending: false, uncertain: false, error: null, notice: null, canAct: true, receivedAt: Date.now() });
function mount(data: unknown = resumed) { const onSubmit = vi.fn(); render(<SkillgameView state={state(data)} onSubmit={onSubmit} onRefresh={vi.fn()} onRetry={vi.fn()} />); return onSubmit; }
afterEach(cleanup);
describe('skillgame accessible controls', () => {
  it('uses explicit open/flag mode and dispatches one server version per tap', () => {
    const submit = mount(); fireEvent.click(screen.getByRole('button', { name: 'Флаг' }));
    fireEvent.click(screen.getByRole('button', { name: /^A1 —/ }));
    expect(submit).toHaveBeenCalledWith('action', { session_id: 'one', version: 0, action: 'flag', cell: 0 });
  });
  it('requires deliberate quit confirmation while keeping refresh harmless', () => {
    const submit = mount(); fireEvent.click(screen.getByRole('button', { name: 'Завершить партию' }));
    expect(submit).not.toHaveBeenCalled();
    const dialog = screen.getByRole('dialog'); fireEvent.click(within(dialog).getByRole('button', { name: 'Остаться' }));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Завершить партию' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Подтвердить выход' }));
    expect(submit).toHaveBeenCalledWith('action', { session_id: 'one', version: 0, action: 'quit' });
  });
  it('permits selecting ship, orientation and anchor by tap; submits the whole fleet', () => {
    const submit = mount({ ...empty, active_session: battle });
    fireEvent.click(screen.getByRole('button', { name: /^Корабль 1/ })); fireEvent.click(screen.getByRole('button', { name: /^A1 —/ }));
    fireEvent.click(screen.getByRole('button', { name: /^Корабль 2/ })); fireEvent.click(screen.getByRole('button', { name: /^A3 —/ }));
    fireEvent.click(screen.getByRole('button', { name: /^Корабль 3/ })); fireEvent.click(screen.getByRole('button', { name: 'Вертикально' })); fireEvent.click(screen.getByRole('button', { name: /^F1 —/ }));
    fireEvent.click(screen.getByRole('button', { name: /^Корабль 4/ })); fireEvent.click(screen.getByRole('button', { name: /^F6 —/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расстановку' }));
    expect(submit).toHaveBeenCalledWith('action', { session_id: 'one', version: 0, action: 'place', ships: [[0, 1, 2], [12, 13], [5, 11], [35]] });
  });
  it('shows enemy as main board and toggles own board without firing at it', () => {
    const submit = mount({ ...empty, active_session: { ...battle, state: { ...battle.state, phase: 'active', your_turn: true, own_ships: [[0, 1, 2], [12, 13], [5, 11], [35]] } } });
    expect(screen.getByRole('table', { name: 'Поле соперника' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Моё поле' }));
    const own = screen.getByRole('table', { name: 'Моё поле' }); fireEvent.click(within(own).getByRole('button', { name: /^A1 —/ }));
    expect(submit).not.toHaveBeenCalled();
  });
  it('renders rules, reward gate and future game as unsupported rather than guessing mechanics', () => {
    mount({ ...empty, catalog: [...catalog, { ...catalog[0], game_type: 'future-game', name: 'Будущая игра' }] });
    expect(screen.getAllByText('Сезонные награды отключены')).toHaveLength(2);
    expect(screen.getByText('Будущая игра')).toBeTruthy();
    expect(screen.getByText('Нужна более новая версия панели')).toBeTruthy();
  });
});

describe('skillgame polling and rules regressions', () => {
  it('keeps unsaved tap placement during unchanged polling snapshots', () => {
    const submit = vi.fn(); const props = { onSubmit: submit, onRefresh: vi.fn(), onRetry: vi.fn() };
    const data = { ...empty, active_session: battle };
    const result = render(<SkillgameView state={state(data)} {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /^A1 —/ }));
    expect(screen.getByRole('button', { name: 'A1 — корабль' })).toBeTruthy();
    result.rerender(<SkillgameView state={state(JSON.parse(JSON.stringify(data)))} {...props} />);
    expect(screen.getByRole('button', { name: 'A1 — корабль' })).toBeTruthy();
  });
  it('displays immutable session reward rules rather than changed catalog rules', () => {
    mount({ ...resumed, active_session: { ...session, rules: { ...catalog[0], rewards: { enabled: false, reason: 'Правила этой сохранённой партии' } } } });
    expect(screen.getByText('Правила этой сохранённой партии')).toBeTruthy();
  });
});

describe('skillgame disclosed consequences', () => {
  it('confirms restart separately and never implicitly starts a new paid/ranked command', () => {
    const submit = mount(); fireEvent.click(screen.getByRole('button', { name: 'Сбросить попытку' })); expect(submit).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Подтвердить сброс' }));
    expect(submit).toHaveBeenCalledExactlyOnceWith('action', { session_id: 'one', version: 0, action: 'restart' });
  });
  it('shows the server reward amount and calibration disclosure without defaults', () => {
    mount({ ...empty, catalog: [{ ...catalog[0], balance_status: 'Баланс ещё проверяется', rewards: { ...catalog[0]!.rewards, immediate_points: 0 }, contest: { sponsor: 'Организатор из сервера', not_sponsors: ['Apple', 'Twitch'] } }] });
    expect(screen.getByText('Баланс ещё проверяется')).toBeTruthy();
    expect(screen.getByText('Крустики за отдельную победу: 0')).toBeTruthy();
    expect(screen.getByText(/Организатор из сервера/)).toBeTruthy();
  });
});

describe('shared match version is not own placement revision', () => {
  it('preserves a manual draft when opponent placement/readiness increments shared version', () => {
    const props = { onSubmit: vi.fn(), onRefresh: vi.fn(), onRetry: vi.fn() };
    const result = render(<SkillgameView state={state({ ...empty, active_session: battle })} {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /^A1 —/ }));
    result.rerender(<SkillgameView state={state({ ...empty, active_session: { ...battle, version: 1, state: { ...battle.state, opponent_ready: true } } })} {...props} />);
    expect(screen.getByRole('button', { name: 'A1 — корабль' })).toBeTruthy();
  });
  it('replaces a local draft when server acknowledges a changed own fleet', () => {
    const props = { onSubmit: vi.fn(), onRefresh: vi.fn(), onRetry: vi.fn() };
    const result = render(<SkillgameView state={state({ ...empty, active_session: battle })} {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /^A1 —/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Авторасстановка' }));
    result.rerender(<SkillgameView state={state({ ...empty, active_session: { ...battle, version: 1, state: { ...battle.state, own_ships: [[6, 7, 8], [24, 25], [4, 10], [35]] } } })} {...props} />);
    expect(screen.getByRole('button', { name: 'A1 — неизвестно' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'A2 — корабль' })).toBeTruthy();
  });
});

describe('server admission flags', () => {
  it('disables new games with the exact server availability reason', () => {
    const submit = mount({ ...empty, catalog: [{ ...catalog[0], availability: { enabled: false, reason: 'Техническая пауза сервера' } }] });
    expect(screen.getByText('Техническая пауза сервера')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Рейтинг' })); expect(submit).not.toHaveBeenCalled();
  });
  it('preserves moves in an existing session when admission is disabled', () => {
    const submit = mount({ ...resumed, catalog: [{ ...catalog[0], availability: { enabled: false, reason: 'Техническая пауза сервера' } }] });
    fireEvent.click(screen.getByRole('button', { name: /^A1 —/ }));
    expect(submit).toHaveBeenCalledWith('action', { session_id: 'one', version: 0, action: 'open', cell: 0 });
  });
  it('renders localized server result while retaining unknown reason fallback', () => {
    mount({ ...resumed, active_session: { ...session, status: 'finished', result: { outcome: 'loss', reason: 'mine_hit', message: 'Поражение', reason_message: 'Открыта клетка с миной' } } });
    expect(screen.getByText('Поражение')).toBeTruthy(); expect(screen.getByText('Открыта клетка с миной')).toBeTruthy();
  });
});
