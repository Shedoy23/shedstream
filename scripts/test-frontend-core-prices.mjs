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

const configFrom = src.indexOf('let coreConfig =');
const configTo = src.indexOf('async function loadCoreConfig(');
if (configFrom < 0 || configTo <= configFrom) {
    check('блок core config найден', false);
} else {
    const body = src.slice(configFrom, configTo);
    const run = new Function(body +
        '\nreturn { value: corePrice, setConfig: (c) => { coreConfig = c; } };');
    const api = run();
    api.setConfig({ tts_cost: null, tts_max_len: '', free_cost: 0 });
    check('null и пустая строка не превращаются в ноль',
          api.value('tts_cost', 5000) === 5000 && api.value('tts_max_len', 200) === 200);
    check('явный серверный ноль сохраняется', api.value('free_cost', 42) === 0);
}

check('нет отдельной константы цены TTS', !/\bTTS_COST\b/.test(src));
check('модалка получает цену из core config',
      /const ttsCost = corePrice\(['"]tts_cost['"],\s*5000\)/.test(src));
check('гейт баланса использует серверную цену', /balance >= ttsCost/.test(src));
check('подтверждение показывает серверную цену', /\$\{ttsCost\}💎/.test(src));
check('лимит TTS приходит из core config',
      /const ttsMaxLen = corePrice\(['"]tts_max_len['"],\s*200\)/.test(src));
check('нет отдельной константы лимита TTS', !/\bTTS_MAX_LEN\b/.test(src));

console.log(fails.length ? `\nПРОВАЛЕНО: ${fails.join('; ')}` : '\nВСЁ ЗЕЛЁНОЕ');
process.exit(fails.length ? 1 : 0);
