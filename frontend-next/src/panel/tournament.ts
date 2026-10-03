import { actionKey, validPrice, type PanelState } from './contracts';
export interface TournamentReply {
  success: boolean;
  queue: { username: string; class_key?: string | null }[];
  state: { status: string; current_round?: number; participants?: string[]; last_winner?: string | null; started_at?: string | null };
  in_queue: boolean;
  my_prediction?: { target: string; amount?: number } | null;
  my_username?: string;
  config?: { join_price?: number; entry_fee_gold?: number };
}
// The API has no tournament ID. This guards observable replacement only; a
// same-shaped game switch between GET and POST still requires server support.
export const tournamentContext = (t?: TournamentReply | null) => JSON.stringify([t?.state.status, t?.state.started_at, t?.state.current_round]);
export function tournamentAllowed(s: PanelState, type: string, target?: string, context?: string) {
  const t = s.tournament;
  if (!s.canAct || s.mutationBlocked || !t?.success || s.errors.tournament) return false;
  if (type === 'hero.join_tournament') return t.state.status !== 'running' && !t.in_queue && validPrice(t.config?.join_price) && t.config.join_price === 0 && !(s.cooldowns[type] > s.now) && !s.busy.includes(actionKey(type, { price: 0 }));
  return type === 'tournament.predict' && context === tournamentContext(t) && t.state.status === 'running' && !t.my_prediction && !!target && t.state.participants?.includes(target) === true && !s.busy.includes(actionKey(type, { target }));
}
