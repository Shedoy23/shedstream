import { act } from '@testing-library/preact';
import { expect, it } from 'vitest';
import saved from './panel-fixtures/party-responses.json';
import { combatPair, flush, usageEvents } from './panel-combat-support';
import type { LegacyFixtures, LegacyJson, LegacyRequest } from './panel-legacy-harness';
const r=saved.responses;
const actions=(q:LegacyRequest):LegacyJson=>{
  const b=q.body as {action_type:string;data:{is_elite:boolean}};
  if(b.action_type==='hero.recruit_troops')return (b.data.is_elite?r.recruit_elite:r.recruit_basic).response;
  if(b.action_type==='hero.train_troops')return r.train_full.response;
  throw new Error('Unexpected retinue action '+JSON.stringify(b));
};
const pair=(o:Partial<LegacyFixtures>={})=>combatPair({config:r.config,hero:r.hero_retinue_full,action:actions,...o},false,'hero',true);
const selectors=['#bnr-recruit-basic-btn','#bnr-recruit-elite-btn','#bnr-train-troops-btn'];
const buttons=(host:ParentNode)=>selectors.map(q=>{const b=host.querySelector<HTMLButtonElement>(q);return b?{disabled:b.disabled,text:b.textContent?.replace(/\s+/g,' ').trim()}:null;});
for(const [name,hero] of Object.entries({full:r.hero_retinue_full,empty:r.hero_empty_retinue_rich,poor:r.hero_empty_retinue_poor,full_poor:r.hero_retinue_poor,cap7:r.hero_retinue_cap7}))it(`entire ${name} retinue has three real controls with old affordance`,async()=>{
  const p=await pair({hero});expect(buttons(p.ui.container)).toEqual(buttons(p.old.document));expect(buttons(p.ui.container).every(Boolean)).toBe(true);p.check();
});
for(const q of selectors)it(`retinue ${q} exact complete request action and hidden 3500ms tail`,async()=>{
  const p=await pair();await p.click(q);await p.hide(true);await p.advance(3500);p.check();expect(p.trace.filter(x=>x.method==='POST'&&x.path.endsWith('/action'))).toHaveLength(1);
});
it('empty retinue affordability updates poor to rich to poor without reload (intentional legacy fix)',async()=>{
  const p=await pair({hero:r.hero_empty_retinue_poor});
  expect((p.ui.container.querySelector(selectors[0]) as HTMLButtonElement|null)?.disabled).toBe(true);
  p.fixtures.hero=r.hero_empty_retinue_rich;await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();});
  expect(p.old.document.querySelector<HTMLButtonElement>(selectors[0])?.disabled).toBe(true);
  expect((p.ui.container.querySelector(selectors[0]) as HTMLButtonElement|null)?.disabled).toBe(false);
  p.fixtures.hero=r.hero_empty_retinue_poor;await act(async()=>{await p.controller.refreshHero();});expect((p.ui.container.querySelector(selectors[0]) as HTMLButtonElement|null)?.disabled).toBe(true);
});
it('cap-only update and gold update reconcile buttons and retain expanded details',async()=>{
  const p=await pair();const detail=(p.ui.container.querySelector('[data-bnr-details="retinue"]') as HTMLDetailsElement|null);expect(detail).not.toBeNull();
  await act(async()=>{detail!.open=true;detail!.dispatchEvent(new Event('toggle'));});
  p.fixtures.hero=r.hero_retinue_cap7;await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();});
  expect(p.ui.container.textContent).toContain('Свита (5/7)');expect(detail!.open).toBe(true);expect(buttons(p.ui.container)).toEqual(buttons(p.old.document));
});
it('nondefault server tier prices and elite multiplier drive all estimates',async()=>{
  const config={...r.config,recruit_tier_costs:[1,2,3,4,5,6],recruit_elite_mult:7};const p=await pair({config});expect(buttons(p.ui.container)).toEqual(buttons(p.old.document));expect(p.ui.container.querySelector(selectors[2])?.getAttribute('title')).toContain('точную сумму считает игра');p.check();
});
it('missing server price and cap fail closed rather than quoting free or invented values',async()=>{
  const p=await pair({config:{...r.config,recruit_tier_costs:[]}});expect(buttons(p.ui.container).every(b=>b?.disabled)).toBe(true);expect(p.ui.container.textContent).toContain('Сервер не передал');
  p.fixtures.config=r.config;await act(async()=>{p.ui.getByRole('button',{name:'Обновить цены свиты'}).click();await flush();});expect(buttons(p.ui.container).every(b=>b&&!b.disabled)).toBe(true);
});
it('both recruit choices share returned cooldown and recover at expiry',async()=>{
  const p=await pair();await p.click(selectors[0]);await p.advance(1000);for(const q of selectors.slice(0,2))expect((p.ui.container.querySelector(q) as HTMLButtonElement|null)?.disabled).toBe(true);await p.advance(10000);expect((p.ui.container.querySelector(selectors[1]) as HTMLButtonElement|null)?.disabled).toBe(false);p.check();
});
it('same-turn duplicate action stays single flight and keeps usage attempts',async()=>{
  const p=await pair();await p.click(selectors[0],selectors[0],2);await p.advance(30000);p.check();expect(p.trace.filter(x=>x.path.endsWith('/action'))).toHaveLength(1);expect(usageEvents(p.trace)).toContainEqual({kind:'action_attempt',feature:'bannerlord:hero.recruit_troops',count:2});
});
it('real cooldown refusal displays returned seconds and no success tail',async()=>{
  const p=await pair({action:r.train_cooldown.response});await p.click(selectors[2]);await p.advance(1000);expect(p.ui.container.querySelector(selectors[2])?.textContent).toContain('29');p.check();
});
it('details exposure records real feature telemetry once per expansion',async()=>{
  const p=await pair();for(const host of [p.old.document,p.ui.container]){const detail=(host.querySelector('[data-bnr-details="retinue"]') as HTMLDetailsElement|null);expect(detail).not.toBeNull();detail!.open=true;detail!.dispatchEvent(new (host===p.old.document?p.old.window.Event:Event)('toggle'));}await act(async()=>{await flush();});await p.advance(30000);p.check();expect(usageEvents(p.trace)).toContainEqual({kind:'section_open',feature:'bannerlord:details.retinue',count:1});
});
it('stop aborts retinue action follow-up reads and ignores an old hero result',async()=>{
  const p=await pair();let resolve!:(v:LegacyJson)=>void;p.fixtures.hero=()=>new Promise<LegacyJson>(r=>{resolve=r;});
  const pending=p.controller.refreshHero();await flush();p.controller.stop();resolve(r.hero_retinue_cap7);await act(async()=>{await pending;});expect(p.controller.snapshot().hero).toBeNull();
});
for(const [key,tier] of [['basic',5],['elite',5],['elite',6]] as const)it(`${key} tier ${tier} preserves inherited full-roster eligibility`,async()=>{
  const hero=structuredClone(r.hero_retinue_full);hero.retinue=hero.retinue.map(s=>({...s,is_elite:key==='elite',tier}));const p=await pair({hero});expect(buttons(p.ui.container)).toEqual(buttons(p.old.document));p.check();
});
for(const value of [undefined,null,-1,'3',Infinity])it(`malformed multiplier ${String(value)} cannot manufacture free prices`,async()=>{
  const p=await pair({config:{...r.config,recruit_elite_mult:value}});expect(buttons(p.ui.container).every(b=>b?.disabled)).toBe(true);
});
it('zero server prices are valid while zero estimated train cost remains inherited disabled',async()=>{
  const p=await pair({config:{...r.config,recruit_tier_costs:[0,0,0,0,0,0],recruit_elite_mult:0}});expect(buttons(p.ui.container)).toEqual(buttons(p.old.document));await p.click(selectors[0]);p.check();
});
it('latest hero gold and cap prevent stale detached retinue controls acting after hero identity changes',async()=>{
  const p=await pair(),old=p.ui.container.querySelector(selectors[0]) as HTMLButtonElement;
  p.fixtures.hero={...r.hero_retinue_full,hero:{...r.hero_retinue_full.hero,hero_id:'fixture_successor'}};
  await act(async()=>{await p.controller.refreshHero();old.click();await flush();});expect(p.trace.filter(x=>x.path.endsWith('/action'))).toHaveLength(0);
});
it('retinue unknown-outcome locks every action and permits refresh',async()=>{
  const p=await pair({action:null});await act(async()=>{(p.ui.container.querySelector(selectors[0]) as HTMLButtonElement).click();await flush();});expect(p.controller.snapshot().mutationBlocked).toBe(true);expect(buttons(p.ui.container).every(b=>b?.disabled)).toBe(true);await act(async()=>{await p.controller.refreshHero();});expect(p.controller.snapshot().hero?.has_hero).toBe(true);
});
it('returned retinue cooldown from real buffs applies to both recruit choices',async()=>{
  const p=await pair({buffs:r.buffs_recruit_basic});await p.advance(1000);expect(buttons(p.ui.container)).toEqual(buttons(p.old.document));p.check();
});
it('retinue buttons use new identity authorization only after fresh resolution',async()=>{
  const p=await pair();await act(async()=>{p.authorize({token:'rotated',channelId:'channel-a',userId:'opaque-alice'});await flush();});
  await act(async()=>{(p.ui.container.querySelector(selectors[0]) as HTMLButtonElement).click();await flush();});expect(p.trace.filter(x=>x.path.endsWith('/action')).at(-1)?.token).toBe('rotated');
});
it('real server insufficient-gold refusal keeps exact text and has no success refresh tail',async()=>{
  const p=await pair({action:r.recruit_insufficient.response});await p.click(selectors[0]);expect(p.ui.container.textContent).toContain(r.recruit_insufficient.response.message);await p.hide(true);await p.advance(3500);p.check();expect(p.trace.filter(x=>x.path.endsWith('/my-hero'))).toHaveLength(1);
});
it('unknown server retinue cap prevents all three mutations without inventing five slots',async()=>{
  const hero={...r.hero_retinue_full,hero:{...r.hero_retinue_full.hero,retinue_cap:null}};const p=await pair({hero});expect(buttons(p.ui.container).every(b=>b?.disabled)).toBe(true);expect(p.ui.container.textContent).toContain('Свита (5/—)');
});
