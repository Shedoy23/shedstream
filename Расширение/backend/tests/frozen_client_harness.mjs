// frozen_client_harness.mjs — стенд для контракта замороженного клиента 0.0.5.
//
// Сам по себе не тест: его запускает tests/test_frozen_client_0_0_5.py. Питон
// готовит ответы НАСТОЯЩИХ обработчиков бэкенда на временной базе и потом
// проверяет, что увидел клиент. Здесь ровно одно: загрузить клиента из
// распакованного архива — порядок скриптов берётся из его же extension.html,
// как у Twitch, — подать ему эти ответы вместо сети и записать, что он сделал.
//
// Что подменено и почему это честно:
//   * сеть — fetch отдаёт ответы, заранее полученные от настоящих обработчиков;
//   * DOM — записывающие элементы: клиентский код идёт по своим веткам, а стенд
//     запоминает, что он написал в innerHTML/textContent и какие обработчики
//     кнопок повесил. «Нажать Да» — это вызов onclick, который поставил сам
//     клиент, а не подмена диалога;
//   * showNotification — ОБЁРНУТА для наблюдения, оригинал продолжает работать;
//   * таймеры — очередь, которую стенд прокручивает после каждого шага.
// Интерпретация ответов — код архива, её здесь не трогает ничто.
//
// Запуск: node frozen_client_harness.mjs <каталог_клиента> <scenarios.json> <out.json>
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const [, , clientDir, scenariosPath, outPath] = process.argv;
const scenarios = JSON.parse(readFileSync(scenariosPath, 'utf8'));
const shell = readFileSync(path.join(clientDir, 'extension.html'), 'utf8');
const scripts = [...shell.matchAll(/<script[^>]+src="([^"]+)"/g)]
    .map((m) => m[1].split('?')[0])
    .filter((s) => !/^https?:/i.test(s));

/** Элемент, который можно дёргать как угодно: вызов, свойство, цепочка. */
function noop() {
    return new Proxy(function () {}, {
        get(_t, p) {
            if (p === 'then') return undefined;           // не thenable — иначе await виснет
            if (p === Symbol.toPrimitive) return () => '';
            return noop();
        },
        apply() { return noop(); },
        set() { return true; },
    });
}

function makeEl(rec, tag, id) {
    const o = { tagName: String(tag || 'div').toUpperCase(), id: id || '',
                __children: [], __attrs: {}, __listeners: {} };
    return new Proxy(o, {
        get(t, p) {
            if (p === 'then') return undefined;
            if (Object.prototype.hasOwnProperty.call(t, p)) return t[p];
            switch (p) {
                case 'style': case 'dataset': t[p] = {}; return t[p];
                case 'classList':
                    return { add() {}, remove() {}, toggle() { return false; }, contains() { return false; } };
                case 'appendChild': case 'append': case 'prepend':
                case 'insertBefore': case 'replaceChildren':
                    return (...cs) => { t.__children.push(...cs); return cs[0]; };
                case 'remove': return () => { t.__removed = true; };
                case 'setAttribute': return (k, v) => { t.__attrs[k] = String(v); };
                case 'getAttribute': return (k) => (k in t.__attrs ? t.__attrs[k] : null);
                case 'removeAttribute': return (k) => { delete t.__attrs[k]; };
                case 'addEventListener':
                    return (e, f) => { (t.__listeners[e] = t.__listeners[e] || []).push(f); };
                case 'removeEventListener': return () => {};
                case 'querySelector': return () => makeEl(rec, 'div', null);
                case 'querySelectorAll': return () => [];
                case 'closest': return () => null;
                case 'children': case 'childNodes': return t.__children;
                case 'textContent': case 'innerHTML': case 'innerText':
                case 'value': case 'className': return '';
                case 'disabled': case 'checked': case 'hidden': return false;
                case 'offsetWidth': case 'offsetHeight': case 'scrollHeight':
                case 'clientWidth': case 'clientHeight': return 0;
                case Symbol.toPrimitive: return () => '';
                case 'toString': return () => '[element]';
                default: return noop();
            }
        },
        set(t, p, v) {
            t[p] = v;
            if (p === 'innerHTML' || p === 'textContent' || p === 'innerText') {
                rec.writes.push({ id: t.id || null, prop: p, value: String(v) });
            }
            return true;
        },
    });
}

function response(status, body) {
    const text = JSON.stringify(body === undefined ? {} : body);
    return {
        ok: status >= 200 && status < 300, status,
        json: () => Promise.resolve(JSON.parse(text)),
        text: () => Promise.resolve(text),
        headers: { get: () => 'application/json' },
    };
}

const settle = () => new Promise((r) => setImmediate(r));

async function runScenario(sc) {
    const rec = { name: sc.name, loadErrors: [], stepErrors: [], notifications: [],
                  fetches: [], unmatched: [], writes: [], console: [], observed: {} };
    const byId = new Map();
    const doc = {
        getElementById: (id) => {
            if (!byId.has(id)) byId.set(id, makeEl(rec, 'div', id));
            return byId.get(id);
        },
        querySelector: () => makeEl(rec, 'div', null),
        querySelectorAll: () => [],
        createElement: (tag) => makeEl(rec, tag, null),
        createTextNode: (s) => ({ textContent: String(s) }),
        addEventListener: () => {}, removeEventListener: () => {},
        body: makeEl(rec, 'body', null), head: makeEl(rec, 'head', null),
        documentElement: makeEl(rec, 'html', null),
        // 'loading', а не 'complete': иначе часть файлов стартовала бы панель
        // прямо при загрузке — со всеми её запросами. Стенд зовёт разборщики
        // ответов напрямую, по шагам сценария.
        readyState: 'loading', hidden: false, visibilityState: 'visible', cookie: '',
    };

    const queue = [];
    let tid = 0;
    const log = (kind) => (...a) => rec.console.push(kind + ': ' + a.map(String).join(' ').slice(0, 300));
    const sandbox = {
        console: { log() {}, info() {}, debug() {}, warn: log('warn'), error: log('error') },
        document: doc,
        setTimeout: (fn, _ms) => { const id = ++tid; if (typeof fn === 'function') queue.push({ id, fn }); return id; },
        clearTimeout: (id) => { const i = queue.findIndex((q) => q.id === id); if (i >= 0) queue.splice(i, 1); },
        setInterval: () => ++tid, clearInterval: () => {},
        queueMicrotask,
        fetch: (url, opts = {}) => {
            const u = String(url);
            const method = String((opts && opts.method) || 'GET').toUpperCase();
            let body = opts && opts.body;
            try { body = body ? JSON.parse(body) : null; } catch (_) { /* не JSON — оставляем строкой */ }
            rec.fetches.push({ url: u, method, body });
            const route = (sc.routes || []).find((r) => u.includes(r.match) && (!r.method || r.method === method));
            if (!route) { rec.unmatched.push(method + ' ' + u); return Promise.resolve(response(200, {})); }
            let answer = route;
            if (Array.isArray(route.sequence)) {
                route.__calls = (route.__calls || 0) + 1;
                answer = route.sequence[Math.min(route.__calls, route.sequence.length) - 1];
            }
            if (answer.network_error) return Promise.reject(new TypeError('Failed to fetch'));
            return Promise.resolve(response(answer.status || 200, answer.body));
        },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        location: { href: 'https://extension-files.twitch.tv/', search: '', hash: '',
                    hostname: 'extension-files.twitch.tv', protocol: 'https:',
                    origin: 'https://extension-files.twitch.tv', reload() {} },
        navigator: { userAgent: 'node-frozen-client', language: 'ru-RU' },
        crypto: { randomUUID: () => 'cid-' + (++tid) },
        Date, Math, JSON, Promise, Object, Array, String, Number, Boolean, RegExp, Error,
        TypeError, Map, Set, WeakMap, Intl, Symbol, Proxy, Reflect,
        parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent,
        URLSearchParams, URL, TextEncoder, TextDecoder,
        atob: (s) => Buffer.from(String(s), 'base64').toString('binary'),
        btoa: (s) => Buffer.from(String(s), 'binary').toString('base64'),
        addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true,
        requestAnimationFrame: () => 0, cancelAnimationFrame() {},
        alert() {}, confirm: () => true, prompt: () => null,
        performance: { now: () => 0 },
        WebSocket: function () { return { addEventListener() {}, close() {}, send() {} }; },
        AbortController: function () { return { signal: {}, abort() {} }; },
        matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
        getComputedStyle: () => ({ getPropertyValue: () => '' }),
        __notes: rec.notifications,
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.self = sandbox;
    sandbox.Twitch = { ext: {
        onAuthorized() {}, onContext() {}, onError() {}, onVisibilityChanged() {},
        listen() {}, unlisten() {}, send() {},
        actions: { requestIdShare() {}, minimize() {}, followChannel() {} },
        configuration: { onChanged() {}, broadcaster: null, global: null, developer: null },
        viewer: { id: null, opaqueId: null, isLinked: false, onChanged() {} },
        features: { onChanged() {} }, rig: { log() {} },
        bits: { onTransactionComplete() {}, getProducts: () => Promise.resolve([]) },
    } };
    sandbox.__click = (id) => {
        const f = doc.getElementById(id).onclick;
        return typeof f === 'function' ? f() : null;
    };
    const ctx = vm.createContext(sandbox);

    for (const f of scripts) {
        try {
            new vm.Script(readFileSync(path.join(clientDir, f), 'utf8'), { filename: f }).runInContext(ctx);
        } catch (e) {
            rec.loadErrors.push(f + ': ' + String((e && e.message) || e));
        }
    }
    // Наблюдение за уведомлениями: оригинал продолжает работать.
    vm.runInContext(`(function () {
        if (typeof showNotification !== 'function') return;
        var original = showNotification;
        globalThis.showNotification = function (m, t) {
            __notes.push({ message: String(m), type: String(t || 'info') });
            return original.apply(this, arguments);
        };
    })();`, ctx);

    async function drain() {
        for (let round = 0; round < 50; round++) {
            await settle();
            if (!queue.length) { await settle(); if (!queue.length) return; }
            const batch = queue.splice(0, queue.length);
            for (const q of batch) {
                try { await q.fn(); } catch (e) { rec.stepErrors.push('таймер: ' + String((e && e.message) || e)); }
            }
        }
    }

    if (sc.setup) {
        try { vm.runInContext(sc.setup, ctx); } catch (e) { rec.stepErrors.push('setup: ' + String((e && e.message) || e)); }
    }
    for (const step of sc.steps || []) {
        try {
            const v = vm.runInContext(step, ctx);
            if (v && typeof v.then === 'function') await v;
        } catch (e) {
            rec.stepErrors.push(step.slice(0, 80) + ': ' + String((e && e.message) || e));
        }
        await drain();
    }
    for (const [key, expr] of Object.entries(sc.observe || {})) {
        try {
            let v = vm.runInContext(expr, ctx);
            if (v && typeof v.then === 'function') v = await v;
            rec.observed[key] = JSON.parse(JSON.stringify(v === undefined ? null : v));
        } catch (e) {
            rec.observed[key] = { __error__: String((e && e.message) || e) };
        }
    }
    rec.writes = rec.writes.slice(-200);
    return rec;
}

const results = [];
for (const sc of scenarios) results.push(await runScenario(sc));
writeFileSync(outPath, JSON.stringify({ scripts, results }, null, 1));
