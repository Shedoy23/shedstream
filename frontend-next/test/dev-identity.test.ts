import { describe, expect, it, vi } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';

// 03.10: the server's resolver verifies Twitch-signed tokens only; a dev preview token
// (signed by the server's dev key) must not depend on it — login comes from ?dev_user=.
const auth = { token: 'a.eyJ1c2VyX2lkIjoiOTgzMTk4NTcifQ.c', channelId: '98319857', userId: 'U98319857' };

describe('dev preview identity', () => {
  it('dev helper with ?dev_user= is ready without calling the Twitch resolver', async () => {
    window.history.pushState({}, '', '/panel-extension.html?dev_jwt=x&dev_user=shedoy23');
    const fetcher = vi.fn();
    const identity = new IdentityBootstrap(new TwitchAuthStore(), 'https://api.invalid', fetcher as unknown as typeof fetch, { panelProtocol: true });
    identity.attach({ environment: 'dev', onAuthorized: cb => cb(auth) });
    await vi.waitFor(() => expect(identity.snapshot().status).toBe('ready'));
    expect(identity.snapshot().login).toBe('shedoy23');
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('a real (non-dev) helper still asks the server resolver even if ?dev_user= is in the URL', async () => {
    window.history.pushState({}, '', '/panel-extension.html?dev_user=attacker');
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ login: 'real_viewer' }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const identity = new IdentityBootstrap(new TwitchAuthStore(), 'https://api.invalid', fetcher as unknown as typeof fetch, { panelProtocol: true });
    identity.attach({ onAuthorized: cb => cb(auth) });
    await vi.waitFor(() => expect(identity.snapshot().status).toBe('ready'));
    expect(identity.snapshot().login).toBe('real_viewer');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
