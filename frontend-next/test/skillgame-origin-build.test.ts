// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import { build, type Rollup } from 'vite';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
afterEach(() => vi.unstubAllEnvs());
async function buildAt(origin: string) {
  vi.stubEnv('VITE_SKILLGAME_EBS_ORIGIN', origin);
  const result = await build({ root, logLevel: 'silent', build: { write: false, sourcemap: false } });
  return (Array.isArray(result) ? result[0] : result) as Rollup.RollupOutput;
}
function html(output: Rollup.RollupOutput, entry: string) {
  const asset = output.output.find(item => item.type === 'asset' && item.fileName === `${entry}.html`);
  if (!asset || asset.type !== 'asset') throw new Error(`Missing ${entry}.html`);
  return String(asset.source);
}
function connectSources(page: string) { return page.match(/connect-src ([^;]+)/)?.[1].split(/\s+/); }

describe('skillgame build-time EBS boundary', () => {
  it('adds the explicit HTTPS origin to all three identical skillgame CSPs only', async () => {
    const output = await buildAt('https://EBS.EXAMPLE.INVALID:8443');
    const index = html(output, 'index');
    expect(html(output, 'extension')).toBe(index);
    expect(html(output, 'mobile')).toBe(index);
    expect(connectSources(index)).toEqual(["'self'", 'https://api.twitch.tv', 'https://ebs.example.invalid:8443']);
    expect(connectSources(html(output, 'tournament'))).toEqual(["'self'", 'https://api.twitch.tv']);
    for (const entry of ['index', 'extension', 'mobile', 'tournament']) expect(html(output, entry)).not.toMatch(/unsafe-inline|unsafe-eval/);
  }, 30000);

  it('keeps the default build same-origin without a hard-coded EBS destination', async () => {
    const output = await buildAt('');
    expect(connectSources(html(output, 'index'))).toEqual(["'self'", 'https://api.twitch.tv']);
    expect(html(output, 'index')).toBe(html(output, 'extension'));
    expect(html(output, 'index')).toBe(html(output, 'mobile'));
    const javascript = output.output.filter(item => item.type === 'chunk').map(item => item.code).join('\n');
    expect(javascript).not.toContain('shedoy23.ru');
    expect(javascript).not.toContain('ebs.example.invalid');
  }, 30000);

  it.each(['http://ebs.example.invalid', 'https://u:p@ebs.example.invalid', 'https://ebs.example.invalid/api', 'https://ebs.example.invalid?x=1', 'https://ebs.example.invalid#x'])(
    'rejects invalid origins before creating a build: %s', async value => {
      await expect(buildAt(value)).rejects.toThrow(/VITE_SKILLGAME_EBS_ORIGIN/);
    }, 30000,
  );
});
