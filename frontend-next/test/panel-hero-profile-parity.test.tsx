import {act} from '@testing-library/preact';
import {expect,it} from 'vitest';
import {heroPair} from './panel-hero-support';
import {nextResponseTurn} from './panel-response-order';
import type {LegacyFixtures,LegacyJson} from './panel-legacy-harness';
import saved from './panel-fixtures/hero-profile-responses.json';
import properties from './panel-fixtures/property-responses.json';
import daily from './panel-fixtures/hero-lifecycle-responses.json';
const r=saved.responses,p=properties.responses;
async function pair(mode:'gender'|'family',overrides:Partial<LegacyFixtures>={}){
  const family=mode==='family';
  return heroPair({config:r.config,hero:r.hero_married,action:q=>{const b=q.body as {action_type:string;data:{gender:string}};const key=b.action_type==='hero.set_gender'?'gender_'+b.data.gender:b.action_type==='hero.make_baby'?'baby':b.action_type.replace('hero.','');const result=(r as unknown as Record<string,{response:LegacyJson}>)[key];if(!result)throw Error('Unmatched profile action '+key);return result.response;},...overrides},{genderHost:!family,dailyHost:!family,propertyHost:family,profileHost:family,extraRoutes:{'GET /api/bannerlord/daily-status':daily.responses.daily_ready,'GET /api/bannerlord/my-workshops':p.workshops,'GET /api/bannerlord/my-fiefs':p.fiefs,'GET /api/bannerlord/my-caravans':p.caravans,'GET /api/bannerlord/inheritance-log?limit=15':p.inheritance}});
}
for(const gender of ['male','female'] as const)it(`hero profile ${gender} confirms game gold and exact gender with generic action tails`,async()=>{
  const p=await pair('gender');p.check();const selector=`[data-gender-set="${gender}"]`;
  await p.old.click(selector);await p.newClick(selector);expect(p.trace.some(q=>q.method==='POST')).toBe(false);
  expect(p.ui.getByRole('dialog').textContent).toContain('50 000');await p.confirm();await p.finish();
  expect(p.trace.find(q=>q.method==='POST')?.body).toMatchObject(r[gender==='male'?'gender_male':'gender_female'].request);expect(p.ui.container.textContent).toContain('Ждём подтверждения игры');
});
for(const type of ['marry','divorce','baby'] as const)it(`hero profile ${type} preserves raw action, family snapshot and all continuations`,async()=>{
  const p=await pair('family',{hero:type==='marry'?r.hero_single:r.hero_married});p.check();
  expect(p.ui.container.textContent).toContain('Отец фикстуры');expect(p.ui.container.textContent).toContain('Ребёнок фикстуры');
  const selector='#bnr-'+(type==='baby'?'make-baby':type)+'-btn';await p.old.click(selector);await p.newClick(selector);
  if(type==='divorce')await p.old.click('#confirm-dyn-yes');expect(p.trace.some(q=>q.method==='POST')).toBe(false);await p.confirm();await p.finish();
  expect(p.trace.find(q=>q.method==='POST')?.body).toMatchObject(r[type].request);
});
it('hero profile refusal displays the actual reason without inventing a successful family change',async()=>{
  const p=await pair('family',{action:r.baby_refused.response});await p.old.click('#bnr-make-baby-btn');await p.newClick('#bnr-make-baby-btn');await p.confirm();await p.finish();expect(p.ui.container.textContent).toContain(r.baby_refused.response.message);
});
it('hero profile missing game price blocks gender changes without the old fallback',async()=>{
  const p=await pair('gender',{config:{...r.config,gender_swap_cost:null}});p.check();expect((p.ui.container.querySelector('[data-gender-set="female"]') as HTMLButtonElement).disabled).toBe(true);expect(p.ui.container.textContent).toContain('Цена не получена');
});
it('hero profile spouse replacement cancels divorce before any request',async()=>{
  const p=await pair('family');await p.newClick('#bnr-divorce-btn');expect(p.ui.queryByRole('dialog')).not.toBeNull();
  p.fixtures.hero={...r.hero_married,hero:{...r.hero_married.hero,spouse_name:'Другой супруг',family_info:{...r.hero_married.hero.family_info,spouse:{...r.hero_married.hero.family_info!.spouse,hero_id:'replacement',name:'Другой супруг'}}}};
  await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();});await act(nextResponseTurn);expect(p.ui.queryByRole('dialog')).toBeNull();expect(p.trace.some(q=>q.method==='POST')).toBe(false);p.check();
});
it('hero profile delegates the unexposed child limit to the server and game instead of copying five',async()=>{
  const p=await pair('family',{hero:r.hero_many_children,action:r.baby_queued_limit.response});p.check();
  expect((p.old.document.querySelector('#bnr-make-baby-btn') as HTMLButtonElement).disabled).toBe(true);
  await p.newClick('#bnr-make-baby-btn');expect(p.ui.getByRole('dialog').textContent).toContain('Лимит детей проверит игра');await p.confirm();
  expect(p.trace.find(q=>q.method==='POST')?.body).toMatchObject(r.baby_queued_limit.request);
});
