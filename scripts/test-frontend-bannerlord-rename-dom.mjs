// Real legacy renderer/event handlers in a DOM. Run with root devDependencies installed.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
const { parseHTML } = createRequire(import.meta.url)('linkedom');
const source = readFileSync(new URL('../Расширение/frontend/viewer-bannerlord.js', import.meta.url), 'utf8');
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)); };
function jwt(user = 'viewer-a', channel = 'channel-a', revision = '1') {
    return 'header.' + Buffer.from(JSON.stringify({ user_id: user, channel_id: channel, opaque_user_id: 'U' + user, revision })).toString('base64url') + '.signature';
}
function harness() {
    const { window, document } = parseHTML('<html><head></head><body><div id="bnr-vassals-slot"></div></body></html>');
    window._bnrCdTickerStarted = true;
    window.HTMLInputElement.prototype.select = function () {};
    const calls = [], requests = [], timers = [];
    const fixture = { vassals: [{ id: 1, vassal_name: 'Old clan' }], heirs: [] };
    let mutate = async () => ({ success: true });
    let respond = async url => ({ success: true, ...(url.includes('eligible-heirs') ? { heirs: fixture.heirs } : { vassals: fixture.vassals }) });
    const context = vm.createContext({ window, document, AbortController, clearTimeout() {}, API_URL: 'https://fixture.invalid', authToken: jwt(), userId: 'Uviewer-a', _authUserId: 'viewer-a',
        atob: value => Buffer.from(value, 'base64').toString('binary'),
        escapeHtml: value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
        console: { info() {}, warn() {}, error() {} }, ShedLink: { registerGame() {} },
        BnrBuilds: { reset() {} }, BnrEquipmentShop: { reset() {} }, showNotification() {},
        setInterval: () => 1, clearInterval() {}, safeInterval: () => 1, setTimeout: fn => { timers.push(fn); },
        fetch: async url => { requests.push(url); return { ok: true, json: async () => respond(url) }; } });
    vm.runInContext(source, context);
    context._bannerlordBuyAction = async (...args) => { calls.push(args); return mutate(...args); };
    const invoke = code => vm.runInContext(code, context);
    const query = selector => document.querySelector(selector);
    const click = selector => { const node = query(selector); assert(node, 'missing ' + selector); node.dispatchEvent(new window.Event('click', { bubbles: true })); };
    const submit = () => query('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    const edit = name => { click('.bnr-vas-rename'); query('input').value = name; };
    return { context, document, fixture, calls, requests, timers, invoke, query, click, submit, edit,
        mutation: fn => { mutate = fn; }, response: fn => { respond = fn; } };
}
const failures = [];
let total = 0;
async function test(name, fn) {
    total++;
    try { await fn(); console.log('PASS ' + name); }
    catch (error) { failures.push(name); console.error('FAIL ' + name + ': ' + error.message); }
}
for (const mode of ['cancel', 'unchanged']) await test('rename ' + mode + ' exits editor and can reopen', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); h.edit('Old clan');
    if (mode === 'cancel') h.click('[data-bnr-vassal-rename-cancel]'); else h.submit();
    await flush(); assert.equal(!!h.query('form'), false, 'loader guard must not trap the editor');
    assert.equal(h.calls.length, 0); h.edit('Another clan'); assert(h.query('form'), 'restored button must keep its handler');
});
await test('rename success closes editor, refreshes echoed name and stays reusable', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); h.edit(' New clan '); h.submit(); await flush();
    assert.equal(h.calls.length, 1); assert.equal(h.calls[0][0], 'hero.rename_vassal');
    assert.equal(JSON.stringify(h.calls[0][1]), JSON.stringify({ vassal_id: 1, new_name: 'New clan' }));
    assert.equal(!!h.query('form'), false, 'accepted action must release editor guard');
    h.fixture.vassals[0].vassal_name = 'New clan'; for (const fn of h.timers.splice(0)) await fn(); await flush();
    assert.match(h.query('#bnr-vassals-slot').textContent, /New clan/);
    h.edit('Third clan'); assert(h.query('form'));
});
for (const result of [false, null, { success: false, message: 'Denied' }]) await test('failed mutation ' + JSON.stringify(result) + ' preserves edit and allows retry', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); h.mutation(async () => result);
    h.edit('Retry clan'); h.submit(); await flush();
    assert.equal(h.query('input').disabled, false, 'failed action must re-enable form');
    assert.equal(h.query('input').value, 'Retry clan'); assert.equal(h.query('[data-bnr-vassal-rename-error]').style.display, 'block');
    assert.equal(h.timers.length, 0, 'failed mutation must not schedule a success reload');
    h.mutation(async () => ({ success: true })); h.submit(); await flush(); assert.equal(h.calls.length, 2); assert.equal(!!h.query('form'), false);
});
await test('thrown mutation preserves edit, reports error, and can cancel', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); h.mutation(async () => { throw Error('offline'); });
    h.edit('Retry clan'); h.submit(); await flush(); assert.equal(h.query('input').disabled, false);
    assert.match(h.query('[data-bnr-vassal-rename-error]').textContent, /offline/);
    h.click('[data-bnr-vassal-rename-cancel]'); await flush(); assert.equal(!!h.query('form'), false);
});
await test('pending rename ignores repeated submission and poll preserves input', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); let resolve;
    h.mutation(() => new Promise(r => { resolve = r; })); h.edit('Pending clan'); h.submit(); h.submit();
    assert.equal(h.calls.length, 1, 'double submission must not issue two mutations');
    h.fixture.vassals = []; await h.invoke('loadBannerlordVassals()');
    assert.equal(h.query('input').value, 'Pending clan', 'empty polling response cannot erase active edit');
    resolve({ success: true }); await flush(); assert.equal(!!h.query('form'), false);
});
await test('invalid names do not submit or close editor', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); h.edit('   '); h.submit(); await flush();
    assert.equal(h.calls.length, 0); h.query('input').value = 'x'.repeat(51); h.submit(); await flush();
    assert.equal(h.calls.length, 0); assert(h.query('form')); assert.equal(h.query('[data-bnr-vassal-rename-error]').style.display, 'block');
});
await test('vassal read failure keeps the last good UI', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); const good = h.query('#bnr-vassals-slot').innerHTML;
    h.response(async () => ({ success: false })); await h.invoke('loadBannerlordVassals()');
    assert.equal(h.query('#bnr-vassals-slot').innerHTML, good);
});
await test('old vassal request does not overwrite a newer result', async () => {
    const h = harness(); const deferred = [];
    h.response(() => new Promise(resolve => deferred.push(resolve)));
    const old = h.invoke('loadBannerlordVassals()'); await flush();
    h.response(async url => ({ success: true, ...(url.includes('eligible-heirs') ? { heirs: [] } : { vassals: [{ id: 1, vassal_name: 'Fresh clan' }] }) }));
    await h.invoke('loadBannerlordVassals()');
    deferred[0]({ success: true, vassals: [{ id: 1, vassal_name: 'Stale clan' }] }); deferred[1]({ success: true, heirs: [] }); await old;
    assert.match(h.query('#bnr-vassals-slot').textContent, /Fresh clan/);
});
await test('stop invalidates pending rename and restart can load a fresh editor', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); let resolve;
    h.mutation(() => new Promise(r => { resolve = r; })); h.edit('Old pending'); h.submit();
    h.invoke('_stopBannerlordPolling()'); h.fixture.vassals[0].vassal_name = 'Restarted clan';
    await h.invoke('loadBannerlordVassals()'); resolve({ success: true }); await flush();
    assert.equal(h.timers.length, 0, 'old mutation must not schedule work in the new lifecycle');
    assert.match(h.query('#bnr-vassals-slot').textContent, /Restarted clan/); h.edit('Fresh edit'); assert(h.query('form'));
});
await test('stop invalidates pending vassal read', async () => {
    const h = harness(); const deferred = []; h.response(() => new Promise(resolve => deferred.push(resolve)));
    const old = h.invoke('loadBannerlordVassals()'); await flush(); h.invoke('_stopBannerlordPolling()');
    deferred[0]({ success: true, vassals: [{ id: 1, vassal_name: 'Stale clan' }] }); deferred[1]({ success: true, heirs: [] }); await old;
    assert.equal(h.query('#bnr-vassals-slot').innerHTML, '');
});
await test('accepted rename timer cannot refresh after stop', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); h.edit('New clan'); h.submit(); await flush();
    assert.equal(h.timers.length, 1); h.invoke('_stopBannerlordPolling()'); const before = h.requests.length;
    for (const fn of h.timers.splice(0)) await fn(); await flush(); assert.equal(h.requests.length, before);
});
await test('poll begun before editing cannot erase an empty-list edit', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); const deferred = [];
    h.response(() => new Promise(resolve => deferred.push(resolve)));
    const poll = h.invoke('loadBannerlordVassals()'); await flush(); h.edit('Unsaved clan');
    deferred[0]({ success: true, vassals: [] }); deferred[1]({ success: true, heirs: [] }); await poll;
    assert.equal(h.query('input')?.value, 'Unsaved clan');
});
await test('dynasty HTTP fanout is deferred but opening preserves real summaries', async () => {
    const h = harness(); h.document.body.innerHTML = '<div id="hero-body"></div>' + ['combat', 'hero', 'inventory', 'dynasty'].map(name =>
        `<div class="bnr-tab-pane ${name === 'combat' ? 'active' : ''}" data-bnr-pane="${name}"><div id="bnr-pane-${name}-body"></div></div>`).join('');
    h.context._cachedUserPoints = 10000;
    for (const name of ['loadBannerlordDaily', 'loadBannerlordProgression', 'loadBannerlordGender',
        '_renderRetinue', 'renderBannerlordClassPicker', '_renderBannerlordStance']) h.context[name] = () => {};
    h.response(async url => url.endsWith('/my-hero') ? { success: true, has_hero: true, hero: {
        display_name: 'Current hero', is_alive: true, clan_name: 'Known clan', kingdom_name: 'Known kingdom',
        clan_info: { is_leader: true }, gold: 10000 }, equipment: {}, retinue: [] }
        : { success: true, heirs: [{ name: 'Known heir' }], vassals: [{ id: 1, vassal_name: 'Known vassal' }], children: [], incoming: [], outgoing: [] });
    await h.invoke('loadBannerlordHero()'); await flush();
    assert.equal(h.requests.length, 3, 'hidden dynasty reads hero and the two game metadata snapshots');
    assert.deepEqual(h.requests.map(url => url.split('/').at(-1)), ['my-hero', 'content-catalogs', 'progression']);
    h.invoke('_setBnrInnerTab("dynasty")'); await flush();
    assert.equal(h.requests.length, 15, 'opening adds the existing 12 dynasty HTTP requests');
    assert.match(h.query('#bnr-heir-slot').textContent, /Known heir/);
    assert.match(h.query('#bnr-vassals-slot').textContent, /Known vassal/);
    for (const id of ['bnr-workshops-slot', 'bnr-caravans-slot', 'bnr-party-orders-slot']) assert(h.query('#' + id + ' summary'), id + ' summary remains available');
    const workshop = h.query('#bnr-workshops-slot details'); workshop.open = false;
    await h.invoke('loadBannerlordHero()'); await flush();
    assert(h.query('#bnr-workshops-slot summary'), 'collapsed summary is still rendered on refresh');
    h.invoke('_setBnrInnerTab("combat")'); const before = h.requests.length;
    await h.invoke('loadBannerlordHero()'); await flush(); assert.equal(h.requests.length, before + 3);
});
for (const poll of [false, true]) await test('JWT refresh keeps cached rename handler alive (poll=' + poll + ')', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); h.context.authToken = jwt('viewer-a', 'channel-a', '2');
    if (poll) await h.invoke('loadBannerlordVassals()');
    h.click('.bnr-vas-rename'); assert(h.query('form'), 'same identity must not lose cached DOM handlers');
});
for (const action of ['cancel', 'unchanged', 'submit']) await test('open editor survives JWT refresh: ' + action, async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); h.edit(action === 'unchanged' ? 'Old clan' : 'New clan');
    const token = jwt('viewer-a', 'channel-a', '2'); h.context.authToken = token;
    let usedToken; h.mutation(async () => { usedToken = h.context.authToken; return { success: true }; });
    if (action === 'cancel') h.click('[data-bnr-vassal-rename-cancel]'); else h.submit();
    await flush(); assert.equal(!!h.query('form'), false, 'token refresh must not trap editor');
    assert.equal(h.calls.length, action === 'submit' ? 1 : 0);
    if (action === 'submit') assert.equal(usedToken, token, 'submit uses latest JWT');
});
for (const outcome of ['success', 'failure', 'throw']) await test('token rotation during pending rename fences old ' + outcome + ' and reloads', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); let resolve, reject;
    h.mutation(() => new Promise((yes, no) => { resolve = yes; reject = no; })); h.edit('Pending name'); h.submit();
    h.context.authToken = jwt('viewer-a', 'channel-a', '2'); h.fixture.vassals[0].vassal_name = 'Authoritative name';
    if (outcome === 'throw') reject(Error('old-token error')); else resolve({ success: outcome === 'success', message: 'old-token error' });
    await flush(); assert.equal(!!h.query('form'), false, 'stale outcome must release pending editor');
    assert.equal(h.timers.length, 0, 'stale outcome must not schedule success callbacks');
    assert.equal(h.requests.length, 4, 'settle with a new authenticated read');
    assert.match(h.query('#bnr-vassals-slot').textContent, /Authoritative name/);
    assert.doesNotMatch(h.query('#bnr-vassals-slot').textContent, /old-token error/);
    h.edit('Fresh action'); assert(h.query('form'));
});
for (const identity of ['user', 'channel']) await test('changed ' + identity + ' cannot submit old form and can bind a fresh one', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); h.edit('Old identity action');
    h.context.authToken = identity === 'user' ? jwt('viewer-b') : jwt('viewer-a', 'channel-b');
    h.submit(); await flush(); assert.equal(h.calls.length, 0, 'old target must never be submitted as new identity');
    await h.invoke('loadBannerlordVassals()'); assert.equal(!!h.query('form'), false, 'new identity read must invalidate old edit guard');
    h.edit('New identity action'); h.submit(); await flush(); assert.equal(h.calls.length, 1);
});
await test('changed identity fences old pending result without erasing new editor', async () => {
    const h = harness(); await h.invoke('loadBannerlordVassals()'); let resolve;
    h.mutation(() => new Promise(r => { resolve = r; })); h.edit('Old pending'); h.submit();
    h.context.authToken = jwt('viewer-b'); await h.invoke('loadBannerlordVassals()');
    h.edit('New identity draft'); resolve({ success: true }); await flush();
    assert.equal(h.query('input').value, 'New identity draft'); assert.equal(h.timers.length, 0);
});
await test('JWT refresh during a vassal read drops old response and new read recovers', async () => {
    const h = harness(); const deferred = []; h.response(() => new Promise(resolve => deferred.push(resolve)));
    const old = h.invoke('loadBannerlordVassals()'); await flush(); h.context.authToken = jwt('viewer-a', 'channel-a', '2');
    deferred[0]({ success: true, vassals: [{ id: 1, vassal_name: 'Stale token' }] }); deferred[1]({ success: true, heirs: [] }); await old;
    assert.equal(h.query('#bnr-vassals-slot').innerHTML, '');
    h.response(async () => ({ success: true, vassals: [{ id: 1, vassal_name: 'Current token' }], heirs: [] }));
    await h.invoke('loadBannerlordVassals()'); assert.match(h.query('#bnr-vassals-slot').textContent, /Current token/);
});
console.log(`${total - failures.length}/${total} passed`);
if (failures.length) process.exitCode = 1;
