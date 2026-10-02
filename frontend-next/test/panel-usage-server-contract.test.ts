import { execFileSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import { PanelUsage } from '../src/panel/usage';
import fixtures from './panel-fixtures/real-responses.json';

it('the unchanged server validator accepts an actual new collector batch, rejects extra personal data', async () => {
  const bodies: string[] = [], auth = new TwitchAuthStore(); auth.authorize({ token: 'private-auth-header', channelId: 'channel', userId: 'viewer' });
  const identity = { snapshot: () => ({ status: 'ready' as const, login: 'alice', message: '', canShare: false, shareRequested: false }), subscribe: () => () => {} };
  const fetcher: typeof fetch = async (_, init) => { bodies.push(String(init?.body)); return new Response(JSON.stringify(fixtures.responses.usage_ok)); };
  const usage = new PanelUsage({ auth, identity, baseUrl: '', surface: 'mobile', fetcher }); usage.start();
  try {
    usage.trackPanel('core'); usage.trackPanel('bannerlord'); usage.trackSection('bannerlord:tab.inventory'); usage.trackSection('bannerlord:tab.hero');
    for (const feature of ['hero.add_attribute', 'hero.add_focus', 'hero.set_class', 'hero.set_specialization', 'hero.claim_starter', 'hero.buy_equipment', 'hero.equip_owned', 'hero.unequip_owned', 'hero.discard_owned']) usage.trackAction('bannerlord:' + feature);
    await usage.flush(); expect(bodies).toHaveLength(1);
    const backend = resolve(dirname(fileURLToPath(import.meta.url)), '../../Расширение/backend');
    // Python + PyYAML are existing backend test requirements. No backend source
    // or DB is changed; this executes the current canonical manifest validator.
    const result = execFileSync(process.env.PANEL_BACKEND_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-c', [
      'import copy,json,sys', 'from ui_usage import validate_batch', 'body=json.load(sys.stdin)', 'assert validate_batch(body)==body',
      'for key in ("token","login","coordinates","payload"):', '    bad=copy.deepcopy(body);bad["events"][0][key]="must not be accepted"',
      '    try: validate_batch(bad)', '    except ValueError: pass', '    else: raise AssertionError(key)',
      'print("CURRENT_SERVER_ACCEPTS_BATCH_REJECTS_PERSONAL_FIELDS")',
    ].join('\n')], { cwd: backend, input: bodies[0], encoding: 'utf8' });
    expect(result.trim()).toBe('CURRENT_SERVER_ACCEPTS_BATCH_REJECTS_PERSONAL_FIELDS');
  } finally { usage.stop(); }
});
