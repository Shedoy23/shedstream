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

const accessorFrom = src.indexOf('function _bnrPrice(actionType, fallback)');
const accessorTo = src.indexOf('function _fmtK(', accessorFrom);
if (accessorFrom < 0 || accessorTo <= accessorFrom) {
    checks.push(['блок серверных цен Bannerlord найден', false]);
} else {
    const accessorBody = src.slice(accessorFrom, accessorTo);
    const accessors = new Function('_bnrCfg', accessorBody +
        '\nreturn { price: _bnrPrice, gold: _bnrGold };')({
            action_prices: { missing: null, empty: '', free: 0 },
            hero_gold_costs: { missing: null, empty: '', free: 0 },
        });
    checks.push(['null action price использует fallback', accessors.price('missing', 42) === 42]);
    checks.push(['пустая action price использует fallback', accessors.price('empty', 42) === 42]);
    checks.push(['явная нулевая action price сохраняется', accessors.price('free', 42) === 0]);
    checks.push(['null hero gold использует fallback', accessors.gold('missing', 42) === 42]);
    checks.push(['явная нулевая hero gold сохраняется', accessors.gold('free', 42) === 0]);
}
const failed = checks.filter(([, ok]) => !ok);
for (const [name, ok] of checks) console.log((ok ? '  OK   ' : '  FAIL ') + name);
if (failed.length) console.error(`\nПРОВАЛЕНО: ${failed.map(([name]) => name).join('; ')}`);
else console.log('\nВСЁ ЗЕЛЁНОЕ');
process.exit(failed.length ? 1 : 0);
