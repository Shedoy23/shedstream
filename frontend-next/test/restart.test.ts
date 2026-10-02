import { describe, expect, it, vi } from 'vitest';
import { TournamentController } from '../src/controller';
import { TwitchAuthStore } from '../src/auth';
import type { ActionReply, TournamentSnapshot } from '../src/contracts';
import { authOne, deferred, idle } from './fixtures';
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
const join = { action_type: 'hero.join_tournament' as const, data: { price: 0 as const } };
function setup() {
  const auth = new TwitchAuthStore(); auth.authorize(authOne);
  const transport = { read: vi.fn<(signal: AbortSignal) => Promise<TournamentSnapshot>>().mockResolvedValue(idle), act: vi.fn<(action: typeof join) => Promise<ActionReply>>() };
  const controller = new TournamentController(transport, auth);
  return { auth, transport, controller };
}

describe('retained controller restart ownership', () => {
  it('clears old viewer/channel data before starting a delayed read for a new identity', async () => {
    const { auth, transport, controller } = setup();
    controller.start(); await flush(); controller.stop();
    auth.authorize({ ...authOne, channelId: 'channel-b', userId: 'viewer-b', token: 'token-b' });
    const delayed = deferred<TournamentSnapshot>(); transport.read.mockReturnValue(delayed.promise);
    controller.start();
    expect(controller.snapshot().data).toBeNull();
    expect(controller.snapshot().canAct).toBe(false);
    await controller.submit(join);
    expect(transport.act).not.toHaveBeenCalled();
    controller.stop();
  });
  it('settles a known refusal after stop/restart instead of locking the same viewer forever', async () => {
    const { transport, controller } = setup();
    const pending = deferred<ActionReply>(); transport.act.mockReturnValue(pending.promise);
    controller.start(); await flush(); const sent = controller.submit(join);
    controller.stop(); controller.start();
    pending.resolve({ success: false, message: 'Not accepted' });
    await sent; await flush(); await controller.refresh();
    expect(controller.snapshot().pending).toBe(false);
    expect(controller.snapshot().canAct).toBe(true);
    expect(controller.snapshot().notice).toBe('Not accepted');
    controller.stop();
  });
  it('retains a known refusal received while stopped and publishes it only on restart', async () => {
    const { transport, controller } = setup();
    const pending = deferred<ActionReply>(); transport.act.mockReturnValue(pending.promise);
    controller.start(); await flush(); const sent = controller.submit(join);
    controller.stop(); const stoppedState = controller.snapshot();
    pending.resolve({ success: false, message: 'Refused while stopped' }); await sent;
    expect(controller.snapshot()).toBe(stoppedState);
    controller.start(); await flush();
    expect(controller.snapshot().pending).toBe(false);
    expect(controller.snapshot().canAct).toBe(true);
    expect(controller.snapshot().notice).toBe('Refused while stopped');
    controller.stop();
  });
  it('does not issue a duplicate after success received while stopped, before confirmation', async () => {
    const { transport, controller } = setup();
    const pending = deferred<ActionReply>(); transport.act.mockReturnValue(pending.promise);
    controller.start(); await flush(); const sent = controller.submit(join);
    controller.stop(); const stoppedState = controller.snapshot();
    pending.resolve({ success: true, message: 'Accepted while stopped' }); await sent;
    expect(controller.snapshot()).toBe(stoppedState);
    controller.start(); await flush();
    expect(controller.snapshot().pending).toBe(false);
    expect(controller.snapshot().canAct).toBe(false);
    await controller.submit(join);
    expect(transport.act).toHaveBeenCalledTimes(1);
    transport.read.mockResolvedValue({ ...idle, in_queue: true }); await controller.refresh();
    expect(controller.snapshot().data?.in_queue).toBe(true);
    controller.stop();
  });
  it('never unlocks or notifies a new identity with the previous viewer response', async () => {
    const { auth, transport, controller } = setup();
    const pending = deferred<ActionReply>(); transport.act.mockReturnValue(pending.promise);
    controller.start(); await flush(); const sent = controller.submit(join);
    controller.stop();
    auth.authorize({ ...authOne, userId: 'viewer-b', token: 'token-b' });
    transport.read.mockResolvedValue({ ...idle, my_username: 'viewer_b' });
    controller.start(); await flush();
    pending.resolve({ success: true, message: 'Old viewer accepted' }); await sent;
    expect(controller.snapshot().data?.my_username).toBe('viewer_b');
    expect(controller.snapshot().notice).toBeNull();
    expect(controller.snapshot().pending).toBe(false);
    expect(controller.snapshot().canAct).toBe(true);
    controller.stop();
  });
  it('keeps an unknown POST outcome locked after stop/restart', async () => {
    const { transport, controller } = setup();
    const pending = deferred<ActionReply>(); transport.act.mockReturnValue(pending.promise);
    controller.start(); await flush(); const sent = controller.submit(join);
    controller.stop(); pending.reject(new Error('Результат неизвестен')); await sent;
    controller.start(); await flush();
    expect(controller.snapshot().pending).toBe(false);
    expect(controller.snapshot().canAct).toBe(false);
    expect(controller.snapshot().notice).toContain('неизвестен');
    await controller.submit(join); expect(transport.act).toHaveBeenCalledTimes(1);
    controller.stop();
  });
});
