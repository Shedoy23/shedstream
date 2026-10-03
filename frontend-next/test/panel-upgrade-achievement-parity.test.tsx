import {act} from '@testing-library/preact';
import {expect,it,vi} from 'vitest';
import {heroPair,normalized} from './panel-hero-support';
import {nextResponseTurn} from './panel-response-order';
import type {LegacyFixture,LegacyFixtures} from './panel-legacy-harness';
import saved from './panel-fixtures/upgrade-achievement-responses.json';
import properties from './panel-fixtures/property-responses.json';
import profile from './panel-fixtures/hero-profile-responses.json';
const r=saved.responses,w=properties.responses;
async function pair(extras:Record<string,LegacyFixture>={},overrides:Partial<LegacyFixtures>={}){
  const routes:Record<string,LegacyFixture>={'GET /api/bannerlord/clan-upgrades':r.catalog,'POST /api/bannerlord/clan-upgrades/buy':r.buy.response,'GET /api/bannerlord/achievements':r.achievements,'GET /api/bannerlord/my-workshops':w.workshops,'GET /api/bannerlord/my-fiefs':w.fiefs,'GET /api/bannerlord/my-caravans':w.caravans,'GET /api/bannerlord/inheritance-log?limit=15':w.inheritance,...extras};
  const p=await heroPair({hero:profile.responses.hero_married,...overrides},{rewardsHost:true,propertyHost:true,extraRoutes:routes});return {...p,routes};
}
type Pair=Awaited<ReturnType<typeof pair>>;
const posts=(p:Pair)=>p.trace.filter(q=>q.method==='POST');
async function open(p:Pair,kind:'upgrades'|'achievements'){
  if(kind==='upgrades')await p.old.openClanUpgrades();else await p.old.openHeroAchievements();
  await newOpen(p,kind);
}
async function newOpen(p:Pair,kind:'upgrades'|'achievements'){
  await act(async()=>{const d=p.ui.container.querySelector(`[data-bnr-details="${kind==='upgrades'?'dyn-upgrades':'inv-achievements'}"]`) as HTMLDetailsElement;d.open=true;d.dispatchEvent(new Event('toggle'));await nextResponseTurn();});
}
async function select(p:Pair,id:string){await p.old.click(`[data-bnr-upg-id="${id}"]`);await p.newClick(`[data-bnr-upg-id="${id}"]`);}
it('clan upgrades and hero achievements stay lazy and retain every authenticated read on open',async()=>{const p=await pair();p.check();expect(p.trace.some(q=>q.path.endsWith('/clan-upgrades'))).toBe(false);await open(p,'upgrades');await open(p,'achievements');p.check();expect(p.ui.container.textContent).toContain('Дружина');expect(p.ui.container.textContent).toContain('Кровожадный');});
it('clan bulk upgrade preserves sorted selected IDs exact JSON and immediate catalog then hero continuations',async()=>{const p=await pair();await open(p,'upgrades');await select(p,'fixture-b');await select(p,'fixture-a');await p.old.click('.bnr-bulk-buy');await p.newClick('.bnr-bulk-buy');expect(posts(p)).toHaveLength(0);await p.confirm();await p.finish();expect(posts(p)[0].body).toEqual(r.buy.request);expect(posts(p)[0].rawBody).toBe(JSON.stringify(r.buy.request));});
it('clan bulk refusal preserves selected controls and performs no success refresh',async()=>{const p=await pair({'POST /api/bannerlord/clan-upgrades/buy':r.duplicate.response});await open(p,'upgrades');await select(p,'fixture-a');await p.old.click('.bnr-bulk-buy');await p.newClick('.bnr-bulk-buy');await p.confirm();await p.finish();expect(p.ui.container.textContent).toContain(r.duplicate.response.message);expect((p.ui.container.querySelector('[data-bnr-upg-id="fixture-a"]') as HTMLInputElement).checked).toBe(true);});
it('clan catalog reflects pending game ownership and exact remaining gold',async()=>{const p=await pair({'GET /api/bannerlord/clan-upgrades':r.pending});await open(p,'upgrades');p.check();expect(p.ui.container.textContent).toContain('Ждём подтверждения игры');expect(p.ui.container.textContent).toContain(r.pending.hero_gold.toLocaleString('ru-RU'));expect(p.ui.container.querySelector('[data-bnr-upg-id="fixture-a"]')).toBeNull();});
it('clan draft survives hero polling but confirmation closes after the game save changes',async()=>{const p=await pair();await open(p,'upgrades');await select(p,'fixture-a');await p.newClick('.bnr-bulk-buy');await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();});await act(nextResponseTurn);p.check();expect(p.ui.queryByRole('dialog')).not.toBeNull();p.fixtures.hero={...profile.responses.hero_married,hero:{...profile.responses.hero_married.hero,hero_id:'replacement-hero'}};await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();});await act(nextResponseTurn);expect(p.ui.queryByRole('dialog')).toBeNull();expect(posts(p)).toHaveLength(0);p.check();});
it('clan invalid price cannot be selected or silently replaced; old renderer throws on malformed quote',async()=>{const p=await pair({'GET /api/bannerlord/clan-upgrades':{...r.catalog,upgrades:r.catalog.upgrades.map(u=>u.upgrade_id==='fixture-a'?{...u,gold_cost:null}:u)}});await expect(p.old.openClanUpgrades()).rejects.toThrow('toLocaleString');await newOpen(p,'upgrades');p.check();expect(p.ui.container.querySelector('[data-bnr-upg-id="fixture-a"]')).toBeNull();expect(p.ui.container.textContent).toContain('Цена не получена');expect(posts(p)).toHaveLength(0);});
it('hero achievement progress and unlocked status come from the server catalog',async()=>{const p=await pair();await open(p,'achievements');p.check();const row=p.ui.container.querySelector('[data-hero-achievement="bloodthirsty"]')!;expect(row.textContent).toContain('37 / 100');expect((row.querySelector('progress') as HTMLProgressElement).value).toBe(37);expect(p.ui.container.querySelector('[data-hero-achievement="first_blood"]')!.textContent).toContain('Открыто');});
it('hero achievements render a server refusal without inventing catalog rows',async()=>{const p=await pair({'GET /api/bannerlord/achievements':{success:false,message:'Профиль временно недоступен'}});await open(p,'achievements');p.check();expect(p.ui.container.textContent).toContain('Профиль временно недоступен');expect(p.ui.container.querySelector('[data-hero-achievement]')).toBeNull();});
it('clan server refuses eleven upgrades instead of copying an unpublished UI cap (explicit request exception)',async()=>{
  const upgrades=Array.from({length:11},(_,i)=>({...r.catalog.upgrades[0],upgrade_id:'fixture-'+i,gold_cost:1})),ids=upgrades.map(u=>u.upgrade_id);
  const p=await pair({'GET /api/bannerlord/clan-upgrades':{...r.catalog,upgrades},'POST /api/bannerlord/clan-upgrades/buy':r.too_many.response});await open(p,'upgrades');for(const id of ids)await select(p,id);p.check();
  expect((p.old.document.querySelector('.bnr-bulk-buy') as HTMLButtonElement).disabled).toBe(true);await p.newClick('.bnr-bulk-buy');await p.confirm();await p.old.advance(3510);await act(async()=>{await vi.advanceTimersByTimeAsync(3510);await nextResponseTurn();});p.old.assertHealthy();
  expect(normalized(p.trace)).toEqual([...normalized(p.old.trace),{method:'POST',path:'/api/bannerlord/clan-upgrades/buy',query:'',body:{upgrade_ids:ids},rawBody:JSON.stringify({upgrade_ids:ids}),token:'alice-token',contentType:'application/json',cache:null}]);expect(p.ui.container.textContent).toContain(r.too_many.response.message);
});
