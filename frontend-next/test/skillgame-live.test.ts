// @vitest-environment node
import { expect, it } from 'vitest';
import { TwitchAuthStore, type TwitchAuthorization } from '../src/auth';
import { IdentityBootstrap, type IdentityHelper } from '../src/skillgames/identity';
import { HttpSkillgameTransport } from '../src/skillgames/transport';
import { terminal, type Session } from '../src/skillgames/contracts';
const base = process.env.LOCAL_TEST_BASE_URL;
// An explicit loopback-only opt-in. This test can never target production/EBS.
if (base && !/^http:\/\/(?:127\.0\.0\.1|localhost):[0-9]+$/.test(base)) throw new Error('LOCAL_TEST_BASE_URL must be an explicit loopback HTTP origin with port');
async function waitForIdentity(boot: IdentityBootstrap, target: 'blocked' | 'ready') {
  if (boot.snapshot().status === target) return;
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => { stop(); reject(new Error(`Identity did not reach ${target}: ${boot.snapshot().message}`)); }, 22000);
    const stop = boot.subscribe(() => { if (boot.snapshot().status === target) { clearTimeout(timer); stop(); resolve(); } });
  });
}
async function connect(player: string) {
  const auth = new TwitchAuthStore(); const boot = new IdentityBootstrap(auth, base!);
  const getIdentity = async (linked: boolean) => await (await fetch(`${base}/local-identity?player=${player}&channel=22&linked=${linked ? '1' : '0'}`)).json() as TwitchAuthorization;
  let authorized!: (value: TwitchAuthorization) => void;
  const helper: IdentityHelper = { onAuthorized: callback => { authorized = callback; }, actions: { requestIdShare: () => { void getIdentity(true).then(authorized); } } };
  const detach = boot.attach(helper);
  authorized(await getIdentity(false)); await waitForIdentity(boot, 'blocked');
  expect(auth.current()).toBeNull();
  // Deliberate test-user permission action; helper callback delivers a real signed JWT.
  boot.requestShare(); await waitForIdentity(boot, 'ready');
  expect(auth.current()?.userId.startsWith('U')).toBe(true);
  return { transport: new HttpSkillgameTransport(base!, auth), detach };
}
const read = (transport: HttpSkillgameTransport, id?: string) => transport.read(new AbortController().signal, id);
async function action(transport: HttpSkillgameTransport, session: Session, action: string, extra = {}) {
  const reply = await transport.mutate('action', { session_id: session.id, version: session.version, action, ...extra });
  expect(reply.success, `${reply.reason}: ${reply.message}`).toBe(true); expect(reply.session).toBeDefined(); return reply.session!;
}
const secretsAbsent = (value: unknown) => { const json = JSON.stringify(value); for (const key of ['mines', 'seed', 'fleets', 'opponent_ships', 'certification']) expect(json).not.toContain(`"${key}"`); };
it.skipIf(!base)('real HTTP: opaque Twitch onboarding, Mines lifecycle, and both Battleship projections through production frontend adapters', async () => {
  const alice = await connect('alice'); const bobby = await connect('bobby');
  try {
    for (const client of [alice, bobby]) {
      const old = await read(client.transport); if (old.active_session && !terminal(old.active_session)) await action(client.transport, old.active_session, 'quit');
      await client.transport.mutate('cancel', {});
    }
    const initial = await read(alice.transport);
    expect(initial.catalog.map(game => game.game_type)).toEqual(['battleship', 'minesweeper']);
    expect(initial.request_retention_seconds).toBeGreaterThan(0);
    const started = await alice.transport.mutate('start', { game_type: 'minesweeper', mode: 'practice', difficulty: 'beginner' });
    expect(started.success).toBe(true); expect(started.session?.status).toBe('awaiting_first_move');
    const opened = await action(alice.transport, started.session!, 'open', { cell: 0 });
    expect(Object.keys(opened.state.opened as object).length).toBeGreaterThan(0); secretsAbsent(opened);
    expect((await read(alice.transport, opened.id)).active_session?.id).toBe(opened.id);
    const ended = await action(alice.transport, opened, 'quit'); expect(terminal(ended)).toBe(true); expect(ended.result?.message).toBeTruthy();
    expect((await alice.transport.mutate('queue', {})).success).toBe(true);
    expect((await bobby.transport.mutate('queue', {})).success).toBe(true);
    let a = (await read(alice.transport)).active_session!;
    expect(a.game_type).toBe('battleship'); expect(a.state.phase).toBe('placement');
    await action(alice.transport, a, 'place', { ships: [[0, 1, 2], [12, 13], [5, 11], [35]] });
    await action(bobby.transport, (await read(bobby.transport)).active_session!, 'autoplace');
    await action(alice.transport, (await read(alice.transport)).active_session!, 'ready');
    await action(bobby.transport, (await read(bobby.transport)).active_session!, 'ready');
    a = (await read(alice.transport)).active_session!;
    const b = (await read(bobby.transport)).active_session!;
    for (const projection of [a, b]) { expect(projection.state.phase).toBe('active'); expect(projection.state.own_ships).toHaveLength(4); secretsAbsent(projection); }
    const shooter = a.state.your_turn ? alice.transport : bobby.transport;
    const target = a.state.your_turn ? a : b;
    const shot = await action(shooter, target, 'fire', { cell: 0 }); expect(shot.state.shots).toHaveLength(1);
    const finished = await action(alice.transport, (await read(alice.transport)).active_session!, 'quit');
    expect(terminal(finished)).toBe(true); expect(finished.result?.message).toBeTruthy(); secretsAbsent(finished);
  } finally { alice.detach(); bobby.detach(); }
}, 30000);
