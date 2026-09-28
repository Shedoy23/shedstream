// Цены RimWorld во фронте обязаны приходить с сервера.
//
// ЗАЧЕМ. 24.07 копии цен во фронте и на бэке разошлись: кнопка удаления черты
// рисовала 2000💎 при реальных 300. Тогда завели /api/rimworld/config как
// единственный источник — но фронт его так и не подключил, и до 05.09 все числа
// оставались зашитыми в pawn.js и в разметке. Фронт живёт на CDN Twitch и
// замерзает до следующего ревью, поэтому расхождение чинится неделями.
//
// Тест держит две вещи:
//   1. подписи кнопок перерисовываются тем, что прислал сервер;
//   2. в pawn.js не осталось числовых цен (они там и появлялись).
//
// Запуск: node scripts/test-frontend-rimworld-prices.mjs
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.join(root, 'Расширение', 'frontend');
const fails = [];
const check = (name, ok, detail = '') => {
    console.log((ok ? '  OK   ' : '  FAIL ') + name + (ok ? '' : ' — ' + detail));
    if (!ok) fails.push(name);
};

// ── 1. подписи берутся из ответа сервера ──────────────────────────────────
const src = readFileSync(path.join(frontend, 'viewer-rimworld.js'), 'utf8');
const labels = {};
const el = (id) => ({
    set innerHTML(v) { labels[id] = v; },
    set textContent(v) { labels[id] = v; },
});
const sandbox = {
    document: { getElementById: (id) => el(id) },
    window: {},
    API_URL: 'http://test',
    fetch: async () => ({ ok: false }),
    loadMyPawn: () => {},
    console,
};
// Берём только блок цен: остальной файл тянет глобалы всей панели.
const from = src.indexOf('let rimworldPrices = null;');
const to = src.indexOf('// ===== RIMWORLD ONLINE STATUS =====');
if (from < 0 || to < 0 || to < from) {
    check('блок цен найден в viewer-rimworld.js', false, 'разметка блока изменилась');
} else {
    const body = src.slice(from, to);
    const run = new Function(...Object.keys(sandbox),
        body + '\nreturn { loadRimworldPrices, rimworldPrice, applyRimworldPriceLabels, setPrices: (p) => { rimworldPrices = p; } };');
    const api = run(...Object.values(sandbox));

    api.applyRimworldPriceLabels();
    check('без ответа сервера рисуются запасные числа',
          /150/.test(labels['heal-pawn-btn']) && /500/.test(labels['btn-resurrect']),
          JSON.stringify(labels));

    api.setPrices({ heal_cost: 999, resurrect_cost: 777, spawn_cost: 111 });
    api.applyRimworldPriceLabels();
    check('цена лечения приходит с сервера', /999/.test(labels['heal-pawn-btn']), labels['heal-pawn-btn']);
    check('цена воскрешения приходит с сервера', /777/.test(labels['btn-resurrect']), labels['btn-resurrect']);
    check('цена создания пешки приходит с сервера', /111/.test(labels['create-pawn-btn']), labels['create-pawn-btn']);
    check('битую цену подменяет запасная',
          api.rimworldPrice('heal_cost', 150) === 999 && api.rimworldPrice('нет_такой', 42) === 42);
    api.setPrices({ null_cost: null, empty_cost: '', free_cost: 0 });
    check('null и пустая цена используют fallback, явный ноль сохраняется',
          api.rimworldPrice('null_cost', 42) === 42 &&
          api.rimworldPrice('empty_cost', 42) === 42 &&
          api.rimworldPrice('free_cost', 42) === 0);
}

// ── 2. подтверждения и клиентские гейты читают тот же конфиг ──────────────
check('удаление черты использует серверную цену',
      /rimworldPrice\(['"]trait_remove_cost['"],\s*300\)/.test(src) &&
      !/за <b[^>]*>300💎<\/b>/.test(src));
check('удаление гена использует серверную цену',
      /rimworldPrice\(['"]gene_remove_cost['"],\s*3000\)/.test(src) &&
      !/за <b[^>]*>3000💎<\/b>/.test(src));
check('гейт создания пешки использует серверную цену',
      /const spawnCost = rimworldPrice\(['"]spawn_cost['"],\s*200\)/.test(src) &&
      /balance < spawnCost/.test(src));
check('подтверждение создания пешки использует серверную цену',
      /\$\{spawnCost\}💎/.test(src));

// Поздний ответ конфига обязан перерисовать уже показанную пешку.
if (from >= 0 && to >= 0 && to > from) {
    let pawnRefreshes = 0;
    const lateSandbox = {
        ...sandbox,
        fetch: async () => ({ ok: true, json: async () => ({
            heal_cost: 999, resurrect_cost: 777, spawn_cost: 111,
            trait_remove_cost: 50, gene_remove_cost: 9000,
        }) }),
        loadMyPawn: () => { pawnRefreshes += 1; },
    };
    const body = src.slice(from, to);
    const run = new Function(...Object.keys(lateSandbox),
        body + '\nreturn { loadRimworldPrices };');
    const api = run(...Object.values(lateSandbox));
    await api.loadRimworldPrices();
    check('поздний конфиг перерисовывает пешку', pawnRefreshes === 1,
          `loadMyPawn вызван ${pawnRefreshes} раз`);
}

// ── 3. в pawn.js не осталось зашитых цен ──────────────────────────────────
const pawn = readFileSync(path.join(frontend, 'pawn.js'), 'utf8');
const hardcoded = [...pawn.matchAll(/(\d+)\s*💎/g)].map((m) => m[0]);
check('в pawn.js нет числовых цен', hardcoded.length === 0, hardcoded.join(', '));

// ── 4. у кнопок ShedColony нет цен числом ─────────────────────────
// Линтер цен ищет число рядом со значком, а тут формат другой — «Покормить · 75».
// Из-за этого 17 кнопок считались перенесёнными, хотя показывали копию цены
// (нашёл внешний обзор 05.09).
const colony = readFileSync(path.join(frontend, 'viewer-shedcolony.js'), 'utf8');
const colonyHardcoded = [...colony.matchAll(/data-sc="([a-z_]+)"[^>]*>[^<]*?[·—-]\s*(\d{2,})/g)]
    .map((m) => `${m[1]}=${m[2]}`);
check('у кнопок ShedColony цена не вписана числом', colonyHardcoded.length === 0,
      colonyHardcoded.join(', '));

console.log(fails.length ? `\nПРОВАЛЕНО: ${fails.join('; ')}` : '\nВСЁ ЗЕЛЁНОЕ');
process.exit(fails.length ? 1 : 0);
