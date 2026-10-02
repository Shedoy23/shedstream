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
