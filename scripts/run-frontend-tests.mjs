// Discover every dependency-light frontend gate, just like CI. A failed child
// exit is a failed run; no fixed list that forgets the next regression test.
import {readdirSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const files = readdirSync(new URL('./', import.meta.url))
    .filter(name => /^test-(frontend|viewer)-.*\.mjs$/.test(name)).sort();
if (!files.length) throw new Error('No frontend behaviour gates found');
const failed = [];
for (const name of files) {
    console.log(`\n=== ${name}`);
    const result = spawnSync(process.execPath, ['scripts/' + name], {cwd: root, stdio: 'inherit'});
    if (result.error || result.status !== 0) failed.push(`${name}: ${result.error?.message || result.status}`);
}
console.log(`\n${files.length - failed.length}/${files.length} frontend gate files passed`);
if (failed.length) { console.error(failed.join('\n')); process.exitCode = 1; }
