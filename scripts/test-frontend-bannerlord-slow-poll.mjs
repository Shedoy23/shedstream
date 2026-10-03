// Execute real polling/dispatch code with logical 8s ticks and responses at 9s.
// In-flight newer reads must not starve older successful reads forever, while
// already-completed newer reads and accepted actions still fence stale replies.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
const { parseHTML } = createRequire(import.meta.url)('linkedom');
const source = readFileSync(new URL('../Расширение/frontend/viewer-bannerlord.js', import.meta.url), 'utf8');
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)); };
function hero(gold = 100) {
    return { success: true, has_hero: true, hero: { display_name: 'Hero', level: 2, gold,
        is_alive: true, clan_id: 'clan', clan_info: { is_leader: true } }, equipment: {}, retinue: [] };
}
function harness() {
    const { window, document } = parseHTML('<html><head></head><body><div id="hero-body"></div><div id="rimworld-tab" class="active"><div data-bnr-pane="dynasty" class="bnr-tab-pane active"><div id="bnr-vassals-slot"></div></div></div></body></html>');
    window._bnrCdTickerStarted = true; window.HTMLInputElement.prototype.select = function () {};
    const requests = [], intervals = [], timers = [];
    const context = vm.createContext({ window, document, API_URL: 'https://fixture.invalid', authToken: 'fixture',
        escapeHtml: value => String(value), console: { info() {}, warn() {}, error() {} },
        localStorage: { getItem: () => 'dynasty', setItem() {} },
        ShedLink: { registerGame() {}, buyAction: async (_game, _action, _data, options) => { options.onSuccess(); return { success: true }; } },
        BnrBuilds: { reset() {} }, BnrEquipmentShop: { reset() {} }, showNotification() {},
        safeInterval: (callback, delay) => { intervals.push({ callback, delay }); return intervals.length; },
        setInterval: () => 1, clearInterval() {}, setTimeout: callback => { timers.push(callback); },
        fetch: url => new Promise((resolve, reject) => requests.push({ url, resolve, reject })) });
    vm.runInContext(source, context);
    // Keep the controlled 9s hero/vassal responses isolated from subordinate
    // metadata reads; the complete unmodified loader chain has its own parity harness.
    context._loadBnrContentCatalogs = async () => null;
    context._loadBnrProgression = async () => null;
    const stub = ['ClanMgmt','KingdomMgmt','ProfileFamily','Heirs','Family','PartyOrders','Army','Diplomacy',
        'RansomPool','Workshops','Fiefs','Caravans','Inheritance','DynastyLockedActions','Daily','Progression',
        'Gender','Shop','Status','Classes','Build','Buffs','Tournament','BattleStatus','EquipmentShop'];
    for (const name of stub) context['loadBannerlord' + name] = () => {};
    for (const name of ['_renderRetinue','renderBannerlordClassPicker','_renderBannerlordStance','_hydrateBnrConfig']) context[name] = () => {};
    const invoke = code => vm.runInContext(code, context);
    const reply = (request, data) => request.resolve({ ok: true, json: async () => structuredClone(data) });
    const reads = suffix => requests.filter(request => request.url.endsWith(suffix));
    const replyVassals = (index, name) => {
        reply(reads('/vassals')[index], { success: true, vassals: [{ id: 1, vassal_name: name }] });
        reply(reads('/eligible-heirs')[index], { success: true, heirs: [] });
    };
    const query = selector => document.querySelector(selector);
    const click = selector => { const node = query(selector); assert(node, 'missing ' + selector); node.dispatchEvent(new window.Event('click', { bubbles: true })); };
    return { context, document, requests, intervals, timers, invoke, reply, reads, replyVassals, query, click };
}
let total = 0, failed = 0;
async function test(name, fn) {
    total++;
    try { await fn(); console.log('PASS ' + name); }
    catch (error) { failed++; console.error('FAIL ' + name + ': ' + error.message); }
}
await test('real 8s hero polling keeps rendering each successful 9s response', async () => {
    const h = harness(); h.context.loadBannerlordVassals = () => {};
    h.invoke('_startBannerlordPolling()'); const tick = h.intervals.find(item => item.delay === 8000).callback;
    for (let i = 0; i < 6; i++) {
        tick(); // t=8,16,...: the next read starts before the previous read finishes.
        h.reply(h.reads('/my-hero')[i], hero(100 + i)); await flush(); // t=9,17,...
        assert.equal(h.invoke('_bannerlordLastHero?.hero.gold'), 100 + i, 'successful slow hero stream must make progress');
        assert.match(h.query('#hero-body').textContent, /Hero/);
    }
});
await test('real visible dynasty dispatch keeps rendering successful overlapping 9s pairs', async () => {
    const h = harness(); h.invoke('_bannerlordLastHero = ' + JSON.stringify(hero())); h.invoke('_loadBannerlordDynasty()');
    for (let i = 0; i < 6; i++) {
        h.invoke('_loadBannerlordDynasty()'); h.replyVassals(i, 'Server clan ' + i); await flush();
        assert.match(h.query('#bnr-vassals-slot').textContent, new RegExp('Server clan ' + i), 'successful slow vassal stream must make progress');
    }
});
await test('hero reversed completed results still favor the newer request', async () => {
    const h = harness(); h.context.loadBannerlordVassals = () => {};
    const old = h.invoke('loadBannerlordHero()'), fresh = h.invoke('loadBannerlordHero()');
    h.reply(h.reads('/my-hero')[1], hero(200)); await fresh;
    h.reply(h.reads('/my-hero')[0], hero(100)); await old;
    assert.equal(h.invoke('_bannerlordLastHero.hero.gold'), 200);
});
await test('vassal reversed completed results still favor the newer request', async () => {
    const h = harness(); const old = h.invoke('loadBannerlordVassals()'), fresh = h.invoke('loadBannerlordVassals()');
    h.replyVassals(1, 'Fresh clan'); await fresh; h.replyVassals(0, 'Old clan'); await old;
    assert.match(h.query('#bnr-vassals-slot').textContent, /Fresh clan/);
});
await test('new hero failure fences older success, next slow success can recover', async () => {
    const h = harness(); h.context.loadBannerlordVassals = () => {};
    const old = h.invoke('loadBannerlordHero()'), fresh = h.invoke('loadBannerlordHero()');
    h.reads('/my-hero')[1].reject(Error('offline')); await fresh;
    h.reply(h.reads('/my-hero')[0], hero()); await old; assert.match(h.query('#hero-body').textContent, /Ошибка сети/);
    const recovering = h.invoke('loadBannerlordHero()'); h.invoke('loadBannerlordHero()');
    h.reply(h.reads('/my-hero')[2], hero(300)); await recovering; assert.equal(h.invoke('_bannerlordLastHero.hero.gold'), 300);
});
await test('enter then cancel editor still invalidates pre-edit reads', async () => {
    const h = harness(); const initial = h.invoke('loadBannerlordVassals()'); h.replyVassals(0, 'Current clan'); await initial;
    const old = h.invoke('loadBannerlordVassals()'); h.click('.bnr-vas-rename'); h.click('[data-bnr-vassal-rename-cancel]');
    h.replyVassals(1, 'Pre-edit stale clan'); await old;
    assert.match(h.query('#bnr-vassals-slot').textContent, /Current clan/); assert.doesNotMatch(h.query('#bnr-vassals-slot').textContent, /Pre-edit/);
});
for (const target of ['hero', 'vassal']) await test('accepted action fences pre-action ' + target + ' reads until fresh reload', async () => {
    const h = harness(); if (target === 'hero') h.context.loadBannerlordVassals = () => {};
    const old = h.invoke(target === 'hero' ? 'loadBannerlordHero()' : 'loadBannerlordVassals()');
    await h.invoke('_bannerlordBuyAction("hero.rename_vassal", {vassal_id:1,new_name:"New clan"})');
    if (target === 'hero') h.reply(h.reads('/my-hero')[0], hero(10)); else h.replyVassals(0, 'Pre-action stale');
    await old;
    assert.equal(target === 'hero' ? h.query('#hero-body').innerHTML : h.query('#bnr-vassals-slot').innerHTML, '', 'pre-action data must not paint after accepted mutation');
    const fresh = h.invoke(target === 'hero' ? 'loadBannerlordHero()' : 'loadBannerlordVassals()');
    if (target === 'hero') h.reply(h.reads('/my-hero')[1], hero(20)); else h.replyVassals(1, 'After action');
    await fresh;
    assert(target === 'hero' ? h.invoke('_bannerlordLastHero.hero.gold === 20') : h.query('#bnr-vassals-slot').textContent.includes('After action'));
});
console.log(`${total - failed}/${total} passed`);
if (failed) process.exitCode = 1;
