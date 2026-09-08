import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../Расширение/frontend/viewer.js', import.meta.url), 'utf8');
function body(name, next) {
    return source.slice(source.indexOf(`function ${name}(`), source.indexOf(next, source.indexOf(`function ${name}(`)));
}
const functions = body('updateUIAfterAuth', '// Sprint 5.31 #45b —')
    + body('handleAuthLost', '// ===== БЕЗОПАСНОСТЬ =====');
function harness() {
    const elements = new Map();
    const timers = [];
    let loads = 0, perks = 0, stats = 0;
    const element = id => {
        if (!elements.has(id)) elements.set(id, {
            textContent: '', style: {}, disabled: false,
            remove() { elements.delete(id); },
            addEventListener(_, fn) { this.click = fn; },
            insertBefore() {},
        });
        return elements.get(id);
    };
    const context = vm.createContext({
        userLogin: 'alice', authToken: 'token', _authUiInitialized: true,
        _authLost: false, _authUserId: '123', _authOpaqueId: 'Uopaque', _authRecoverTried: 0,
        document: { getElementById: element, createElement: () => ({ style: {} }), body: element('body') },
        window: { Twitch: { ext: { actions: { requestIdShare() {} } } } },
        console, setTimeout: fn => timers.push(fn),
        getUsernameFromTwitchId: async () => 'alice',
        loadUserData() { loads++; }, loadUserPerksBadge() { perks++; }, loadStats() { stats++; },
        showNotification() {},
    });
    vm.runInContext(functions, context);
    return { context, elements, element, timers, counts: () => ({ loads, perks, stats }) };
}
const failures = [];
async function test(name, fn) {
    try { await fn(); console.log('PASS', name); }
    catch (e) { failures.push(name); console.error('FAIL', name, e.message); }
}
await test('identity recovery refreshes balance, income, quests, cases and role', async () => {
    const h = harness();
    vm.runInContext('handleAuthLost()', h.context);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.counts().loads, 1);
    assert.equal(h.counts().perks, 1);
});
await test('reauthorization removes prompt and refreshes state immediately', () => {
    const h = harness();
    h.element('login-prompt');
    vm.runInContext('_authLost = true; updateUIAfterAuth()', h.context);
    assert.equal(h.elements.has('login-prompt'), false);
    assert.equal(h.context._authLost, false);
    assert.equal(h.counts().loads, 1);
    assert.equal(h.counts().perks, 1);
});
await test('declined identity share leaves login retry usable despite old login', () => {
    const h = harness();
    vm.runInContext('showLoginPrompt()', h.context);
    const button = h.element('login-prompt-btn');
    button.click();
    assert.equal(button.disabled, true);
    h.timers[0]();
    assert.equal(button.disabled, false);
});
await test('statistics tab bypasses cached personal responses', async () => {
    const calls = [];
    const ctx = vm.createContext({ userLogin: 'alice', authToken: 'token', API_URL: 'https://example.test',
        fetch: async (url, opts) => { calls.push(opts); return { json: async () => ({}) }; },
        document: { getElementById: () => null }, renderStreak() {}, renderAchievements() {}, console,
    });
    vm.runInContext('async ' + body('loadStats', 'function renderStreak'), ctx);
    await vm.runInContext('loadStats()', ctx);
    assert.equal(calls.length, 3);
    for (const opts of calls) assert.equal(opts.cache, 'no-store');
});
if (failures.length) process.exitCode = 1;
