import { readFileSync, readdirSync, existsSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolveConfig } from 'vite';

const config = await resolveConfig({ root: fileURLToPath(new URL('../', import.meta.url)) }, 'build');
// Resolve through the same build validator, including .env.production and overrides.
const apiOrigin = JSON.parse(config.define['import.meta.env.VITE_SKILLGAME_EBS_ORIGIN']);
const pages = new Map();
for (const entry of ['index', 'extension', 'mobile', 'tournament']) {
const html = readFileSync(new URL(`../dist/${entry}.html`, import.meta.url), 'utf8');
pages.set(entry, html);
const expectedSources = ["'self'", 'https://api.twitch.tv', ...(entry !== 'tournament' && apiOrigin ? [apiOrigin] : [])];
assert.deepEqual(html.match(/connect-src ([^;]+)/)?.[1].split(/\s+/), expectedSources, `${entry}: CSP must permit only the expected API origins`);
const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
assert.match(scripts[0][1], /src="https:\/\/extension-files\.twitch\.tv\/helper\/v1\/twitch-ext\.min\.js"/, 'Twitch helper must be FIRST');
assert(scripts.every(script => !script[2].trim()), 'No inline JavaScript');
assert(scripts.slice(1).every(script => /src="\.\//.test(script[1])), 'All application scripts must be relative local assets');
assert(!/viewer(?:-bannerlord|-actions)?\.js/.test(html), 'Legacy DOM/action owners must not be loaded');
assert(!/unsafe-eval|unsafe-inline/.test(html), 'Preview CSP must not require unsafe execution');
}
assert.equal(pages.get('index'), pages.get('extension'), 'Index and desktop must mount the same application');
assert.equal(pages.get('extension'), pages.get('mobile'), 'Desktop and mobile must mount the same application');
const assets = readdirSync(new URL('../dist/assets/', import.meta.url));
const javascript = assets.filter(name => name.endsWith('.js')).map(name => readFileSync(new URL(`../dist/assets/${name}`, import.meta.url), 'utf8')).join('\n');
assert(javascript.split('\n').length > 1000, 'React/application bundle must remain readable, not minified');
assert(!/https:\/\/(?:unpkg|esm\.sh|cdn\.jsdelivr)/.test(javascript), 'No runtime CDN dependency');
if (!apiOrigin) assert(!javascript.includes('shedoy23.ru'), 'Default local build must not include a production URL');
assert(!javascript.includes('/api/bannerlord/action'), 'HTTP mutation transport must not enter preview bundle');
assert(assets.some(name => name.endsWith('.css')), 'Styles must be external');
assert(javascript.includes('/api/skillgames/'), 'New entrypoints must include the real skillgame HTTP adapter');
// Inspect the tournament's complete emitted import graph, not the combined bundle.
const manifest = JSON.parse(readFileSync(new URL('../dist/.vite/manifest.json', import.meta.url), 'utf8'));
const visited = new Set();
function checkTournament(key) {
  if (visited.has(key)) return;
  visited.add(key);
  const chunk = manifest[key];
  assert(chunk, `Missing tournament dependency: ${key}`);
  const source = readFileSync(new URL(`../dist/${chunk.file}`, import.meta.url), 'utf8');
  assert(!source.includes('/api/'), 'Tournament preview must not load an HTTP API adapter');
  for (const dependency of [...(chunk.imports || []), ...(chunk.dynamicImports || [])]) checkTournament(dependency);
}
checkTournament('tournament.html');
console.log('PASS: four entrypoints; identical skillgame pages; validated EBS origin/CSP; isolated tournament preview; helper first; readable local assets; no legacy owner');

const noticesUrl = new URL('../dist/THIRD_PARTY_NOTICES.txt', import.meta.url);
assert(existsSync(noticesUrl), 'Bundled React runtime requires third-party license notices');
const notices = readFileSync(noticesUrl, 'utf8');
for (const name of ['react', 'react-dom', 'scheduler']) {
  const packageInfo = JSON.parse(readFileSync(new URL(`../node_modules/${name}/package.json`, import.meta.url), 'utf8'));
  const license = readFileSync(new URL(`../node_modules/${name}/LICENSE`, import.meta.url), 'utf8').trim();
  assert(notices.includes(`${name}@${packageInfo.version}`) && notices.includes(license), `Missing or stale license notice: ${name}`);
}
console.log('PASS: bundled runtime licenses and pinned versions included');
