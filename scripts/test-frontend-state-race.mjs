// Гонка ответов при загрузке состояния зрителя.
//
// ЗАЧЕМ. `loadUserData()` зовут из 30 мест (интервал, после каждой покупки,
// после восстановления входа), а счётчика поколений и AbortController во
// фронте нет ни одного. Значит два запроса могут завершиться в обратном
// порядке, и последним закрасит панель СТАРЫЙ ответ.
//
// Два последствия, оба видит зритель:
//   1. Купил — баланс уменьшился — прилетает ответ, отправленный ДО покупки,
//      и рисует прежнюю сумму. Деньги «не списались», зритель жмёт снова.
//      Это ровно тот класс, из-за которого войну объявляли четыре раза подряд.
//   2. Панель восстановила вход, а следом приезжает ответ, отправленный до
//      восстановления, со `status: unauthorized`. Он зовёт `handleAuthLost()`,
//      стирает баланс в «—» и показывает карточку входа поверх рабочей панели.
//
// Гейт исполняет НАСТОЯЩИЙ `loadUserData` из `viewer.js` в песочнице и
// заставляет ответы приходить в обратном порядке.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(
    new URL('../Расширение/frontend/viewer.js', import.meta.url), 'utf8');

function slice(from, to) {
    const start = source.indexOf(from);
    const end = source.indexOf(to, start);
    if (start < 0 || end < 0) throw new Error(`не найден блок ${from}`);
    return source.slice(start, end);
}

// Берём объявление счётчика (если он уже есть) вместе с функцией.
const seqDecl = source.includes('let _stateSeq')
    ? slice('let _stateSeq', 'async function loadUserData()')
    : '';
const fnBody = slice('async function loadUserData()', '// ===== СИСТЕМА УРОВНЕЙ =====');

function harness() {
    const els = new Map();
    const element = id => {
        if (!els.has(id)) els.set(id, { textContent: '', style: {}, id });
        return els.get(id);
    };
    const painted = { quests: 0, cases: 0, authLostCalls: 0 };
    let pending = [];
    const context = vm.createContext({
        userLogin: 'alice',
        authToken: 'token',
        API_URL: 'https://example.invalid',
        _authLost: false,
        _cachedUserPoints: 0,
        _activeIntegrationModule: null,
        shopAllItems: [],
        rimworldEvents: [],
        console: { error() {}, warn() {}, log() {} },
        document: { getElementById: element },
        // fetch отдаёт управляемый промис: тест сам решает, когда и чем ответить
        fetch: () => new Promise(resolve => { pending.push(resolve); }),
        handleAuthLost() {
            painted.authLostCalls++;
            element('points').textContent = '—';
            element('income').textContent = '—';
        },
        renderInventoryCases() { painted.cases++; },
        renderQuests() { painted.quests++; },
        switchIntegrationModule() {},
        renderFirstStep() {},
        applyCardSubtitles() {},
        loadUserLevel() {},
        applyShopFilters() {},
        renderEvents() {},
        showNotification() {},
    });
    vm.runInContext(seqDecl + fnBody, context);
    const reply = (index, payload) => pending[index]({
        ok: true, json: async () => payload, text: async () => '',
    });
    const tick = () => new Promise(resolve => setImmediate(resolve));
    return { context, element, painted, reply, tick, pendingCount: () => pending.length };
}

const failures = [];
async function test(name, fn) {
    try { await fn(); console.log('  OK   ' + name); }
    catch (e) { failures.push(name); console.log('  FAIL ' + name + ' — ' + e.message); }
}

await test('ответы в обратном порядке: побеждает свежий баланс, а не старый',
    async () => {
        const h = harness();
        vm.runInContext('loadUserData()', h.context);   // старый запрос
        vm.runInContext('loadUserData()', h.context);   // свежий, после покупки
        assert.equal(h.pendingCount(), 2, 'ожидались два запроса в полёте');
        h.reply(1, { points: 2000, income_per_min: 5 });  // свежий отвечает первым
        await h.tick(); await h.tick();
        h.reply(0, { points: 9999, income_per_min: 1 }); // старый приходит последним
        await h.tick(); await h.tick();
        assert.equal(
            h.element('points').textContent, 2000,
            `панель показывает ${h.element('points').textContent} — старый ответ затёр свежий`);
    });

await test('старый «unauthorized» после восстановления входа не гасит панель',
    async () => {
        const h = harness();
        vm.runInContext('loadUserData()', h.context);   // уйдёт с прежним токеном
        vm.runInContext('loadUserData()', h.context);   // после восстановления
        h.reply(1, { points: 5000, income_per_min: 7 });
        await h.tick(); await h.tick();
        h.reply(0, { status: 'unauthorized' });          // старый, уже неактуальный
        await h.tick(); await h.tick();
        assert.equal(h.painted.authLostCalls, 0,
            'старый ответ вызвал handleAuthLost — зритель увидит карточку входа');
        assert.equal(h.element('points').textContent, 5000,
            `баланс стёрт в «${h.element('points').textContent}» устаревшим ответом`);
    });

if (failures.length) {
    console.log('\nПРОВАЛЕНО: ' + failures.join('; '));
    process.exit(1);
}
console.log('\nВСЁ ЗЕЛЁНОЕ');
