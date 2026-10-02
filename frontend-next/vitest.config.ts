import { defineConfig } from 'vitest/config';
import { preactAliases } from './preact.config';
export default defineConfig({ resolve: { alias: preactAliases }, test: { environment: 'jsdom', restoreMocks: true } });
