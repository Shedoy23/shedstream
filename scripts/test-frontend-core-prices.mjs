// Core actions must use the price returned by /api/core/config everywhere the
// viewer sees or acts on it. The CDN build can outlive a backend price change.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = readFileSync(path.join(root, 'Расширение', 'frontend', 'viewer.js'), 'utf8');
const fails = [];
const check = (name, ok) => {
    console.log((ok ? '  OK   ' : '  FAIL ') + name);
    if (!ok) fails.push(name);
};

check('нет отдельной константы цены TTS', !/\bTTS_COST\b/.test(src));
check('модалка получает цену из core config',
      /const ttsCost = corePrice\(['"]tts_cost['"],\s*5000\)/.test(src));
check('гейт баланса использует серверную цену', /balance >= ttsCost/.test(src));
check('подтверждение показывает серверную цену', /\$\{ttsCost\}💎/.test(src));

console.log(fails.length ? `\nПРОВАЛЕНО: ${fails.join('; ')}` : '\nВСЁ ЗЕЛЁНОЕ');
process.exit(fails.length ? 1 : 0);
