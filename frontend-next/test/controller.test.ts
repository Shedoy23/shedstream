import { describe, expect, it, vi } from 'vitest';
import { TournamentController } from '../src/controller';
import { TwitchAuthStore } from '../src/auth';
import type { ActionReply, TournamentSnapshot } from '../src/contracts';
import { authOne, deferred, idle, running } from './fixtures';

function setup() {
  const auth = new TwitchAuthStore();
  auth.authorize(authOne);
  const transport = { read: vi.fn<(signal: AbortSignal) => Promise<TournamentSnapshot>>(), act: vi.fn<() => Promise<ActionReply>>() };
  const controller = new TournamentController(transport, auth);
  return { auth, transport, controller };
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

describe('snapshot ownership and lifecycle', () => {
  it('aborts the old read and refuses out-of-order replies even if abort is ignored', async () => {
    const { controller, transport } = setup();
    const older = deferred<TournamentSnapshot>();
    const newer = deferred<TournamentSnapshot>();
    transport.read.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    controller.start();
    const firstSignal = transport.read.mock.calls[0][0];
    const refresh = controller.refresh();
    expect(firstSignal.aborted).toBe(true);
    newer.resolve(running); await refresh;
    older.resolve(idle); await flush();
    expect(controller.snapshot().data?.state.status).toBe('running');
    controller.stop();
  });
  it('ignores both successful and failed completions after unmount', async () => {
    const { controller, transport } = setup();
    const request = deferred<TournamentSnapshot>();
    transport.read.mockReturnValue(request.promise);
    controller.start(); controller.stop();
    const afterStop = controller.snapshot();
    request.reject(new Error('late network error')); await flush();
    expect(controller.snapshot()).toBe(afterStop);
    expect(transport.read.mock.calls[0][0].aborted).toBe(true);
  });
  it('invalidates old viewer data and requests on authorization changes', async () => {
    const { controller, transport, auth } = setup();
    const request = deferred<TournamentSnapshot>();
    transport.read.mockReturnValueOnce(request.promise).mockResolvedValueOnce({ ...idle, my_username: 'new_viewer' });
    controller.start();
    auth.authorize({ ...authOne, userId: 'different-viewer', token: 'new-token' });
    request.resolve(running); await flush();
    expect(controller.snapshot().data?.my_username).toBe('new_viewer');
    controller.stop();
  });
  it('does not let a stale read error replace newer successful data', async () => {
    const { controller, transport } = setup();
    const old = deferred<TournamentSnapshot>();
    transport.read.mockReturnValueOnce(old.promise).mockResolvedValueOnce(running);
    controller.start(); await controller.refresh();
    old.reject(new Error('old failure')); await flush();
    expect(controller.snapshot().error).toBeNull();
    expect(controller.snapshot().data?.state.status).toBe('running');
    controller.stop();
  });
  it('shows a failed refresh with last-known data marked stale', async () => {
    const { controller, transport } = setup();
    transport.read.mockResolvedValueOnce(idle).mockRejectedValueOnce(new Error('Новая причина сервера'));
    controller.start(); await flush(); await controller.refresh();
    expect(controller.snapshot().data).toEqual(idle);
    expect(controller.snapshot().error).toBe('Новая причина сервера');
    expect(controller.snapshot().canAct).toBe(false);
    controller.stop();
  });
  it('never claims joining applied before an authoritative snapshot confirms it', async () => {
    const { controller, transport } = setup();
    transport.read.mockResolvedValue(idle);
    transport.act.mockResolvedValue({ success: true, message: 'Действие в очереди', cooldown_applied_s: 30 });
    controller.start(); await flush();
    await controller.submit({ action_type: 'hero.join_tournament', data: { price: 0 } });
    expect(controller.snapshot().data?.in_queue).toBe(false);
    expect(controller.snapshot().notice).toContain('Действие в очереди');
    expect(controller.snapshot().canAct).toBe(false);
    controller.stop();
  });
  it('guards action double-clicks synchronously before a React rerender', async () => {
    const { controller, transport } = setup();
    transport.read.mockResolvedValue(idle);
    const pending = deferred<ActionReply>(); transport.act.mockReturnValue(pending.promise);
    controller.start(); await flush();
    const action = { action_type: 'hero.join_tournament' as const, data: { price: 0 as const } };
    const first = controller.submit(action);
    await controller.submit(action);
    expect(transport.act).toHaveBeenCalledTimes(1);
    pending.resolve({ success: false, message: 'Отказ' }); await first;
    controller.stop();
  });
  it('allows prediction after joining is confirmed and the tournament starts', async () => {
    const { controller, transport } = setup();
    transport.read.mockResolvedValue(idle);
    transport.act.mockResolvedValue({ success: true });
    controller.start(); await flush();
    await controller.submit({ action_type: 'hero.join_tournament', data: { price: 0 } });
    expect(controller.snapshot().canAct).toBe(false);
    transport.read.mockResolvedValue({ ...idle, in_queue: true });
    await controller.refresh();
    transport.read.mockResolvedValue(running);
    await controller.refresh();
    await controller.submit({ action_type: 'tournament.predict', data: { target: 'viewer_one' } });
    expect(transport.act).toHaveBeenCalledTimes(2);
    controller.stop();
  });
  it('allows a new prediction in the next round without remounting', async () => {
    const { controller, transport } = setup();
    transport.read.mockResolvedValue(running);
    transport.act.mockResolvedValue({ success: true });
    controller.start(); await flush();
    await controller.submit({ action_type: 'tournament.predict', data: { target: 'viewer_one' } });
    transport.read.mockResolvedValue({ ...running, state: { ...running.state, current_round: 2 } });
    await controller.refresh();
    await controller.submit({ action_type: 'tournament.predict', data: { target: 'viewer_one' } });
    expect(transport.act).toHaveBeenCalledTimes(2);
    controller.stop();
  });
  it('allows an in-flight POST to settle after same-viewer token rotation', async () => {
    const { controller, transport, auth } = setup();
    transport.read.mockResolvedValue(idle);
    const pending = deferred<ActionReply>(); transport.act.mockReturnValue(pending.promise);
    controller.start(); await flush();
    const send = controller.submit({ action_type: 'hero.join_tournament', data: { price: 0 } });
    auth.authorize({ ...authOne, token: 'rotated' });
    pending.resolve({ success: false, message: 'Отказ новой версии сервера' });
    await send; await flush();
    expect(controller.snapshot().pending).toBe(false);
    expect(controller.snapshot().notice).toBe('Отказ новой версии сервера');
    expect(controller.snapshot().canAct).toBe(true);
    controller.stop();
  });
  it('does not inherit an old viewer pending POST or overwrite the new viewer', async () => {
    const { controller, transport, auth } = setup();
    transport.read.mockResolvedValue(idle);
    const pending = deferred<ActionReply>(); transport.act.mockReturnValue(pending.promise);
    controller.start(); await flush();
    const send = controller.submit({ action_type: 'hero.join_tournament', data: { price: 0 } });
    auth.authorize({ ...authOne, userId: 'another-viewer', token: 'another-token' });
    pending.resolve({ success: true, message: 'Old viewer success' });
    await send; await flush();
    expect(controller.snapshot().pending).toBe(false);
    expect(controller.snapshot().notice).toBeNull();
    expect(controller.snapshot().canAct).toBe(true);
    controller.stop();
  });
  it('respects server-supplied cooldown rather than hardcoding local game rules', async () => {
    vi.useFakeTimers();
    try {
      const { controller, transport } = setup();
      transport.read.mockResolvedValue(idle);
      transport.act.mockResolvedValue({ success: false, message: 'Нужно подождать', cooldown_remaining_s: 12 });
      controller.start(); await flush();
      await controller.submit({ action_type: 'hero.join_tournament', data: { price: 0 } });
      expect(controller.snapshot().canAct).toBe(false);
      await vi.advanceTimersByTimeAsync(12001); await controller.refresh();
      expect(controller.snapshot().canAct).toBe(true);
      controller.stop();
    } finally { vi.useRealTimers(); }
  });

});
