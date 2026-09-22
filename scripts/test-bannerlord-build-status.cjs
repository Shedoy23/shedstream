const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = process.argv[2] || path.join(__dirname, '../Расширение/frontend/viewer-bannerlord-builds.js');
const slots = Object.fromEntries(['hero-class-picker-slot','bnr-active-powers-slot','bnr-build-choice-slot'].map(id => [id, {innerHTML:''}]));
let fixture;
const sandbox = {
    document: {getElementById: id => slots[id]}, API_URL:'', authToken:'',
    escapeHtml: value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
    fetch: async () => ({ok:true,json:async () => fixture}),
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(source,'utf8'),sandbox);
(async () => {
    fixture = {success:true,enabled:true,ready:false,build:{},message:'Старый герой: новые сборки недоступны <img src=x>'};
    await sandbox.loadBannerlordBuild();
    for (const id of ['hero-class-picker-slot','bnr-active-powers-slot']) {
        assert(slots[id].innerHTML.includes('Старый герой'),id+': show actual server reason');
        assert(!slots[id].innerHTML.includes('<img'),id+': escape server text');
    }
    fixture = {success:true,enabled:true,ready:false,build:{}};
    await sandbox.loadBannerlordBuild();
    assert(slots['hero-class-picker-slot'].innerHTML.includes('синхронизируются'));
    assert(!slots['hero-class-picker-slot'].innerHTML.includes('подключения игры'));
    console.log('PASS build status: server reason in hero/combat, escaping, unknown data distinct from offline');
})().catch(error => {console.error(error);process.exitCode=1;});
