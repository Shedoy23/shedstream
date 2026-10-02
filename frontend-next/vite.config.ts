import { defineConfig } from 'vite';
export default defineConfig({
  base: './',
  build: { rollupOptions: { input: ['index.html', 'extension.html', 'mobile.html', 'tournament.html'] }, minify: false, cssMinify: false, sourcemap: true, assetsInlineLimit: 0 },
});
