import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = readFileSync(path.join(root, 'Расширение', 'frontend', 'cases.js'), 'utf8');
const start = src.indexOf('async function openAllCases()');
const end = src.indexOf('async function openCase(', start);
if (start < 0 || end <= start) {
    console.error('FAIL openAllCases не найдена');
    process.exit(1);
}

const btn = { disabled: false, textContent: '🎁 Открыть все (3)' };
const run = new Function('document', 'fetch', 'API_URL', 'authToken',
    'showNotification', 'loadUserData', 'loadCases', 'console',
    src.slice(start, end) + '\nreturn openAllCases;');
const openAllCases = run(
    { getElementById: () => btn },
    async () => ({ json: async () => ({ success: false, message: 'отказ' }) }),
    'http://test', 'jwt', () => {}, () => {}, async () => {}, console);

await openAllCases();
const checks = [
    ['кнопка снова доступна после отказа', btn.disabled === false],
    ['исходная подпись восстановлена после отказа', btn.textContent === '🎁 Открыть все (3)'],
];
const failed = checks.filter(([, ok]) => !ok);
for (const [name, ok] of checks) console.log((ok ? '  OK   ' : '  FAIL ') + name);
process.exit(failed.length ? 1 : 0);
