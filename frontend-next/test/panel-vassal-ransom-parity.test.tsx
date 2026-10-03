import {act} from '@testing-library/preact';
import {expect,it} from 'vitest';
import {heroPair} from './panel-hero-support';
import {nextResponseTurn} from './panel-response-order';
import type {LegacyFixture,LegacyFixtures} from './panel-legacy-harness';
import saved from './panel-fixtures/vassal-ransom-responses.json';
import properties from './panel-fixtures/property-responses.json';
import profile from './panel-fixtures/hero-profile-responses.json';
const r=saved.responses,w=properties.responses;
async function pair(overrides:Partial<LegacyFixtures>={},extras:Record<string,LegacyFixture>={}){
  const routes:Record<string,LegacyFixture>={'GET /api/bannerlord/vassals':r.vassals,'GET /api/bannerlord/eligible-heirs':r.eligible,'GET /api/bannerlord/ransom-pool':r.ransom,'GET /api/bannerlord/my-workshops':w.workshops,'GET /api/bannerlord/my-fiefs':w.fiefs,'GET /api/bannerlord/my-caravans':w.caravans,'GET /api/bannerlord/inheritance-log?limit=15':w.inheritance};
  Object.assign(routes,extras);const p=await heroPair({config:r.config,hero:profile.responses.hero_married,action:q=>{const type=(q.body as {action_type:string}).action_type;return type==='hero.create_vassal_clan'?r.create.response:type==='hero.rename_vassal'?r.rename.response:r.ransom_pay.response;},...overrides},{civicHost:true,propertyHost:true,extraRoutes:routes});return {...p,routes};
}
type Pair=Awaited<ReturnType<typeof pair>>;
async function oldInput(p:Pair,selector:string,value:string){const el=p.old.document.querySelector(selector) as HTMLInputElement;el.value=value;el.dispatchEvent(new p.old.window.Event('input',{bubbles:true}));await p.old.settle();}
async function oldToggle(p:Pair){const d=p.old.document.querySelector('[data-bnr-details="vas-create"]') as HTMLDetailsElement;d.open=true;d.dispatchEvent(new p.old.window.Event('toggle'));await p.old.settle();}
const posts=(p:Pair)=>p.trace.filter(q=>q.method==='POST');
async function input(p:Pair,selector:string,value:string){await act(async()=>{const el=p.ui.container.querySelector(selector) as HTMLInputElement;el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));await nextResponseTurn();});}
async function create(p:Pair){
  await oldToggle(p);await act(async()=>{const d=p.ui.container.querySelector('[data-bnr-details="vas-create"]') as HTMLDetailsElement;d.open=true;d.dispatchEvent(new Event('toggle'));await nextResponseTurn();});
  await oldInput(p,'#bnr-vas-name-input',' Дом наследника ');await input(p,'#bnr-vas-name-input',' Дом наследника ');
  await p.old.click('#bnr-vas-confirm');await p.newClick('#bnr-vas-confirm');expect(posts(p)).toHaveLength(0);await p.confirm();
}
async function rename(p:Pair){
  await p.old.click('.bnr-vas-rename');await p.newClick('.bnr-vas-rename');await oldInput(p,'[data-bnr-vassal-rename-form] input',' Южный дом ');await input(p,'[data-bnr-vassal-rename-form] input',' Южный дом ');
  await p.old.click('[data-bnr-vassal-rename-form] button[type="submit"]');await p.newClick('[data-bnr-vassal-rename-form] button[type="submit"]');expect(posts(p)).toHaveLength(0);await p.confirm();
}
it('vassals and ransom keep every initial authenticated read and observed data',async()=>{const p=await pair();p.check();expect(p.ui.getByRole('region',{name:'Вассальные кланы'}).textContent).toContain('Северный дом');expect(p.ui.getByRole('region',{name:'Выкуп пленных'}).textContent).toContain('Партия разбойников');});
it('vassal create keeps actual eligible hero ID and 2000ms plus generic continuation',async()=>{const p=await pair();await create(p);await p.finish();expect(posts(p)[0].body).toMatchObject(r.create.request);expect(p.ui.container.textContent).toContain('Ждём');});
it('vassal rename keeps stable vassal ID trimmed name and success-only 1500ms continuation',async()=>{const p=await pair();await rename(p);await p.finish();expect(posts(p)[0].body).toMatchObject(r.rename.request);});
it('vassal rename refusal keeps the editable form and adds no refresh tail',async()=>{const p=await pair({action:r.rename_refused.response});await rename(p);await p.finish();expect(p.ui.container.querySelector('[data-bnr-vassal-rename-form]')).not.toBeNull();expect(p.ui.container.textContent).toContain(r.rename_refused.response.message);});
it('vassal create refusal still reloads its authoritative lists',async()=>{const p=await pair({action:r.create_refused.response});await create(p);await p.finish();expect(p.ui.container.textContent).toContain(r.create_refused.response.message);});
it('vassal open draft survives hero refresh and suppresses only the legacy vassal reads',async()=>{const p=await pair();await p.old.click('.bnr-vas-rename');await p.newClick('.bnr-vas-rename');await oldInput(p,'[data-bnr-vassal-rename-form] input','Не потерять');await input(p,'[data-bnr-vassal-rename-form] input','Не потерять');await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();});await act(nextResponseTurn);p.check();expect((p.ui.container.querySelector('[data-bnr-vassal-rename-form] input') as HTMLInputElement).value).toBe('Не потерять');});
for(const refused of [false,true])it(`ransom contribution ${refused?'refusal':'acceptance'} keeps captured viewer and both continuations`,async()=>{const p=await pair(refused?{action:r.ransom_refused.response}:{});await p.old.click('[data-captured="bob"] .bnr-ransom-pay');await p.newClick('[data-captured="bob"] .bnr-ransom-pay');expect(posts(p)).toHaveLength(0);await p.confirm();await p.finish();expect(posts(p)[0].body).toMatchObject(r.ransom_pay.request);});
it('ransom capture replacement invalidates a paid confirmation',async()=>{const p=await pair();await p.newClick('.bnr-ransom-pay');p.routes['GET /api/bannerlord/ransom-pool']={...r.ransom,captures:r.ransom.captures.map(c=>({...c,captor_party:'Другой пленитель'}))};await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();});await act(nextResponseTurn);p.check();expect(p.ui.queryByRole('dialog')).toBeNull();expect(posts(p)).toHaveLength(0);});
it('missing economic and contribution quotes disable paid controls without legacy fallbacks',async()=>{const config=structuredClone(r.config);delete (config.hero_gold_costs as Record<string,unknown>).create_vassal_clan;delete (config.action_prices as Record<string,unknown>)['hero.pay_ransom'];const p=await pair({config});p.check();expect((p.ui.container.querySelector('.bnr-ransom-pay') as HTMLButtonElement).disabled).toBe(true);});
it('vassals do not invent the legacy five-clan UI cap absent from the response (explicit visibility exception)',async()=>{const v=r.vassals.vassals[0];const p=await pair({},{'GET /api/bannerlord/vassals':{success:true,vassals:Array.from({length:5},(_,i)=>({...v,id:i+1,vassal_clan_id:'fixture-'+i}))}});p.check();expect(p.old.document.querySelector('[data-bnr-details="vas-create"]')).toBeNull();expect(p.ui.container.querySelector('[data-bnr-details="vas-create"]')).not.toBeNull();expect(posts(p)).toHaveLength(0);});
