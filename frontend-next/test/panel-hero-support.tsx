import { afterEach, beforeEach, expect, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/preact';
import { TwitchAuthStore } from '../src/auth';
import { PanelController } from '../src/panel/controller';
import { HttpPanelTransport } from '../src/panel/transport';
import { HeroDevelopmentView } from '../src/panel/HeroDevelopmentView';
import {PropertiesView} from '../src/panel/PropertiesView';
import {HeroProfileView} from '../src/panel/HeroProfileView';
import {ChildrenView} from '../src/panel/ChildrenView';
import {VassalsView} from '../src/panel/VassalsView';
import {RansomView} from '../src/panel/RansomView';
import {ClanUpgradesView} from '../src/panel/ClanUpgradesView';
import {HeroAchievementsView} from '../src/panel/HeroAchievementsView';
import {ShopView} from '../src/panel/ShopView';
import {LegacyGearView} from '../src/panel/LegacyGearView';
import {LegacyInventoryView} from '../src/panel/LegacyInventoryView';
import {HeroSummaryView} from '../src/panel/HeroSummaryView';
import {useSyncExternalStore} from 'react';
import { createLegacyHarness, type LegacyFixture, type LegacyFixtures, type LegacyRequest } from './panel-legacy-harness';
const close: (() => void)[] = [];
const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };
beforeEach(() => { vi.useFakeTimers({toFake:['setTimeout','clearTimeout','setInterval','clearInterval','Date']}); vi.setSystemTime(Date.UTC(2026, 9, 2, 12)); });
afterEach(() => { cleanup(); close.splice(0).forEach(fn => fn()); vi.useRealTimers(); });
export function normalized(rows: LegacyRequest[]) {
  return rows.map(row => {
    const body = structuredClone(row.body) as {data?: {client_action_id?: string}} | null;
    const id = body?.data?.client_action_id;
    if (id) body!.data!.client_action_id = '<generated-id>';
    return {...row, body, rawBody: id ? row.rawBody!.replace(JSON.stringify(id), JSON.stringify('<generated-id>')) : row.rawBody};
  });
}
function PropertyScope({controller,profile,children,civic,rewards}:{controller:PanelController;profile?:boolean;children?:boolean;civic?:boolean;rewards?:boolean}){const s=useSyncExternalStore(controller.subscribe,controller.snapshot);return <>{s.message&&<p role="status">{s.message}</p>}{profile&&<HeroProfileView controller={controller} mode="family"/>}{children&&<ChildrenView controller={controller} active/>}{civic&&<><VassalsView controller={controller} active/><RansomView controller={controller} active/></>}{rewards&&<><ClanUpgradesView controller={controller} active/><HeroAchievementsView controller={controller} active/></>}<PropertiesView controller={controller} active/></>;}
function CommerceScope({controller}:{controller:PanelController}){const s=useSyncExternalStore(controller.subscribe,controller.snapshot);return <>{s.message&&<p role="status">{s.message}</p>}<HeroSummaryView controller={controller}/><ShopView controller={controller}/><LegacyGearView controller={controller}/><LegacyInventoryView controller={controller} active/></>;}
export async function heroPair(overrides: Partial<LegacyFixtures> = {}, options:{commerceHost?:boolean;rewardsHost?:boolean;civicHost?:boolean;childrenHost?:boolean;genderHost?:boolean;profileHost?:boolean;propertyHost?:boolean;dailyHost?:boolean;extraRoutes?:Record<string,LegacyFixture>}={}) {
  const old = createLegacyHarness(overrides,options); close.push(old.dispose); await old.bootHero();
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
    const extra=options.extraRoutes?.[row.method+' '+row.path+row.query];
    if (extra===undefined&&(!key || row.query)) { failures.push(row.path + row.query); throw Error('UNMATCHED ' + row.path); }
    const countKey=row.method+' '+row.path+row.query;counts[countKey] = (counts[countKey] || 0) + 1;
    const fixture = extra===undefined?old.fixtures[key]:extra, value = typeof fixture === 'function' ? await fixture(row, counts[countKey]) : fixture;
    return new Response(JSON.stringify(value));
  };
  const auth = new TwitchAuthStore(); auth.authorize({token:'alice-token',userId:'opaque-alice',channelId:'channel-a'});
  const identity = {snapshot:()=>({status:'ready' as const,login:'alice',message:'',canShare:false,shareRequested:false}),subscribe:()=>()=>{}};
  const controller = new PanelController(new HttpPanelTransport('', auth, fetcher), auth, identity);
  if(options.commerceHost)controller.enableCommerce();
  close.push(() => controller.stop()); await controller.start(); await flush();
  const ui = render(options.commerceHost?<CommerceScope controller={controller}/>:options.propertyHost?<PropertyScope controller={controller} profile={options.profileHost} children={options.childrenHost} civic={options.civicHost} rewards={options.rewardsHost}/>:<HeroDevelopmentView controller={controller} {...{full:!!options.dailyHost}}/>);await act(flush);
  const check = () => { old.assertHealthy(); expect(failures).toEqual([]); expect(normalized(trace)).toEqual(normalized(old.trace)); };
  return {old, trace, controller, ui, check, fixtures:old.fixtures, auth,
    async newClick(selector: string) { await act(async () => { (ui.container.querySelector(selector) as HTMLElement).click(); await flush(); }); },
    async confirm() { await act(async () => { ui.getByRole('button',{name:'Подтвердить'}).click(); await flush(); }); },
    async finish() { await old.advance(3510); await act(async () => { await vi.advanceTimersByTimeAsync(3510); await flush(); }); check(); },
  };
}
