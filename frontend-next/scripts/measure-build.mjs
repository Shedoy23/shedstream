// Reproducible raw/gzip-9 sizes, including the complete initial import closure.
// Usage: node scripts/measure-build.mjs [dist-directory] [page.html] [startup dynamic manifest keys...]
// Source maps are listed for the review package, but are not initial page traffic.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const root = resolve(process.argv[2] || fileURLToPath(new URL('../dist', import.meta.url)));
const page = process.argv[3] || 'panel-mobile.html';
const manifest = JSON.parse(readFileSync(resolve(root, '.vite/manifest.json'), 'utf8'));
const size = file => {
  const path = resolve(root, file);
  return { raw: statSync(path).size, gzip9: gzipSync(readFileSync(path), { level: 9 }).length };
};
const files = Object.fromEntries(readdirSync(resolve(root, 'assets')).sort().map(name => [`assets/${name}`, size(`assets/${name}`)]));
const visited = new Set();
const initial = new Set([page]);
function walk(key) {
  if (visited.has(key)) return;
  visited.add(key);
  const chunk = manifest[key];
  if (!chunk) throw new Error(`Missing import ${key}`);
  initial.add(chunk.file);
  for (const css of chunk.css || []) initial.add(css);
  for (const imported of chunk.imports || []) walk(imported);
}
const html = readFileSync(resolve(root, page), 'utf8');
for (const match of html.matchAll(/(?:src|href)="\.\/([^"?#]+)"/g)) {
  const file = relative(root, resolve(dirname(resolve(root, page)), match[1])).split(sep).join('/');
  initial.add(file);
  for (const [key, chunk] of Object.entries(manifest)) if (chunk.file === file) walk(key);
}
const sum = entries => ({
  raw: entries.reduce((n, entry) => n + entry.raw, 0),
  gzip9: entries.reduce((n, entry) => n + entry.gzip9, 0),
});
const staticInitial = [...initial];
const startupDynamicKeys = process.argv.slice(4);
for (const key of startupDynamicKeys) walk(key);
console.log(JSON.stringify({
  method: 'Node zlib gzip level 9; decimal bytes; each file separately; portable manifest paths',
  files,
  assets_total: sum(Object.values(files)),
  runtime_assets_total: sum(Object.entries(files).filter(([file]) => !file.endsWith('.map')).map(([, value]) => value)),
  page,
  startup_dynamic_keys: startupDynamicKeys,
  static_import_total: sum(staticInitial.map(size)),
  initial_files: [...initial].sort(),
  initial_total: sum([...initial].map(size)),
  lazy_chunks: Object.entries(manifest).filter(([, chunk]) => chunk.isDynamicEntry).map(([key, chunk]) => ({ key, file: chunk.file, ...size(chunk.file), css: (chunk.css || []).map(file => ({ file, ...size(file) })) })),
  excludes: ['Twitch-hosted Helper script (external and unchanged)', 'HTTP API responses', 'source maps from initial traffic'],
}, null, 2));
