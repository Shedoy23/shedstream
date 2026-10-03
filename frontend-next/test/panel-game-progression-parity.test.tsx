import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/preact';
import { TwitchAuthStore } from '../src/auth';
import { PanelController } from '../src/panel/controller';
import { HttpPanelTransport } from '../src/panel/transport';
import { HeroDevelopmentView } from '../src/panel/HeroDevelopmentView';
import { createLegacyHarness, gameResponses as g, type LegacyFixtures, type LegacyRequest, type LegacyJson } from './panel-legacy-harness';
const close: (() => void)[] = [];
const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };
beforeEach(() => { vi.useFakeTimers({toFake:['setTimeout','clearTimeout','setInterval','clearInterval','Date']}); vi.setSystemTime(Date.UTC(2026, 9, 2, 12)); });
afterEach(() => { cleanup(); close.splice(0).forEach(fn => fn()); vi.useRealTimers(); });
function normalized(rows: LegacyRequest[]) {
  return rows.map(row => {
    const body = structuredClone(row.body) as {data?: {client_action_id?: string}} | null;
    const id = body?.data?.client_action_id;
    if (id) body!.data!.client_action_id = '<generated-id>';
    return {...row, body, rawBody: id ? row.rawBody!.replace(JSON.stringify(id), JSON.stringify('<generated-id>')) : row.rawBody};
  });
}
async function pair(overrides: Partial<LegacyFixtures> = {}) {
  const old = createLegacyHarness(overrides); close.push(old.dispose); await old.bootHero();
  const trace: LegacyRequest[] = [], failures: string[] = [], counts: Record<string, number> = {};
  const routes: Record<string, keyof LegacyFixtures> = {
    '/api/bannerlord/config':'config', '/api/bannerlord/my-hero':'hero', '/api/bannerlord/classes':'classes',
    '/api/bannerlord/build':'build', '/api/bannerlord/my-buffs':'buffs', '/api/bannerlord/content-catalogs':'catalogs',
    '/api/bannerlord/progression':'progression', '/api/bannerlord/action':'action', '/api/viewer/stats/alice':'stats',
    '/api/user/level/alice':'level', '/api/duel/list':'duels',
  };
  const fetcher: typeof fetch = async (url, init = {}) => {
    const u = new URL(String(url), 'https://fixture.invalid'), headers = new Headers(init.headers), rawBody = init.body == null ? null : String(init.body);
    const row: LegacyRequest = {method:init.method || 'GET', path:u.pathname, query:u.search, body:rawBody ? JSON.parse(rawBody) : null,
      rawBody, token:headers.get('X-Twitch-JWT') || '', contentType:headers.get('Content-Type') || '', cache:init.cache || null};
    trace.push(row);
    const key = routes[row.path];
    if (!key || row.query) { failures.push(row.path + row.query); throw Error('UNMATCHED ' + row.path); }
    counts[key] = (counts[key] || 0) + 1;
    const fixture = old.fixtures[key], value = typeof fixture === 'function' ? await fixture(row, counts[key]) : fixture;
    return new Response(JSON.stringify(value));
  };
  const auth = new TwitchAuthStore(); auth.authorize({token:'alice-token',userId:'opaque-alice',channelId:'channel-a'});
  const identity = {snapshot:()=>({status:'ready' as const,login:'alice',message:'',canShare:false,shareRequested:false}),subscribe:()=>()=>{}};
  const controller = new PanelController(new HttpPanelTransport('', auth, fetcher), auth, identity);
  close.push(() => controller.stop()); await controller.start(); await flush();
  const ui = render(<HeroDevelopmentView controller={controller}/>);
  const check = () => { old.assertHealthy(); expect(failures).toEqual([]); expect(normalized(trace)).toEqual(normalized(old.trace)); };
  return {old, trace, controller, ui, check,
    async newClick(selector: string) { await act(async () => { (ui.container.querySelector(selector) as HTMLElement).click(); await flush(); }); },
    async confirm() { await act(async () => { ui.getByRole('button',{name:'Подтвердить'}).click(); await flush(); }); },
    async finish() { await old.advance(3510); await act(async () => { await vi.advanceTimersByTimeAsync(3510); await flush(); }); check(); },
  };
}
it('game progression startup preserves every metadata request including no-store', async () => {
  const p = await pair(); p.check();
  expect(p.trace.filter(r => r.path.endsWith('/progression'))).toMatchObject([{cache:'no-store',token:'alice-token'}]);
});
it('progression presents vanilla skills under their attribute without changing wire data',async()=>{const p=await pair();p.check();expect(p.ui.container.querySelector('[data-skill="Engineering"]')?.closest('[data-attribute-group]')?.getAttribute('data-attribute-group')).toBe('intelligence');});
it('progression groups custom skills by game metadata and retains ungrouped mod skills',async()=>{const progression={...g.progression_mod,progression:{...g.progression_mod.progression,skills:[{...g.progression_mod.progression.skills[0],attribute:'Mod.Attribute'},{...g.progression_mod.progression.skills[0],id:'Other.Skill'}]}};const p=await pair({progression});p.check();expect(p.ui.container.querySelector('[data-skill="Mod.Skill"]')?.closest('[data-attribute-group]')?.getAttribute('data-attribute-group')).toBe('mod.attribute');expect(p.ui.container.querySelector('[data-skill="Other.Skill"]')?.closest('[data-attribute-group]')?.getAttribute('data-attribute-group')).toBe('other');});
for (const kind of ['focus','attribute'] as const) it(`game ${kind} uses exact quote/context bytes and every success continuation`, async () => {
  const id = kind === 'focus' ? g.progression.progression.skills[0].id : g.progression.progression.attributes[0].id;
  const selector = kind === 'focus' ? `[data-skill="${id}"]` : `[data-attr="${id}"]`;
  const p = await pair({action:kind === 'focus' ? g.focus_success.response : g.attribute_success.response}); p.check();
  await p.old.click(selector); await p.newClick(selector);
  expect(p.trace.filter(r => r.method === 'POST')).toHaveLength(0);
  expect(p.ui.getByRole('dialog').textContent).toContain('Подтвердить');
  await p.confirm(); await p.finish();
  expect(p.trace.find(r => r.method === 'POST')?.body).toMatchObject(kind === 'focus' ? g.focus_success.request : g.attribute_success.request);
});
it('game metadata keeps custom IDs, zero gold and values above former vanilla caps', async () => {
  const p = await pair({progression:g.progression_mod, catalogs:{...g.catalogs, skills:{available:true,entries:[{id:'Mod.Skill',name:'Навык мода'}]}, attributes:{available:true,entries:[{id:'Mod.Attribute',name:'Атрибут мода'}]}}});
  p.check(); expect(p.ui.container.textContent).toContain('Навык мода'); expect(p.ui.container.textContent).toContain('Атрибут мода');
  expect((p.ui.container.querySelector('[data-skill="Mod.Skill"]') as HTMLButtonElement).disabled).toBe(false);
  expect((p.ui.container.querySelector('[data-attr="Mod.Attribute"]') as HTMLButtonElement).disabled).toBe(false);
  expect(p.ui.container.querySelector('[data-skill="OneHanded"]')).toBeNull();
});
for (const [name,snapshot] of Object.entries({missing:g.progression_missing,pending:g.progression_pending})) it(`${name} game quotes never use the old config price fallback`, async () => {
  const p = await pair({progression:snapshot}); p.check();
  const buttons = [...p.ui.container.querySelectorAll<HTMLButtonElement>('[data-skill],[data-attr]')];
  expect(buttons.length).toBeGreaterThan(0); expect(buttons.every(b => b.disabled)).toBe(true);
  await act(async () => { buttons.forEach(b => b.click()); await flush(); }); expect(p.trace.every(r => r.method === 'GET')).toBe(true);
});
it('a changed session while confirming cannot submit the old progression quote', async () => {
  const p = await pair(); await p.newClick('[data-skill="OneHanded"]');
  p.old.fixtures.progression = {...g.progression,context:{...g.progression.context,equipment_session_id:'replaced-session'}} as LegacyJson;
  await act(async () => { await p.controller.refreshHero(); await flush(); });
  const button = p.ui.queryByRole('button',{name:'Подтвердить'}); if (button) await act(async () => {button.click(); await flush();});
  expect(p.trace.filter(r => r.method === 'POST')).toHaveLength(0);
});
