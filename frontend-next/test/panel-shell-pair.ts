import { expect, vi } from 'vitest';



import { createLegacyHarness, legacyResponses, type LegacyRequest, type LegacyFixture } from './panel-legacy-harness';
import { TwitchAuthStore, type TwitchAuthorization } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { ViewerRuntime, type ViewerHelper } from '../src/common/runtime';
const pending: (() => void)[] = [];
export function disposePairs() { pending.splice(0).forEach(f => f()); }
export const flush = async () => { for (let i = 0; i < 80; i++) await Promise.resolve(); };
export const token = 'fixture.' + Buffer.from(JSON.stringify({ user_id: '456', channel_id: '123' })).toString('base64') + '.fixture';
export const authorization = { token, userId: 'Ufixture123', channelId: '123', clientId: 'extension-fixture' };
export async function pair(overrides: Record<string, LegacyFixture> = {}, prepare?: (runtime: ViewerRuntime, context: {auth: TwitchAuthStore; identity: IdentityBootstrap; fetcher: typeof fetch}) => void) {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] }); vi.setSystemTime(Date.UTC(2026, 9, 2, 12));
  const routes: Record<string, LegacyFixture> = {
    'GET /api/core/config': { tts_cost: 7700, tts_max_len: 190, divorce_cost: 8100, guild_create_cost: 1300 },
    'POST /api/user/resolve-twitch-token': { login: 'alice' },
    'GET /api/viewer/online-list': { users: ['alice', 'bob'] }, 'POST /api/viewer/online': { status: 'ok' },
    'GET /api/viewer/perks': { success: true, role: 'moderator', twitch_sub_tier: 2 },
    'GET /api/notices': { success: true, notices: [] }, 'POST /api/notices/ack': { success: true },
    'GET /api/viewer/stats/alice': { ...legacyResponses.stats, active_module: null },
    'GET /api/user/level/alice': legacyResponses.level, 'GET /api/duel/list': legacyResponses.duels,
    'POST /api/viewer/activity': { status: 'ok' }, 'POST /api/viewer/attendance': { rewarded: false },
    'POST /api/viewer/chat-message': { status: 'ok' }, 'POST /api/viewer/ui-usage': legacyResponses.usage_ok,
    'GET /api/viewer/achievements/alice': { achievements: [{ key: 'first', name: 'Первый шаг', emoji: '⭐', description: 'Посетить стрим', reward: 456, unlocked: true }] },
    'GET /api/viewer/streak/alice': { current_streak: 3, max_streak: 8 },
    'POST /api/promo/use': { success: true, message: 'Промокод принят' }, 'POST /api/tts/submit': { success: true, message: 'Добавлено в очередь' }, 'POST /api/bug-report': { success: true, message: 'Сообщение принято' },
  };
  Object.assign(routes, overrides);
  const old = createLegacyHarness({}, { shellHost: true, token, extraRoutes: routes }); pending.push(old.dispose);
  const trace: LegacyRequest[] = [], subscriptions = new Map<string, (target: string, contentType: string, message: string) => void>(), callbacks: ((a: TwitchAuthorization) => void)[] = [];
  let chat: ((channel: string, user: string, message: string, id: string) => void) | undefined;
  const helper: ViewerHelper = { onAuthorized: cb => { callbacks.push(cb); }, listen: (target, cb) => { subscriptions.set(target, cb); }, unlisten: target => { subscriptions.delete(target); }, chat: { onMessage: cb => { chat = cb; } } };
  const calls = new Map<string, number>();
  const fetcher: typeof fetch = async function(this: unknown, input, init = {}) {
    expect(this).toBeUndefined(); const u = new URL(String(input), 'https://fixture.invalid'), h = new Headers(init.headers), rawBody = init.body == null ? null : String(init.body);
    trace.push({ method: init.method || 'GET', path: u.pathname, query: u.search, rawBody, body: rawBody ? JSON.parse(rawBody) : null, token: h.get('X-Twitch-JWT') || '', contentType: h.get('Content-Type') || '', cache: init.cache || null, ...(init.keepalive === undefined ? {} : { keepalive: init.keepalive }) });
    const key = `${init.method || 'GET'} ${u.pathname}${u.search}`, data = routes[key]; if (data === undefined) throw new Error('Unmatched shell route ' + u.pathname);
    const call = (calls.get(key) || 0) + 1; calls.set(key, call);
    return new Response(JSON.stringify(typeof data === 'function' ? await data(trace.at(-1)!, call) : data));
  };
  const auth = new TwitchAuthStore(), identity = new IdentityBootstrap(auth, '', fetcher, { panelProtocol: true });
  const runtime = new ViewerRuntime(auth, identity, { fetcher, baseUrl: '', surface: 'desktop' }); prepare?.(runtime, {auth,identity,fetcher}); runtime.start(); runtime.attach(helper); const detach = identity.attach(helper); pending.push(() => { detach(); runtime.stop(); });
  await old.bootShell(authorization); callbacks.forEach(cb => cb(authorization)); await flush();
  const normalize = (rows: LegacyRequest[]) => rows.map(q => ({ ...q, body: JSON.stringify(q.body).replace(/("(?:client_action_id|batch_id)":)"[^"\\]*"/g, '$1"<generated>"'), rawBody: q.rawBody?.replace(/("(?:client_action_id|batch_id)":)"[^"\\]*"/g, '$1"<generated>"') ?? null }));
  return { old, runtime, auth, identity, fetcher, trace, routes, subscriptions, callbacks, async advance(ms: number) { await old.advance(ms); await vi.advanceTimersByTimeAsync(ms); await flush(); }, async message(message: string) { await old.chatMessage(message); chat?.('123', 'alice', message, 'fixture'); await flush(); }, check(exception?: { extraConfirmationClicks?: number; inactiveRimworldEmptyPawnTab?:boolean }) {
    let applied = false;
    const expected = old.trace.map(row => {
      if (!exception?.extraConfirmationClicks || applied || row.path !== '/api/viewer/activity') return row;
      applied = true; const body = { ...(row.body as Record<string, number | string>), active_clicks: Number((row.body as Record<string, unknown>).active_clicks) + exception.extraConfirmationClicks };
      return { ...row, body, rawBody: JSON.stringify(body) };
    });
    if (exception?.extraConfirmationClicks) expect(applied, 'the explicit added-confirmation click must appear in a real activity POST').toBe(true);
    if(exception?.inactiveRimworldEmptyPawnTab){
      // One concrete legacy defect: the integration tab reads RimWorld on a
      // Bannerlord channel. Assert the complete two rows before omitting them.
      const at=expected.findIndex(q=>q.path==='/api/rimworld/my-pawn/alice');expect(at).toBeGreaterThan(0);
      expect(expected.slice(at,at+2)).toEqual([{method:'GET',path:'/api/rimworld/my-pawn/alice',query:'',body:null,rawBody:null,token,contentType:'',cache:null},{method:'GET',path:'/api/rimworld/catalog',query:'?username=alice',body:null,rawBody:null,token,contentType:'',cache:null}]);
      expected.splice(at,2);
    }
    expect(normalize(trace)).toEqual(normalize(expected));
  } };
}

