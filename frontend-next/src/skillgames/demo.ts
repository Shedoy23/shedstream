import { parseSnapshot, type Command, type Endpoint, type SkillgameSnapshot, type SkillgameTransport } from './contracts';
// Deliberately synthetic, display-only examples. No client game engine or result authority.
const catalog = [
  { game_type: 'battleship', availability: { enabled: true, reason: null }, name: 'Морской бой', board: { rows: 6, cols: 6 }, modes: ['ranked'], difficulties: [], timers: { setup_seconds: 120, turn_seconds: 45 }, rating: { initial: 1000 }, rewards: { enabled: false, reason: 'Демо: сезонные награды отключены' }, rules: ['Демо правил: расставьте флот 3 / 2 / 2 / 1 без касаний.', 'Стреляйте по очереди. Попадание не даёт дополнительного хода.'] },
  { game_type: 'minesweeper', availability: { enabled: true, reason: null }, name: 'Сапёр', board: { rows: 6, cols: 6 }, modes: ['ranked', 'practice'], difficulties: [{ id: 'beginner', label: 'Начальный' }, { id: 'advanced', label: 'Продвинутый' }], timers: { attempt_seconds: 600 }, rating: { initial: 1000 }, rewards: { enabled: false, reason: 'Демо: сезонные награды отключены' }, rules: ['Демо правил: безопасная первая область, поле решаемо без угадывания.', 'Два режима нажатия: открыть и флаг. Флаги не обязательны для победы.'] },
];
export class DemoSkillgameTransport implements SkillgameTransport {
  constructor(private readonly scenario: string) {}
  async read(): Promise<SkillgameSnapshot> {
    const base = { id: 'local-demo', game_type: this.scenario, mode: 'practice', difficulty: 'beginner', status: 'active', version: 4, created_at: Date.now() / 1000, started_at: Date.now() / 1000, expires_at: Date.now() / 1000 + 600, result: null };
    const session = this.scenario === 'minesweeper' ? { ...base, state: { rows: 6, cols: 6, status: 'active', opened: { '0': 0, '1': 0, '2': 1, '6': 0, '7': 0, '8': 1, '12': 0, '13': 1, '14': 2, '18': 1, '19': 2 }, flags: [20] } }
      : this.scenario === 'battleship' ? { ...base, mode: 'ranked', difficulty: null, state: { rows: 6, cols: 6, fleet_sizes: [3, 2, 2, 1], phase: 'placement', status: 'active', own_ships: [], ready: false, opponent_ready: true, opponent: 'demo_viewer', shots: [], incoming: [], sunk_count: 0, your_turn: false, turn_started_at: null, winner: null } } : null;
    return parseSnapshot({ success: true, catalog, active_session: session, queue: { status: 'idle' }, ratings: { battleship: 1000, minesweeper: 1000 }, server_time: Date.now() / 1000, poll_interval_ms: 10000 });
  }
  async mutate(_endpoint: Endpoint, _command: Command) { return { success: false, reason: 'display_only_fixture', message: 'Это макет. Для игры откройте панель с подключённым API и Twitch-авторизацией.' }; }
  async retry() { return this.mutate('action', {}); }
  hasUncertain() { return false; }
}
