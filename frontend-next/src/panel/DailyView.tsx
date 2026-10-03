import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import type {PanelController} from './controller';
import {heroContext} from './contracts';
type Reward='gold'|'xp';
interface Daily {success:boolean;can_claim:boolean;last_claim_date?:string|null;today_date?:string;last_reward_type?:Reward|null;reward_amounts?:Partial<Record<Reward,number>>}
const amount=(n:unknown):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0;
export function DailyView({controller}:{controller:PanelController}){
  const state=useSyncExternalStore(controller.subscribe,controller.snapshot);
  const [localDaily,setDaily]=useState<Daily|null>(null),[pending,setPending]=useState(false),[error,setError]=useState('');
  const daily=controller.isHosted()?state.daily||null:localDaily;
  const current=useRef<Daily|null>(null),sequence=useRef(0),mounted=useRef(true),claiming=useRef(false);
  if(controller.isHosted())current.current=daily;
  useLayoutEffect(()=>()=>{mounted.current=false;sequence.current++;},[]);
  const refresh=async()=>{
    if(controller.isHosted()){await controller.refreshDaily();return;}
    if(!controller.ready()||!controller.snapshot().hero?.hero?.is_alive)return;
    const owns=controller.captureRequestOwner(),hero=heroContext(controller.snapshot().hero),issued=++sequence.current;
    try{
      const reply=await controller.read<Daily>('/api/bannerlord/daily-status');
      if(!mounted.current||!owns()||issued!==sequence.current||hero!==heroContext(controller.snapshot().hero))return;
      current.current=reply;setDaily(reply);setError('');
    }catch(e){if(mounted.current&&owns()&&issued===sequence.current){current.current=null;setDaily(null);setError(e instanceof Error?e.message:'Не удалось загрузить награду');}}
  };
  useLayoutEffect(()=>{if(controller.isHosted())return;if(state.hero?.hero?.is_alive)void refresh();else {sequence.current++;current.current=null;setDaily(null);}},[state.hero,state.generation]);
  const claim=async(kind:Reward)=>{
    const shown=daily,latest=current.current;
    if(!controller.ready()||controller.snapshot().mutationBlocked||claiming.current||!shown?.can_claim||JSON.stringify(shown)!==JSON.stringify(latest)||!amount(shown.reward_amounts?.[kind]))return;
    const owns=controller.captureRequestOwner();claiming.current=true;setPending(true);
    await controller.post('/api/bannerlord/daily-claim',{reward_type:kind},'Заявка на ежедневную награду принята. Ждём начисления в игре.');
    if(!mounted.current||!owns())return;
    claiming.current=false;setPending(false);void refresh();controller.scheduleOwnedRead(1500,()=>controller.refreshHero());
  };
  if(!state.hero?.hero?.is_alive)return null;
  const reward=daily?.last_reward_type;
  return <section className="panel-card" aria-label="Ежедневная награда"><h2>Ежедневная награда</h2>
    {error?<p role="alert">{error}</p>:!daily?<p role="status">Проверяем доступность награды…</p>:daily.can_claim?<><p>Выбери одну награду. Она поступит после обработки заявки в игре.</p><div className="panel-choices">{(['gold','xp'] as const).map(kind=><button type="button" key={kind} id={'bnr-daily-claim-'+kind} disabled={!state.canAct||state.mutationBlocked||pending||!amount(daily.reward_amounts?.[kind])} onClick={()=>void claim(kind)}>{amount(daily.reward_amounts?.[kind])?`+${daily.reward_amounts![kind]!.toLocaleString('ru-RU')} ${kind==='gold'?'💰 динаров':'XP'}`:'Размер награды не получен'}</button>)}</div></>:<><p>Сегодня уже забрал: {reward&&amount(daily.reward_amounts?.[reward])?`${daily.reward_amounts![reward]!.toLocaleString('ru-RU')} ${reward==='gold'?'💰 динаров':'XP'}`:'награда получена'}.</p><p className="panel-muted">Следующая награда доступна после 00:00 UTC.</p></>}
  </section>;
}
