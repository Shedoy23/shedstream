import {act} from '@testing-library/preact';
import {expect,it,vi} from 'vitest';
import {heroPair,normalized} from './panel-hero-support';
import {nextResponseTurn} from './panel-response-order';
import type {LegacyFixture,LegacyFixtures,LegacyJson} from './panel-legacy-harness';
import saved from './panel-fixtures/children-responses.json';
import properties from './panel-fixtures/property-responses.json';
import profile from './panel-fixtures/hero-profile-responses.json';
const r=saved.responses,w=properties.responses;
async function pair(overrides:Partial<LegacyFixtures>={}){
  const routes:Record<string,LegacyFixture>={'GET /api/bannerlord/heirs':r.heirs,'GET /api/bannerlord/my-children':r.children,'GET /api/bannerlord/proposals':r.proposals,'GET /api/bannerlord/public-children?username=bob':r.public_children,'GET /api/bannerlord/my-workshops':w.workshops,'GET /api/bannerlord/my-caravans':w.caravans,'GET /api/bannerlord/my-fiefs':w.fiefs,'GET /api/bannerlord/inheritance-log?limit=15':w.inheritance};
  const p=await heroPair({config:r.config,hero:profile.responses.hero_married,action:q=>{const b=q.body as {action_type:string;data:{accept:boolean}};const key=b.action_type==='hero.respond_marriage_proposal'?(b.data.accept?'accept':'reject'):({'hero.rename_child':'rename','hero.change_child_looks':'looks','hero.respec_child_skills':'respec','hero.propose_marriage':'propose','hero.cancel_proposal':'cancel'} as Record<string,string>)[b.action_type];const result=(r as unknown as Record<string,{response:LegacyJson}>)[key];if(!result)throw Error('Unmatched child action '+b.action_type);return result.response;},...overrides},{childrenHost:true,propertyHost:true,profileHost:true,extraRoutes:routes});
  return {...p,routes};
}
type Pair=Awaited<ReturnType<typeof pair>>;
async function input(p:Pair,label:string,value:string){await act(async()=>{const el=p.ui.getByLabelText(label) as HTMLInputElement;el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));await nextResponseTurn();});}
async function button(p:Pair,name:string){await act(async()=>{p.ui.getByRole('button',{name,exact:true}).click();await nextResponseTurn();});}
const posts=(p:Pair)=>p.trace.filter(q=>q.method==='POST');
it('children and heirs retain complete initial reads and observed names',async()=>{const p=await pair();p.check();expect(p.ui.getByRole('region',{name:'Наследники'}).textContent).toContain('Взрослый наследник');expect(p.ui.getByRole('region',{name:'Взрослые дети и предложения'}).textContent).toContain('Наследница Боба');});
for(const accept of [true,false])it(`children proposal ${accept?'accept':'reject'} keeps exact ID boolean and 1500ms family tail`,async()=>{const p=await pair();const selector=`[data-proposal-id="200"] .bnr-prop-${accept?'accept':'reject'}`;await p.old.click(selector);await p.newClick(selector);await p.finish();expect(posts(p)[0].body).toMatchObject(r[accept?'accept':'reject'].request);});
it('children cancel warns and preserves the original proposal ID and continuation',async()=>{const p=await pair();const selector=`[data-proposal-id="${r.outgoing_id}"] .bnr-fam-cancel`;await p.old.click(selector);await p.newClick(selector);expect(posts(p)).toHaveLength(0);await p.confirm();await p.finish();expect(posts(p)[0].body).toMatchObject(r.cancel.request);});
for(const kind of ['rename','looks'] as const)it(`children ${kind} preserves the exact child and edited text with paid confirmation`,async()=>{
  const p=await pair();const text=kind==='rename'?' Новое имя ':'  fixture-body-properties  ';p.old.window.prompt=()=>text;
  await p.old.click(`[data-child-id="child-a"] .bnr-fam-${kind}`);await p.newClick(`[data-child-id="child-a"] .bnr-fam-${kind}`);
  await input(p,kind==='rename'?'Новое имя ребёнка':'Код внешности ребёнка',text);await button(p,'Продолжить');expect(posts(p)).toHaveLength(0);await p.confirm();await p.finish();expect(posts(p)[0].body).toMatchObject(r[kind].request);
});
it('children respec preserves irreversible warning and has no invented local family tail',async()=>{const p=await pair();await p.old.click('[data-child-id="child-a"] .bnr-fam-respec');await p.newClick('[data-child-id="child-a"] .bnr-fam-respec');await p.old.click('#confirm-dyn-yes');await p.confirm();await p.finish();expect(posts(p)[0].body).toMatchObject(r.respec.request);});
it('children propose uses normalized username and the selected actual child ID',async()=>{
  const p=await pair();const answers=[' @BoB ','1'];p.old.window.prompt=()=>answers.shift()??null;
  await p.old.click('[data-child-id="child-a"] .bnr-fam-propose');await p.newClick('[data-child-id="child-a"] .bnr-fam-propose');
  await input(p,'Зритель для предложения',' @BoB ');await button(p,'Найти детей');
  await act(async()=>{const select=p.ui.getByLabelText('Ребёнок другого зрителя') as HTMLSelectElement;select.value='child-b';select.dispatchEvent(new Event('change',{bubbles:true}));await nextResponseTurn();});
  await button(p,'Продолжить');expect(posts(p)).toHaveLength(0);await p.confirm();await p.finish();expect(posts(p)[0].body).toMatchObject(r.propose.request);
});
it('children refusal keeps the server reason and original refresh requests',async()=>{const p=await pair({action:r.respond_refused.response});await p.old.click('[data-proposal-id="200"] .bnr-prop-accept');await p.newClick('[data-proposal-id="200"] .bnr-prop-accept');await p.finish();expect(p.ui.container.textContent).toContain(r.respond_refused.response.message);});
it('children stale editor cannot rename a child removed by a fresh observation',async()=>{const p=await pair();await p.newClick('[data-child-id="child-a"] .bnr-fam-rename');await input(p,'Новое имя ребёнка',' Новое имя ');await button(p,'Продолжить');p.routes['GET /api/bannerlord/my-children']={success:true,children:[]};await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();});await act(nextResponseTurn);expect(p.ui.queryByRole('dialog')).toBeNull();expect(posts(p)).toHaveLength(0);p.check();});
it('children missing price never copies a fifty-crustic rename fallback',async()=>{const p=await pair({config:{...r.config,action_prices:{...r.config.action_prices,'hero.rename_child':null}}});p.check();expect((p.ui.container.querySelector('.bnr-fam-rename') as HTMLButtonElement).disabled).toBe(true);});
it('children propose uses rebalanced server quote instead of legacy literal 100 (explicit raw-price exception)',async()=>{
  const p=await pair({config:{...r.config,action_prices:{...r.config.action_prices,'hero.propose_marriage':137}}});const answers=['bob','1'];p.old.window.prompt=()=>answers.shift()??null;
  await p.old.click('[data-child-id="child-a"] .bnr-fam-propose');await p.newClick('[data-child-id="child-a"] .bnr-fam-propose');await input(p,'Зритель для предложения','bob');await button(p,'Найти детей');
  await act(async()=>{const select=p.ui.getByLabelText('Ребёнок другого зрителя') as HTMLSelectElement;select.value='child-b';select.dispatchEvent(new Event('change',{bubbles:true}));await nextResponseTurn();});await button(p,'Продолжить');expect(p.ui.getByRole('dialog').textContent).toContain('137');await p.confirm();
  await p.old.advance(3510);await act(async()=>{await vi.advanceTimersByTimeAsync(3510);await nextResponseTurn();});
  const expected=normalized(p.old.trace).map(q=>{if(q.path!=='/api/bannerlord/action')return q;expect(q.body).toMatchObject({action_type:'hero.propose_marriage',data:{price:100}});return {...q,body:{...(q.body as object),data:{...(q.body as {data:object}).data,price:137}},rawBody:q.rawBody!.replace('"price":100','"price":137')};});
  p.old.assertHealthy();expect(normalized(p.trace)).toEqual(expected);
});
