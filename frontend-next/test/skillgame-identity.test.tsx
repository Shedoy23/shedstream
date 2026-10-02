import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { TwitchAuthStore, type TwitchAuthorization } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { IdentityGate } from '../src/skillgames/IdentityGate';
import { authOne, deferred } from './fixtures';
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function setup(fetcher = vi.fn().mockResolvedValue(response({ login: 'verified_login' }))) {
  const auth = new TwitchAuthStore(); let callback!: (value: TwitchAuthorization) => void;
  const share = vi.fn(); const helper = { onAuthorized: (fn: typeof callback) => { callback = fn; }, actions: { requestIdShare: share } };
  const boot = new IdentityBootstrap(auth, '', fetcher); boot.attach(helper);
  return { auth, boot, fetcher, share, authorized: (value = authOne) => callback(value) };
}
afterEach(() => { cleanup(); vi.useRealTimers(); });
describe('server-owned Twitch identity bootstrap', () => {
  it('resolves token and opaque ID before authorizing game API, without client login claims', async () => {
    const pending = deferred<Response>(); const setupData = setup(vi.fn().mockReturnValue(pending.promise));
    setupData.authorized(); expect(setupData.auth.current()).toBeNull(); expect(setupData.boot.snapshot().status).toBe('resolving');
    const [url, options] = setupData.fetcher.mock.calls[0];
    expect(url).toBe('/api/user/resolve-twitch-token');
    expect(JSON.parse(options.body)).toEqual({ token: authOne.token, opaque_id: authOne.userId });
    pending.resolve(response({ login: 'verified_login' })); await flush();
    expect(setupData.auth.current()).toEqual(authOne); expect(setupData.boot.snapshot().status).toBe('ready');
  });
  it('never authorizes login=null and never prompts for permission without a click', async () => {
    const { auth, boot, share, authorized } = setup(vi.fn().mockResolvedValue(response({ login: null, error: 'Зритель не передал Twitch ID' })));
    authorized(); await flush(); expect(auth.current()).toBeNull(); expect(share).not.toHaveBeenCalled();
    render(<IdentityGate state={boot.snapshot()} onRetry={() => { void boot.retry(); }} onShare={() => boot.requestShare()} />);
    expect(screen.getByText('Зритель не передал Twitch ID')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Поделиться Twitch ID' }));
    expect(share).toHaveBeenCalledTimes(1); expect(auth.current()).toBeNull();
  });
  it('fences stale token resolutions, including responses that ignore abort', async () => {
    const old = deferred<Response>(); const current = deferred<Response>();
    const { auth, boot, authorized, fetcher } = setup(vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise));
    authorized(); authorized({ ...authOne, token: 'rotated', userId: 'new-opaque' });
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    current.resolve(response({ login: 'second_viewer' })); await flush(); old.resolve(response({ login: 'first_viewer' })); await flush();
    expect(auth.current()?.token).toBe('rotated'); expect(boot.snapshot().status).toBe('ready');
  });
  it('retries resolver failure deliberately and retains same-identity token until replacement resolves', async () => {
    const next = deferred<Response>(); const { auth, boot, authorized } = setup(vi.fn().mockResolvedValueOnce(response({ login: 'verified' })).mockReturnValueOnce(next.promise).mockResolvedValueOnce(response({ login: 'verified' })));
    authorized(); await flush(); authorized({ ...authOne, token: 'rotated' });
    expect(auth.current()?.token).toBe(authOne.token); expect(boot.snapshot().status).toBe('resolving');
    next.resolve(response({ login: null, error: 'Временная ошибка Helix' })); await flush();
    expect(boot.snapshot().status).toBe('blocked'); await boot.retry();
    expect(auth.current()?.token).toBe('rotated'); expect(boot.snapshot().status).toBe('ready');
  });
  it('clears another viewer immediately and bounded timeout cannot authorize the new viewer', async () => {
    vi.useFakeTimers(); const { auth, boot, authorized } = setup(vi.fn().mockResolvedValueOnce(response({ login: 'first' })).mockImplementationOnce(() => new Promise<Response>(() => {})));
    authorized(); await flush(); authorized({ ...authOne, userId: 'second' }); expect(auth.current()).toBeNull();
    await vi.advanceTimersByTimeAsync(20000);
    expect(boot.snapshot().status).toBe('blocked'); expect(auth.current()).toBeNull();
  });
  it('handles unavailable or denied identity-sharing without claiming approval', async () => {
    const { auth, boot, authorized, share } = setup(vi.fn().mockResolvedValue(response({ login: null })));
    authorized(); await flush(); share.mockImplementation(() => { throw new Error('Permission denied'); }); boot.requestShare();
    expect(boot.snapshot().message).toContain('не получено'); expect(auth.current()).toBeNull();
    const bare = new IdentityBootstrap(new TwitchAuthStore(), '', vi.fn()); bare.attach({ onAuthorized: vi.fn() });
    expect(bare.snapshot().canShare).toBe(false);
  });
});
