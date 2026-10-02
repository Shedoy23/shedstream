import { isRecord } from '../contracts';
export interface GameCatalog {
  game_type: string; name: string; rules: string[]; modes: string[];
  difficulties: { id: string; label: string; mine_count?: number; puzzle_rating?: number }[];
  board: { rows: number; cols: number }; fleet?: number[];
  timers: Record<string, number>; rewards: { enabled: boolean; reason: string };
  rating: Record<string, unknown>;
  [key: string]: unknown;
}
export interface Session {
  rules?: GameCatalog;
  id: string; game_type: string; mode: string; difficulty: string | null; status: string; version: number;
  created_at: number; started_at: number | null; expires_at: number | null;
  state: Record<string, unknown> & { rows: number; cols: number };
  result: null | { outcome?: string; winner?: string | null; reason?: string; rating?: { before: number; after: number; delta: number }; [key: string]: unknown };
}
export interface SkillgameSnapshot {
  success: true; catalog: GameCatalog[]; active_session: Session | null;
  queue: { status: string; [key: string]: unknown }; ratings: Record<string, number>;
  server_time?: number; poll_interval_ms?: number;
}
export type Endpoint = 'start' | 'action' | 'queue' | 'cancel';
export type Command = Record<string, unknown>;
export interface MutationReply {
  success: boolean; reason?: string; message?: string; session?: Session;
  active_session?: Session | null; server_time?: number; [key: string]: unknown;
}
export interface SkillgameTransport {
  read(signal: AbortSignal, sessionId?: string): Promise<SkillgameSnapshot>;
  mutate(endpoint: Endpoint, command: Command): Promise<MutationReply>;
  retry(): Promise<MutationReply>;
  hasUncertain(): boolean;
}
const int = (n: unknown): n is number => typeof n === 'number' && Number.isSafeInteger(n);
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const textArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string');
function dimensions(v: unknown): v is { rows: number; cols: number } {
  return isRecord(v) && int(v.rows) && int(v.cols) && v.rows > 0 && v.cols > 0 && v.rows <= 32 && v.cols <= 32;
}
export function parseCatalog(value: unknown): GameCatalog[] {
  if (!Array.isArray(value) || !value.every(v => isRecord(v) && typeof v.game_type === 'string' && typeof v.name === 'string'
    && textArray(v.rules) && textArray(v.modes) && Array.isArray(v.difficulties) && v.difficulties.every(d => isRecord(d) && typeof d.id === 'string' && typeof d.label === 'string')
    && dimensions(v.board) && isRecord(v.timers) && Object.values(v.timers).every(n => finite(n) && n >= 0)
    && isRecord(v.rewards) && typeof v.rewards.enabled === 'boolean' && typeof v.rewards.reason === 'string' && isRecord(v.rating))) {
    throw new Error('Неизвестный формат каталога игр. Действия отключены.');
  }
  return value as GameCatalog[];
}
export function parseSession(value: unknown): Session {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.game_type !== 'string' || typeof value.mode !== 'string'
    || !(typeof value.difficulty === 'string' || value.difficulty === null) || typeof value.status !== 'string' || !int(value.version) || value.version < 0
    || !finite(value.created_at) || !(value.started_at === null || finite(value.started_at)) || !(value.expires_at === null || finite(value.expires_at))
    || !dimensions(value.state) || !(value.result === null || isRecord(value.result))) throw new Error('Неизвестный формат партии. Действия отключены.');
  const s = value.state as Record<string, unknown> & { rows: number; cols: number };
  const validCell = (cell: unknown) => int(cell) && cell >= 0 && cell < s.rows * s.cols;
  if (value.game_type === 'minesweeper' && (!isRecord(s.opened) || !Array.isArray(s.flags) || !s.flags.every(validCell)
    || !Object.entries(s.opened).every(([key, n]) => /^\d+$/.test(key) && validCell(Number(key)) && int(n) && n >= 0 && n <= 8))) {
    throw new Error('Неизвестный формат поля сапёра. Действия отключены.');
  }
  if (value.game_type === 'battleship') {
    const shotsValid = (v: unknown) => Array.isArray(v) && v.every(x => isRecord(x) && validCell(x.cell) && (x.result === 'hit' || x.result === 'miss'));
    if (!Array.isArray(s.fleet_sizes) || !s.fleet_sizes.length || !s.fleet_sizes.every(x => int(x) && x > 0 && x <= Math.max(s.rows, s.cols))
      || !Array.isArray(s.own_ships) || !s.own_ships.every(x => Array.isArray(x) && x.every(validCell))
      || !shotsValid(s.shots) || !shotsValid(s.incoming) || typeof s.ready !== 'boolean' || typeof s.opponent_ready !== 'boolean'
      || typeof s.opponent !== 'string' || typeof s.your_turn !== 'boolean' || !int(s.sunk_count) || !['placement', 'active', 'finished'].includes(String(s.phase))) {
      throw new Error('Неизвестный формат морского боя. Действия отключены.');
    }
  }
  if (value.rules !== undefined) {
    const [rules] = parseCatalog([value.rules]);
    if (rules.game_type !== value.game_type) throw new Error('Правила не соответствуют сохранённой партии');
  }
  if (isRecord(value.result)) {
    const result = value.result;
    if ((result.outcome !== undefined && typeof result.outcome !== 'string') || (result.reason !== undefined && typeof result.reason !== 'string')
      || (result.rating != null && (!isRecord(result.rating) || !['before', 'after', 'delta'].every(key => finite((result.rating as Record<string, unknown>)[key]))))) {
      throw new Error('Неизвестный формат результата партии');
    }
  }
  if (knownGame(value.game_type) && !['awaiting_first_move', 'generating', 'active', 'finished', 'void'].includes(value.status)) throw new Error('Неизвестное состояние партии; обновите панель');
  return value as unknown as Session;
}
export function parseSnapshot(value: unknown): SkillgameSnapshot {
  if (!isRecord(value) || value.success !== true || !isRecord(value.queue) || typeof value.queue.status !== 'string'
    || !isRecord(value.ratings) || !Object.values(value.ratings).every(finite)) throw new Error('Неизвестный формат состояния игр');
  const catalog = parseCatalog(value.catalog);
  const active_session = value.active_session === null ? null : parseSession(value.active_session);
  return { ...value, catalog, active_session } as SkillgameSnapshot;
}
export const knownGame = (game: string) => game === 'battleship' || game === 'minesweeper';
export const terminal = (session: Session) => ['finished', 'void'].includes(session.status);
