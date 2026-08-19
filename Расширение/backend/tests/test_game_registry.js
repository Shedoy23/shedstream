/* Реестр игровых модулей фронта: активна не более одной игры, все остальные
 * остановлены.
 *
 * ЗАЧЕМ ИМЕННО ЭТОТ ИНВАРИАНТ. 03.08 панель Bannerlord сделала тысячи запросов
 * к RimWorld: опрос RimWorld стартовал при разборе файла, а гасить его было
 * некому. Раньше инвариант держался тем, что в каждой ветке `if/else` внутри
 * `switchIntegrationModule` вручную стояли вызовы «останови остальных», и
 * тест проверял их СТРОКАМИ в исходнике. Строковая проверка зеленела бы и в
 * случае, когда до этих строк не доходит управление.
 *
 * Теперь инвариант записан один раз в `frontend/viewer-registry.js`, а этот
 * тест проверяет его ПОВЕДЕНИЕМ: кого позвали, кого спрятали, кого погасили.
 *
 * Запуск:  node tests/test_game_registry.js   (из папки backend)
 *          python scripts/run-backend-tests.py game_registry
 * Судить по КОДУ ВОЗВРАТА.
 *
 * vm, а не require — по той же причине, что и в test_buy_action.js: плоские
 * <script> делят одну лексическую область, у модулей Node её нет.
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

// ── фальшивый DOM: только то, чем пользуется реестр ──────────────────────────
function makeDocument(ids) {
    const nodes = {};
    ids.forEach((id) => { nodes[id] = { id, style: { display: '' }, textContent: '' }; });
    return {
        nodes,
        getElementById: (id) => nodes[id] || null,
    };
}

function shown(doc, id) { return doc.nodes[id] && doc.nodes[id].style.display !== 'none'; }

function makeContext(doc) {
    const sandbox = { console, document: doc };
    const context = vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(FRONTEND, 'viewer-registry.js'), 'utf8'),
                    context, { filename: 'viewer-registry.js' });
    return sandbox;
}

function main() {
    const doc = makeDocument([
        'integration-empty', 'panel-module-name',
        'alpha-content', 'beta-content', 'gamma-content',
    ]);
    const ShedLink = makeContext(doc).ShedLink;

    const log = [];
    function game(id) {
        return {
            rootId: id + '-content',
            title: 'T:' + id,
            start: () => log.push('start:' + id),
            stop: () => log.push('stop:' + id),
        };
    }

    ShedLink.registerGame('alpha', game('alpha'));
    ShedLink.registerGame('beta', game('beta'));
    ShedLink.registerGame('gamma', game('gamma'));

    check(ShedLink.registeredGames().join(',') === 'alpha,beta,gamma',
          'игры регистрируются сами и видны ядру списком');

    // 1. Включаем первую
    log.length = 0;
    let active = ShedLink.switchGame('alpha');
    check(active === 'alpha' && ShedLink.activeGame() === 'alpha',
          'switchGame возвращает ставшую активной игру');
    check(log.filter((e) => e === 'start:alpha').length === 1,
          'активная игра запущена ровно один раз');
    check(log.includes('stop:beta') && log.includes('stop:gamma'),
          'все НЕактивные игры остановлены — это тот самый инвариант, '
          + 'который 03.08 стоил тысяч запросов в чужую игру');
    check(!log.includes('stop:alpha'), 'активную игру не гасим тем же вызовом');
    check(shown(doc, 'alpha-content')
          && !shown(doc, 'beta-content') && !shown(doc, 'gamma-content'),
          'видна панель только активной игры');
    check(!shown(doc, 'integration-empty'),
          'заглушка «модуль не подключён» спрятана');
    check(doc.nodes['panel-module-name'].textContent === 'T:alpha',
          'подпись игры под названием расширения проставлена');

    // 2. Переключение
    log.length = 0;
    ShedLink.switchGame('beta');
    check(log.includes('stop:alpha'), 'предыдущая игра остановлена при переключении');
    check(log.filter((e) => e === 'start:beta').length === 1, 'новая игра запущена');
    check(!log.includes('start:alpha'), 'старая игра повторно не стартует');
    check(shown(doc, 'beta-content') && !shown(doc, 'alpha-content'),
          'панели поменялись местами');

    // 3. Неизвестная игра = ни одной
    log.length = 0;
    active = ShedLink.switchGame('minesweeper');
    check(active === null && ShedLink.activeGame() === null,
          'неизвестный модуль не становится активным');
    check(log.filter((e) => e.indexOf('stop:') === 0).length === 3,
          'остановлены ВСЕ игры (получено: ' + JSON.stringify(log) + ')');
    check(log.filter((e) => e.indexOf('start:') === 0).length === 0,
          'ничего не запущено');
    check(shown(doc, 'integration-empty'),
          'показана заглушка «игровой модуль не подключён»');
    check(doc.nodes['panel-module-name'].textContent === '',
          'подпись игры очищена — иначе в шапке висит название выключенной игры');

    // 4. То же для null: бэкенд шлёт active_module=null, когда игра не выбрана
    log.length = 0;
    check(ShedLink.switchGame(null) === null && shown(doc, 'integration-empty'),
          'null обрабатывается так же, как неизвестный модуль');

    // 5. Повторный вызов той же игры — как было до реестра: ядро зовёт
    //    switchGame на каждом опросе профиля, старт обязан быть безопасным.
    ShedLink.switchGame('alpha');
    log.length = 0;
    ShedLink.switchGame('alpha');
    check(log.filter((e) => e === 'start:alpha').length === 1
          && !log.includes('stop:alpha'),
          'повторное переключение в ту же игру не гасит её и зовёт start снова '
          + '(защита от дублей — внутри самой игры, как и раньше)');

    // 6. Падение одной игры не оставляет панель в подвешенном состоянии
    ShedLink._resetGames();
    const log2 = [];
    ShedLink.registerGame('boom', {
        rootId: 'alpha-content', title: 'boom',
        start: () => { throw new Error('boom start'); },
        stop: () => { throw new Error('boom stop'); },
    });
    ShedLink.registerGame('ok', {
        rootId: 'beta-content', title: 'ok',
        start: () => log2.push('start:ok'), stop: () => log2.push('stop:ok'),
    });
    ShedLink.switchGame('boom');
    ShedLink.switchGame('ok');
    check(log2.includes('start:ok'),
          'падение stop() у соседней игры не мешает запустить новую');
    check(shown(doc, 'beta-content') && !shown(doc, 'alpha-content'),
          'панели переключились, несмотря на исключение внутри игры');

    // 7. Игра, у которой в этой оболочке нет блока, всё равно гасится
    ShedLink._resetGames();
    const log3 = [];
    ShedLink.registerGame('ghost', {
        rootId: 'missing-content', title: 'ghost',
        start: () => log3.push('start:ghost'), stop: () => log3.push('stop:ghost'),
    });
    ShedLink.registerGame('real', {
        rootId: 'beta-content', title: 'real',
        start: () => log3.push('start:real'), stop: () => log3.push('stop:real'),
    });
    ShedLink.switchGame('real');
    check(log3.includes('stop:ghost'),
          'игра без блока в оболочке всё равно останавливается — раньше '
          + 'отсутствие одного элемента прерывало переключение целиком');

    console.log('='.repeat(70));
    console.log('PASSED: ' + passed + '   FAILED: ' + failed);
    console.log(failed
        ? 'КРАСНО — реестр перестал держать «активна одна, остальные молчат».'
        : 'ALL GREEN — активна не более одной игры, остальные остановлены.');
    process.exit(failed ? 1 : 0);
}

main();
