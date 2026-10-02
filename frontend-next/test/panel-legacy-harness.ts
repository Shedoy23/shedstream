/**
 * Independent frozen-client oracle. Every local script is evaluated unchanged,
 * in extension.html order, in its own actual jsdom document/VM. The Twitch SDK
 * is the only omitted external script; its registration surface is inert.
 *
 * Scope is the development sub-screen, not the whole extension startup:
 * - DOMContentLoaded startup is withheld and the SDK never authorizes itself.
 * - Only hero header, hero stats, class/build picker and progression hosts exist.
 * - The existing stats host prevents the legacy build-once skeleton from adding
 *   daily/retinue/gender hosts. No DOM lookup or renderer is intercepted.
 * - A real controlled 8-second development interval owns _bannerlordPollId.
 *   This makes the unchanged game registry's repeated start call (from successful
 *   stats refresh) a no-op instead of starting unrelated whole-panel polling.
 * - The source-created one-second cooldown ticker remains operational. Buff
 *   polling is explicit via refreshBuffs(), not the whole-panel 2.5-second loop.
 * - panelLifecycle adds the unchanged old tab bindings and the selected-host
 *   8s/2.5s polling schedule, including the old active-inventory condition. It
 *   still excludes unrelated shop/status/tournament/battle hosts and startup.
 * - combatHost adds the real combat DOM without tournament, the 2s battle
 *   loader, the exact source-owned 1s buff timer, and the shared-shell 60s
 *   loadUserData interval (including hidden pages). It is still selected-host
 *   initialization, not a claim to execute the complete extension bootstrap.
 * All resulting requests, including stats/level/duels and the 3.5-second tail,
 * are recorded. There is no route fall-through, request filtering or action stub.
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';
import savedResponses from './panel-fixtures/real-responses.json';
import combatSaved from './panel-fixtures/combat-responses.json';

const require = createRequire(import.meta.url);
type LegacyWindow = Window & {
  Event: typeof Event;
  Date: DateConstructor;
  Twitch: unknown;
  matchMedia: typeof window.matchMedia;
  fetch: typeof fetch;
};
type LegacyDom = { window: LegacyWindow; getInternalVMContext(): vm.Context };
// jsdom has no bundled declarations in this existing package. Keep its untyped
// boundary here rather than introducing any into the request fixture contract.
const { JSDOM } = require('jsdom') as {
  JSDOM: new (html: string, options: Record<string, unknown>) => LegacyDom;
};
const legacyRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../Расширение/frontend') + '/';
const shell = readFileSync(`${legacyRoot}extension.html`, 'utf8');
const sourceFiles = [...shell.matchAll(/<script\b[^>]*\bsrc="([^"]+)"[^>]*>/g)]
  .map(match => match[1].split('?')[0]).filter(file => !/^https?:/i.test(file));
const sources = sourceFiles.map(file => ({ file, source: readFileSync(`${legacyRoot}${file}`, 'utf8') }));
// All scripts below still execute unchanged. Selected-host startup additionally
// registers the exact original buff timer statement; do not rewrite its callback
// in this harness or replace any of the live old render/action functions.
const combatSource = sources.find(entry => entry.file === 'viewer-bannerlord.js')!.source;
const buffTimerMarker = '    _bannerlordBuffTickId = safeInterval(() => {';
if (combatSource.split(buffTimerMarker).length !== 2) throw new Error('Original buff timer selector drifted');
const buffTimerStart = combatSource.indexOf(buffTimerMarker);
const buffTimerEnd = combatSource.indexOf('    }, 1000);', buffTimerStart);
if (buffTimerStart < 0 || buffTimerEnd < 0) throw new Error('Original buff timer registration missing');
const originalBuffTimer = combatSource.slice(buffTimerStart, buffTimerEnd + '    }, 1000);'.length);

export const legacyResponses = savedResponses.responses;
export const combatResponses = combatSaved.responses;
export type LegacyJson = null | boolean | number | string | LegacyJson[] | { [key: string]: LegacyJson | undefined };
export interface LegacyRequest {
  method: string;
  path: string;
  query: string;
  body: LegacyJson | null;
  rawBody: string | null;
  token: string;
  contentType: string;
  cache: string | null;
  keepalive?: boolean;
}
export interface LegacyHttpReply { legacyHttpReply: true; status: number; json: LegacyJson }
export const legacyHttpReply = (json: LegacyJson, status = 200): LegacyHttpReply => ({ legacyHttpReply: true, status, json });
export type LegacyFixture = LegacyJson | LegacyHttpReply |
  ((request: LegacyRequest, call: number) => LegacyJson | LegacyHttpReply | Promise<LegacyJson | LegacyHttpReply>);
export interface LegacyFixtures {
  config: LegacyFixture;
  hero: LegacyFixture;
  classes: LegacyFixture;
  build: LegacyFixture;
  buffs: LegacyFixture;
  action: LegacyFixture;
  stats: LegacyFixture;
  level: LegacyFixture;
  duels: LegacyFixture;
  usage: LegacyFixture;
  equipment: LegacyFixture;
  battle: LegacyFixture;
}
export const legacySelectors = {
  focus: (key: string) => `.bnr-prog-focus-btn[data-skill=${JSON.stringify(key)}]`,
  attribute: (key: string) => `.bnr-prog-attr-btn[data-attr=${JSON.stringify(key)}]`,
  class: '#bnr-class-select',
  specialization: (id: string) => `[data-bnr-build-spec=${JSON.stringify(id)}]`,
  starter: (id: string) => `[data-bnr-build-starter=${JSON.stringify(id)}]`,
  notice: '.notification',
};

export function createLegacyHarness(overrides: Partial<LegacyFixtures> = {}, options: {
  login?: string; token?: string; now?: number; scope?: 'hero' | 'equipment'; equipmentHost?: boolean; panelLifecycle?: boolean; combatHost?: boolean;
} = {}) {
  let login = options.login ?? 'alice';
  let token = options.token ?? 'alice-token';
  const equipmentOnly = options.scope === 'equipment';
  const fixtures: LegacyFixtures = {
    config: legacyResponses.config,
    hero: legacyResponses.hero,
    classes: legacyResponses.classes,
    build: legacyResponses.build_legacy,
    buffs: legacyResponses.buffs,
    // No generic successful mutation default. Each action family uses its actual
    // handler-generated response. Unknown action types fail the fixture boundary.
    action: request => {
      const body = request.body as { action_type?: string } | null;
      switch (body?.action_type) {
        case 'hero.add_focus': return legacyResponses.focus_success.response;
        case 'hero.add_attribute': return legacyResponses.attribute_success.response;
        case 'hero.set_class': return legacyResponses.class_success.response;
        case 'hero.set_specialization': return legacyResponses.specialization_success.response;
        case 'hero.claim_starter': return legacyResponses.starter_success.response;
        case 'hero.buy_equipment': return legacyResponses.equipment_buy.response;
        case 'hero.equip_owned': return legacyResponses.equipment_equip.response;
        case 'hero.unequip_owned': return legacyResponses.equipment_unequip.response;
        case 'hero.discard_owned': return legacyResponses.equipment_discard.response;
        default: throw new Error(`Unmatched legacy action fixture: ${body?.action_type}`);
      }
    },
    // The shared-shell success tail also comes from actual route handlers on
    // the isolated full-migrations DB, not a hand-invented minimal shape.
    stats: legacyResponses.stats,
    level: legacyResponses.level,
    duels: legacyResponses.duels,
    usage: legacyHttpReply(legacyResponses.usage_unauthorized, 401),
    equipment: legacyResponses.equipment_inventory,
    battle: combatResponses.battle_idle,
    ...overrides,
  };
  const dom = new JSDOM(shell, { url: 'https://extension-files.twitch.tv/extension.html', runScripts: 'outside-only', pretendToBeVisual: true });
  const window = dom.window;
  const document = window.document;
  const context = dom.getInternalVMContext();
  const trace: LegacyRequest[] = [];
  const failures: Error[] = [];
  let now = options.now ?? Date.UTC(2026, 9, 2, 12);
  let nextTimer = 0, nextTimerOrder = 0;
  let disposed = false;
  let booted = false;
  const timers = new Map<number, { at: number; order: number; repeat: number; run: () => void }>();
  const evaluate = <T = unknown>(source: string): T => vm.runInContext(source, context) as T;
  function recordFailure(error: unknown) {
    const failure = error instanceof Error ? error : new Error(String(error));
    failures.push(failure);
    return failure;
  }
  function assertHealthy() {
    if (failures.length) throw new Error(`Legacy harness failed: ${failures.map(error => error.message).join('; ')}`);
  }
  const registerTimer = (handler: TimerHandler, ms: number | undefined, args: unknown[], interval: boolean) => {
    const id = ++nextTimer;
    const delay = Math.max(interval ? 1 : 0, Number(ms) || 0);
    timers.set(id, { at: now + delay, order: ++nextTimerOrder, repeat: interval ? delay : 0, run: () => {
      if (typeof handler === 'string') evaluate(handler);
      else handler(...args);
    } });
    return id;
  };
  window.setTimeout = (handler, ms, ...args) => registerTimer(handler, ms, args, false);
  window.setInterval = (handler, ms, ...args) => registerTimer(handler, ms, args, true);
  window.clearTimeout = id => { if (id !== undefined) timers.delete(id); };
  window.clearInterval = id => { if (id !== undefined) timers.delete(id); };
  window.requestAnimationFrame = callback => registerTimer(() => callback(now), 16, [], false);
  window.cancelAnimationFrame = id => { if (id !== undefined) timers.delete(id); };
  window.Date.now = () => now;
  window.matchMedia = () => ({ matches: false, media: '', onchange: null,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent() { return true; } });
  const addDocumentListener = document.addEventListener.bind(document);
  document.addEventListener = ((name: string, listener: EventListenerOrEventListenerObject, opts?: AddEventListenerOptions | boolean) => {
    if (name !== 'DOMContentLoaded') addDocumentListener(name, listener, opts);
  }) as typeof document.addEventListener;
  window.addEventListener('error', event => {
    recordFailure(event.error ?? event.message);
    event.preventDefault();
  });
  Object.defineProperty(window, 'Twitch', { value: { ext: {
    onAuthorized() {}, onContext() {}, onError() {}, onVisibilityChanged() {}, listen() {}, unlisten() {}, send() {},
    actions: { requestIdShare() {} }, configuration: { onChanged() {}, broadcaster: null, global: null, developer: null },
    viewer: { id: null, opaqueId: null, isLinked: false, onChanged() {} },
    features: { onChanged() {} }, rig: { log() {} }, bits: { onTransactionComplete() {}, getProducts: async () => [] },
  } } });
  const routeKeys = new Map<string, keyof LegacyFixtures>([
    ['GET /api/bannerlord/config', 'config'], ['GET /api/bannerlord/my-hero', 'hero'],
    ['GET /api/bannerlord/classes', 'classes'], ['GET /api/bannerlord/build', 'build'],
    ['GET /api/bannerlord/my-buffs', 'buffs'], ['POST /api/bannerlord/action', 'action'],
    ['GET /api/bannerlord/equipment-shop', 'equipment'],
    ['GET /api/bannerlord/battle-status', 'battle'],
    [`GET /api/viewer/stats/${login}`, 'stats'], [`GET /api/user/level/${login}`, 'level'],
    ['GET /api/duel/list', 'duels'], ['POST /api/viewer/ui-usage', 'usage'],
  ]);
  const callCounts = new Map<keyof LegacyFixtures, number>();
  window.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), window.location.href);
    const rawBody = init.body === undefined || init.body === null ? null : String(init.body);
    let body: LegacyJson | null = null;
    if (rawBody !== null) {
      try { body = JSON.parse(rawBody) as LegacyJson; }
      catch { throw recordFailure(new Error(`Non-JSON legacy request body: ${rawBody}`)); }
    }
    const request: LegacyRequest = { method: (init.method ?? 'GET').toUpperCase(), path: url.pathname,
      query: url.search, body, rawBody, token: new Headers(init.headers).get('X-Twitch-JWT') ?? '',
      contentType: new Headers(init.headers).get('Content-Type') ?? '', cache: init.cache ?? null, ...(init.keepalive !== undefined ? { keepalive: init.keepalive } : {}) };
    trace.push(request);
    const key = routeKeys.get(`${request.method} ${request.path}`);
    if (!key || request.query !== '' || (request.method === 'GET' && rawBody !== null)) {
      throw recordFailure(new Error(`Unmatched legacy request: ${request.method} ${request.path}${request.query} ${rawBody ?? ''}`));
    }
    const fixture = fixtures[key];
    const call = (callCounts.get(key) ?? 0) + 1;
    callCounts.set(key, call);
    let result: LegacyJson | LegacyHttpReply;
    try { result = typeof fixture === 'function' ? await fixture(request, call) : fixture; }
    catch (error) { throw recordFailure(error); }
    const wrapped = result !== null && typeof result === 'object' && 'legacyHttpReply' in result && result.legacyHttpReply === true;
    const status = wrapped ? (result as LegacyHttpReply).status : 200;
    const json = wrapped ? (result as LegacyHttpReply).json : result;
    return { ok: status >= 200 && status < 300, status, json: async () => structuredClone(json),
      text: async () => JSON.stringify(json) } as Response;
  }) as typeof fetch;

  for (const { file, source } of sources) {
    try { vm.runInContext(source, context, { filename: file }); }
    catch (error) { throw recordFailure(new Error(`${file}: ${String(error)}`)); }
  }
  document.body.innerHTML = equipmentOnly
    ? '<main id="bannerlord-content"><div id="bnr-equipment-shop"></div></main>'
    : `<main id="bannerlord-content">
    ${options.combatHost ? '<button class="bnr-tab-btn" data-bnr-tab="combat">Боевые действия</button>' : ''}
    ${options.panelLifecycle ? '<button class="bnr-tab-btn" data-bnr-tab="hero">Развитие</button><button class="bnr-tab-btn" data-bnr-tab="inventory">Снаряжение</button>' : ''}
    ${options.combatHost ? '<section class="bnr-tab-pane" data-bnr-pane="combat"><div id="bnr-battle-banner-slot"></div><div id="bnr-combat-stance-slot"></div><div id="bnr-buff-hud"></div><div id="bnr-detachment-slot"></div><div id="bnr-summon-slot" data-bnr-ui-section="summon"></div><div id="bnr-active-powers-slot" data-bnr-ui-section="active_powers"></div><div id="bnr-build-choice-slot" data-bnr-ui-section="weapon_choice"></div></section>' : ''}
    <div id="hero-body"></div>
    <section id="bnr-pane-hero-body" class="bnr-tab-pane active" data-bnr-pane="hero">
      <div id="bnr-pane-hero-stats"></div>
      <div id="hero-class-picker-slot"></div>
      <div id="bnr-progression-slot"></div>
    </section>
    ${options.equipmentHost || options.panelLifecycle ? '<section class="bnr-tab-pane" data-bnr-pane="inventory"><div id="bnr-equipment-shop"></div></section>' : ''}
  </main>`;
  evaluate(`authToken=${JSON.stringify(token)};userLogin=${JSON.stringify(login)};window.userLogin=userLogin;`);
  if (options.panelLifecycle) evaluate(`localStorage.setItem('bnr_active_tab',${JSON.stringify(options.combatHost ? 'combat' : 'hero')});_bindBnrInnerTabs();`);

  async function settle() {
    // A native event-loop turn drains recursively scheduled promise jobs from
    // old VM fetch/json, shared actions and their unawaited follow-up loaders.
    await new Promise<void>(resolve => setImmediate(resolve));
    assertHealthy();
  }
  async function advance(ms: number) {
    if (!Number.isFinite(ms) || ms < 0) throw new Error('advance(ms) needs a finite nonnegative duration');
    await settle();
    const until = now + ms;
    let count = 0;
    while (!disposed) {
      const due = [...timers].filter(([, timer]) => timer.at <= until)
        .sort((a, b) => a[1].at - b[1].at || a[1].order - b[1].order)[0];
      if (!due) break;
      if (++count > 100000) throw new Error('Legacy timer runaway');
      const [id, timer] = due;
      now = timer.at;
      // A repeating timer schedules its next task after its current task,
      // just like the browser/Vitest timer queue. Its original handle does not
      // give it priority over an earlier scheduled equal-deadline timeout.
      if (timer.repeat) { timer.at += timer.repeat; timer.order = ++nextTimerOrder; }
      else timers.delete(id);
      try { timer.run(); } catch (error) { recordFailure(error); }
      await settle();
    }
    now = until;
    await settle();
  }
  function enterLifecycle() {
    if (booted) return;
    booted = true;
    // Keep the registered module already active without invoking whole-panel
    // startup. This is a real selected-screen polling interval, not a sentinel.
    const reads = equipmentOnly ? 'loadBannerlordEquipmentShop();'
      : 'loadBannerlordHero(); loadBannerlordClasses(); loadBannerlordBuild();' + (options.panelLifecycle ? `if (document.querySelector('[data-bnr-pane="inventory"].active')) loadBannerlordEquipmentShop();` : '');
    evaluate(`_bannerlordPollId = safeInterval(() => { if (!document.hidden) { ${reads} } }, 8000);`);
    if (options.panelLifecycle) evaluate('_bannerlordBuffPollId = safeInterval(() => { if (!document.hidden) loadBannerlordBuffs(); }, 2500);');
    if (options.combatHost) evaluate('_bannerlordBattlePollId = safeInterval(() => { if (!document.hidden) loadBannerlordBattleStatus(); }, 2000);');
    // Actual shared-shell affordability dependency; safeInterval itself does
    // not suppress hidden reads. No unrelated active stats-tab host exists.
    if (options.combatHost) { evaluate(originalBuffTimer); evaluate('uiUpdateInterval = safeInterval(() => { loadUserData(); }, 60000);'); }
  }
  async function bootEquipment() {
    if (!document.getElementById('bnr-equipment-shop')) throw new Error('bootEquipment needs scope:equipment or equipmentHost:true');
    enterLifecycle();
    await refresh('loadBannerlordEquipmentShop');
  }
  function setIdentity(nextLogin: string, nextToken: string) {
    routeKeys.delete(`GET /api/viewer/stats/${login}`);
    routeKeys.delete(`GET /api/user/level/${login}`);
    login = nextLogin;
    token = nextToken;
    routeKeys.set(`GET /api/viewer/stats/${login}`, 'stats');
    routeKeys.set(`GET /api/user/level/${login}`, 'level');
    evaluate(`authToken=${JSON.stringify(token)};userLogin=${JSON.stringify(login)};window.userLogin=userLogin;`);
  }
  async function resetEquipment(nextLogin = login, nextToken = token) {
    evaluate('BnrEquipmentShop.reset()');
    setIdentity(nextLogin, nextToken);
    await settle();
  }
  async function bootHero() {
    if (booted) throw new Error('bootHero may be called only once; use refreshHero/refreshBuild/refreshBuffs');
    if (equipmentOnly) throw new Error('bootHero needs the hero scope');
    enterLifecycle();
    for (const loader of ['_hydrateBnrConfig', 'loadBannerlordHero', 'loadBannerlordClasses', 'loadBannerlordBuild', 'loadBannerlordBuffs']) {
      await evaluate<Promise<void>>(`${loader}()`);
      await settle();
    }
  }
  async function bootCombat() {
    if (!options.combatHost) throw new Error('bootCombat requires combatHost:true');
    await bootHero(); await refresh('loadUserData'); await refresh('loadBannerlordBattleStatus');
  }
  function element(selector: string) {
    const node = document.querySelector<HTMLElement>(selector);
    if (!node) throw new Error(`Old rendered element missing: ${selector}`);
    return node;
  }
  async function click(selector: string) { element(selector).click(); await settle(); }
  async function change(selector: string, value: string) {
    const node = element(selector) as HTMLSelectElement;
    if (node.tagName !== 'SELECT') throw new Error(`Old change target is not a select: ${selector}`);
    if (![...node.options].some(option => option.value === value)) throw new Error(`Old select option missing: ${value}`);
    node.value = value;
    node.dispatchEvent(new window.Event('change', { bubbles: true }));
    await settle();
  }
  async function refresh(loader: string) { await evaluate<Promise<void>>(`${loader}()`); await settle(); }
  async function exposeUsagePanels() {
    if (!booted) throw new Error('Usage exposure requires the selected host to be booted');
    if (!document.querySelector('.tab[data-tab="rimworld"]')) {
      const tab = document.createElement('button'); tab.className = 'tab active'; tab.dataset.tab = 'rimworld'; document.body.prepend(tab);
    }
    // The actual integration switch populates module context and calls the
    // actual visibility/exposure function; the existing poll owner avoids
    // unrelated whole-shell startup, just as after a real stats refresh.
    evaluate("switchIntegrationModule('bannerlord');"); await settle();
  }
  async function setHidden(hidden: boolean) {
    Object.defineProperty(document, 'hidden', { configurable: true, value: hidden });
    document.dispatchEvent(new window.Event('visibilitychange')); await settle();
  }
  function dispose() { disposed = true; timers.clear(); window.close(); }
  assertHealthy();
  return { bootHero, bootCombat, bootEquipment, resetEquipment, setIdentity, exposeUsagePanels, setHidden, trace, document, window, fixtures, sourceFiles: [...sourceFiles], settle, advance, click, change,
    refreshConfig: () => refresh('_hydrateBnrConfig'),
    refreshHero: () => refresh('loadBannerlordHero'), refreshBuild: () => refresh('loadBannerlordBuild'),
    refreshBuffs: () => refresh('loadBannerlordBuffs'),
    refreshBattle: () => refresh('loadBannerlordBattleStatus'),
    refreshEquipment: () => refresh('loadBannerlordEquipmentShop'), assertHealthy, dispose };
}
