import {act} from '@testing-library/preact';
import {expect,it} from 'vitest';
import {heroPair} from './panel-hero-support';
import {nextResponseTurn} from './panel-response-order';
import {gameResponses as g,type LegacyFixture,type LegacyFixtures} from './panel-legacy-harness';
import saved from './panel-fixtures/property-responses.json';
import kingdom from './panel-fixtures/kingdom-responses.json';
const r=saved.responses;
const catalog={available:true,entries:[{id:'brewery',name:'Пивоварня',available:true}]};
async function pair(overrides:Partial<LegacyFixtures>={},extras:Record<string,LegacyFixture>={}){
  const routes:Record<string,LegacyFixture>={'GET /api/bannerlord/my-workshops':r.workshops,'GET /api/bannerlord/my-caravans':r.caravans,'GET /api/bannerlord/my-fiefs':r.fiefs,'GET /api/bannerlord/inheritance-log?limit=15':r.inheritance,'GET /api/bannerlord/settlements':r.settlements,...extras};
  const actions:Record<string,LegacyFixture>={'hero.buy_workshop':r.workshop_buy.response,'hero.sell_workshop':r.workshop_sell.response,'hero.buy_caravan':r.caravan_buy.response,'hero.sell_caravan':r.caravan_sell.response};
  const p=await heroPair({config:r.config,hero:kingdom.responses.hero_ruler,catalogs:{...g.catalogs,workshop_types:catalog},action:q=>{
    const b=q.body as {action_type:string};const result=actions[b.action_type];if(!result||typeof result==='function')throw Error('Unmatched property action '+b.action_type);return result;
  },...overrides},{propertyHost:true,extraRoutes:routes});
  return {...p,routes};
}
type Pair=Awaited<ReturnType<typeof pair>>;
async function open(p:Pair,kind:'ws'|'caravan'){
  for(const host of [p.old.document,p.ui.container]){const d=host.querySelector<HTMLDetailsElement>(`[data-bnr-details="${kind}-buy"]`);expect(d).not.toBeNull();d!.open=true;d!.dispatchEvent(new (host===p.old.document?p.old.window.Event:Event)('toggle'));}
  await p.old.settle();await act(nextResponseTurn);
}
async function town(p:Pair,kind:'ws'|'caravan'){
  const selector=kind==='ws'?'#bnr-ws-town':'#bnr-caravan-home';await p.old.change(selector,'town_fixture');
  await act(async()=>{const n=p.ui.container.querySelector<HTMLSelectElement>(selector)!;n.value='town_fixture';n.dispatchEvent(new Event('change',{bubbles:true}));await nextResponseTurn();});
}
it('properties read full selected-host traffic including exact inheritance query and server totals',async()=>{
  const p=await pair();p.check();expect(p.ui.container.textContent).toContain('12 345');expect(p.ui.container.textContent).toContain('6 789');expect(p.ui.container.textContent).toContain('65 432');expect(p.ui.container.textContent).toContain('Унаследованная мастерская');expect(p.ui.container.textContent).toContain('54 321');
});
for(const kind of ['ws','caravan'] as const){
  const action=kind==='ws'?'workshop':'caravan',id=kind==='ws'?r.workshop_id:r.caravan_id;
  it(`properties ${action} buy preserves catalog selection, exact raw action and all 2000/3500ms tails`,async()=>{
    const p=await pair();await open(p,kind);await town(p,kind);p.check();
    await p.old.click(`#bnr-${kind}-buy-confirm`);await p.newClick(`#bnr-${kind}-buy-confirm`);
    expect(p.trace.filter(q=>q.method==='POST')).toHaveLength(0);await p.confirm();await p.finish();
    const post=p.trace.find(q=>q.method==='POST')!;const body=post.body as {action_type:string;data:Record<string,unknown>};
    expect(body.action_type).toBe(`hero.buy_${action}`);expect(body.data).toMatchObject(r[`${action}_buy`].request.data);expect(p.ui.container.textContent).toContain('Заявка принята');
  });
  it(`properties ${action} sell confirms the observed ID with 1500/3500ms tails`,async()=>{
    const p=await pair();const selector=`[data-${action}-id="${id}"] .bnr-${kind}-sell`;
    await p.old.click(selector);await p.newClick(selector);expect(p.trace.filter(q=>q.method==='POST')).toHaveLength(0);
    await p.old.click('#confirm-dyn-yes');await p.confirm();await p.finish();
    expect(p.trace.find(q=>q.method==='POST')?.body).toMatchObject({action_type:`hero.sell_${action}`,data:{[`${action}_id`]:id}});
  });
  it(`properties ${action} refusal still runs its original local refresh`,async()=>{
    const p=await pair({action:r[`${action}_refused`].response});const selector=`[data-${action}-id="${id}"] .bnr-${kind}-sell`;
    await p.old.click(selector);await p.newClick(selector);await p.old.click('#confirm-dyn-yes');await p.confirm();await p.finish();
    expect(p.ui.container.textContent).toContain(r[`${action}_refused`].response.message);
  });
}
it('properties share the original sixty-second settlements cache across both forms',async()=>{
  const p=await pair();await open(p,'ws');await open(p,'caravan');p.check();expect(p.trace.filter(q=>q.path==='/api/bannerlord/settlements')).toHaveLength(1);
});
it('properties missing catalog or price fails closed without hardcoded workshop choices',async()=>{
  const p=await pair({config:{...r.config,workshop_price:null},catalogs:{...g.catalogs,workshop_types:{available:false,entries:[]}}});await open(p,'ws');p.check();
  expect(p.ui.container.querySelector('input[name="bnr-ws-type"]')).toBeNull();expect((p.ui.container.querySelector('#bnr-ws-buy-confirm') as HTMLButtonElement).disabled).toBe(true);expect(p.trace.some(q=>q.method==='POST')).toBe(false);
});
it('properties remove a pending sale when its observed object vanishes',async()=>{
  const p=await pair();await p.newClick(`[data-workshop-id="${r.workshop_id}"] .bnr-ws-sell`);expect(p.ui.queryByRole('dialog')).not.toBeNull();
  p.routes['GET /api/bannerlord/my-workshops']=r.workshops_empty;
  await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();await nextResponseTurn();});
  await act(nextResponseTurn);
  expect(p.ui.queryByRole('dialog')).toBeNull();expect(p.trace.some(q=>q.method==='POST')).toBe(false);p.check();
});
it('properties custom game workshop IDs are selectable and sent verbatim (old static catalog limitation)',async()=>{
  const p=await pair({catalogs:g.catalogs,action:r.workshop_modded.response});await open(p,'ws');await town(p,'ws');p.check();
  expect(p.old.document.querySelector('input[value="Mod.Workshop-X"]')).toBeNull();
  await p.newClick('input[value="Mod.Workshop-X"]');await p.newClick('#bnr-ws-buy-confirm');await p.confirm();
  expect(p.trace.find(q=>q.method==='POST')?.body).toMatchObject(r.workshop_modded.request);
});
it('properties never sell a card from the previous game save while its replacement read is pending',async()=>{
  const p=await pair();
  p.routes['GET /api/bannerlord/my-workshops']=()=>new Promise(()=>{});
  p.fixtures.catalogs={...g.catalogs,save_id:'new-save',workshop_types:catalog};
  await act(async()=>{await p.controller.refreshCatalogs();await nextResponseTurn();});
  await p.newClick(`[data-workshop-id="${r.workshop_id}"] .bnr-ws-sell`);
  expect(p.ui.queryByRole('dialog')).toBeNull();expect(p.trace.some(q=>q.method==='POST')).toBe(false);
});
