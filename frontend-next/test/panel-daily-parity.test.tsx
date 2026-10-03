import {act} from '@testing-library/preact';
import {expect,it} from 'vitest';
import {heroPair} from './panel-hero-support';
import {nextResponseTurn} from './panel-response-order';
import saved from './panel-fixtures/hero-lifecycle-responses.json';
import type {LegacyFixture} from './panel-legacy-harness';
const h=saved.responses;
for(const kind of ['gold','xp'] as const)it(`daily ${kind} keeps exact POST and immediate status plus 1500ms hero and metadata tails`,async()=>{
  const routes:Record<string,LegacyFixture>={'GET /api/bannerlord/daily-status':h.daily_ready,'POST /api/bannerlord/daily-claim':()=>{routes['GET /api/bannerlord/daily-status']=h['daily_claimed_'+kind as 'daily_claimed_gold'];return h['daily_'+kind as 'daily_gold'];}};
  const p=await heroPair({}, {dailyHost:true,extraRoutes:routes});p.check();
  await p.old.click('#bnr-daily-claim-'+kind);await p.newClick('#bnr-daily-claim-'+kind);await p.finish();
  expect(p.trace.filter(q=>q.method==='POST')).toMatchObject([{path:'/api/bannerlord/daily-claim',rawBody:JSON.stringify({reward_type:kind})}]);
  expect(p.ui.container.textContent).toContain('Заявка на ежедневную награду принята');
  expect(p.ui.container.textContent).toContain('Сегодня уже забрал');
});
it('daily server refusal retains the exact message and both original refresh continuations',async()=>{
  const p=await heroPair({}, {dailyHost:true,extraRoutes:{'GET /api/bannerlord/daily-status':h.daily_ready,'POST /api/bannerlord/daily-claim':h.daily_refused}});p.check();
  await p.old.click('#bnr-daily-claim-gold');await p.newClick('#bnr-daily-claim-gold');await p.finish();
  expect(p.ui.container.textContent).toContain(h.daily_refused.message);
});
it('daily status never invents missing reward amounts and an already claimed day has no claim buttons',async()=>{
  const routes:Record<string,LegacyFixture>={'GET /api/bannerlord/daily-status':{...h.daily_ready,reward_amounts:{}}};
  const p=await heroPair({}, {dailyHost:true,extraRoutes:routes});
  expect((p.ui.container.querySelector('#bnr-daily-claim-gold') as HTMLButtonElement).disabled).toBe(true);
  expect((p.ui.container.querySelector('#bnr-daily-claim-xp') as HTMLButtonElement).disabled).toBe(true);
  routes['GET /api/bannerlord/daily-status']=h.daily_claimed_gold;
  await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();});await act(nextResponseTurn);
  expect(p.ui.container.querySelector('#bnr-daily-claim-gold')).toBeNull();expect(p.trace.some(q=>q.method==='POST')).toBe(false);p.check();
});
