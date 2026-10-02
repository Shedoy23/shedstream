// Synthetic contract fixtures, never a claim about a real channel/game.
export const idle = {
  success: true as const,
  queue: [{ username: 'viewer_one', entry_fee: 0, class_key: null }],
  state: { status: 'idle', current_round: 0, participants: [], last_winner: 'previous_winner', started_at: null },
  in_queue: false, my_prediction: null, my_username: 'pilot_viewer',
  config: { entry_fee_gold: 0, join_price: 0 },
};
export const running = {
  ...idle,
  state: { ...idle.state, status: 'running', current_round: 1, participants: ['viewer_one', '<img src=x onerror=alert(1)>'] },
};
export const authOne = { token: 'first-token', channelId: 'channel-a', userId: 'viewer-a' };
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
