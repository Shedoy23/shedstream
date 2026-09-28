const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../Расширение/frontend/viewer-bannerlord.js'), 'utf8');
const begin = source.indexOf('function _renderBannerlordDetachmentPanel(');
const end = source.indexOf('\n// 2026-06-10', begin);
const slot = {innerHTML: '', querySelectorAll: () => []};
const sandbox = {document: {getElementById: () => slot}, console,
    _bannerlordClassesCache: null, BnrBuilds: {detachment: () => null}, _bnrPrice: (_, fallback) => fallback};
vm.createContext(sandbox);
vm.runInContext(source.slice(begin, end), sandbox);
function render(extra = {}, stats = {}) {
    sandbox._renderBannerlordDetachmentPanel({in_battle: true, my_stats: {alive: true, ...stats}, ...extra});
    return slot.innerHTML;
}
function button(html, action) { return html.match(new RegExp('<button[^>]*data-det-act="hero\\.' + action + '"[^>]*>'))[0]; }
for (const siege of [undefined, false, 'true']) {
    const html = render({is_siege: siege});
    assert.match(button(html, 'detach_gate'), /\bdisabled\b/, 'Unavailable siege must not sell gate movement');
    assert.match(button(html, 'detach_walls'), /\bdisabled\b/);
    assert.doesNotMatch(button(html, 'detach_charge'), /\bdisabled\b/);
}
let html = render({is_siege: true}, {order_status: 'blocked'});
assert.doesNotMatch(button(html, 'detach_gate'), /\bdisabled\b/);
assert.match(html, /Путь недоступен/);
assert.match(html, /Приказы герою/);
assert.match(render({}, {order_status: 'waiting_target'}), /Ожидает доступного противника/);
assert.match(render({}, {order_status: '<img src=x>'}), /Статус приказа неизвестен/);
assert.doesNotMatch(slot.innerHTML, /<img/);
render({in_battle: false});
assert.equal(slot.innerHTML, '');
console.log('PASS order UI: siege gating, status, unknown fallback, hidden outside battle');
