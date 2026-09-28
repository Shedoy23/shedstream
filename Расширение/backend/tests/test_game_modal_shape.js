/**
 * test_game_modal_shape.js — раскрытый блок не должен закрываться сам.
 *
 * Запуск (его же делает scripts/run-backend-tests.py):
 *     node tests/test_game_modal_shape.js
 *
 * ЗАЧЕМ. 2026-09-02 владелец открыл «Правила» в канате на телефоне — и они
 * схлопнулись через секунду. Причина не в <details>: опрос раз в 2 секунды
 * переписывал innerHTML ВСЕГО тела модалки, вместе с блоками правил и рейтинга,
 * и браузер честно возвращал их в исходное свёрнутое состояние.
 *
 * Почему это не косметика: блок правил — наш ответ на требование ревью
 * показывать правила ДО входа в матч (Apple 5.3.2 / блокер №3 комплаенс-ревью
 * каната). Правила, которые закрываются сами, — это правила, которых ревьюер
 * не прочитал.
 *
 * Крестики этого класса не имеют: у них меняется только `#ttt-content`, а
 * лидерборд живёт в оболочке рядом. Тест закрепляет ровно это разделение —
 * `<details>` обязан лежать в функции-ОБОЛОЧКЕ, которая рисуется один раз, и не
 * встречаться в функциях, которые дёргает опрос.
 *
 * Тест текстовый (разбор исходника), а не браузерный: поднимать DOM ради одного
 * структурного правила дороже, чем оно стоит, а правило нарушается именно на
 * уровне «кто что переписывает».
 */
'use strict';

const fs = require('fs');
const path = require('path');

const FRONT = path.join(__dirname, '..', '..', 'frontend');
let failures = 0;

function check(ok, what, detail) {
    if (ok) {
        console.log('  OK  ' + what);
    } else {
        console.log('  FAIL ' + what + (detail ? ' -- ' + detail : ''));
        failures += 1;
    }
}

/** Тело функции по имени: от `function name(` до строки, где скобка закрылась. */
function functionBody(src, name) {
    const start = src.indexOf('function ' + name + '(');
    if (start < 0) return null;
    let i = src.indexOf('{', start);
    if (i < 0) return null;
    let depth = 0;
    for (let j = i; j < src.length; j++) {
        const c = src[j];
        if (c === '{') depth++;
        else if (c === '}') {
            depth--;
            if (depth === 0) return src.slice(i, j + 1);
        }
    }
    return null;
}

console.log('='.repeat(70));
console.log('Свёрнутые блоки переживают опрос (правила и рейтинг сезона)');
console.log('='.repeat(70));

// Пары: файл, функция-оболочка (рисуется один раз), функции, которые дёргает опрос.
const CASES = [
    {
        file: 'tugofwar.js',
        shell: '_renderTugModal',
        polled: ['_renderTugContent'],
    },
    {
        file: 'tictactoe.js',
        shell: '_renderTttModal',
        polled: ['_renderTttIdle', '_renderTttQueued'],
    },
];

for (const c of CASES) {
    const src = fs.readFileSync(path.join(FRONT, c.file), 'utf8');
    const shell = functionBody(src, c.shell);
    check(shell !== null, c.file + ': функция-оболочка ' + c.shell + ' найдена');
    if (shell) {
        check(shell.indexOf('<details') >= 0,
              c.file + ': свёрнутые блоки объявлены в оболочке',
              'иначе им негде пережить перерисовку');
    }
    for (const fn of c.polled) {
        const body = functionBody(src, fn);
        check(body !== null, c.file + ': перерисовываемая функция ' + fn + ' найдена');
        if (body) {
            check(body.indexOf('<details') < 0,
                  c.file + ': ' + fn + ' не рисует <details>',
                  'опрос будет схлопывать блок каждые пару секунд');
        }
    }
}

// Общая форма стартового экрана. Разнобой заметил владелец: три мини-игры одного
// расширения открывались по-разному, и это читается как незаконченность.
console.log('');
console.log('='.repeat(70));
console.log('Стартовый экран мини-игр выглядит одинаково');
console.log('='.repeat(70));

for (const file of ['tictactoe.js', 'tugofwar.js', 'duels.js']) {
    const src = fs.readFileSync(path.join(FRONT, file), 'utf8');
    check(src.indexOf('Найти противника') >= 0,
          file + ': кнопка поиска называется одинаково',
          'у игр были «Найти соперника» и «Найти противника» вперемешку');
    check(/font-size:64px/.test(src),
          file + ': крупный знак игры на стартовом экране');
    check(src.indexOf('🏆') >= 0, file + ': блок рейтинга сезона на месте');
}

console.log('');
console.log('='.repeat(70));
if (failures) {
    console.log('ПРОВАЛ: ' + failures);
    process.exit(1);
}
console.log('ВСЁ ЗЕЛЁНОЕ — блоки переживают опрос, стартовые экраны единообразны');
process.exit(0);
