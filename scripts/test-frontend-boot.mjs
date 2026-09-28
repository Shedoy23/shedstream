// Панель обязана пережить загрузку и синхронный onAuthorized.
//
// ЗАЧЕМ. 08.09 вход в панель падал с ReferenceError: колбэк onAuthorized
// присваивал переменную, объявленную `let` ниже по файлу. Twitch вызывает этот
// колбэк СРАЗУ при регистрации, если токен уже есть, — то есть пока файл ещё
// выполняется. Синтаксис верный, поэтому ни `node --check`, ни eslint ничего не
// сказали; увидел это только прод — панель владельца доходила до
// /api/core/config и замолкала.
//
// Отдельный статический гейт (test-frontend-auth-init.mjs) ловит сам порядок
// объявлений. Этот идёт дальше и ЗАПУСКАЕТ файл: любая ошибка на старте, а не
// только временная мёртвая зона, валит проверку.
//
// Запуск: node scripts/test-frontend-boot.mjs
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fails = [];
const check = (name, ok, detail = '') => {
    console.log((ok ? '  OK   ' : '  FAIL ') + name + (ok ? '' : ' — ' + detail));
    if (!ok) fails.push(name);
};

/** Заглушка DOM: всё возвращает объект, который можно бесконечно дёргать. */
function makeElement() {
    const el = new Proxy(function () {}, {
        get(_t, prop) {
            if (prop === 'style' || prop === 'dataset' || prop === 'classList') return makeElement();
            if (prop === 'textContent' || prop === 'innerHTML' || prop === 'value') return '';
            if (prop === 'children' || prop === 'childNodes') return [];
            if (prop === Symbol.toPrimitive || prop === 'toString') return () => '';
            return makeElement();
        },
        set() { return true; },
        apply() { return makeElement(); },
    });
    return el;
}

function bootstrap(twitchStub) {
    const errors = [];
    const calls = [];
    // Слушателей DOMContentLoaded ЗАПОМИНАЕМ и дёргаем сами. Без этого стенд
    // проверял пустоту: вся инициализация панели (включая регистрацию
    // onAuthorized) висит именно на этом событии, и первая версия харнесса
    // осталась зелёной на заведомо сломанном файле.
    const domReady = [];
    const doc = {
        getElementById: () => makeElement(),
        querySelector: () => makeElement(),
        querySelectorAll: () => [],
        createElement: () => makeElement(),
        addEventListener: (evt, fn) => {
            if (evt === 'DOMContentLoaded' && typeof fn === 'function') domReady.push(fn);
        },
        removeEventListener: () => {},
        body: makeElement(),
        head: makeElement(),
        readyState: 'loading',
        cookie: '',
    };
    const sandbox = {
        console: { log: () => {}, warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
        document: doc,
        setTimeout: () => 0,
        clearTimeout: () => {},
        setInterval: () => 0,
        clearInterval: () => {},
        fetch: (url) => {
            calls.push(String(url));
            return Promise.resolve({
                ok: true, status: 200,
                json: () => Promise.resolve({ login: 'alice', points: 1 }),
                text: () => Promise.resolve(''),
            });
        },
        localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
        location: { href: 'https://localhost/', search: '', hostname: 'localhost', protocol: 'https:', origin: 'https://localhost' },
        navigator: { userAgent: 'node' },
        crypto: { randomUUID: () => 'test-uuid' },
        Date, Math, JSON, Promise, Object, Array, String, Number, Boolean, RegExp, Error, Map, Set,
        parseInt, parseFloat, isNaN, encodeURIComponent, decodeURIComponent, atob: (s) => Buffer.from(String(s), 'base64').toString('binary'),
        addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => true,
        requestAnimationFrame: () => 0, cancelAnimationFrame: () => {},
        alert: () => {}, confirm: () => true, prompt: () => null,
        URLSearchParams, URL, TextEncoder, TextDecoder, Symbol, Proxy, Reflect,
        WebSocket: function () { return { addEventListener() {}, close() {}, send() {} }; },
        performance: { now: () => 0 },
        AbortController: function () { return { signal: {}, abort() {} }; },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.self = sandbox;
    sandbox.Twitch = twitchStub;
    vm.createContext(sandbox);

    const src = readFileSync(path.join(root, 'Расширение', 'frontend', 'viewer.js'), 'utf8');
    try {
        new vm.Script(src, { filename: 'viewer.js' }).runInContext(sandbox);
    } catch (e) {
        errors.push('загрузка файла: ' + String(e && e.message || e));
    }
    // Теперь то, ради чего всё затевалось: страница «готова», панель стартует.
    for (const fn of domReady) {
        try {
            fn();
        } catch (e) {
            errors.push('старт панели: ' + String(e && e.message || e));
        }
    }
    return { errors, sandbox, calls, domReadyCount: domReady.length };
}

/** Twitch, который вызывает onAuthorized СИНХРОННО — как при готовом токене. */
const syncTwitch = () => {
    const stub = {
        ext: {
            onAuthorized(cb) {
                cb({ token: 'a.eyJ1c2VyX2lkIjoiMTIzIn0.c', userId: 'U7SM4O56SUT9PGNKUOBVH',
                     clientId: 'cid', helixToken: 'h' });
            },
            onContext() {}, onError() {}, listen() {}, unlisten() {},
            actions: { requestIdShare() {}, minimize() {}, followChannel() {} },
            configuration: {}, viewer: {}, rig: {},
        },
    };
    return stub;
};

/** И вариант, где Twitch недоступен вовсе — панель не должна падать и тут. */
const noTwitch = () => undefined;

// ── Сначала проверяем, что харнесс вообще способен увидеть ошибку ────────────
// Без этого «зелено» означало бы только то, что мы ничего не запустили.
{
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    vm.createContext(sandbox);
    let caught = '';
    try {
        new vm.Script('boom = notDeclaredAnywhere.field;').runInContext(sandbox);
    } catch (e) { caught = String(e.message); }
    check('харнесс видит ошибку выполнения', caught.length > 0, 'песочница молчит — проверка слепая');
}

{
    const { errors, calls, domReadyCount } = bootstrap(syncTwitch());
    // Без этой проверки стенд мог бы «пройти», ничего не запустив, — ровно так
    // первая версия и осталась зелёной на сломанном файле.
    check('стартовый обработчик панели найден и вызван', domReadyCount > 0,
          'DOMContentLoaded никто не слушает — проверка смотрит в пустоту');
    check('панель загружается при синхронном onAuthorized', errors.length === 0,
          errors.join(' | '));
    // ГЛАВНАЯ проверка. Ошибку внутри колбэка панель глотает, поэтому судить
    // по «упало / не упало» бесполезно — вторая версия этого стенда так и
    // осталась зелёной на сломанном файле. Судим по ИСХОДУ: получив токен,
    // панель обязана пойти опознаваться на сервер. Не пошла — вход мёртв,
    // ровно как это выглядело у владельца 08.09.
    check('получив токен, панель идёт опознаваться',
          calls.some(u => u.includes('resolve-twitch-token')),
          'запросов опознания нет; фактические вызовы: ' + (calls.join(', ') || 'ни одного'));
}

{
    const { errors } = bootstrap(noTwitch());
    check('панель загружается и без Twitch-хелпера', errors.length === 0,
          errors.join(' | '));
}

console.log('');
if (fails.length) {
    console.log(`ПРОВАЛЕНО: ${fails.length}`);
    process.exit(1);
}
console.log('ВСЁ ЗЕЛЁНОЕ');
