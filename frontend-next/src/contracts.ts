// Mirrors backend/routes/bannerlord.py: bannerlord_tournament / bannerlord_action.
// No invented server fields. Unknown response fields are intentionally retained.
export interface TournamentSnapshot {
  success: true;
  queue: { username: string; entry_fee: number; class_key: string | null }[];
  state: { status: string; current_round: number; participants: string[]; last_winner: string | null; started_at: string | null };
  in_queue: boolean;
  my_prediction: { target: string; amount: number } | null;
  my_username: string;
  config: { entry_fee_gold: number; join_price: number };
}
export type TournamentAction =
  | { action_type: 'hero.join_tournament'; data: { price: 0 } }
  | { action_type: 'tournament.predict'; data: { target: string } };
export interface ActionReply {
  success: boolean;
  message?: string;
  action_id?: string;
  charged?: number;
  idempotent_replay?: boolean;
  cooldown_applied_s?: number;
  cooldown_remaining_s?: number;
  required_role?: string;
  your_role?: string;
  reason?: string;
  [key: string]: unknown;
}
export interface TournamentTransport {
  read(signal: AbortSignal): Promise<TournamentSnapshot>;
  act(action: TournamentAction): Promise<ActionReply>;
}
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const nullableText = (value: unknown) => value === null || typeof value === 'string';
export function isSnapshot(value: unknown): value is TournamentSnapshot {
  if (!isRecord(value) || value.success !== true || !isRecord(value.state) || !isRecord(value.config)) return false;
  const { state, config } = value;
  return Array.isArray(value.queue) && value.queue.every(q => isRecord(q) && typeof q.username === 'string' && finite(q.entry_fee) && nullableText(q.class_key))
    && typeof state.status === 'string' && finite(state.current_round)
    && Array.isArray(state.participants) && state.participants.every(p => typeof p === 'string')
    && nullableText(state.last_winner) && nullableText(state.started_at)
    && typeof value.in_queue === 'boolean' && typeof value.my_username === 'string'
    && (value.my_prediction === null || (isRecord(value.my_prediction) && typeof value.my_prediction.target === 'string' && finite(value.my_prediction.amount)))
    && finite(config.entry_fee_gold) && finite(config.join_price);
}
