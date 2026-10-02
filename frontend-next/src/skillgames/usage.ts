import { TwitchAuthStore } from '../auth';
const allowed = new Map<string, Set<string>>([
  ['panel_view', new Set(['core:panel'])],
  ['section_open', new Set(['core:game.battleship', 'core:game.minesweeper'])],
  ['action_attempt', new Set([
    ...['queue', 'place', 'autoplace', 'ready', 'fire', 'quit'].map(action => `core:battleship.${action}`),
    ...['start', 'open', 'flag', 'unflag', 'quit', 'restart'].map(action => `core:minesweeper.${action}`),
  ])],
]);
const identity = (auth: TwitchAuthStore) => JSON.stringify([auth.current()?.channelId, auth.current()?.userId]);
// In-memory semantic counters only. Never accept payload objects, board content,
// names or user IDs in events. Failed/uncertain telemetry is discarded, not retried.
export class SkillgameUsage {
  private events = new Map<string, { kind: string; feature: string; count: number }>();
  private owner: string; private lastFlush: number; private busy = false;
  constructor(private readonly auth: TwitchAuthStore, private readonly surface: 'desktop' | 'mobile', private readonly fetcher: typeof fetch = fetch, private readonly clock = () => Date.now()) { this.owner = identity(auth); this.lastFlush = clock(); }
  private sync() { const next = identity(this.auth); if (next !== this.owner) { this.events.clear(); this.owner = next; } }
  record(kind: string, feature: string) {
    this.sync(); if (!this.auth.current() || !allowed.get(kind)?.has(feature)) return;
    const key = `${kind}:${feature}`; const event = this.events.get(key);
    const total = [...this.events.values()].reduce((n, item) => n + item.count, 0);
    if (total >= 100 || (!event && this.events.size >= 20)) return;
    if (event) event.count = Math.min(event.count + 1, 20);
    else this.events.set(key, { kind, feature, count: 1 });
  }
  async flush() {
    this.sync(); const token = this.auth.current()?.token;
    if (this.busy || !token || !this.events.size || this.clock() - this.lastFlush < 15000) return;
    const events = [...this.events.values()]; this.events.clear(); this.busy = true; this.lastFlush = this.clock();
    try {
      await this.fetcher('/api/viewer/ui-usage', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': token }, body: JSON.stringify({ batch_id: crypto.randomUUID(), surface: this.surface, events }) });
    } catch { /* Best effort: gameplay and privacy take precedence over telemetry. */ }
    finally { this.busy = false; }
  }
}
