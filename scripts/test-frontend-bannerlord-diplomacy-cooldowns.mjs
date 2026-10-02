// Real diplomacy renderers, click handlers, shared purchase dispatcher and clock.
// The server owns cooldown duration; refused/offline requests must not invent one.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
const { parseHTML } = createRequire(import.meta.url)('linkedom');
const source = readFileSync(new URL('../Расширение/frontend/viewer-bannerlord.js', import.meta.url), 'utf8');
const actions = readFileSync(new URL('../Расширение/frontend/viewer-actions.js', import.meta.url), 'utf8');
function harness(reply = { success: true, cooldown_applied_s: 17.5 }) {
    const { window, document } = parseHTML('<html><head></head><body><div id="bnr-diplo-slot"></div></body></html>');
    window._bnrCdTickerStarted = true;
    const namespace = window.ShedLink = { registerGame() {} };
    let now = 1_800_000_000_000, cooldowns = [];
    const posts = [], errors = [], notices = [];
    const kingdom = { success: true, has_hero: true, kingdom_id: 'ours', kingdom_name: 'Our kingdom',
        is_king: true, is_clan_leader: true };
    const context = vm.createContext({ window, document, ShedLink: namespace,
        API_URL: 'https://fixture.invalid', authToken: 'fixture',
        escapeHtml: value => String(value), isAuthUser: () => true, dbg() {},
        Date: class extends Date { static now() { return now; } },
        console: { info() {}, warn: (...args) => errors.push(args.map(String).join(' ')), error() {} },
        BnrBuilds: { reset() {} }, BnrEquipmentShop: { reset() {} },
        setInterval: () => 1, clearInterval() {}, safeInterval: () => 1, setTimeout() {},
        showNotification: (...args) => notices.push(args),
        fetch: async (url, options = {}) => {
            if (options.method === 'POST') {
                posts.push(JSON.parse(options.body));
                if (reply instanceof Error) throw reply;
                return { ok: true, json: async () => structuredClone(reply) };
            }
            if (url.endsWith('/my-buffs')) return { ok: true, json: async () => ({ success: true, buffs: [], cooldowns }) };
            assert(url.endsWith('/kingdom-state'), 'unexpected request: ' + url);
            return { ok: true, json: async () => structuredClone(kingdom) };
        } });
    vm.runInContext(actions, context);
    vm.runInContext(source, context);
    vm.runInContext('_bannerlordLastHero = {hero:{kingdom_info:{all_kingdoms:[{id:"peaceful",name:"Peaceful",at_war:false},{id:"enemy",name:"Enemy",at_war:true}]}}}', context);
    const invoke = code => vm.runInContext(code, context);
    const button = side => document.getElementById(side === 'war' ? 'bnr-war-propose' : 'bnr-peace-vote-propose');
    const render = async () => { await invoke('loadBannerlordDiplomacy()'); assert.deepEqual(errors, []); };
    const click = async side => {
        const select = document.getElementById(side === 'war' ? 'bnr-war-target' : 'bnr-peace-vote-target');
        select.querySelector('option').setAttribute('selected', '');
        button(side).dispatchEvent(new window.Event('click'));
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(errors, []);
        assert.equal(posts.length, 1, 'the real handler must send one action');
        assert.equal(posts[0].action_type, 'kingdom.propose_' + side);
    };
    const poll = async entries => { cooldowns = entries; await invoke('loadBannerlordBuffs()'); invoke('_bnrActionCdTick()'); };
    const advance = seconds => { now += seconds * 1000; invoke('_bnrActionCdTick()'); };
    return { invoke, button, render, click, poll, advance, posts, notices, kingdom };
}
let total = 0, failed = 0;
async function test(name, fn) {
    total++;
    try { await fn(); console.log('PASS ' + name); }
    catch (error) { failed++; console.error('FAIL ' + name + ': ' + error.message); }
}
for (const side of ['war', 'peace']) {
    for (const [name, reply] of [
        ['ordinary refusal', { success: false, message: 'Server refusal' }],
        ['network error', Error('offline')],
        ['success without cooldown', { success: true }],
    ]) await test(side + ': ' + name + ' never invents a 300s cooldown', async () => {
        const h = harness(reply); await h.render(); await h.click(side);
        assert.equal(h.button(side).disabled, false, 'no server cooldown means no arbitrary local wait');
        assert(!h.button(side).textContent.includes('⏳'));
    });
    for (const [name, reply, seconds] of [
        ['accepted', { success: true, cooldown_applied_s: 17.5 }, 17.5],
        ['cooldown refusal', { success: false, cooldown_remaining_s: 42.5 }, 42.5],
    ]) await test(side + ': ' + name + ' uses server duration and existing absolute clock', async () => {
        const h = harness(reply); await h.render(); const label = h.button(side).textContent;
        await h.click(side);
        assert.equal(h.button(side).disabled, true);
        assert.equal(h.button(side).textContent, '⏳ ' + Math.ceil(seconds) + 'с');
        assert.equal(h.button(side === 'war' ? 'peace' : 'war').disabled, false, 'other action has a separate cooldown');
        h.advance(seconds - 0.5); assert.equal(h.button(side).textContent, '⏳ 1с');
        h.advance(0.5); assert.equal(h.button(side).disabled, false, 'expiry must not require a new kingdom request');
        assert.equal(h.button(side).textContent, label, 'expiry restores the actual priced action label');
    });
}
await test('initial server cooldown survives diplomacy repaint and expires without stale disabled state', async () => {
    const h = harness(); await h.poll([{ power_key: 'kingdom.propose_war', remaining_s: 12.5 }]);
    await h.render(); assert.equal(h.button('war').textContent, '⏳ 13с');
    assert.equal(h.button('war').disabled, true);
    h.kingdom.kingdom_name = 'Renamed'; await h.render(); assert.equal(h.button('war').textContent, '⏳ 13с');
    h.advance(13); assert.equal(h.button('war').disabled, false);
    assert(h.button('war').textContent.includes('2000'), 'repaint must retain the original price label');
});
await test('server poll replaces local deadline and can clear it', async () => {
    const h = harness(); await h.render(); await h.click('peace');
    await h.poll([{ power_key: 'kingdom.propose_peace', remaining_s: 4 }]);
    assert.equal(h.button('peace').textContent, '⏳ 4с');
    await h.poll([]); assert.equal(h.button('peace').disabled, false);
    assert(h.button('peace').textContent.includes('3000'));
});
console.log(`${total - failed}/${total} passed`);
if (failed) process.exitCode = 1;
