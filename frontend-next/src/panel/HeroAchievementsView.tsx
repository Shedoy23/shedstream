import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import type {PanelController} from './controller';
interface Achievement {id:string;name:string;description:string;icon:string;threshold:number;current_value:number;unlocked:boolean;unlocked_at:string|null}
interface Reply {success:boolean;achievements:Achievement[];total:number;unlocked_count:number;message?:string}
export function HeroAchievementsView({controller,active}:{controller:PanelController;active:boolean}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),[data,setData]=useState<Reply|null>(null),[error,setError]=useState(''),[open,setOpen]=useState(false);
  const opened=useRef(false),mounted=useRef(true),sequence=useRef(0),selected=useRef(active);selected.current=active;
  useLayoutEffect(()=>()=>{mounted.current=false;},[]);
  useLayoutEffect(()=>{sequence.current++;opened.current=false;setOpen(false);setData(null);setError('');},[s.generation]);
  const load=async()=>{if(!mounted.current||!controller.ready()||!selected.current)return;const owns=controller.captureRequestOwner(),seq=++sequence.current;setData(null);setError('');try{const r=await controller.read<Reply>('/api/bannerlord/achievements');if(!mounted.current||!owns()||seq!==sequence.current)return;if(!r.success||!Array.isArray(r.achievements))throw Error(r.message||'Не удалось загрузить достижения');setData(r);}catch(e){if(mounted.current&&owns()&&seq===sequence.current)setError(e instanceof Error?e.message:'Ошибка сети');}};
  const toggle=(next:boolean)=>{if(next===opened.current)return;opened.current=next;setOpen(next);if(next){controller.trackSection('bannerlord:details.inv-achievements');void load();}};
  return <details className="panel-card" data-bnr-details="inv-achievements" open={open} onToggle={e=>toggle(e.currentTarget.open)}><summary>Достижения героя</summary>{open&&<>{error?<p role="alert">{error}</p>:data?<><p>Открыто {data.unlocked_count}/{data.total}</p>{data.achievements.map(a=><article key={a.id} data-hero-achievement={a.id}><h3>{a.icon} {a.name}</h3><p>{a.description}</p><p>{a.unlocked?'Открыто · ':''}{a.current_value.toLocaleString('ru-RU')} / {a.threshold.toLocaleString('ru-RU')}</p><progress aria-label={'Прогресс: '+a.name} max={100} value={a.unlocked?100:a.threshold>0?Math.min(100,Math.max(0,Math.round(a.current_value/a.threshold*100))):0}/></article>)}{!data.achievements.length&&<p>Нет данных.</p>}</>:<p>Загружаем достижения…</p>}</>}</details>;
}
