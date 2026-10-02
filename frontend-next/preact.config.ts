import { compilerOptions } from './tsconfig.json';

// One alias contract for the typechecker, Vite and Vitest. Exact matches avoid
// accidentally resolving react/jsx-runtime as preact/compat/jsx-runtime.
export const preactAliases = Object.entries(compilerOptions.paths).map(([name, [target]]) => ({
  find: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`),
  replacement: target.replace('./node_modules/', ''),
}));
