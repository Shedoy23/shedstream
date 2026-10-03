// Actual asynchronous Bannerlord renderers, not prebuilt details: delayed DOM
// must receive persistence/usage handlers after repaint, with no polling events.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
const { parseHTML } = createRequire(import.meta.url)('linkedom');
const source = readFileSync(new URL('../Расширение/frontend/viewer-bannerlord.js', import.meta.url), 'utf8');
function harness(slotId) {
    const { window, document } = parseHTML(`<html><head></head><body><div id="${slotId}"></div></body></html>`);
    // linkedom does not implement HTMLDetailsElement.open; mirror the browser attribute.
    Object.defineProperty(window.HTMLElement.prototype, 'open', { configurable: true,
        get() { return this.hasAttribute('open'); }, set(value) { this.toggleAttribute('open', !!value); } });
    window._bnrCdTickerStarted = true;
    const events = [], errors = [], requests = [], games = {};
    const data = { success: true, has_hero: true, kingdom_id: 'kingdom', kingdom_name: 'Kingdom', is_king: true,
        is_clan_leader: true, vassals: [], heirs: [{ hero_id: 'heir-1', name: 'Heir' }],
        workshops: [], caravans: [], fiefs: [{ fief_id: 'town-1', fief_name: 'Town', fief_type: 'town' }] };
    const context = vm.createContext({ window, document, AbortController, clearTimeout() {}, API_URL: 'https://fixture.invalid', authToken: 'fixture',
        _cachedUserPoints: 100000, escapeHtml: value => String(value),
        console: { info() {}, warn: (...args) => errors.push(args.map(String).join(' ')), error: (...args) => errors.push(args.map(String).join(' ')) },
        ShedLink: { registerGame: (name, spec) => { games[name] = spec; }, usage: { trackSection: key => events.push(key) } },
        BnrBuilds: { reset() {} }, BnrEquipmentShop: { reset() {} }, showNotification() {},
        setInterval: () => 1, clearInterval() {}, safeInterval: () => 1, setTimeout() {},
        fetch: async url => { requests.push(url); await new Promise(resolve => setImmediate(resolve)); return { ok: true, json: async () => structuredClone(data) }; } });
    vm.runInContext(source, context);
    vm.runInContext('_bannerlordLastHero = {has_hero:true,hero:{gold:1000000,clan_info:{is_leader:true}}}', context);
    // The controls being tested are produced by real loaders. Lazy form contents
    // are a different concern; avoid their auxiliary requests after opening.
    for (const name of ['_renderCreateVassalInline', '_renderBuyWorkshopInline', '_renderBuyCaravanInline',
        '_renderPartyOrderInline', '_renderMakePeaceInline', '_renderCreateKingdomInline', '_renderJoinInline', '_renderCreateClanInline']) context[name] = () => {};
    const invoke = code => vm.runInContext(code, context);
    const detail = key => document.querySelector(`[data-bnr-details="${key}"]`);
    const section = key => document.querySelector(`[data-bnr-section="${key}"]`);
    const toggle = (node, open) => { assert(node, 'renderer must create the target details'); node.open = open; node.dispatchEvent(new window.Event('toggle')); };
    return { context, document, data, errors, events, requests, games, invoke, detail, section, toggle };
}
let total = 0, failed = 0;
async function test(name, fn) {
    total++;
    try { await fn(); console.log('PASS ' + name); }
    catch (error) { failed++; console.error('FAIL ' + name + ': ' + error.message); }
}
const detailCases = [
    ['bnr-vassals-slot', 'loadBannerlordVassals()', 'vas-create'],
    ['bnr-workshops-slot', 'loadBannerlordWorkshops()', 'ws-buy'],
    ['bnr-caravans-slot', 'loadBannerlordCaravans()', 'caravan-buy'],
    ['bnr-party-orders-slot', 'loadBannerlordPartyOrders()', 'party-order'],
    ['bnr-diplo-slot', 'loadBannerlordDiplomacy()', 'diplo-policy'],
    ['bnr-diplo-slot', 'loadBannerlordDiplomacy()', 'diplo-peace'],
    ['bnr-kingdom-mgmt-slot', 'loadBannerlordKingdomMgmt()', 'kingdom-create'],
    ['bnr-kingdom-mgmt-slot', 'loadBannerlordKingdomMgmt()', 'kingdom-join'],
    ['bnr-dynasty-locked-actions', 'loadBannerlordDynastyLockedActions()', 'locked-create'],
    ['bnr-dynasty-locked-actions', 'loadBannerlordDynastyLockedActions()', 'locked-join'],
    ['bnr-retinue-slot', '_renderRetinue([])', 'retinue'],
];
for (const [slot, loader, key] of detailCases) await test('post-render details: ' + key, async () => {
    const h = harness(slot); h.invoke('_bnrBindDetailsPersistence(); _bnrBindSectionToggle()');
    await h.invoke(loader); assert.deepEqual(h.errors, [], 'renderer must execute successfully');
    assert.deepEqual(h.events, [], 'rendering is not a user opening');
    h.toggle(h.detail(key), true);
    assert.deepEqual(h.events, ['bannerlord:details.' + key]);
    assert.equal(h.invoke(`_bannerlordDetailsOpen.has('${key}')`), true, 'user-open persists');
    await h.invoke(loader); assert.equal(h.events.length, 1, 'polling/restored open must not count');
    h.invoke('_bnrBindDetailsPersistence(); _bnrBindSectionToggle()');
    h.toggle(h.detail(key), true); assert.equal(h.events.length, 1, 'redundant toggle/bind must not count twice');
    h.toggle(h.detail(key), false); assert.equal(h.invoke(`_bannerlordDetailsOpen.has('${key}')`), false);
    h.toggle(h.detail(key), true); assert.equal(h.events.length, 2, 'a later real opening counts once');
});
const sectionCases = [
    ['bnr-workshops-slot', 'loadBannerlordWorkshops()', 'workshops'],
    ['bnr-caravans-slot', 'loadBannerlordCaravans()', 'caravans'],
    ['bnr-fiefs-slot', 'loadBannerlordFiefs()', 'fiefs'],
    ['bnr-party-orders-slot', 'loadBannerlordPartyOrders()', 'partyorders'],
    ['bnr-diplo-slot', 'loadBannerlordDiplomacy()', 'diplomacy'],
    ['bnr-army-slot', 'loadBannerlordArmy()', 'army'],
];
for (const [slot, loader, key] of sectionCases) await test('post-render section: ' + key, async () => {
    const h = harness(slot); h.invoke('_bnrBindSectionToggle()'); await h.invoke(loader);
    assert.deepEqual(h.errors, []); const node = h.section(key); assert(node); assert.equal(node.open, true);
    h.toggle(node, true); assert.deepEqual(h.events, [], 'default-open toggle is not user intent');
    h.toggle(node, false); assert.equal(h.invoke(`_bnrSectionCollapsed.has('${key}')`), true, 'collapse persists immediately');
    h.invoke('_bnrBindSectionToggle()'); h.toggle(node, true);
    assert.deepEqual(h.events, ['bannerlord:section.' + key], 'rebind must not duplicate open');
});
await test('changed async data rebinds new nodes and retains collapsed section', async () => {
    const h = harness('bnr-workshops-slot'); await h.invoke('loadBannerlordWorkshops()');
    const previous = h.section('workshops'); h.toggle(previous, false);
    h.data.max_workshops = 4; await h.invoke('loadBannerlordWorkshops()');
    assert.notEqual(h.section('workshops'), previous, 'fixture must cause actual DOM replacement');
    assert.equal(h.section('workshops').open, false); assert.deepEqual(h.events, []);
    h.toggle(h.detail('ws-buy'), true); assert.deepEqual(h.events, ['bannerlord:details.ws-buy']);
});
await test('retinue replacement binds new closed details without hero structural repaint', async () => {
    const h = harness('bnr-retinue-slot'); h.invoke('_renderRetinue([]); _bnrBindDetailsPersistence()');
    const previous = h.detail('retinue');
    h.invoke('_renderRetinue([{troop_id:"troop",troop_name:"Troop",tier:1}])');
    assert.notEqual(h.detail('retinue'), previous); h.toggle(h.detail('retinue'), true);
    assert.deepEqual(h.events, ['bannerlord:details.retinue']);
});
await test('inactive outer integration tab blocks dynasty HTTP and visible callback refreshes entry', async () => {
    const h = harness('bnr-vassals-slot');
    h.document.body.innerHTML = '<div id="rimworld-tab" class="tab-content"><div data-bnr-pane="dynasty" class="bnr-tab-pane active"><div id="bnr-vassals-slot"></div></div></div>';
    h.invoke('_loadBannerlordDynasty()'); await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.requests.length, 0, 'inner active does not make a hidden outer tab visible');
    h.document.getElementById('rimworld-tab').classList.add('active');
    assert.equal(typeof h.games.bannerlord.visible, 'function', 'registry must be able to signal actual re-entry');
    h.games.bannerlord.visible(); await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.requests.length, 2, 'entry immediately refreshes real vassal/heir reads');
});
await test('hidden viewer panel blocks dynasty HTTP and panel restore callback refreshes', async () => {
    const h = harness('bnr-vassals-slot');
    h.document.body.innerHTML = '<div id="rimworld-tab" class="tab-content active"><div data-bnr-pane="dynasty" class="bnr-tab-pane active"><div id="bnr-vassals-slot"></div></div></div>';
    let visible = false; h.context._isViewerPanelVisible = () => visible;
    h.invoke('_loadBannerlordDynasty()'); await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.requests.length, 0, 'closed outer panel must not fan out');
    visible = true; assert.equal(typeof h.games.bannerlord.visible, 'function');
    h.games.bannerlord.visible(); await new Promise(resolve => setImmediate(resolve)); assert.equal(h.requests.length, 2);
});
console.log(`${total - failed}/${total} passed`);
if (failed) process.exitCode = 1;
