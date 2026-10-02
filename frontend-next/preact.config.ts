import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { normalizePath, type Plugin } from 'vite';
import tsconfig from './tsconfig.json' with { type: 'json' };

// One alias contract for the typechecker, Vite and Vitest. Exact matches avoid
// accidentally resolving react/jsx-runtime as preact/compat/jsx-runtime.
export const preactAliases = Object.entries(tsconfig.compilerOptions.paths).map(([name, [target]]) => ({
  find: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`),
  replacement: target.replace('./node_modules/', ''),
}));

// Preact ships minified distributions plus original source maps. Compose those
// maps without changing the distributed code, so Twitch reviewers get the
// original readable runtime sources as well as our own application sources.
export function preactSourceMaps(): Plugin {
  return {
    name: 'preact-original-source-maps',
    enforce: 'pre',
    // A load map preserves its original filename even when it has one source;
    // Rolldown normalizes single-source transform maps back to the module ID.
    load(id) {
      if (!/\/node_modules\/preact\/(?:dist|(?:compat|hooks|jsx-runtime)\/dist)\/[^/]+\.mjs$/.test(normalizePath(id))) return;
      const code = readFileSync(id, 'utf8');
      const map = JSON.parse(readFileSync(`${id}.map`, 'utf8'));
      map.sources = map.sources.map((source: string) => normalizePath(resolve(dirname(id), map.sourceRoot || '', source)));
      delete map.sourceRoot;
      return { code, map };
    },
  };
}
