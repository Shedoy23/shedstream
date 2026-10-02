import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/preact';
import { TwitchAuthStore } from '../src/auth';
import { IdentityBootstrap } from '../src/skillgames/identity';
import { PanelController } from '../src/panel/controller';
import { PanelApp } from '../src/panel/PanelApp';
import { EquipmentView } from '../src/panel/EquipmentView';
import { HttpPanelTransport } from '../src/panel/transport';
import data from './panel-fixtures/combat-responses.json';
import base from './panel-fixtures/real-responses.json';
const c=data.responses,f=base.responses,epoch=Date.UTC(2026,9,2,12),initial={token:'alice-token',userId:'opaque-alice',channelId:'channel-a'};
const flush=async()=>{for(let i=0;i<45;i++)await Promise.resolve();};
const response=(body:unknown)=>new Response(JSON.stringify(body));
const deferred=<T,>()=>{let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {resolve,promise};};
const cleanupFns:(()=>void)[]=[];
beforeEach(()=>{vi.useFakeTimers({toFake:['setTimeout','clearTimeout','setInterval','clearInterval','Date']});vi.setSystemTime(epoch);localStorage.clear();Object.defineProperty(document,'hidden',{configurable:true,value:false});});
afterEach(()=>{cleanup();cleanupFns.splice(0).forEach(fn=>fn());vi.useRealTimers();});
async function setup(overrides:Record<string,unknown>={},savedTab?:string){
  if(savedTab)localStorage.setItem('bnr_active_tab',savedTab);
  const trace:{path:string;method:string;body?:{action_type:string;data:Record<string,unknown>};token:string|null}[]=[];
  const routes:Record<string,unknown>={'/api/user/resolve-twitch-token':{login:'alice'},'/api/bannerlord/config':f.config,'/api/bannerlord/my-hero':f.hero,'/api/bannerlord/classes':c.classes_by_key.tank,'/api/bannerlord/build':c.build_combat_one_handed,'/api/bannerlord/my-buffs':c.buffs_empty,'/api/bannerlord/battle-status':c.battle_siege,'/api/viewer/stats/alice':f.stats,'/api/user/level/alice':f.level,'/api/viewer/stats/carol':{...f.stats,points:0},'/api/user/level/carol':f.level,'/api/duel/list':f.duels,'/api/bannerlord/equipment-shop':f.equipment_inventory,'/api/bannerlord/action':c.build_power_one_handed.response,...overrides};
  const fetcher:typeof fetch=async(input,init={})=>{const path=String(input);trace.push({path,method:init.method||'GET',body:init.body?JSON.parse(String(init.body)):undefined,token:new Headers(init.headers).get('X-Twitch-JWT')});if(!(path in routes))throw Error('UNMATCHED '+path);let value=routes[path];if(typeof value==='function')value=(value as ()=>unknown)();if(value instanceof Promise)value=await value;return value instanceof Response?value.clone():response(value);};
  const auth=new TwitchAuthStore();let authorize!:(v:typeof initial)=>void;const identity=new IdentityBootstrap(auth,'',fetcher),detach=identity.attach({onAuthorized:fn=>authorize=fn});cleanupFns.push(detach);
  const controller=new PanelController(new HttpPanelTransport('',auth,fetcher),auth,identity);let ui!:ReturnType<typeof render>;
  await act(async()=>{authorize(initial);await flush();ui=render(<PanelApp controller={controller} identity={identity} Equipment={EquipmentView} combat/>);await flush();});await act(flush);
  const firstTab=ui.container.querySelector('.panel-tabs [aria-pressed=true]')?.textContent;
  await act(async()=>{ui.getByRole('button',{name:'Боевые действия'}).click();await flush();});
  const button=(q:string)=>{const node=ui.container.querySelector(q);expect(node,q).toBeTruthy();return node as HTMLButtonElement;};
  return {ui,firstTab,controller,auth,authorize,identity,trace,routes,button,posts:()=>trace.filter(r=>r.path==='/api/bannerlord/action'),async click(q:string){await act(async()=>{button(q).click();await flush();});},async advance(ms:number){await act(async()=>{await vi.advanceTimersByTimeAsync(ms);await flush();});},async load(key:'Build'|'Buffs'|'Battle'|'Config'|'Balance'|'Hero'){await act(async()=>{await controller[`refresh${key}`]();await flush();});}};
}
for(const price of [undefined,null,-1,'300',Infinity])for(const family of ['order','spawn','legacy','new'] as const)it(`${family} fails closed for malformed price ${String(price)}`,async()=>{
  let q:string,overrides:Record<string,unknown>={};
  if(family==='order'){q='[data-det-act="hero.detach_hold"]';overrides['/api/bannerlord/config']={...f.config,action_prices:{...f.config.action_prices,'hero.detach_hold':price}};}
  else if(family==='spawn'){q='#bnr-summon-enemy-btn';overrides['/api/bannerlord/config']={...f.config,spawn_prices:{...f.config.spawn_prices,enemy:price}};}
  else if(family==='legacy'){q='[data-bnr-power="rage"]';overrides['/api/bannerlord/build']=c.build_no_session;overrides['/api/bannerlord/classes']={...c.classes_by_key.tank,current_powers:c.classes_by_key.tank.current_powers.map(p=>p.power_key==='rage'?{...p,price}:p)};}
  else {q='[data-bnr-build-activate="rage"]';overrides['/api/bannerlord/build']={...c.build_combat_one_handed,build:{...c.build_combat_one_handed.build,power_options:c.build_combat_one_handed.build.power_options.map(p=>p.power_key==='rage'?{...p,price}:p)}};}
  const s=await setup(overrides);expect(s.button(q).disabled).toBe(true);await s.click(q);expect(s.posts()).toHaveLength(0);
});
for(const points of [299,300,301])it(`new weapon balance boundary ${points} uses actual stats response`,async()=>{
  const s=await setup({'/api/viewer/stats/alice':{...f.stats,points}});expect(s.button('[data-bnr-build-activate="rage"]').disabled).toBe(points<300);await s.click('[data-bnr-build-activate="rage"]');expect(s.posts()).toHaveLength(points<300?0:1);
});
it('legacy insufficient balance dims and explains without disabling its server-authorized request',async()=>{
  const s=await setup({'/api/bannerlord/build':c.build_no_session,'/api/viewer/stats/alice':{...f.stats,points:0}});await s.advance(1000);const b=s.button('[data-bnr-power="rage"]');expect(b.disabled).toBe(false);expect(b.title).toContain('Не хватает');expect(b.classList.contains('bnr-cant-afford')).toBe(true);await s.click('[data-bnr-power="rage"]');expect(s.posts()).toHaveLength(1);
});
for(const source of ['buffs','remaining','persisted'])it(`${source} shared weapon cooldown disables selected weapon while common heal stays independent`,async()=>{
  const build=structuredClone(c.build_combat_one_handed),overrides:Record<string,unknown>={};
  if(source==='buffs')overrides['/api/bannerlord/my-buffs']=c.buffs_build_bow;
  if(source==='remaining')build.cooldown_remaining_s=42;
  if(source==='persisted')build.build.weapon_power_cooldown_until=epoch/1000+42;
  overrides['/api/bannerlord/build']=build;const s=await setup(overrides);expect(s.button('[data-bnr-build-activate="rage"]').disabled).toBe(true);expect(s.button('[data-bnr-build-activate="heal_burst"]').disabled).toBe(false);await s.click('[data-bnr-build-activate="rage"]');expect(s.posts()).toHaveLength(0);
});
it('choosing another weapon never resets shared cooldown received from the build route',async()=>{
  const s=await setup({'/api/bannerlord/build':{...c.build_choices,cooldown_remaining_s:60}});await s.click('[data-bnr-build-select="bow"]');
  s.routes['/api/bannerlord/build']={...c.build_combat_bow,cooldown_remaining_s:59};await s.load('Build');expect(s.button('[data-bnr-build-activate="explosive_arrows"]').disabled).toBe(true);expect(s.button('[data-bnr-build-activate="heal_burst"]').disabled).toBe(false);
});
it('battle can_manage=false still allows all actual new selected/common activation',async()=>{
  const s=await setup();expect(s.controller.snapshot().build?.can_manage).toBe(false);expect(s.button('[data-bnr-build-activate="rage"]').disabled).toBe(false);expect(s.button('[data-bnr-build-activate="heal_burst"]').disabled).toBe(false);
});
for(const reverse of [false,true])it(`battle read applies monotonically without starvation; reversed=${reverse}`,async()=>{
  const s=await setup(),a=deferred<Response>(),b=deferred<Response>();s.routes['/api/bannerlord/battle-status']=a.promise;const first=s.controller.refreshBattle();s.routes['/api/bannerlord/battle-status']=b.promise;const second=s.controller.refreshBattle();
  if(reverse){b.resolve(response(c.battle_dead));await second;a.resolve(response(c.battle_siege));await first;}else{a.resolve(response(c.battle_dead));await first;expect(s.controller.snapshot().battle?.my_stats?.alive).toBe(false);b.resolve(response(c.battle_dead));await second;}
  expect(s.controller.snapshot().battle?.my_stats?.alive).toBe(false);
});
it('a pre-action buffs reply cannot erase acknowledged weapon_power cooldown and a later read can',async()=>{
  const s=await setup(),waiting=deferred<Response>();s.routes['/api/bannerlord/my-buffs']=waiting.promise;const poll=s.controller.refreshBuffs();await s.click('[data-bnr-build-activate="rage"]');waiting.resolve(response(c.buffs_empty));await poll;expect(s.controller.cooldown('weapon_power')).toBe(90);s.routes['/api/bannerlord/my-buffs']=c.buffs_empty;await s.load('Buffs');expect(s.controller.cooldown('weapon_power')).toBe(0);
});
it('pre-action build response cannot unlock the new-build family after a queued activation',async()=>{
  const s=await setup(),waiting=deferred<Response>();s.routes['/api/bannerlord/build']=waiting.promise;const poll=s.controller.refreshBuild();await s.click('[data-bnr-build-activate="rage"]');waiting.resolve(response(c.build_combat_one_handed));await act(async()=>{await poll;await flush();});expect(s.controller.snapshot().buildPending).toBe(true);expect(s.button('[data-bnr-build-activate="heal_burst"]').disabled).toBe(true);
});
it('development and weapon selection share a synchronous family lock before any rerender',async()=>{
  const build={...f.build_ready,build:{...f.build_ready.build,power_options:c.build_choices.build.power_options}},waiting=deferred<Response>();const s=await setup({'/api/bannerlord/build':build,'/api/bannerlord/action':waiting.promise});
  await act(async()=>{s.button('[data-bnr-build-spec="assault"]').click();s.button('[data-bnr-build-select="bow"]').click();await flush();});expect(s.posts()).toHaveLength(1);waiting.resolve(response(f.specialization_success.response));await act(flush);expect(s.button('[data-bnr-build-select="bow"]').disabled).toBe(true);
});
it('weapon selection blocks development and heal in the same frame',async()=>{
  const build={...f.build_ready,build:{...f.build_ready.build,power_options:c.build_choices.build.power_options}},waiting=deferred<Response>();const s=await setup({'/api/bannerlord/build':build,'/api/bannerlord/action':waiting.promise});
  await act(async()=>{s.button('[data-bnr-build-select="bow"]').click();s.button('[data-bnr-build-spec="assault"]').click();s.button('[data-bnr-build-activate="heal_burst"]').click();await flush();});expect(s.posts()).toHaveLength(1);waiting.resolve(response(c.select_bow.response));await act(flush);
});
it('old viewer balance, battle, build and action cannot populate or refresh a new viewer',async()=>{
  const s=await setup(),balance=deferred<Response>(),battle=deferred<Response>(),build=deferred<Response>(),action=deferred<Response>();
  s.routes['/api/viewer/stats/alice']=balance.promise;const r1=s.controller.refreshBalance();s.routes['/api/bannerlord/battle-status']=battle.promise;const r2=s.controller.refreshBattle();s.routes['/api/bannerlord/build']=build.promise;const r3=s.controller.refreshBuild();s.routes['/api/bannerlord/action']=action.promise;await s.click('[data-bnr-build-activate="rage"]');
  s.routes['/api/user/resolve-twitch-token']={login:'carol'};s.routes['/api/bannerlord/battle-status']=c.battle_idle;s.routes['/api/bannerlord/build']=c.build_combat_bow;
  await act(async()=>{s.authorize({...initial,userId:'opaque-carol',token:'carol-token'});await flush();});const before=s.trace.length;
  balance.resolve(response(f.stats));battle.resolve(response(c.battle_siege));build.resolve(response(c.build_combat_one_handed));action.resolve(response(c.build_power_one_handed.response));await act(async()=>{await Promise.all([r1,r2,r3]);await flush();});
  expect(s.controller.snapshot().points).toBe(0);expect(s.controller.snapshot().battle?.in_battle).toBe(false);expect(s.controller.snapshot().build?.build?.selected_weapon_type).toBe('bow');expect(s.trace.slice(before)).toEqual([]);expect(s.controller.snapshot().buildPending).toBe(false);
});
it('unknown mutation result locks every combat mutation but leaves safe reads usable',async()=>{
  const s=await setup({'/api/bannerlord/action':{}});await s.click('[data-bnr-build-activate="rage"]');expect(s.controller.snapshot().mutationBlocked).toBe(true);
  for(const q of ['[data-stance="aggressive"]','#bnr-summon-enemy-btn','[data-det-act="hero.detach_hold"]','[data-bnr-build-activate="heal_burst"]']){expect(s.button(q).disabled).toBe(true);await s.click(q);}
  expect(s.posts()).toHaveLength(1);await s.load('Battle');expect(s.controller.snapshot().battle?.in_battle).toBe(true);
});
it('same-user token refresh keeps combat rendered but cannot dispatch while resolution is pending',async()=>{
  const s=await setup(),waiting=deferred<Response>();const b=s.button('[data-bnr-build-activate="rage"]');s.routes['/api/user/resolve-twitch-token']=waiting.promise;s.authorize({...initial,token:'rotated'});b.click();await act(flush);expect(s.posts()).toHaveLength(0);waiting.resolve(response({login:'alice'}));await act(flush);expect(s.button('[data-bnr-build-activate="rage"]')).toBe(b);await s.click('[data-bnr-build-activate="rage"]');expect(s.posts()[0].token).toBe('rotated');
});
it('unmount cancels combat polls, action tails and stale response ownership',async()=>{
  const s=await setup();await s.click('[data-bnr-build-activate="rage"]');s.ui.unmount();const before=s.trace.length;await vi.advanceTimersByTimeAsync(30000);expect(s.trace).toHaveLength(before);expect(s.controller.snapshot().battle).toBeNull();
});
it('old stance refusal cannot roll back a later accepted optimistic choice',async()=>{
  const first=deferred<Response>(),second=deferred<Response>();const s=await setup({'/api/bannerlord/action':first.promise});await s.click('[data-stance="aggressive"]');s.routes['/api/bannerlord/action']=second.promise;await s.click('[data-stance="defensive"]');second.resolve(response(c.stance_defensive.response));await act(flush);first.resolve(response(c.order_poor_refuse.response));await act(flush);expect(s.button('[data-stance="defensive"]').getAttribute('aria-pressed')).toBe('true');
});
for(const field of ['buffs','battle','build'])it(`${field} read failure closes its dependent combat actions without legacy fallback`,async()=>{
  const s=await setup();s.routes['/api/bannerlord/'+({buffs:'my-buffs',battle:'battle-status',build:'build'}[field])]={success:false,message:'Текущие данные недоступны'};await s.load(({buffs:'Buffs',battle:'Battle',build:'Build'} as const)[field as 'buffs'|'battle'|'build']);
  expect(s.ui.container.querySelector('[data-bnr-power]')).toBeNull();const button=s.ui.container.querySelector('[data-bnr-build-activate="rage"]') as HTMLButtonElement|null;expect(!button || button.disabled).toBe(true);
});
it('known new build remains new through a later disabled/null reply',async()=>{
  const s=await setup();s.routes['/api/bannerlord/build']=c.build_no_session;await s.load('Build');expect(s.controller.snapshot().newBuild).toBe(true);expect(s.ui.container.querySelector('[data-bnr-power]')).toBeNull();
});
it('only strict boolean siege permits wall and gate; unknown order/buff are safe text',async()=>{
  const s=await setup({'/api/bannerlord/battle-status':{...c.battle_siege,is_siege:'true',my_stats:{...c.battle_siege.my_stats,order_status:'<img src=x onerror=alert(1)>'}},'/api/bannerlord/my-buffs':{success:true,buffs:[{power_key:'<b>unknown</b>',remaining_s:1.2}],cooldowns:[]}});
  expect(s.button('[data-det-act="hero.detach_walls"]').disabled).toBe(true);expect(s.ui.container.textContent).toContain('Статус приказа неизвестен');expect(s.ui.container.querySelector('#bnr-buff-hud')?.textContent).toContain('<b>unknown</b> 2с');expect(s.ui.container.querySelector('#bnr-buff-hud b')).toBeNull();
  s.routes['/api/bannerlord/my-buffs']=c.buffs_empty;await s.advance(2000);expect(s.ui.container.querySelector('#bnr-buff-hud')?.textContent).toBe('');
});
it('queued stance followed by its own later mod refusal restores confirmed stance',async()=>{
  const s=await setup({'/api/bannerlord/action':c.stance_aggressive.response});await s.click('[data-stance="aggressive"]');expect(s.button('[data-stance="aggressive"]').getAttribute('aria-pressed')).toBe('true');s.routes['/api/bannerlord/my-hero']=c.hero_refund_stance_aggressive;await s.load('Hero');expect(s.button('[data-stance="balanced"]').getAttribute('aria-pressed')).toBe('true');expect(s.ui.getAllByText('❌ Сейчас недоступно')).toHaveLength(1);
});
it('older refunded stance does not clear a newer accepted optimistic stance',async()=>{
  const s=await setup({'/api/bannerlord/action':c.stance_aggressive.response});await s.click('[data-stance="aggressive"]');s.routes['/api/bannerlord/action']=c.stance_defensive.response;await s.click('[data-stance="defensive"]');s.routes['/api/bannerlord/my-hero']=c.hero_refund_stance_aggressive;await s.load('Hero');expect(s.button('[data-stance="defensive"]').getAttribute('aria-pressed')).toBe('true');
});
it('unknown asynchronous refusal does not expose raw diagnostics, clears across identity change',async()=>{
  const s=await setup({'/api/bannerlord/my-hero':{...f.hero,recent_refunds:[{action_id:'test-future',type:'power.activate',reason:'exception:private-debug-path',refunded:true}]}});expect(s.ui.getAllByText('❌ Действие не удалось — крустики возвращены')).toHaveLength(1);expect(s.ui.container.textContent).not.toContain('private-debug-path');s.routes['/api/user/resolve-twitch-token']={login:'carol'};s.routes['/api/bannerlord/my-hero']=f.hero;await act(async()=>{s.authorize({...initial,userId:'opaque-carol',token:'carol-token'});await flush();});expect(s.ui.queryByText('❌ Действие не удалось — крустики возвращены')).toBeNull();
});
for(const battle of [c.battle_idle,c.battle_not_spawned,c.battle_dead])it(`new build participant gate in_battle=${battle.in_battle} alive=${battle.my_stats?.alive}`,async()=>{
  const s=await setup({'/api/bannerlord/battle-status':battle});for(const q of ['[data-bnr-build-activate="rage"]','[data-bnr-build-activate="heal_burst"]']){expect(s.button(q).disabled).toBe(true);await s.click(q);}expect(s.posts()).toHaveLength(0);
});
it('unknown legacy power keys cannot manufacture controls',async()=>{
  const s=await setup({'/api/bannerlord/build':c.build_no_session,'/api/bannerlord/classes':{...c.classes_by_key.tank,current_powers:[{power_key:'imaginary_power',price:10}]}});expect(s.ui.container.querySelector('[data-bnr-power]')).toBeNull();
});
for(const [saved,expected] of [['combat','Боевые действия'],['hero','Развитие'],['inventory','Снаряжение'],['dynasty','Боевые действия'],['invalid','Боевые действия']])it(`first open preserves supported saved tab ${saved}`,async()=>{const s=await setup({},saved);expect(s.firstTab).toBe(expected);});
it('60-second balance phase survives same-viewer token resolution without leaking old authorization',async()=>{
  const s=await setup({'/api/viewer/stats/alice':{...f.stats,points:299}});await s.advance(30000);await act(async()=>{s.authorize({...initial,token:'rotated'});await flush();});s.routes['/api/viewer/stats/alice']={...f.stats,points:300};const before=s.trace.filter(r=>r.path==='/api/viewer/stats/alice').length;await s.advance(30000);const reads=s.trace.filter(r=>r.path==='/api/viewer/stats/alice');expect(reads).toHaveLength(before+1);expect(reads.at(-1)?.token).toBe('rotated');expect(s.button('[data-bnr-build-activate="rage"]').disabled).toBe(false);
});
