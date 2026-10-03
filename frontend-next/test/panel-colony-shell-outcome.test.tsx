import {act,cleanup,render} from '@testing-library/preact';
import {afterEach,expect,it,vi} from 'vitest';
import {TwitchAuthStore,type TwitchAuthorization} from '../src/auth';
import {IdentityBootstrap} from '../src/skillgames/identity';
import {ViewerRuntime,type ViewerHelper} from '../src/common/runtime';
import {ViewerShell} from '../src/common/ViewerShell';
import {PanelController} from '../src/panel/controller';
import {HttpPanelTransport} from '../src/panel/transport';
import {ColonyController} from '../src/colony/controller';
import {RimworldController} from '../src/rimworld/controller';
import policy from './panel-fixtures/colony-policy-responses.json';
import rimworld from './panel-fixtures/rimworld-responses.json';

// Real ViewerShell + IdentityBootstrap + ViewerRuntime, including the resolving
// gate that unmounts lazy game components. No mocked shell or forced rerender.
vi.setConfig({testTimeout:30000});
const stops:(()=>void)[]=[];
afterEach(()=>{cleanup();stops.splice(0).forEach(fn=>fn());localStorage.clear();vi.useRealTimers();});
const flush=async()=>{for(let i=0;i<80;i++)await Promise.resolve();};
const settle=async()=>{await flush();await vi.dynamicImportSettled();await flush();};
const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status});
const deferred=<T,>()=>{let resolve!:(value:T)=>void,reject!:(error:Error)=>void;const promise=new Promise<T>((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const initialChannel=policy.cases.rate_limited.request.identity.channelId;

async function shell(){
  vi.useFakeTimers();vi.setSystemTime(Date.UTC(2026,9,3,12));
  let login='alice',channel=initialChannel,activeModule:string|null='shedcolony',serial=0;
  let resolveIdentity=async()=>json({login});
  let actionReply=async()=>json({success:true,message:'Принято'});
  const trace:{path:string;method:string;token:string;body:unknown;rawBody:string|null}[]=[];
  const fetcher:typeof fetch=async(input,init={})=>{
    const path=new URL(String(input),'https://fixture.invalid').pathname,method=init.method||'GET',rawBody=init.body==null?null:String(init.body);
    trace.push({path,method,token:new Headers(init.headers).get('X-Twitch-JWT')||'',body:rawBody?JSON.parse(rawBody):null,rawBody});
    if(path==='/api/user/resolve-twitch-token')return resolveIdentity();
    if(path==='/api/shedcolony/action')return actionReply();
    if(path.startsWith('/api/viewer/stats/'))return json({points:100000,active_module:activeModule,income_per_min:25});
    if(path.startsWith('/api/user/level/'))return json({level:2});
    const rw=rimworld.responses;
    const routes:Record<string,unknown>={
      '/api/core/config':{tts_cost:7700,tts_max_len:190},'/api/viewer/online-list':{users:[]},'/api/viewer/online':{status:'ok'},'/api/viewer/perks':{success:true},'/api/notices':{success:true,notices:[]},'/api/duel/list':{},
      '/api/viewer/activity':{status:'ok'},'/api/viewer/attendance':{rewarded:false},'/api/viewer/ui-usage':{success:true},
      '/api/shedcolony/config':{action_prices:{'colonist.heal':1459}},'/api/shedcolony/my-colonist':{success:true,linked:true,citizen_id:41,name:login,state:{hp:12,max_hp:20}},'/api/shedcolony/capacity':{success:true,stale:false},
      '/api/rimworld/config':rw.config,'/api/rimworld/status':rw.status,'/api/rimworld/colonists':rw.colonists,'/api/rimworld/my-pawn/alice':rw.empty_pawn,'/api/rimworld/catalog':rw.catalog,'/api/rimworld/events':rw.events,
    };
    if(!(path in routes))throw new Error('Unmatched full shell route '+method+' '+path);
    return json(routes[path]);
  };
  const auth=new TwitchAuthStore(),identity=new IdentityBootstrap(auth,'',fetcher,{panelProtocol:true});
  const runtime=new ViewerRuntime(auth,identity,{baseUrl:'',surface:'desktop',fetcher}),colony=new ColonyController(runtime),rim=new RimworldController(runtime);
  const controller=new PanelController(new HttpPanelTransport('',auth,fetcher),auth,identity,Date.now,runtime.usage);
  controller.useHostUsage();controller.useHostBalance({refresh:()=>runtime.snapshot().client?.refreshUser()||Promise.resolve(),points:()=>Number(runtime.snapshot().stats?.points)});controller.bindHost(runtime);
  const callbacks:((value:TwitchAuthorization)=>void)[]=[];
  const helper:ViewerHelper={onAuthorized:fn=>{callbacks.push(fn);},listen:()=>{},unlisten:()=>{}};
  runtime.start();runtime.attach(helper);const detach=identity.attach(helper);stops.push(()=>{detach();runtime.stop();});
  const authorization=()=>({token:'fixture.'+btoa(JSON.stringify({user_id:login==='alice'?'456':'789',channel_id:channel}))+'.rotation'+(++serial),userId:login==='alice'?'Ualice':'Ubob',channelId:channel,clientId:'fixture-extension'});
  const ui=render(<ViewerShell auth={auth} identity={identity} runtime={runtime} controller={controller} colony={colony} rimworld={rim}/>);
  const firstAuthorization=authorization();await act(async()=>{callbacks.forEach(cb=>cb(firstAuthorization));await settle();});
  await act(async()=>{ui.getByRole('button',{name:'Игра',exact:true}).click();await settle();});
  const button=()=>ui.container.querySelector<HTMLButtonElement>('[data-sc="heal"]')!;
  expect(button()?.disabled).toBe(false);
  const posts=()=>trace.filter(q=>q.path==='/api/shedcolony/action');
  const buy=async()=>{
    await act(async()=>{button().click();await flush();});
    const confirm=ui.queryByRole('button',{name:'Подтвердить',exact:true});
    if(confirm)await act(async()=>{confirm.click();await flush();});
  };
  async function beginAuthorization(nextLogin=login,nextChannel=channel){
    const oldButton=button(),held=deferred<Response>();login=nextLogin;channel=nextChannel;resolveIdentity=()=>held.promise;
    const next=authorization();await act(async()=>{callbacks.forEach(cb=>cb(next));await settle();});
    expect(identity.snapshot().status).toBe('resolving');expect(ui.queryByRole('heading',{name:'Колония стримера'})).toBeNull();expect(oldButton.isConnected,'the real resolving gate must unmount the old ColonyView').toBe(false);
    return async()=>{await act(async()=>{held.resolve(json({login}));await settle();});expect(identity.snapshot().status).toBe('ready');expect(button()).not.toBe(oldButton);resolveIdentity=async()=>json({login});};
  }
  async function module(value:string|null){activeModule=value;await act(async()=>{await runtime.snapshot().client!.refreshUser();await settle();});await act(settle);}
  return {ui,button,posts,buy,beginAuthorization,module,runtime,trace,setReply:(fn:()=>Promise<Response>)=>{actionReply=fn;}};
}

it.each(['before-refresh','during-resolver','after-remount'] as const)('colony shell unknown response %s stays blocked after held same-viewer JWT resolution',async timing=>{
  const p=await shell(),held=deferred<Response>();p.setReply(()=>held.promise);await p.buy();expect(p.posts()).toHaveLength(1);
  if(timing==='before-refresh')await act(async()=>{held.reject(new Error('Response lost'));await flush();});
  const ready=await p.beginAuthorization();
  if(timing==='during-resolver')await act(async()=>{held.reject(new Error('Response lost'));await flush();});
  await ready();
  if(timing==='after-remount')await act(async()=>{held.reject(new Error('Response lost'));await flush();});
  await p.buy();expect(p.posts(),'same-viewer remount must not send a second paid POST after an unknown outcome').toHaveLength(1);
  expect(p.button().disabled).toBe(true);expect(p.ui.container.textContent).toContain('Исход заявки неизвестен');
});

it('colony shell a still pending POST also survives JWT remount and a definite refusal releases it',async()=>{
  const p=await shell(),held=deferred<Response>();p.setReply(()=>held.promise);await p.buy();const ready=await p.beginAuthorization();await ready();await p.buy();
  const sent=p.posts().length;await act(async()=>{held.resolve(json({success:false,message:'Определённый отказ'}));await flush();});
  expect(sent,'a pending admitted action must survive the same remount').toBe(1);expect(p.button().disabled).toBe(false);expect(p.ui.container.textContent).toContain('Определённый отказ');
});

it.each(['viewer','channel'] as const)('colony shell unknown guard belongs to its %s and survives leaving then returning',async kind=>{
  const p=await shell();p.setReply(async()=>{throw new Error('Response lost');});await p.buy();
  await (await p.beginAuthorization(kind==='viewer'?'bob':'alice',kind==='channel'?'999':initialChannel))();
  expect(p.button().disabled,'a different owner must not inherit the unknown outcome').toBe(false);p.setReply(async()=>json({success:true}));await p.buy();expect(p.posts()).toHaveLength(2);
  await (await p.beginAuthorization('alice',initialChannel))();await p.buy();expect(p.posts(),'returning to the original owner must restore its unknown guard').toHaveLength(2);expect(p.button().disabled).toBe(true);
});

it('colony shell old-owner response loss cannot overwrite a different owner pending action',async()=>{
  const p=await shell(),old=deferred<Response>(),next=deferred<Response>();p.setReply(()=>old.promise);await p.buy();await (await p.beginAuthorization('bob'))();p.setReply(()=>next.promise);await p.buy();
  await act(async()=>{old.reject(new Error('Response lost'));await flush();});expect(p.button().disabled).toBe(true);expect(p.ui.container.textContent).not.toContain('Исход заявки неизвестен');
  await act(async()=>{next.resolve(json({success:false,message:'Отказ для bob'}));await flush();});expect(p.button().disabled).toBe(false);expect(p.ui.container.textContent).toContain('Отказ для bob');
  await (await p.beginAuthorization('alice'))();await p.buy();expect(p.posts(),'late old-owner loss must be retained for that owner').toHaveLength(2);expect(p.button().disabled).toBe(true);
});

it('colony shell exact captured pre-action 429 remains a definite refusal across remount',async()=>{
  const p=await shell(),r=policy.cases.rate_limited.response;p.setReply(async()=>new Response(r.raw_body,{status:r.status,headers:r.headers}));await p.buy();
  expect(p.ui.container.textContent).toContain(r.body.detail.message);expect(p.ui.container.textContent).not.toContain('Исход заявки неизвестен');
  await (await p.beginAuthorization())();expect(p.button().disabled).toBe(false);await p.buy();expect(p.posts()).toHaveLength(2);
});

it('colony shell successful requests keep confirmations exact bodies and balance tails through remount',async()=>{
  const p=await shell();await p.buy();expect(p.ui.container.textContent).toContain('Заявка принята');await (await p.beginAuthorization())();expect(p.button().disabled).toBe(false);await p.buy();expect(p.posts()).toHaveLength(2);
  for(const row of p.posts()){expect(row.body).toEqual({action_type:'colonist.heal',data:{client_action_id:expect.any(String)}});expect(row.rawBody).toBe(JSON.stringify(row.body));}
  expect(p.posts()[0].token).not.toBe(p.posts()[1].token);
  const last=p.trace.lastIndexOf(p.posts()[1]);expect(p.trace.slice(last+1).map(q=>q.path)).toContain('/api/viewer/stats/alice');
});

it('colony shell another active game does not erase the Colony unknown outcome on return',async()=>{
  const p=await shell();p.setReply(async()=>{throw new Error('Response lost');});await p.buy();await p.module('rimworld');expect(p.button()).toBeNull();expect(p.ui.container.textContent).toContain('RimWorld');expect(p.posts()).toHaveLength(1);
  await p.module('shedcolony');await p.buy();expect(p.posts(),'switching active games must not reset the Colony owner guard').toHaveLength(1);expect(p.button().disabled).toBe(true);
});
