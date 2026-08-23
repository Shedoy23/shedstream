// Одно правило: no-undef по фронту расширения.
//
// ЗАЧЕМ. `pets.js` и `shop.js` объявляли одноимённую `_buyItem`, покупки
// магазина RimWorld уходили в эндпоинт питомцев, и магазин был мёртв месяцами:
// ошибка молчит внутри обработчика клика. Коллизию имён ловит
// `scripts/lint_consistency.py`. У той истории есть вторая половина, которую он
// поймать не может: функцию переименовали в одном файле, а вызов остался
// старый. Тогда клик даёт ReferenceError — и тоже молча.
//
// КАК ЭТО РАБОТАЕТ. Файлы фронта — классические скрипты с ОДНОЙ общей
// глобальной областью, поэтому `showNotification` из `viewer.js` законно
// вызывается из `shop.js`. ESLint смотрит на файлы по отдельности и без
// подсказки счёл бы такие вызовы неопределёнными.
//
// Список общих имён собирается НА ЛЕТУ из файлов, подключённых в оболочке
// (`scripts/frontend-globals.mjs`). Хранить копию нельзя: переименование
// функции оставило бы старое имя «объявленным», и проверка молча перестала бы
// работать — ровно тот класс, ради которого она написана.
//
// Сборщик вынесен отдельным модулем, потому что конфиг ESLint нельзя запустить
// сам по себе, а модуль можно: `node scripts/frontend-globals.mjs --self-test`.
import globals from "globals";

import {
  selfTest,
  sharedGlobals,
  shellScripts,
} from "./scripts/frontend-globals.mjs";

// Если сбор имён сломается, no-undef начнёт сыпать сотнями ложных ошибок на
// настоящих функциях — и правило отключат как «шумное», вместо того чтобы
// починить сбор. Поэтому падаем громко и сразу.
const check = selfTest();
if (check.missing.length) {
  throw new Error(
    `frontend-globals сломан: не найдены ${check.missing.join(", ")}. ` +
      `Проверка была бы бессмысленной — чиним сбор, а не отключаем правило.`,
  );
}

const files = shellScripts();

export default [
  {
    files: files.map((f) => `Расширение/frontend/${f}`),
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        ...sharedGlobals(files),
        Twitch: "readonly", // SDK расширения, приходит от Twitch
        // Часть файлов грузится и браузером, и Node-тестами
        // (`tests/test_buy_action.js`), поэтому в них есть хвост
        // `typeof module !== "undefined" && module.exports = ...`.
        module: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
    },
  },
];
