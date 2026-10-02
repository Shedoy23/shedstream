import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import type { IdentityState } from '../src/skillgames/identity';
import { PanelUsage } from '../src/panel/usage';
import fixtures from './panel-fixtures/real-responses.json';

// This is the unchanged production collector, executed independently rather
// than a test-side reimplementation of its batching/deduplication algorithm.
const oldSource = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../Расширение/frontend/viewer-usage.js'), 'utf8');
const allowedActions: string[] = JSON.parse(oldSource.match(/var actions = new Set\((\[.*?\])\)/)![1]);
const allowedSections: string[] = JSON.parse(oldSource.match(/var sections = new Set\((\[.*?\])\)/)![1]);
interface UsageApi { trackPanel(module: string): void; trackSection(feature: string): void; trackAction(feature: string): void; flush(): Promise<void> }
interface RequestTrace { url: string; method: string | undefined; headers: [string, string][]; body: string; keepalive: boolean | undefined; signal: AbortSignal | null | undefined }
const authOne = { token: 'private-token-alice', channelId: 'channel-a', userId: 'viewer-a' };
const drains: (() => void)[] = [];
// A handler-emitted fixture (generate-responses.py -> routes.ui_usage), not a
// made-up successful response. Collector semantics use status, never JSON.
const reply = (status = 401) => new Response(JSON.stringify(fixtures.responses.usage_unauthorized), { status });
function pair(surface: 'mobile' | 'desktop' = 'desktop') {
  const oldTrace: RequestTrace[] = [], nextTrace: RequestTrace[] = [];
  const fetcher = (trace: RequestTrace[]) => vi.fn((async (url: RequestInfo | URL, init: RequestInit = {}) => {
    trace.push({ url: String(url), method: init.method, headers: [...new Headers(init.headers)], body: String(init.body), keepalive: init.keepalive, signal: init.signal });
    return reply();
  }) as typeof fetch);
  const oldFetch = fetcher(oldTrace), nextFetch = fetcher(nextTrace);
  const oldDocument = new EventTarget() as EventTarget & { hidden: boolean }; oldDocument.hidden = false;
  const context = vm.createContext({ authToken: authOne.token, API_URL: 'https://ebs.example', location: { pathname: surface === 'mobile' ? '/mobile.html' : '/extension.html' },
    document: oldDocument, crypto, Date, setTimeout, clearTimeout, AbortController, fetch: oldFetch, ShedLink: {} });
  context.window = context; vm.runInContext(oldSource, context);
  const old = (context.ShedLink as { usage: UsageApi }).usage;
  const auth = new TwitchAuthStore(); auth.authorize(authOne);
  let state: IdentityState = { status: 'ready', login: 'alice', message: '', canShare: false, shareRequested: false };
  const listeners = new Set<() => void>();
  const identity = { snapshot: () => state, subscribe: (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; } };
  const next = new PanelUsage({ auth, identity, baseUrl: 'https://ebs.example', surface, fetcher: nextFetch }); next.start();
  drains.push(() => next.stop());
  const both = (run: (usage: UsageApi) => void) => { run(old); run(next); };
  const token = (value: string, userId = authOne.userId) => { context.authToken = value; auth.authorize({ ...authOne, token: value, userId }); };
  return { old, next, both, auth, oldFetch, nextFetch, oldTrace, nextTrace, context, oldDocument, token,
    status: (status: IdentityState['status']) => { state = { ...state, status, login: status === 'ready' ? 'alice' : undefined }; listeners.forEach(fn => fn()); } };
}
const normalize = (trace: RequestTrace[]) => trace.map(({ body, signal, ...request }) => ({ ...request, body: { ...JSON.parse(body), batch_id: '<generated>' }, signal: signal ? 'abort-signal' : null }));
const events = (trace: RequestTrace[], at = 0) => JSON.parse(trace[at].body).events as { kind: string; feature: string; count: number }[];
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(Date.UTC(2026, 9, 2, 12)); Object.defineProperty(document, 'hidden', { configurable: true, value: false }); });
afterEach(() => { drains.splice(0).forEach(fn => fn()); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('legacy panel usage collector parity', () => {
  it.each(['desktop', 'mobile'] as const)('matches the full %s batch after exactly 30 seconds and hidden-page flush', async surface => {
    const p = pair(surface);
    p.both(u => { u.trackPanel('core'); u.trackPanel('bannerlord'); u.trackSection('bannerlord:tab.inventory'); u.trackAction('bannerlord:hero.buy_equipment'); });
    await vi.advanceTimersByTimeAsync(29999); expect(p.nextTrace).toHaveLength(0); expect(p.oldTrace).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1); expect(normalize(p.nextTrace)).toEqual(normalize(p.oldTrace)); expect(p.nextTrace).toHaveLength(1);
    expect(events(p.nextTrace)).toEqual([{ kind: 'panel_view', feature: 'core:panel', count: 1 }, { kind: 'panel_view', feature: 'bannerlord:panel', count: 1 }, { kind: 'section_open', feature: 'bannerlord:tab.inventory', count: 1 }, { kind: 'action_attempt', feature: 'bannerlord:hero.buy_equipment', count: 1 }]);
    p.both(u => u.trackAction('bannerlord:hero.equip_owned'));
    p.oldDocument.hidden = true; p.oldDocument.dispatchEvent(new Event('visibilitychange'));
    Object.defineProperty(document, 'hidden', { configurable: true, value: true }); document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0); expect(p.nextTrace).toHaveLength(2); expect(normalize(p.nextTrace)).toEqual(normalize(p.oldTrace));
  });
  it('deduplicates exposure per UTC day, keeps known modules for midnight action reseeding, and never seeds unseen modules', async () => {
    const p = pair(); vi.setSystemTime(Date.UTC(2026, 9, 2, 23, 59, 59));
    p.both(u => { u.trackPanel('core'); u.trackPanel('bannerlord'); for (let i = 0; i < 10; i++) u.trackPanel('bannerlord'); });
    await p.old.flush(); await p.next.flush();
    vi.setSystemTime(Date.UTC(2026, 9, 3)); p.both(u => { u.trackAction('bannerlord:hero.add_focus'); u.trackAction('rimworld:player.heal'); u.trackAction('bannerlord:hero.add_focus'); });
    await p.old.flush(); await p.next.flush(); expect(normalize(p.nextTrace)).toEqual(normalize(p.oldTrace));
    expect(events(p.nextTrace, 1)).toEqual([{ kind: 'panel_view', feature: 'bannerlord:panel', count: 1 }, { kind: 'action_attempt', feature: 'bannerlord:hero.add_focus', count: 2 }, { kind: 'action_attempt', feature: 'rimworld:player.heal', count: 1 }]);
  });
  it('retains the exact old action and section allowlists, and rejects payload-like feature keys', async () => {
    const p = pair();
    for (const feature of allowedActions) { p.both(u => u.trackAction(feature)); await p.old.flush(); await p.next.flush(); }
    for (const feature of allowedSections) { p.both(u => u.trackSection(feature)); await p.old.flush(); await p.next.flush(); }
    p.both(u => { u.trackAction('bannerlord:hero.buy_equipment:alice:sword:4,5'); u.trackSection('bannerlord:tab.unknown'); u.trackPanel('evil'); });
    await p.old.flush(); await p.next.flush(); expect(p.nextTrace).toHaveLength(allowedActions.length + allowedSections.length);
    expect(normalize(p.nextTrace)).toEqual(normalize(p.oldTrace));
    for (const trace of p.nextTrace) { expect(trace.body).not.toContain(authOne.token); expect(trace.body).not.toContain('alice'); expect(Object.keys(events([trace])[0]).sort()).toEqual(['count', 'feature', 'kind']); }
  });
  it.each(['same viewer', 'new viewer'])('discards queued and in-flight data on token rotation for %s', async kind => {
    const p = pair(); p.oldFetch.mockImplementationOnce(async () => { throw new Error('offline'); }); p.nextFetch.mockImplementationOnce(async () => { throw new Error('offline'); });
    p.both(u => u.trackAction('bannerlord:hero.add_focus')); await p.old.flush(); await p.next.flush();
    p.both(u => u.trackAction('bannerlord:hero.add_attribute')); p.token('new-private-token', kind === 'new viewer' ? 'viewer-b' : authOne.userId);
    p.both(u => u.trackPanel('bannerlord')); await vi.advanceTimersByTimeAsync(180000);
    expect(normalize(p.nextTrace)).toEqual(normalize(p.oldTrace)); expect(p.nextTrace).toHaveLength(1);
    expect(events(p.nextTrace)).toEqual([{ kind: 'panel_view', feature: 'bannerlord:panel', count: 1 }]);
    expect(new Headers(p.nextTrace[0].headers).get('X-Twitch-JWT')).toBe('new-private-token');
  });
  it('blocks flush and collection while identity resolution is blocked, then discards the old token context', async () => {
    const p = pair(); p.next.trackPanel('bannerlord'); p.next.trackAction('bannerlord:hero.add_focus'); p.status('resolving');
    await vi.advanceTimersByTimeAsync(30000); await p.next.flush(); p.next.trackAction('bannerlord:hero.add_attribute');
    p.status('blocked'); await p.next.flush(); expect(p.nextTrace).toHaveLength(0);
    p.token('rotated'); p.status('ready'); p.next.trackPanel('bannerlord'); await p.next.flush();
    expect(events(p.nextTrace)).toEqual([{ kind: 'panel_view', feature: 'bannerlord:panel', count: 1 }]);
  });
  it('resumes a suspended same-token queue only after identity becomes ready', async () => {
    const p = pair(); p.next.trackAction('bannerlord:hero.add_focus'); p.status('blocked'); await vi.advanceTimersByTimeAsync(30000);
    expect(p.nextTrace).toHaveLength(0); p.status('ready'); await vi.advanceTimersByTimeAsync(30000); expect(p.nextTrace).toHaveLength(1);
  });
  it.each([500, 503, 429])('retries status %i twice at 60s with identical batch ID and body', async status => {
    const p = pair(); p.oldFetch.mockImplementation(async (url, init) => { p.oldTrace.push({ url: String(url), method: init?.method, headers: [...new Headers(init?.headers)], body: String(init?.body), keepalive: init?.keepalive, signal: init?.signal }); return reply(status); });
    p.nextFetch.mockImplementation(async (url, init) => { p.nextTrace.push({ url: String(url), method: init?.method, headers: [...new Headers(init?.headers)], body: String(init?.body), keepalive: init?.keepalive, signal: init?.signal }); return reply(status); });
    p.both(u => u.trackAction('bannerlord:hero.add_focus'));
    await vi.advanceTimersByTimeAsync(30000); expect(p.nextTrace).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(59999); expect(p.nextTrace).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1); expect(p.nextTrace).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(60000); expect(p.nextTrace).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(300000); expect(p.nextTrace).toHaveLength(3);
    expect(new Set(p.nextTrace.map(x => x.body)).size).toBe(1); expect(normalize(p.nextTrace)).toEqual(normalize(p.oldTrace));
  });
  it.each([200, 400, 401, 403, 404, 413])('drops a completed status %i instead of retrying', async status => {
    const p = pair(); p.oldFetch.mockResolvedValue(reply(status)); p.nextFetch.mockResolvedValue(reply(status));
    p.both(u => u.trackAction('bannerlord:hero.add_focus')); await vi.advanceTimersByTimeAsync(600000);
    expect(p.oldFetch).toHaveBeenCalledTimes(1); expect(p.nextFetch).toHaveBeenCalledTimes(1);
  });
  it('times out after 5 seconds, aborts transport and retries exactly twice without awaiting user work', async () => {
    const p = pair(); const oldSignals: AbortSignal[] = [], nextSignals: AbortSignal[] = [];
    p.oldFetch.mockImplementation((_, init) => { oldSignals.push(init!.signal!); return new Promise(() => {}); });
    p.nextFetch.mockImplementation((_, init) => { nextSignals.push(init!.signal!); return new Promise(() => {}); });
    p.both(u => u.trackAction('bannerlord:hero.add_focus')); await vi.advanceTimersByTimeAsync(34999); expect(nextSignals[0].aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1); expect(nextSignals[0].aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(130000); expect(nextSignals).toHaveLength(3); expect(nextSignals.every(x => x.aborted)).toBe(true);
    await vi.advanceTimersByTimeAsync(300000); expect(p.nextFetch).toHaveBeenCalledTimes(3); expect(p.oldFetch).toHaveBeenCalledTimes(3); expect(oldSignals.every(x => x.aborted)).toBe(true);
  });
  it('caps each event at 20, distinct events at 20, and total queued attempts at 100', async () => {
    const p = pair();
    p.both(u => { for (let i = 0; i < 99; i++) u.trackAction(allowedActions[0]); }); await p.old.flush(); await p.next.flush(); expect(events(p.nextTrace)[0].count).toBe(20);
    p.both(u => { for (const feature of allowedActions.slice(0, 30)) u.trackAction(feature); }); await p.old.flush(); await p.next.flush(); expect(events(p.nextTrace, 1)).toHaveLength(20);
    p.both(u => { for (const feature of allowedActions.slice(0, 10)) for (let i = 0; i < 20; i++) u.trackAction(feature); }); await p.old.flush(); await p.next.flush();
    expect(events(p.nextTrace, 2).reduce((n, e) => n + e.count, 0)).toBe(100); expect(normalize(p.nextTrace)).toEqual(normalize(p.oldTrace));
  });
  it('isolates thrown transport and UUID failures, does not persist anything, and disposes the lifecycle', async () => {
    const p = pair(); const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage forbidden'); });
    p.nextFetch.mockImplementation(() => { throw new Error('offline'); }); expect(() => p.next.trackAction('bannerlord:hero.add_focus')).not.toThrow(); await expect(p.next.flush()).resolves.toBeUndefined();
    p.token('new'); const uuid = vi.spyOn(crypto, 'randomUUID').mockImplementation(() => { throw new Error('entropy unavailable'); });
    p.next.trackPanel('bannerlord'); await expect(p.next.flush()).resolves.toBeUndefined(); uuid.mockRestore();
    p.next.stop(); p.next.trackAction('bannerlord:hero.add_focus'); document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(300000);
    expect(p.nextFetch).toHaveBeenCalledTimes(1); expect(storage).not.toHaveBeenCalled();
  });
});
