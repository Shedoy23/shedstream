// Вход в панель не должен падать из-за порядка объявлений.
//
// ЗАЧЕМ. Twitch вызывает onAuthorized СРАЗУ при регистрации, если токен уже
// есть, — то есть пока файл ещё выполняется. Если переменная, которой колбэк
// присваивает значение, объявлена через let/const НИЖЕ по файлу, присваивание
// попадает во временную мёртвую зону: ReferenceError, колбэк умирает целиком,
// и панель встаёт на входе. Для зрителя это «расширение не открывается».
//
// 07.09 я сам так сломал вход: добавил `_authUserId = ...` в колбэк на строке
// 399, а `let _authUserId` — на строке 573. Ни `node --check`, ни eslint этого
// не видят: синтаксис верный, дефект только в порядке выполнения. Нашлось по
// логам прода — панель владельца дошла до /api/core/config и замолчала.
//
// Запуск: node scripts/test-frontend-auth-init.mjs
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fails = [];
const check = (name, ok, detail = '') => {
    console.log((ok ? '  OK   ' : '  FAIL ') + name + (ok ? '' : ' — ' + detail));
    if (!ok) fails.push(name);
};

/** Тело колбэка onAuthorized — от регистрации до парной закрывающей скобки. */
function authCallbackBody(src) {
    const start = src.indexOf('onAuthorized(function');
    if (start < 0) return null;
    let depth = 0;
    let i = src.indexOf('{', start);
    if (i < 0) return null;
    const from = i;
    for (; i < src.length; i++) {
        if (src[i] === '{') depth++;
        else if (src[i] === '}') {
            depth--;
            if (depth === 0) return { from, to: i, start };
        }
    }
    return null;
}

/**
 * Переменные, которым колбэк присваивает значение, но которые объявлены
 * let/const ниже точки регистрации колбэка. Каждая такая — падение входа.
 */
function tdzHazards(src) {
    const body = authCallbackBody(src);
    if (!body) return null;
    const inside = src.slice(body.from, body.to);
    const assigned = new Set();
    // Голое присваивание идентификатору: `name = ...`, но не `let name =`,
    // не сравнение `==`/`===` и не свойство `obj.name =`.
    const re = /(^|[^.\w$])([A-Za-z_$][\w$]*)\s*=(?!=)/g;
    let m;
    while ((m = re.exec(inside)) !== null) {
        const before = inside.slice(Math.max(0, m.index - 12), m.index + m[1].length);
        if (/\b(let|const|var)\s*$/.test(before)) continue;
        assigned.add(m[2]);
    }
    const hazards = [];
    for (const name of assigned) {
        const decl = new RegExp(`^\\s*(let|const)\\s+${name}\\b`, 'm').exec(src);
        if (!decl) continue;
        // Объявление ВНУТРИ самого колбэка — законно и опасности не несёт:
        // оно выполняется раньше присваивания на той же итерации. Опасно
        // только объявление ниже по файлу, снаружи.
        const insideCallback = decl.index > body.from && decl.index < body.to;
        if (decl.index > body.start && !insideCallback) {
            hazards.push(name);
        }
    }
    return hazards;
}

// ── Сначала убеждаемся, что детектор вообще работает ────────────────────────
// Синтетический образец с ТОЙ САМОЙ ошибкой. Без этой проверки тест мог бы
// быть зелёным просто потому, что ничего не ищет.
const broken = `
window.Twitch.ext.onAuthorized(function(auth) {
    authToken = auth.token;
    _authUserId = auth.userId;
});
let _authUserId = null;
`;
const brokenHazards = tdzHazards(broken);
check('детектор ловит объявление ниже присваивания',
      Array.isArray(brokenHazards) && brokenHazards.includes('_authUserId'),
      'на заведомо сломанном образце ничего не найдено: проверка смотрит не туда');

const good = `
let _authUserId = null;
window.Twitch.ext.onAuthorized(function(auth) {
    _authUserId = auth.userId;
});
`;
check('правильный порядок детектор не трогает',
      (tdzHazards(good) || []).length === 0);

// ── Теперь сам файл панели ──────────────────────────────────────────────────
const src = readFileSync(path.join(root, 'Расширение', 'frontend', 'viewer.js'), 'utf8');
const hazards = tdzHazards(src);
check('колбэк onAuthorized найден', hazards !== null,
      'структура файла изменилась — проверка ослепла, почини её');
check('в колбэке нет присваиваний переменным, объявленным ниже',
      (hazards || []).length === 0,
      'временная мёртвая зона у: ' + (hazards || []).join(', '));

console.log('');
if (fails.length) {
    console.log(`ПРОВАЛЕНО: ${fails.length}`);
    process.exit(1);
}
console.log('ВСЁ ЗЕЛЁНОЕ');
