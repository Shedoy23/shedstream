export interface TwitchAuthorization { token: string; channelId: string; userId: string }
export interface TwitchHelper { onAuthorized(callback: (authorization: TwitchAuthorization) => void): void }

// A single host-owned instance, in memory only. Tokens are never logged or persisted.
export class TwitchAuthStore {
  private value: TwitchAuthorization | null = null;
  private listeners = new Set<() => void>();
  current = () => this.value;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  authorize(authorization: TwitchAuthorization) {
    this.value = { ...authorization };
    this.listeners.forEach(listener => listener());
  }
  clear() { this.value = null; this.listeners.forEach(listener => listener()); }
  attach(helper: TwitchHelper) {
    let attached = true;
    helper.onAuthorized(authorization => { if (attached) this.authorize(authorization); });
    // Twitch has no matching offAuthorized; invalidate the callback on host teardown.
    return () => { attached = false; this.clear(); };
  }
}
