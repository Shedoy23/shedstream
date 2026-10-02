// Executes the real legacy hero loader/tab dispatcher; no browser dependencies.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const source = readFileSync(new URL('../Расширение/frontend/viewer-bannerlord.js', import.meta.url), 'utf8');
const dynasty = ['ClanMgmt', 'KingdomMgmt', 'ProfileFamily', 'Heirs', 'Family', 'Vassals',
    'PartyOrders', 'Army', 'Diplomacy', 'RansomPool', 'Workshops', 'Fiefs', 'Caravans', 'Inheritance'];
function harness() {
    const body = { id: 'hero-body', innerHTML: '', querySelectorAll: () => [], querySelector: () => null };
    const panes = ['combat', 'hero', 'inventory', 'dynasty'].map(name => {
        const pane = { dataset: { bnrPane: name }, active: name === 'combat' };
        pane.classList = { toggle: (_, active) => { pane.active = active; } };
        return pane;
    });
    const requests = [], calls = [], timers = [];
    const document = { hidden: false, addEventListener() {}, getElementById: id => id === 'hero-body' ? body : null,
        querySelector: selector => selector.includes('data-bnr-pane="dynasty"') ? panes.find(p => p.dataset.bnrPane === 'dynasty' && p.active) || null : null,
        querySelectorAll: selector => selector === '.bnr-tab-pane' ? panes : [] };
    const context = vm.createContext({ document, window: { _bnrCdTickerStarted: true },
        API_URL: 'https://fixture.invalid', authToken: 'token', escapeHtml: value => String(value),
        console: { info() {}, warn() {}, error() {} }, localStorage: { getItem: () => 'combat', setItem() {} },
        ShedLink: { registerGame() {} }, BnrBuilds: { reset() {} }, BnrEquipmentShop: { reset() {} },
        setInterval: () => 1, clearInterval() {}, safeInterval: () => 1,
        setTimeout: fn => { timers.push(fn); }, showNotification() {},
        fetch: url => new Promise((resolve, reject) => requests.push({ url, resolve, reject })) });
    vm.runInContext(source, context);
    const stub = [...dynasty, 'DynastyLockedActions', 'Daily', 'Progression', 'Gender', 'Shop', 'Status',
        'Classes', 'Build', 'Buffs', 'Tournament', 'BattleStatus', 'EquipmentShop'];
    for (const suffix of stub) context['loadBannerlord' + suffix] = () => calls.push(suffix);
    for (const name of ['_renderRetinue', 'renderBannerlordClassPicker', '_renderBannerlordStance', '_hydrateBnrConfig']) context[name] = () => {};
    const invoke = code => vm.runInContext(code, context);
    const reply = (index, value) => requests[index].resolve({ ok: true, json: async () => structuredClone(value) });
    return { context, document, body, requests, calls, timers, invoke, reply };
}
function hero(name = 'Current hero', leader = true) {
    return { success: true, has_hero: true, hero: { display_name: name, level: 2, is_alive: true,
        clan_id: 'clan', clan_info: { is_leader: leader }, gold: 50 }, equipment: {}, retinue: [] };
}
async function load(h, data = hero()) { const p = h.invoke('loadBannerlordHero()'); h.reply(h.requests.length - 1, data); await p; }
const failures = [];
let total = 0;
async function test(name, fn) {
    total++;
    try { await fn(); console.log('PASS ' + name); }
    catch (error) { failures.push(name); console.error('FAIL ' + name + ': ' + error.message); }
}
for (const kind of ['server', 'network']) await test('hero recovers identical data after ' + kind + ' error', async () => {
    const h = harness(); await load(h); const good = h.body.innerHTML;
    const p = h.invoke('loadBannerlordHero()');
    if (kind === 'server') h.reply(1, { success: false, message: 'Temporary failure' });
    else h.requests[1].reject(Error('offline'));
    await p; assert.notEqual(h.body.innerHTML, good, 'fixture must enter error state');
    await load(h); assert.equal(h.body.innerHTML, good, 'error DOM must not survive a successful identical snapshot');
});
await test('hero newest request wins reversed responses', async () => {
    const h = harness(); const old = h.invoke('loadBannerlordHero()'); const fresh = h.invoke('loadBannerlordHero()');
    h.reply(1, hero('Fresh')); await fresh; h.reply(0, hero('Old')); await old;
    assert.equal(h.invoke('_bannerlordLastHero.hero.display_name'), 'Fresh');
});
await test('old hero failure cannot replace fresh success', async () => {
    const h = harness(); const old = h.invoke('loadBannerlordHero()'); const fresh = h.invoke('loadBannerlordHero()');
    h.reply(1, hero()); await fresh; const good = h.body.innerHTML;
    h.requests[0].reject(Error('late failure')); await old; assert.equal(h.body.innerHTML, good);
});
await test('hero response after stop does not render or start dynasty work', async () => {
    const h = harness(); h.invoke('_setBnrInnerTab("dynasty")'); const old = h.invoke('loadBannerlordHero()');
    h.invoke('_stopBannerlordPolling()'); h.reply(0, hero()); await old;
    assert.equal(h.body.innerHTML, ''); assert.deepEqual(h.calls.filter(c => dynasty.includes(c)), []);
});
await test('stop/restart rejects the previous hero lifecycle', async () => {
    const h = harness(); h.invoke('_startBannerlordPolling()'); const old = h.requests[0];
    h.invoke('_stopBannerlordPolling(); _startBannerlordPolling()'); h.reply(1, hero('Restarted'));
    await new Promise(resolve => setImmediate(resolve)); old.resolve({ ok: true, json: async () => hero('Old') });
    await new Promise(resolve => setImmediate(resolve)); assert.equal(h.invoke('_bannerlordLastHero.hero.display_name'), 'Restarted');
});
await test('old authenticated hero response is ignored after token change', async () => {
    const h = harness(); const old = h.invoke('loadBannerlordHero()'); h.context.authToken = 'new-token';
    h.reply(0, hero()); await old; assert.equal(h.body.innerHTML, '');
});
await test('hidden dynasty makes no sub-loader fanout; opening loads every summary', async () => {
    const h = harness(); await load(h);
    assert.deepEqual(h.calls.filter(c => dynasty.includes(c)), [], 'hidden tab must not fan out');
    h.calls.length = 0; h.invoke('_setBnrInnerTab("dynasty")');
    assert.deepEqual(h.calls.filter(c => dynasty.includes(c)), dynasty, 'all summaries load immediately, including collapsed sections');
    h.calls.length = 0; await load(h);
    assert.deepEqual(h.calls.filter(c => dynasty.includes(c)), dynasty, 'visible dynasty continues refreshing');
    h.calls.length = 0; h.invoke('_setBnrInnerTab("hero")'); await load(h);
    assert.deepEqual(h.calls.filter(c => dynasty.includes(c)), []);
});
await test('hidden document and nonleader do not start leader requests', async () => {
    const h = harness(); await load(h, hero('Member', false)); h.calls.length = 0;
    h.invoke('_setBnrInnerTab("dynasty")'); assert.deepEqual(h.calls, ['DynastyLockedActions']);
    h.calls.length = 0; h.document.hidden = true; await load(h);
    assert.deepEqual(h.calls.filter(c => dynasty.includes(c)), []);
});
for (const state of ['missing', 'dead']) await test('same hero returns after ' + state + ' DOM replacement', async () => {
    const h = harness(); await load(h); const good = h.body.innerHTML;
    const changed = state === 'missing' ? { success: true, has_hero: false } : hero();
    if (state === 'dead') changed.hero.is_alive = false;
    await load(h, changed); assert.notEqual(h.body.innerHTML, good);
    await load(h); assert.equal(h.body.innerHTML, good, 'direct state DOM must not survive the returning hero');
});
for (const timing of ['pending', 'scheduled']) await test('shared action refresh rejects stopped lifecycle (' + timing + ')', async () => {
    const h = harness(); let success;
    h.context.ShedLink.buyAction = async (_module, _action, _data, options) => { success = options.onSuccess; return { success: true }; };
    await h.invoke('_bannerlordBuyAction("hero.rename_vassal", {vassal_id:1,new_name:"New"})');
    if (timing === 'scheduled') success();
    h.invoke('_stopBannerlordPolling()');
    if (timing === 'pending') success();
    for (const fn of h.timers.splice(0)) fn();
    assert.equal(h.requests.length, 0, 'accepted action must not restart hero request after stop');
    assert.deepEqual(h.calls, [], 'accepted action must not restart sibling loaders after stop');
});
for (const boundary of ['stop', 'token']) await test('shared action cooldown ignores late callback after ' + boundary, async () => {
    const h = harness(); let cooldown;
    h.context.ShedLink.buyAction = async (_module, _action, _data, options) => { cooldown = options.onCooldown; return { success: true }; };
    await h.invoke('_bannerlordBuyAction("hero.rename_vassal", {vassal_id:1,new_name:"New"})');
    if (boundary === 'stop') h.invoke('_stopBannerlordPolling()'); else h.context.authToken = 'refreshed-token';
    cooldown('hero.rename_vassal', 60);
    assert.equal(h.invoke('_bannerlordCooldowns.length'), 0, 'old request must not repopulate cooldown state');
});
console.log(`${total - failures.length}/${total} passed`);
if (failures.length) process.exitCode = 1;
