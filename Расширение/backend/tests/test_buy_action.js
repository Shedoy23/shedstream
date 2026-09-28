/* Характеризационный тест общего платного пути фронта (ShedLink.buyAction).
 *
 * Живёт в backend/tests, а НЕ в frontend/ — всё, что лежит в frontend/,
 * уезжает в prod-тар и в ZIP на ревью Twitch (RUNBOOK §сборка релиза).
 * Прецедент рядом: test_frontend_module_lifecycle.py тоже проверяет фронт.
 *
 * Запуск:  node tests/test_buy_action.js   (из папки backend)
 *          python scripts/run-backend-tests.py buy_action
 * Код возврата: 0 — зелёное, 1 — есть падения. Судить по КОДУ, не по печати.
 *
 * ПОЧЕМУ ЧЕРЕЗ vm, А НЕ require. 19.08 первая версия теста грузила файл через
 * require и клала зависимости на globalThis — 22 проверки были зелёными, а в
 * настоящем браузере покупка уходила на `undefined/api/shedcolony/action`.
 * Причина: в viewer.js `const API_URL` и `let authToken` объявлены на верхнем
 * уровне классического <script>, а такие объявления НЕ становятся свойствами
 * window — они живут в общей лексической области скриптов. Через `window.X`
 * их не видно, через имя — видно. require-тест этой разницы не воспроизводит:
 * у модулей Node своя область.
 *
 * vm.createContext + два runInContext воспроизводят браузер точно: `const`/`let`
 * из второго скрипта видны первому по имени и отсутствуют как свойства
 * контекста. Тест теперь падает ровно на том, на чём падал браузер.
 */
'use strict';

const fs = require('fs');
const vm = require('vm');
const path = require('path');

const FRONTEND = path.resolve(__dirname, '..', '..', 'frontend');

let passed = 0;
let failed = 0;

function check(cond, msg) {
    if (cond) { passed++; console.log('  OK   ' + msg); }
    else { failed++; console.log('  FAIL ' + msg); }
}

// ── стенд: браузероподобный контекст ─────────────────────────────────────────
let calls;
let ctx;
let ShedLink;

function makeContext() {
    const sandbox = {
        console,
        // Ниже — то, что в браузере действительно является свойством window.
        fetch: null,
        document: null,
        crypto: { randomUUID: () => 'uuid-' + (sandbox.__n = (sandbox.__n || 0) + 1) },
        __calls: null,
        __authed: true,
        __cooldownButton: false,
    };
    const context = vm.createContext(sandbox);

    vm.runInContext(fs.readFileSync(path.join(FRONTEND, 'viewer-actions.js'), 'utf8'),
                    context, { filename: 'viewer-actions.js' });

    // Ровно как в viewer.js: const/let/function на верхнем уровне скрипта.
    // const и let НЕ становятся свойствами контекста — это и есть суть теста.
    vm.runInContext(`
        const API_URL = 'https://example.test';
        let authToken = 'jwt-123';
        const dbg = function () {};
        function showNotification(m, t, ms) { __calls.toasts.push({ m: m, t: t, ms: ms }); }
        function loadUserData() { __calls.loadUserData++; }
        function isAuthUser() { return __authed; }
    `, context, { filename: 'viewer-core-stub.js' });

    return context;
}

function reset(response, opts) {
    opts = opts || {};
    calls = { fetch: [], toasts: [], loadUserData: 0, cooldown: [], onSuccess: 0 };
    ctx.__calls = calls;
    ctx.__authed = (opts.authed !== false);
    ctx.document = { querySelector: () => (opts.cooldownButton ? {} : null) };
    ctx.fetch = async (url, init) => {
        calls.fetch.push({ url, init, body: JSON.parse(init.body) });
        if (opts.networkError) throw new Error('boom');
        return { json: async () => response };
    };
    ShedLink._resetInflight();
}

// ── кейсы ────────────────────────────────────────────────────────────────────
async function main() {
    ctx = makeContext();
    ShedLink = ctx.ShedLink;

    check(typeof ShedLink === 'object' && typeof ShedLink.buyAction === 'function',
          'ShedLink.buyAction виден как свойство window');
    check(!Object.prototype.hasOwnProperty.call(ctx, 'API_URL'),
          'стенд честный: API_URL НЕ свойство window (как в viewer.js)');

    // 1. Успешная покупка
    reset({ success: true, message: 'Готово' });
    let res = await ShedLink.buyAction('bannerlord', 'hero.heal', { amount: 1 });
    check(res && res.success === true, 'успех возвращает ответ бэкенда');
    check(calls.fetch.length === 1
          && calls.fetch[0].url === 'https://example.test/api/bannerlord/action',
          'POST уходит на /api/<игра>/action по НАСТОЯЩЕМУ адресу '
          + '(получено: ' + (calls.fetch[0] ? calls.fetch[0].url : 'запроса не было') + ')');
    check(calls.fetch[0] && calls.fetch[0].init.headers['X-Twitch-JWT'] === 'jwt-123',
          'JWT уходит в заголовке');
    check(calls.fetch[0] && calls.fetch[0].body.action_type === 'hero.heal'
          && calls.fetch[0].body.data.amount === 1,
          'тип действия и данные не потеряны');
    check(calls.fetch[0] && typeof calls.fetch[0].body.data.client_action_id === 'string'
          && calls.fetch[0].body.data.client_action_id.length > 0,
          'client_action_id проставлен — защита от двойного списания при ретрае');

    // 2. Дефект ShedColony 2026-08-19: баланс не обновлялся после покупки.
    check(calls.loadUserData === 1,
          'после успешной покупки баланс крустиков перечитывается (ровно один раз)');
    check(calls.toasts.length === 1 && calls.toasts[0].t === 'success',
          'на успехе показан success-тост');

    // 3. Дабл-клик не даёт второго запроса
    reset({ success: true, message: 'Готово' });
    let slowResolve;
    ctx.fetch = (url, init) => {
        calls.fetch.push({ url, init, body: JSON.parse(init.body) });
        return new Promise((r) => { slowResolve = () => r({ json: async () => ({ success: true }) }); });
    };
    const first = ShedLink.buyAction('shedcolony', 'colonist.spawn', {});
    const second = await ShedLink.buyAction('shedcolony', 'colonist.spawn', {});
    check(calls.fetch.length === 1, 'дабл-клик не отправляет второй запрос');
    check(second === null, 'второй клик возвращает null, а не мусор');
    slowResolve();
    await first;

    // 4. Разные игры не блокируют друг друга
    reset({ success: true });
    await ShedLink.buyAction('bannerlord', 'hero.heal', {});
    await ShedLink.buyAction('shedcolony', 'hero.heal', {});
    check(calls.fetch.length === 2, 'single-flight ключуется игрой, не только действием');

    // 5. Отказ бэкенда
    reset({ success: false, message: 'Недостаточно крустиков' });
    res = await ShedLink.buyAction('bannerlord', 'hero.heal', {});
    check(res && res.success === false, 'отказ возвращается вызывающему');
    check(calls.loadUserData === 0, 'на отказе баланс не дёргаем');
    check(calls.toasts.length === 1 && calls.toasts[0].t === 'error'
          && calls.toasts[0].m === 'Недостаточно крустиков',
          'на отказе показан текст причины с бэкенда');

    // 6. Отказ по кулдауну + кнопка с отсчётом → тоста нет, отсчёт синхронизирован
    reset({ success: false, message: 'Перезарядка', cooldown_remaining_s: 42 },
          { cooldownButton: true });
    await ShedLink.buyAction('bannerlord', 'power.rage', {}, {
        cooldownAttr: 'data-bnr-cd',
        onCooldown: (k, s) => calls.cooldown.push([k, s]),
    });
    check(calls.cooldown.length === 1 && calls.cooldown[0][1] === 42,
          'остаток кулдауна с сервера уходит на кнопку');
    check(calls.toasts.length === 0,
          'при видимом отсчёте на кнопке тост не дублирует его');

    // 7. Тот же отказ, но кнопки с отсчётом нет → тост нужен
    reset({ success: false, message: 'Перезарядка', cooldown_remaining_s: 42 },
          { cooldownButton: false });
    await ShedLink.buyAction('bannerlord', 'power.rage', {}, {
        cooldownAttr: 'data-bnr-cd',
        onCooldown: (k, s) => calls.cooldown.push([k, s]),
    });
    check(calls.toasts.length === 1, 'без кнопки-отсчёта причина отказа показана тостом');

    // 8. Отложенное действие: свой текст важнее общего result.message
    reset({ success: true, message: 'ok' });
    await ShedLink.buyAction('shedcolony', 'colony.upgrade_building', {}, {
        successMessage: 'Заявка принята — строители возьмутся в игре',
        onSuccess: () => { calls.onSuccess++; },
    });
    check(calls.toasts[0] && calls.toasts[0].m === 'Заявка принята — строители возьмутся в игре',
          'successMessage перекрывает result.message (баги #16/#17)');
    check(calls.onSuccess === 1, 'onSuccess зовётся после успеха');

    // 9. Сетевая ошибка не оставляет действие «залипшим»
    reset({ success: true }, { networkError: true });
    res = await ShedLink.buyAction('bannerlord', 'hero.heal', {});
    check(res === null, 'сетевая ошибка возвращает null');
    check(calls.toasts.length === 1 && calls.toasts[0].t === 'error',
          'сетевая ошибка показана зрителю');
    ctx.fetch = async (url, init) => {
        calls.fetch.push({ url, init, body: JSON.parse(init.body) });
        return { json: async () => ({ success: true }) };
    };
    res = await ShedLink.buyAction('bannerlord', 'hero.heal', {});
    check(res && res.success === true,
          'после сбоя single-flight снят — повтор проходит');

    // 10. Неавторизованный не отправляет платный запрос
    reset({ success: true }, { authed: false });
    res = await ShedLink.buyAction('bannerlord', 'hero.heal', {});
    check(calls.fetch.length === 0 && res === null,
          'без авторизации запрос не уходит');

    console.log('='.repeat(70));
    console.log('PASSED: ' + passed + '   FAILED: ' + failed);
    console.log(failed
        ? 'КРАСНО — общий платный путь изменил поведение.'
        : 'ALL GREEN — платный путь един для всех игр.');
    process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
