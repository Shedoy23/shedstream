// Reproducible raw/gzip-9 sizes, including the complete initial import closure.
// Usage: node scripts/measure-build.mjs [dist-directory] [page.html]
// Source maps are listed for the review package, but are not initial page traffic.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = resolve(process.argv[2] || fileURLToPath(new URL('../dist', import.meta.url)));
const page = process.argv[3] || 'mobile.html';
const manifest = JSON.parse(readFileSync(resolve(root, '.vite/manifest.json'), 'utf8'));
const size = file => {
  const path = resolve(root, file);
  const gzip = spawnSync('gzip', ['-9', '-c', path]);
  if (gzip.status !== 0) throw new Error(`gzip failed for ${file}: ${gzip.stderr}`);
  return { raw: statSync(path).size, gzip9: gzip.stdout.length };
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
  const file = resolve(dirname(resolve(root, page)), match[1]).slice(root.length + 1);
  initial.add(file);
  for (const [key, chunk] of Object.entries(manifest)) if (chunk.file === file) walk(key);
}
const sum = entries => ({
  raw: entries.reduce((n, entry) => n + entry.raw, 0),
  gzip9: entries.reduce((n, entry) => n + entry.gzip9, 0),
});
console.log(JSON.stringify({
  method: 'gzip -9 -c <file>; decimal bytes; each file separately',
  files,
  assets_total: sum(Object.values(files)),
  runtime_assets_total: sum(Object.entries(files).filter(([file]) => !file.endsWith('.map')).map(([, value]) => value)),
  page,
  initial_files: [...initial].sort(),
  initial_total: sum([...initial].map(size)),
  excludes: ['Twitch-hosted Helper script (external and unchanged)', 'HTTP API responses', 'source maps from initial traffic'],
}, null, 2));
