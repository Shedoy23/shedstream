import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,render} from '@testing-library/preact';
import {ColonyController} from '../src/colony/controller';
import {ColonyView} from '../src/colony/ColonyView';
import {ViewerClient} from '../src/common/client';
import policy from './panel-fixtures/colony-policy-responses.json';

const stops:(()=>void)[]=[];
afterEach(()=>{cleanup();stops.splice(0).forEach(fn=>fn());vi.useRealTimers();});
const flush=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status});
const citizen=(id:number)=>({success:true,linked:true,citizen_id:id,name:'Алиса',state:{hp:10,max_hp:20}});
const capacity={success:true,stale:false};
// Manually constructed UI data. Policy responses below are captured unchanged ASGI responses.
function client(fetcher:typeof fetch,channelId='33'){return new ViewerClient({login:'alice',channelId,token:'synthetic'},'',fetcher);}
function polling(){
  vi.useFakeTimers();const game=new ColonyController();stops.push(()=>game.stop());let number=0;
  const waiting:{id:number;finish:()=>void}[]=[];
  const c=client(async input=>{const url=String(input);if(url.endsWith('/config'))return json({});if(url.endsWith('/capacity'))return json(capacity);const id=++number;return new Promise<Response>(resolve=>waiting.push({id,finish:()=>resolve(json(citizen(id)))}));});
  game.attach(c);return {game,waiting};
}
it('review colony six-second responses keep advancing under a five-second poll',async()=>{
  vi.useFakeTimers();let issued=0;const game=new ColonyController();stops.push(()=>game.stop());
  game.attach(client(async input=>{if(String(input).endsWith('/config'))return json({});if(String(input).endsWith('/capacity'))return json(capacity);const id=++issued;return new Promise<Response>(resolve=>setTimeout(()=>resolve(json(citizen(id))),6000));}));
  await flush();await vi.advanceTimersByTimeAsync(6000);expect(game.snapshot().citizen?.citizen_id,'first slow snapshot must be applied despite another poll in flight').toBe(2);
  await vi.advanceTimersByTimeAsync(5000);expect(game.snapshot().citizen?.citizen_id).toBe(3);
  await vi.advanceTimersByTimeAsync(5000);expect(game.snapshot().citizen?.citizen_id).toBe(4);
});
it('review colony reverse completion never rolls back a fresher applied snapshot',async()=>{
  const s=polling();await flush();await vi.advanceTimersByTimeAsync(5000);s.waiting[2].finish();await flush();expect(s.game.snapshot().citizen?.citizen_id).toBe(3);s.waiting[1].finish();s.waiting[0].finish();await flush();expect(s.game.snapshot().citizen?.citizen_id).toBe(3);
});
it('review colony old identity completion cannot populate a new channel',async()=>{
  const s=polling();await flush();s.game.attach(client(async input=>json(String(input).endsWith('/config')?{}:String(input).endsWith('/capacity')?capacity:citizen(99)),'99'));await flush();s.waiting.forEach(q=>q.finish());await flush();expect(s.game.snapshot().citizen?.citizen_id).toBe(99);
});

async function actionFixture(reply:()=>Promise<Response>,channelId='33'){
  let posts=0;
  const c=client(async(input,init)=>{if(init?.method==='POST'){posts++;return reply();}const u=String(input);return json(u.endsWith('/config')?{action_prices:{'colonist.heal':1200}}:u.endsWith('/capacity')?capacity:u.endsWith('/my-colonist')?citizen(41):{points:10000});},channelId);
  const ui=render(<ColonyView client={c}/>);await act(flush);
  const buy=async()=>{await act(async()=>{(ui.container.querySelector('[data-sc="heal"]') as HTMLButtonElement).click();});await act(async()=>{ui.getByRole('button',{name:'Подтвердить',exact:true}).click();await flush();});};
  return {ui,buy,posts:()=>posts,button:()=>ui.container.querySelector('[data-sc="heal"]') as HTMLButtonElement};
}
for(const name of ['rate_limited','pending','unregistered'] as const)it(`review colony actual ${name} policy refusal preserves message and permits explicit retry`,async()=>{
  const response=policy.cases[name].response;const s=await actionFixture(async()=>new Response(response.raw_body,{status:response.status,headers:response.headers}),policy.cases[name].request.identity.channelId);await s.buy();expect(s.ui.getByRole('status').textContent).toBe(response.body.detail.message);expect(s.button().disabled).toBe(false);expect(s.posts()).toBe(1);await s.buy();expect(s.posts()).toBe(2);
});
for(const name of ['network','timeout','generic400','generic429','server500','mixed','wrongChannel','viewerPoll','malformed'] as const)it(`review colony ${name} response stays unknown and blocks duplicate purchase`,async()=>{
  const detail={...policy.cases.rate_limited.response.body.detail,channel_id:33};
  const reply=async()=>{if(name==='network')throw new Error('lost');if(name==='timeout')throw new DOMException('timeout','TimeoutError');if(name==='generic400')return json({message:'failed'},400);if(name==='generic429')return json({message:'failed'},429);if(name==='server500')return json({detail},500);if(name==='mixed')return json({detail,success:false},429);if(name==='wrongChannel')return json({detail:{...detail,channel_id:99}},429);if(name==='viewerPoll')return json({detail:{...detail,scope:'viewer_poll'}},429);return new Response('not JSON',{status:429});};
  const s=await actionFixture(reply);await s.buy();expect(s.ui.getByRole('status').textContent).toContain('Исход заявки неизвестен');expect(s.button().disabled).toBe(true);s.button().click();await act(flush);expect(s.posts()).toBe(1);
});
