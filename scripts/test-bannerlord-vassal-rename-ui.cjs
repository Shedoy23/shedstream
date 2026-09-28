const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'Расширение/frontend/viewer-bannerlord.js'), 'utf8');
const start = source.indexOf('async function loadBannerlordVassals()');
const end = source.indexOf('function _renderCreateVassalInline', start);
assert(start >= 0 && end > start, 'vassal renderer found');
const renderer = source.slice(start, end);

assert(!renderer.includes('window.prompt'), 'vassal rename must work inside the Twitch iframe without modal permission');
assert(renderer.includes('data-bnr-vassal-rename-form'), 'inline rename form rendered');
assert(renderer.includes("_bannerlordBuyAction('hero.rename_vassal'"), 'rename action preserved');
assert(renderer.includes('new_name:newName'), 'trimmed inline value sent to backend');
assert(renderer.includes('newName.length > 50'), 'client length guard present');
assert(renderer.includes("slot.querySelector('[data-bnr-vassal-rename-form]')"), 'poll does not erase active edit');

console.log('PASS: vassal rename is inline, validated, poll-safe, and keeps the backend contract');
