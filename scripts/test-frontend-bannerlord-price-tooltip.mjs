// A formatter and the server-config accessor once shared the `_bnrPrice` name.
// JavaScript silently kept the latter, so paid workshop/caravan tooltips said 0.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = readFileSync(
    path.join(root, 'Расширение', 'frontend', 'viewer-bannerlord.js'), 'utf8');
const from = src.indexOf('function _bnrFmtN(');
const to = src.indexOf('// Header strip — current balances.');

if (from < 0 || to < 0 || to <= from) {
    console.error('FAIL блок форматирования цены Bannerlord не найден');
    process.exit(1);
}

const body = src.slice(from, to);
const run = new Function('_cachedUserPoints', '_bannerlordLastHero',
    body + '\nreturn { tooltip: _bnrAffordTooltip, text: _bnrPriceText };');
const api = run(10_000, { hero: { gold: 100_000 } });
const tooltip = api.tooltip(2_500, 0);

const checks = [
    ['форматтер сохраняет цену в крустиках', api.text(2_500, 0) === '💎 2.5K'],
    ['подсказка показывает цену действия', tooltip.includes('💎 2.5K')],
    ['подсказка не называет платное действие бесплатным', !tooltip.includes('Стоимость: 0')],
];
const failed = checks.filter(([, ok]) => !ok);
for (const [name, ok] of checks) console.log((ok ? '  OK   ' : '  FAIL ') + name);
if (failed.length) console.error(`\nПРОВАЛЕНО: ${failed.map(([name]) => name).join('; ')}`);
else console.log('\nВСЁ ЗЕЛЁНОЕ');
process.exit(failed.length ? 1 : 0);
