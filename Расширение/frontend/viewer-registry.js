/* viewer-registry.js — реестр игровых модулей: кто есть, где его панель,
 * как его включить и выключить.
 *
 * Зачем (docs/FRONTEND_MODULE_ARCH_PLAN.md, шаг 2). Раньше переключение игр
 * жило в `switchIntegrationModule` цепочкой if/else, которая знала имена всех
 * игр, id всех блоков и имена всех функций опроса. Добавление игры правило эту
 * цепочку, а забытая ветка означала не «не работает», а «опрашивает чужую
 * игру»: 03.08 панель Bannerlord сделала тысячи запросов к RimWorld, потому что
 * у RimWorld опрос стартовал при разборе файла, а гасить его было некому.
 *
 * Здесь этот инвариант ровно один и записан один раз: активна не более одной
 * игры, все остальные остановлены. Игра сама говорит о себе — ядро не знает
 * ни одного имени игры.
 *
 * Грузится ПЕРЕД viewer.js. Игры регистрируются из своих файлов, которые
 * грузятся ПОСЛЕ него; порядок не важен, потому что переключение происходит
 * в рантайме (из loadUserData), когда загружено уже всё.
 *
 * При загрузке не трогает document — тестируется в node:
 * backend/tests/test_game_registry.js.
 */
(function (global) {
    'use strict';

    var ShedLink = global.ShedLink || (global.ShedLink = {});

    var _games = {};       // id → {id, rootId, title, start, stop}
    var _active = null;

    /**
     * Объявить игровой модуль.
     *
     * @param {string} id      id модуля, как его знает бэкенд (channels.active_module)
     * @param {object} spec
     *   rootId — id корневого <div> панели этой игры в обеих оболочках;
     *   title  — подпись под названием расширения («⚔️ Bannerlord»);
     *   start  — включить опрос/рендер (зовётся, когда игра стала активной);
     *   stop   — выключить опрос (зовётся, когда игра перестала быть активной).
     *
     * start/stop оборачивать в функцию, а не передавать ссылку напрямую, если
     * сама функция объявлена в другом файле: ссылка возьмётся в момент вызова,
     * и порядок <script> перестанет иметь значение.
     */
    ShedLink.registerGame = function (id, spec) {
        if (!id || !spec) { return; }
        _games[id] = {
            id: id,
            rootId: spec.rootId || '',
            title: spec.title || '',
            start: typeof spec.start === 'function' ? spec.start : function () {},
            stop: typeof spec.stop === 'function' ? spec.stop : function () {},
        };
    };

    ShedLink.registeredGames = function () {
        var out = [];
        for (var id in _games) {
            if (Object.prototype.hasOwnProperty.call(_games, id)) { out.push(id); }
        }
        return out.sort();
    };

    ShedLink.activeGame = function () { return _active; };

    function _hide(el, hidden) {
        if (el) { el.style.display = hidden ? 'none' : ''; }
    }

    function _safe(label, fn, id) {
        try {
            fn();
        } catch (e) {
            // Падение одной игры не должно оставить панель в состоянии
            // «старая остановлена, новая не запущена».
            console.error('[games] ' + label + ' failed for ' + id, e);
        }
    }

    /**
     * Сделать активной игру `id` (или ни одной, если id неизвестен/пуст).
     * Возвращает id ставшей активной игры либо null — вызывающий кладёт это
     * в свой стейт.
     */
    ShedLink.switchGame = function (id) {
        var next = Object.prototype.hasOwnProperty.call(_games, id) ? id : null;
        _active = next;

        var doc = global.document;
        if (!doc) { return next; }

        // Сначала гасим всё, что не станет активным: остановленной должна
        // оказаться каждая игра, включая ту, чьего блока нет в этой оболочке.
        for (var gid in _games) {
            if (!Object.prototype.hasOwnProperty.call(_games, gid)) { continue; }
            if (gid === next) { continue; }
            _hide(doc.getElementById(_games[gid].rootId), true);
            _safe('stop', _games[gid].stop, gid);
        }

        var empty = doc.getElementById('integration-empty');
        var nameEl = doc.getElementById('panel-module-name');
        if (nameEl) { nameEl.textContent = next ? _games[next].title : ''; }
        _hide(empty, !!next);

        if (next) {
            _hide(doc.getElementById(_games[next].rootId), false);
            _safe('start', _games[next].start, next);
        }
        return next;
    };

    // Для теста: чистый реестр между кейсами.
    ShedLink._resetGames = function () { _games = {}; _active = null; };

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = ShedLink;
    }
})(typeof window !== 'undefined' ? window : globalThis);
