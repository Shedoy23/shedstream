import type { ActionReply, TournamentAction, TournamentSnapshot, TournamentTransport } from './contracts';
export type Scenario = 'queue' | 'empty' | 'running' | 'joined' | 'predicted' | 'refusal' | 'offline' | 'uncertain';
// Synthetic contract fixtures. No real channel identity, game data or currency.
export const previewSnapshot: TournamentSnapshot = {
  success: true,
  queue: [
    { username: 'Северный_ветер', entry_fee: 0, class_key: null },
    { username: 'viewer_42', entry_fee: 0, class_key: null },
    { username: 'Рыжий_рыцарь', entry_fee: 0, class_key: null },
  ],
  state: { status: 'idle', current_round: 0, participants: [], last_winner: 'Ворон', started_at: null },
  in_queue: false, my_prediction: null, my_username: 'pilot_viewer',
  config: { entry_fee_gold: 0, join_price: 0 },
};
export class PreviewTransport implements TournamentTransport {
  private data: TournamentSnapshot;
  constructor(private scenario: Scenario) {
    this.data = structuredClone(previewSnapshot);
    if (scenario === 'empty') this.data.queue = [];
    if (scenario === 'joined') this.data.in_queue = true;
    if (scenario === 'running' || scenario === 'predicted') {
      this.data.state = { ...this.data.state, status: 'running', current_round: 1, started_at: '2026-10-02T00:00:00Z', participants: ['Северный_ветер', 'viewer_42', 'Рыжий_рыцарь'] };
    }
    if (scenario === 'predicted') this.data.my_prediction = { target: 'viewer_42', amount: 0 };
  }
  async read(signal: AbortSignal) {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    if (this.scenario === 'offline') throw new Error('Локальный пример: связь с сервером отсутствует');
    return structuredClone(this.data);
  }
  async act(action: TournamentAction): Promise<ActionReply> {
    if (this.scenario === 'uncertain') throw new Error('Локальный пример: результат запроса неизвестен. Повтор заблокирован.');
    if (this.scenario === 'refusal') return { success: false, message: 'Локальный пример: новая причина отказа сервера', reason: 'fixture_only' };
    if (action.action_type === 'hero.join_tournament') this.data.in_queue = true;
    else this.data.my_prediction = { target: action.data.target, amount: 0 };
    return { success: true, message: 'Локальная имитация: заявка принята' };
  }
}
