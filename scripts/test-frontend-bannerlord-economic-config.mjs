// Four expensive legacy actions must have a server quote before sending.
// Exercises actual renderers, Enter/click handlers, config hydration and POSTs.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
const { parseHTML } = createRequire(import.meta.url)('linkedom');
const source = readFileSync(new URL('../Расширение/frontend/viewer-bannerlord.js', import.meta.url), 'utf8');
const actions = readFileSync(new URL('../Расширение/frontend/viewer-actions.js', import.meta.url), 'utf8');
const cases = [
    ['hero.create_clan', 'create_clan', '_renderCreateClanInline()', '#bnr-clan-confirm', '#bnr-clan-name-input'],
    ['hero.create_kingdom', 'create_kingdom', '_renderCreateKingdomInline()', '#bnr-k-confirm', '#bnr-kingdom-name-input'],
    ['hero.create_vassal_clan', 'create_vassal_clan', '_renderCreateVassalInline([{hero_id:"heir",name:"Heir"}])', '#bnr-vas-confirm', '#bnr-vas-name-input'],
    ['hero.recruit_vassal_clan', 'recruit_vassal', 'loadBannerlordKingdomMgmt()', '.bnr-recruit-vassal', null],
];
const config = () => ({ hero_gold_costs: { create_clan: 12345, create_kingdom: 23456, create_vassal_clan: 34567, recruit_vassal: 45678 },
    action_prices: { 'hero.create_vassal_clan': 0, 'hero.recruit_vassal_clan': 0 } });
const settle = () => new Promise(resolve => setImmediate(resolve));
function harness() {
    const { window, document } = parseHTML(`<html><head></head><body>
        <details open data-bnr-details="locked-create"><div id="bnr-locked-create-slot"></div></details>
        <details open data-bnr-details="kingdom-create"><div id="bnr-kingdom-create-slot"></div></details>
        <details open data-bnr-details="vas-create"><div id="bnr-vas-create-slot"></div></details>
        <div id="bnr-kingdom-mgmt-slot"></div></body></html>`);
    window._bnrCdTickerStarted = true;
    const namespace = window.ShedLink = { registerGame() {} };
    const posts = [], reads = [], notices = [], confirmations = [], errors = [];
    let confirmResult = Promise.resolve(true);
    const context = vm.createContext({ window, document, ShedLink: namespace,
        API_URL: 'https://fixture.invalid', authToken: 'fixture',
        escapeHtml: value => String(value), isAuthUser: () => true, dbg() {},
        console: { info() {}, warn: (...args) => errors.push(args.map(String).join(' ')), error() {} },
        BnrBuilds: { reset() {} }, BnrEquipmentShop: { reset() {} },
        setInterval: () => 1, clearInterval() {}, safeInterval: () => 1, setTimeout() {},
        showNotification: (...args) => notices.push(args),
        fetch: (url, options = {}) => {
            if (options.method === 'POST') {
                posts.push(JSON.parse(options.body));
                return Promise.resolve({ ok: true, json: async () => ({ success: true }) });
            }
            assert(url.endsWith('/config'), 'unexpected read: ' + url);
            return new Promise((resolve, reject) => reads.push({ resolve, reject }));
        } });
    vm.runInContext(actions, context); vm.runInContext(source, context);
    const invoke = code => vm.runInContext(code, context);
    context._bnrConfirmDanger = async message => { confirmations.push(message); return confirmResult; };
    invoke('_bannerlordLastHero = {hero:{gold:9000000,clan_name:"Clan",kingdom_name:"Kingdom",kingdom_info:{is_ruler:true}}}');
    const respond = (index, body, ok = true) => reads[index].resolve({ ok, json: async () => structuredClone(body) });
    const hydrate = async (body = config(), ok = true) => { const p = invoke('_hydrateBnrConfig()'); respond(reads.length - 1, body, ok); await p; };
    const render = row => { invoke(row[2]); assert.deepEqual(errors, []); return document.querySelector(row[3]); };
    const click = async row => {
        if (row[4]) document.querySelector(row[4]).value = 'Chosen name';
        document.querySelector('#bnr-vas-heir-pick option')?.setAttribute('selected', '');
        document.querySelector(row[3]).dispatchEvent(new window.Event('click', { bubbles: true }));
        await settle();
    };
    const enter = async row => {
        const input = document.querySelector(row[4]); input.value = 'Chosen name';
        const event = new window.Event('keydown'); event.key = 'Enter'; input.dispatchEvent(event); await settle();
    };
    return { invoke, document, posts, reads, notices, confirmations, render, click, enter, hydrate, respond,
        setConfirmation: promise => { confirmResult = promise; } };
}
let total = 0, failed = 0;
async function test(name, fn) {
    total++;
    try { await fn(); console.log('PASS ' + name); }
    catch (error) { failed++; console.error('FAIL ' + name + ': ' + error.message); }
}
for (const row of cases) {
    await test(row[0] + ': absent config disables the real control and direct action', async () => {
        const h = harness(), button = h.render(row);
        assert.equal(button.disabled, true, 'unknown server price must disable purchase');
        assert(button.textContent.includes('цена не загружена'));
        await h.click(row); await h.invoke(`_bannerlordBuyAction('${row[0]}', {})`);
        assert.equal(h.posts.length, 0); assert.equal(h.confirmations.length, 0);
    });
    for (const value of [null, '', ' ', true, -1, Infinity, '12345']) await test(row[0] + ': invalid price ' + JSON.stringify(value) + ' cannot send', async () => {
        const h = harness(), cfg = config(); cfg.hero_gold_costs[row[1]] = value;
        await h.hydrate(cfg); const button = h.render(row);
        assert.equal(button.disabled, true); await h.click(row); assert.equal(h.posts.length, 0);
    });
    await test(row[0] + ': explicit server zero remains a valid quote', async () => {
        const h = harness(), cfg = config(); cfg.hero_gold_costs[row[1]] = 0;
        await h.hydrate(cfg); const button = h.render(row);
        assert.equal(button.disabled, false); assert(button.textContent.includes('0💰'));
        await h.click(row); assert.equal(h.posts.length, 1); assert.equal(h.posts[0].action_type, row[0]);
    });
    await test(row[0] + ': failed retry keeps the purchase closed; retry recovers in place', async () => {
        const h = harness(), button = h.render(row);
        if (row[4]) h.document.querySelector(row[4]).value = 'Keep this name';
        const originalInput = row[4] && h.document.querySelector(row[4]);
        await h.hydrate({}, false); assert.equal(button.disabled, true);
        const retry = h.document.querySelector(`[data-bnr-economic-retry="${row[0]}"]`);
        assert(retry, 'the actual control needs a retry beside it');
        retry.dispatchEvent(new h.document.defaultView.Event('click', { bubbles: true }));
        assert.equal(h.reads.length, 2); h.respond(1, config()); await settle();
        assert.equal(h.document.querySelector(row[3]), button, 'retry must not replace the form/button');
        assert.equal(button.disabled, false);
        if (row[4]) { assert.equal(h.document.querySelector(row[4]), originalInput); assert.equal(originalInput.value, 'Keep this name'); }
    });
}
for (const row of cases.slice(0, 2)) await test(row[0] + ': Enter cannot bypass missing price or discard typed name', async () => {
    const h = harness(); h.render(row); await h.enter(row);
    assert.equal(h.posts.length, 0); assert.equal(h.document.querySelector(row[4]).value, 'Chosen name');
    assert(h.document.querySelector(row[4]).closest('details').hasAttribute('open'));
});
await test('vassal crustic metadata is required independently and both server amounts are shown', async () => {
    const h = harness(), cfg = config(); delete cfg.action_prices['hero.create_vassal_clan'];
    await h.hydrate(cfg); assert.equal(h.render(cases[2]).disabled, true);
    cfg.action_prices['hero.create_vassal_clan'] = 87; await h.hydrate(cfg);
    const button = h.render(cases[2]); assert.equal(button.disabled, false);
    assert(button.textContent.includes('87💎')); assert(button.textContent.includes('34.6K💰'));
});
await test('one missing quote does not block another action or dynamic/free actions', async () => {
    const h = harness(), cfg = config(); delete cfg.hero_gold_costs.create_clan;
    await h.hydrate(cfg); assert.equal(h.render(cases[0]).disabled, true); assert.equal(h.render(cases[1]).disabled, false);
    await h.invoke('_bannerlordBuyAction("hero.buy_equipment", {item_id:"item"}); _bannerlordBuyAction("hero.leave_clan", {})');
    assert.equal(h.posts.length, 2);
});
for (const boundary of ['stop', 'token']) await test('late config after ' + boundary + ' cannot enable old controls or beat retry', async () => {
    const h = harness(); const button = h.render(cases[0]); const old = h.invoke('_hydrateBnrConfig()');
    h.invoke(boundary === 'stop' ? '_stopBannerlordPolling()' : 'authToken="renewed"');
    const fresh = h.invoke('_hydrateBnrConfig()'); assert.equal(h.reads.length, 2);
    const cfg = config(); cfg.hero_gold_costs.create_clan = 76543;
    h.respond(1, cfg); await fresh; h.respond(0, config()); await old;
    assert.equal(button.disabled, false); assert(button.textContent.includes('76.5K💰'));
});
await test('same-context config requests are single-flight', async () => {
    const h = harness(); const one = h.invoke('_hydrateBnrConfig()'), two = h.invoke('_hydrateBnrConfig()');
    assert.equal(h.reads.length, 1); h.respond(0, config()); await Promise.all([one, two]);
});
await test('changed price while recruit confirmation is open requires a fresh confirmation', async () => {
    const h = harness(); await h.hydrate(); h.render(cases[3]); let accept;
    h.setConfirmation(new Promise(resolve => { accept = resolve; })); await h.click(cases[3]);
    assert.equal(h.confirmations.length, 1); const cfg = config(); cfg.hero_gold_costs.recruit_vassal = 98765;
    await h.hydrate(cfg); accept(true); await settle();
    assert.equal(h.posts.length, 0, 'old confirmation cannot approve a changed price');
    assert(h.notices.some(n => n[0].includes('изменилась')));
});
await test('legacy fallback callers remain compatible and missing strict gold is not zero', () => {
    const h = harness(); assert.equal(h.invoke('_bnrGoldLabel("join_clan", 50000)'), '50K💰');
    assert.equal(h.invoke('_bnrPrice("hero.rename_vassal", 100)'), 100);
    assert.equal(h.invoke('_bnrGoldLabel("create_clan")'), 'цена не загружена');
    assert.equal(h.invoke('_fmtK(null)'), '?');
});
console.log(`${total - failed}/${total} passed`);
if (failed) process.exitCode = 1;
