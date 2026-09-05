// Замок двойного клика: различает действия и не молчит.
//
// ЗАЧЕМ. Оба призыва Bannerlord — это action_type "player.spawn", но за
// стримера и против него у них разные цены и РАЗНЫЕ кулдауны на сервере.
// Замок во фронте держался по game+actionType, поэтому второй клик по соседней
// кнопке пропадал: ни тоста, ни отказа, только console.warn. Для зрителя это
// неотличимо от сломанной кнопки (найдено в живом прогоне 03.09).
//
// Запуск: node scripts/test-frontend-action-lock.mjs
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = readFileSync(path.join(root, 'Расширение', 'frontend', 'viewer-actions.js'), 'utf8');
const fails = [];
const check = (name, ok, detail = '') => {
    console.log((ok ? '  OK   ' : '  FAIL ') + name + (ok ? '' : ' — ' + detail));
    if (!ok) fails.push(name);
};

// Вырезаем helper замка и проверяем его отдельно: поднимать всю панель ради
// одной функции незачем.
const from = src.indexOf('function _lockSuffix(data)');
const to = src.indexOf('ShedLink.buyAction = async function');
if (from < 0 || to < 0) {
    check('helper замка найден', false, 'структура файла изменилась');
} else {
    const _lockSuffix = new Function(src.slice(from, to) + '\nreturn _lockSuffix;')();
    const key = (type, data) => 'bannerlord:' + type + ':' + _lockSuffix(data);

    check('стороны призыва не делят один замок',
          key('player.spawn', { price: 50, side: 'player' })
          !== key('player.spawn', { price: 100, side: 'enemy' }));
    check('повторный клик по той же кнопке замком ловится',
          key('player.spawn', { side: 'player', price: 50 })
          === key('player.spawn', { price: 50, side: 'player' }),
          'порядок полей не должен менять ключ');
    check('разные предметы в одном действии не мешают друг другу',
          key('hero.equip_item', { def_name: 'sword' })
          !== key('hero.equip_item', { def_name: 'shield' }));
    check('client_action_id в ключ не входит',
          key('hero.heal', { price: 100, client_action_id: 'a' })
          === key('hero.heal', { price: 100, client_action_id: 'b' }),
          'иначе замок не сработал бы никогда');
}

// И вторая половина: заблокированный клик обязан сказать зрителю, что происходит.
const guard = src.slice(src.indexOf('if (_inflight[key])'), src.indexOf('_inflight[key] = true;'));
check('заблокированный клик показывает объяснение', /_notify\(/.test(guard),
      'в ветке остался только console.warn');

console.log(fails.length ? `\nПРОВАЛЕНО: ${fails.join('; ')}` : '\nВСЁ ЗЕЛЁНОЕ');
process.exit(fails.length ? 1 : 0);
