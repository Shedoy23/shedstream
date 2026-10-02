// @vitest-environment node
// Opt-in real HTTP integration, not browser/visual QA. Only the disposable
// scripts/run-skillgames-local.py service on loopback may be targeted.
// Shares disposable channel 22 / Alice / Bobby with skillgame-live.test.ts.
// Run live files serially: test:live passes --no-file-parallelism, and the
// Vitest config disables file parallelism for any LOCAL_TEST_BASE_URL opt-in.
import { expect, it } from 'vitest';
import { TwitchAuthStore, type TwitchAuthorization } from '../src/auth';
import { SkillgameController } from '../src/skillgames/controller';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { HttpSkillgameTransport } from '../src/skillgames/transport';
import { terminal, type Session } from '../src/skillgames/contracts';

const base = process.env.LOCAL_TEST_BASE_URL;
if (base && !/^http:\/\/(?:127\.0\.0\.1|localhost):[0-9]+$/.test(base)) throw new Error('LOCAL_TEST_BASE_URL must be an explicit loopback HTTP origin with port');
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
const read = (transport: HttpSkillgameTransport, id?: string) => transport.read(new AbortController().signal, id);
const rounded = (ms: number) => Math.round(ms * 10) / 10;

function secretsAbsent(value: unknown) {
  if (Array.isArray(value)) { value.forEach(secretsAbsent); return; }
  if (!value || typeof value !== 'object') return;
  for (const [key, child] of Object.entries(value)) {
    expect(['mines', 'seed', 'fleets', 'opponent_ships', 'secret_state', 'certification', 'generation_token']).not.toContain(key);
    secretsAbsent(child);
  }
}
function publicSession(session: Session) {
  secretsAbsent(session);
  const allowed = session.game_type === 'minesweeper'
    ? ['rules_version', 'tier', 'rows', 'cols', 'mine_count', 'opened', 'flags', 'status']
    : ['rules_version', 'rows', 'cols', 'fleet_sizes', 'phase', 'status', 'own_ships', 'ready', 'opponent_ready', 'opponent', 'shots', 'incoming', 'sunk_count', 'your_turn', 'turn_started_at', 'winner'];
  for (const key of Object.keys(session.state)) expect(allowed).toContain(key);
}
async function connect(player: 'alice' | 'bobby') {
  const auth = new TwitchAuthStore();
  const identity = new IdentityBootstrap(auth, base!);
  const response = await fetch(`${base}/local-identity?player=${player}&channel=22&linked=1`);
  expect(response.ok).toBe(true);
  const authorization = await response.json() as TwitchAuthorization;
  const detach = identity.attach({ onAuthorized: callback => callback(authorization) });
  await expect.poll(() => identity.snapshot().status, { timeout: 22000, interval: 10 }).toBe('ready');
  const requests: { path: string; action?: string; cell?: number; duration_ms?: number }[] = [];
  const checkedFetch: typeof fetch = async (input, init) => {
    const url = new URL(String(input));
    expect(url.origin).toBe(base);
    expect(url.pathname.startsWith('/api/skillgames/')).toBe(true);
    const recorded = init?.method === 'POST' ? { path: url.pathname, ...JSON.parse(String(init.body)), duration_ms: 0 } : null;
    if (recorded) requests.push(recorded);
    const sentAt = performance.now();
    const result = await fetch(input, init);
    secretsAbsent(await result.clone().json());
    if (recorded) recorded.duration_ms = rounded(performance.now() - sentAt);
    return result;
  };
  return { player, auth, detach, requests, transport: new HttpSkillgameTransport(base!, auth, checkedFetch) };
}
type Client = Awaited<ReturnType<typeof connect>>;
async function action(client: Client, session: Session, action: string, extra = {}) {
  const reply = await client.transport.mutate('action', { session_id: session.id, version: session.version, action, ...extra });
  expect(reply.success, `${reply.reason}: ${reply.message}`).toBe(true);
  expect(reply.session).toBeDefined();
  publicSession(reply.session!);
  return reply.session!;
}

// This independent player uses only visible numbers, flags, dimensions and the
// declared mine count. No server imports, database, seed, layout or proof access.
type Constraint = { cells: number[]; count: number };
function deduction(session: Session): { cells: number[]; mine: boolean; rule: 'direct' | 'subset' } {
  const { rows, cols } = session.state;
  const opened = session.state.opened as Record<string, number>;
  const known = new Set(session.state.flags as number[]);
  const unopened = (cell: number) => !(String(cell) in opened) && !known.has(cell);
  const constraints: Constraint[] = [];
  for (const [key, count] of Object.entries(opened)) {
    const cell = Number(key), row = Math.floor(cell / cols), col = cell % cols;
    const adjacent: number[] = [];
    for (let r = Math.max(0, row - 1); r <= Math.min(rows - 1, row + 1); r++) {
      for (let c = Math.max(0, col - 1); c <= Math.min(cols - 1, col + 1); c++) {
        if (r * cols + c !== cell) adjacent.push(r * cols + c);
      }
    }
    const cells = adjacent.filter(unopened);
    if (cells.length) constraints.push({ cells, count: count - adjacent.filter(n => known.has(n)).length });
  }
  constraints.push({ cells: Array.from({ length: rows * cols }, (_, i) => i).filter(unopened), count: Number(session.state.mine_count) - known.size });
  const forced = ({ cells, count }: Constraint, rule: 'direct' | 'subset') => cells.length && (count === 0 || count === cells.length) ? { cells, mine: count !== 0, rule } : null;
  for (const constraint of constraints) { const result = forced(constraint, 'direct'); if (result) return result; }
  for (const small of constraints) for (const large of constraints) {
    if (small.cells.length < large.cells.length && small.cells.every(cell => large.cells.includes(cell))) {
      const result = forced({ cells: large.cells.filter(cell => !small.cells.includes(cell)), count: large.count - small.count }, 'subset');
      if (result) return result;
    }
  }
  throw new Error('Public clues have no forced move; refusing to guess or inspect hidden state');
}

async function solve(client: Client, initial: Session) {
  let session = initial, moves = 0, subsetSteps = 0;
  while (!terminal(session)) {
    expect(moves).toBeLessThan(session.state.rows * session.state.cols * 2);
    const next = deduction(session);
    if (next.rule === 'subset') subsetSteps++;
    for (const cell of next.cells) {
      if (terminal(session)) break;
      if (String(cell) in (session.state.opened as object)) continue;
      session = await action(client, session, next.mine ? 'flag' : 'open', { cell });
      moves++;
    }
  }
  expect(session.result?.outcome).toBe('win');
  expect(session.result?.reason).toBe('completed');
  expect(session.state.status).toBe('won');
  expect(Object.keys(session.state.opened as object)).toHaveLength(session.state.rows * session.state.cols - Number(session.state.mine_count));
  if (session.difficulty === 'advanced') expect(subsetSteps).toBeGreaterThan(0);
  const saved = (await read(client.transport, session.id)).active_session!;
  expect(saved).toEqual(session);
  return { session, moves, subsetSteps };
}

it.skipIf(!base)('real HTTP: six publicly solved Mines wins, controller start/reconnect, and complete two-client Battleship', async () => {
  const clients = { alice: await connect('alice'), bobby: await connect('bobby') };
  const controllers: SkillgameController[] = [];
  const mines: Record<string, unknown>[] = [];
  try {
    for (const client of Object.values(clients)) {
      const previous = (await read(client.transport)).active_session;
      // Clear only disposable remnants of an interrupted prior test, before the
      // measured games. No quit/restart is used to finish any game below.
      if (previous && !terminal(previous)) await action(client, previous, 'quit');
      expect((await client.transport.mutate('cancel', {})).success).toBe(true);
    }
    for (const [player, difficulty] of [['alice', 'beginner'], ['bobby', 'advanced']] as const) {
      for (let round = 1; round <= 3; round++) {
        let client = clients[player];
        const controller = new SkillgameController(client.transport, client.auth);
        controllers.push(controller);
        controller.start();
        await expect.poll(() => controller.snapshot().canAct, { timeout: 22000, interval: 10 }).toBe(true);
        const startAt = performance.now();
        const start = controller.submit('start', { game_type: 'minesweeper', mode: 'practice', difficulty });
        expect(controller.snapshot().pending).toBe(true);
        expect(controller.snapshot().canAct).toBe(false);
        await start;
        const startMs = rounded(performance.now() - startAt);
        const startHttpMs = client.requests.at(-1)!.duration_ms;
        const waiting = controller.snapshot().data!.active_session!;
        expect(waiting.status).toBe('awaiting_first_move');
        expect(Object.keys(waiting.state.opened as object)).toHaveLength(0);
        publicSession(waiting);
        const command = { session_id: waiting.id, version: waiting.version, action: 'open', cell: 0 };
        const openAt = performance.now();
        const opening = controller.submit('action', command);
        expect(controller.snapshot().pending).toBe(true);
        expect(controller.snapshot().canAct).toBe(false);
        // A repeat click during the real in-flight HTTP request must not enqueue
        // another command, even while the server is generating the board.
        await controller.submit('action', command);
        let completed = false;
        void opening.then(() => { completed = true; });
        const observed = new Set<string>();
        while (!completed) {
          const sampled = (await read(client.transport, waiting.id)).active_session!;
          publicSession(sampled); observed.add(sampled.status);
          if (!completed) await delay(5);
        }
        await opening;
        const firstOpenMs = rounded(performance.now() - openAt);
        const firstOpenHttpMs = client.requests.at(-1)!.duration_ms;
        expect(client.requests.filter(request => request.path.endsWith('/action') && request.action === 'open' && request.cell === 0)).toHaveLength(round);
        let session = controller.snapshot().data!.active_session!;
        expect(session.status, controller.snapshot().notice || '').toBe('active');
        expect(controller.snapshot().canAct).toBe(true);
        expect(controller.snapshot().pending).toBe(false);
        expect(Object.keys(session.state.opened as object).length).toBeGreaterThan(0);
        controller.stop();
        if (round === 1) {
          // Fresh bootstrap + transport represents a reconnected client. It has
          // no in-memory session and must recover the same board via HTTP.
          const fresh = await connect(player);
          const restored = (await read(fresh.transport)).active_session!;
          expect(restored).toEqual(session);
          fresh.requests.push(...client.requests);
          client.detach(); clients[player] = fresh; client = fresh; session = restored;
        }
        const result = await solve(client, session);
        const report = { difficulty, round, outcome: result.session.result?.outcome, start_controller_ms: startMs, start_http_ms: startHttpMs, first_open_controller_ms: firstOpenMs, first_open_http_ms: firstOpenHttpMs, observed_http_statuses: [...observed], moves: result.moves, subset_steps: result.subsetSteps };
        mines.push(report);
        console.log('LOCAL_HTTP_MINES', JSON.stringify(report));
      }
    }

    const { alice, bobby } = clients;
    expect((await alice.transport.mutate('queue', {})).success).toBe(true);
    expect((await read(alice.transport)).queue.status).toBe('queued');
    expect((await bobby.transport.mutate('queue', {})).success).toBe(true);
    let a = (await read(alice.transport)).active_session!;
    let b = (await read(bobby.transport)).active_session!;
    expect(a.id).toBe(b.id);
    expect(a.state.phase).toBe('placement');
    a = await action(alice, a, 'place', { ships: [[0, 1, 2], [12, 13], [5, 11], [35]] });
    b = await action(bobby, (await read(bobby.transport)).active_session!, 'autoplace');
    const fleets = { alice: a.state.own_ships, bobby: b.state.own_ships };
    a = await action(alice, (await read(alice.transport)).active_session!, 'ready');
    expect(a.state.ready).toBe(true); expect(a.state.opponent_ready).toBe(false);
    b = await action(bobby, (await read(bobby.transport)).active_session!, 'ready');
    expect(b.state.phase).toBe('active');
    const battleId = b.id;
    let shots = 0;
    while (true) {
      a = (await read(alice.transport, battleId)).active_session!;
      b = (await read(bobby.transport, battleId)).active_session!;
      for (const [player, session] of [['alice', a], ['bobby', b]] as const) {
        publicSession(session);
        expect(session.state.own_ships).toEqual(fleets[player]);
      }
      expect(a.state.shots).toEqual(b.state.incoming);
      expect(b.state.shots).toEqual(a.state.incoming);
      if (terminal(a) || terminal(b)) break;
      expect(a.state.your_turn).not.toBe(b.state.your_turn);
      const shooter = a.state.your_turn ? alice : bobby;
      const projection = a.state.your_turn ? a : b;
      const fired = new Set((projection.state.shots as { cell: number }[]).map(shot => shot.cell));
      // Deterministic public-information sweep; never consult the other client's
      // own_ships when choosing a target. Both players take their real turns.
      const cell = Array.from({ length: projection.state.rows * projection.state.cols }, (_, index) => index).find(index => !fired.has(index));
      expect(cell).toBeDefined();
      await action(shooter, projection, 'fire', { cell });
      shots++;
      expect(shots).toBeLessThanOrEqual(72);
    }
    expect(a.status).toBe('finished'); expect(b.status).toBe('finished');
    expect([a.result?.outcome, b.result?.outcome].sort()).toEqual(['loss', 'win']);
    expect(a.result?.reason).toBe('completed'); expect(b.result?.reason).toBe('completed');
    expect(a.result?.winner).toBe(b.result?.winner);
    expect(a.result?.message).toBeTruthy(); expect(b.result?.message).toBeTruthy();
    expect(a.state.phase).toBe('finished'); expect(b.state.phase).toBe('finished');
    expect(a.state.your_turn).toBe(false); expect(b.state.your_turn).toBe(false);
    const winner = a.result?.outcome === 'win' ? a : b;
    expect(winner.state.sunk_count).toBe(winner.state.fleet_sizes instanceof Array ? winner.state.fleet_sizes.length : 0);
    const reconnected = await connect('alice');
    try { expect((await read(reconnected.transport, battleId)).active_session).toEqual(a); } finally { reconnected.detach(); }
    console.log('LOCAL_HTTP_BATTLESHIP', JSON.stringify({ shots, alice: a.result?.outcome, bobby: b.result?.outcome, reason: a.result?.reason, restored: true }));
    console.log('LOCAL_HTTP_COMPLETE', JSON.stringify({ mines_wins: mines.length, battleship_complete: true, channel: 22, browser_visual_qa: false }));
  } finally {
    controllers.forEach(controller => controller.stop());
    Object.values(clients).forEach(client => client.detach());
  }
}, 180000);
