import type { TwitchAuthorization } from '../auth';
export type RealtimeCallback = (target: string, contentType: string, message: string) => void;
export interface RealtimeHelper { listen?(target: string, callback: RealtimeCallback): void; unlisten?(target: string, callback: RealtimeCallback): void }
/** Hints only: purchase eligibility and balances always come from HTTP. */
export class ViewerRealtime {
  private handlers = new Map<string, Set<(data: unknown) => void>>();
  private unbind: (() => void) | undefined;
  private owner = '';
  subscribe(type: string, handler: (data: unknown) => void) { const set = this.handlers.get(type) || new Set(); set.add(handler); this.handlers.set(type, set); return () => { set.delete(handler); }; }
  bind(helper: RealtimeHelper, auth: TwitchAuthorization) {
    const owner = JSON.stringify([auth.channelId, auth.userId]); if (owner === this.owner) return;
    this.stop(); this.owner = owner; let active = true; const last = new Map<string, number>();
    const callback: RealtimeCallback = (_target, _contentType, message) => {
      if (!active) return;
      try { const env = JSON.parse(message); if (!env || env.v !== 1 || typeof env.type !== 'string') return;
        if (env.seq && env.seq <= (last.get(env.type) || 0)) return; last.set(env.type, env.seq);
        this.handlers.get(env.type)?.forEach(fn => { try { fn(env.data || {}); } catch { /* A failed hint subscriber cannot stop other consumers. */ } });
      } catch { /* Ignore malformed platform messages. */ }
    };
    const targets = ['broadcast', ...(auth.userId ? ['whisper-' + auth.userId] : [])];
    for (const target of targets) { try { helper.listen?.(target, callback); } catch { /* HTTP polling stays available. */ } }
    this.unbind = () => { active = false; for (const target of targets) { try { helper.unlisten?.(target, callback); } catch { /* Callback is already fenced. */ } } };
  }
  stop() { this.unbind?.(); this.unbind = undefined; this.owner = ''; }
}
