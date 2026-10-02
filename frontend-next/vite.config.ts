import { defineConfig, loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { preactAliases } from './preact.config';
import { validateSkillgameEbsOrigin } from './src/skillgames/origin';

export default defineConfig(({ mode }) => {
  const apiOrigin = validateSkillgameEbsOrigin(loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), 'VITE_').VITE_SKILLGAME_EBS_ORIGIN);
  return {
    base: './',
    resolve: { alias: preactAliases },
    define: { 'import.meta.env.VITE_SKILLGAME_EBS_ORIGIN': JSON.stringify(apiOrigin) },
    plugins: [{
      name: 'skillgame-ebs-csp',
      transformIndexHtml(html, context) {
        if (!apiOrigin || !/(?:^|[/\\])(?:index|extension|mobile)\.html$/.test(context.filename)) return html;
        const connect = "connect-src 'self' https://api.twitch.tv";
        if (!html.includes(`${connect};`)) throw new Error('Skillgame CSP connect-src template is missing');
        return html.replace(`${connect};`, `${connect} ${apiOrigin};`);
      },
    }],
    build: { manifest: true, rollupOptions: { input: ['index.html', 'extension.html', 'mobile.html', 'tournament.html'] }, minify: false, cssMinify: false, sourcemap: true, assetsInlineLimit: 0 },
  };
});
