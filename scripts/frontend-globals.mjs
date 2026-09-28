// Собирает имена верхнего уровня, общие для всех файлов оболочки расширения.
//
// Вынесено из `eslint.config.mjs` отдельным модулем СПЕЦИАЛЬНО: конфиг ESLint
// нельзя запустить и проверить сам по себе, а сборщик — можно. Пока он жил
// внутри конфига, его молчаливый сбой выглядел как «функция не объявлена», то
// есть как ложная ошибка правила, ради которого всё написано. Проверять надо
// инструмент, а не только код.
//
// Самопроверка: `node scripts/frontend-globals.mjs --self-test`
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const FRONTEND = path.join(HERE, "..", "Расширение", "frontend");

/** Файлы, реально подключённые в оболочке (порядок сохраняется). */
export function shellScripts(shell = "extension.html") {
  const html = fs.readFileSync(path.join(FRONTEND, shell), "utf8");
  return [...html.matchAll(/src="([a-z0-9_.-]+\.js)/g)].map((m) => m[1]);
}

const DECL = [
  String.raw`^[ \t]*(?:async[ \t]+)?function[ \t]+([A-Za-z_$][\w$]*)`,
  String.raw`^[ \t]*(?:var|let|const)[ \t]+([A-Za-z_$][\w$]*)`,
  String.raw`^[ \t]*class[ \t]+([A-Za-z_$][\w$]*)`,
  String.raw`(?:window|global|globalThis)\.([A-Za-z_$][\w$]*)[ \t]*=`,
];

/** {имя: "writable"} по всем переданным файлам. */
export function sharedGlobals(files = shellScripts()) {
  const found = {};
  for (const file of files) {
    const full = path.join(FRONTEND, file);
    if (!fs.existsSync(full)) continue;
    const src = fs.readFileSync(full, "utf8");
    for (const source of DECL) {
      const re = new RegExp(source, "gm");
      let m;
      while ((m = re.exec(src)) !== null) found[m[1]] = "writable";
    }
  }
  return found;
}

// Имена, которые ОБЯЗАНЫ найтись. Выбраны так, чтобы задеть каждый способ
// объявления: обычная функция, объект через global.*, и имя из файла, который
// подключается отдельно от основного.
const PROBES = ["showNotification", "loadUserData", "escapeHtml", "PetStage"];

export function selfTest() {
  const files = shellScripts();
  const shared = sharedGlobals(files);
  const missing = PROBES.filter((p) => !(p in shared));
  return { files: files.length, names: Object.keys(shared).length, missing };
}

if (process.argv.includes("--self-test")) {
  const r = selfTest();
  console.log(`файлов оболочки: ${r.files}, имён собрано: ${r.names}`);
  if (r.missing.length) {
    console.log(`СЛОМАН: не найдены ${r.missing.join(", ")}`);
    process.exit(1);
  }
  console.log("самопроверка пройдена: все контрольные имена найдены");
}
