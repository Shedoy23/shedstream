import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import {heroContext,validPrice} from './contracts';
import {clanInfo} from './party';
import type {PanelController} from './controller';
interface Capture {captured_hero:string;captor_party:string;ransom_cost:number;pool_total:number;remaining:number;contributors:number;gear_tier:number;level:number}
const type='hero.pay_ransom';
export function RansomView({controller,active}:{controller:PanelController;active:boolean}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),[rows,setRows]=useState<Capture[]|null>(null),current=useRef(rows),[error,setError]=useState('');
  const mounted=useRef(true),selected=useRef(active),sequence=useRef(0),dataContext=useRef('');selected.current=active;
  const context=()=>JSON.stringify([controller.identityGeneration(),heroContext(controller.snapshot().hero),clanInfo(controller.snapshot().hero)?.name,clanInfo(controller.snapshot().hero)?.is_leader,controller.snapshot().catalogs?.save_id]);
  const available=()=>mounted.current&&controller.ready()&&!!controller.snapshot().hero?.hero?.is_alive&&!!clanInfo(controller.snapshot().hero)?.is_leader;
  const price=()=>controller.snapshot().config?.action_prices?.[type];
  const allowed=()=>available()&&selected.current&&dataContext.current===context()&&!controller.snapshot().mutationBlocked&&validPrice(price())&&controller.cooldown(type)<=0&&!controller.snapshot().busy.some(k=>k.startsWith(type+':'));
  const quote=(id:string)=>{const c=current.current?.find(r=>r.captured_hero===id);return JSON.stringify([context(),price(),c?.captured_hero,c?.captor_party,c?.ransom_cost]);};
  const [confirm,setConfirm]=useState<{id:string;quote:string;owns:()=>boolean}|null>(null),confirmation=useRef(confirm);confirmation.current=confirm;
  const load=async()=>{if(!available())return;const owns=controller.captureRequestOwner(),seen=context(),seq=++sequence.current;try{const r=await controller.read<{success:boolean;captures:Capture[];message?:string}>('/api/bannerlord/ransom-pool');if(!mounted.current||!owns()||seen!==context()||seq!==sequence.current)return;if(!r.success||!Array.isArray(r.captures))throw Error(r.message||'Не удалось обновить выкуп');dataContext.current=seen;current.current=r.captures;setRows(r.captures);setError('');}catch(e){if(mounted.current&&owns()&&seen===context()&&seq===sequence.current){dataContext.current='';setError(e instanceof Error?e.message:'Ошибка сети');}}};
  useLayoutEffect(()=>()=>{mounted.current=false;},[]);
  useLayoutEffect(()=>controller.registerDynastyRead('ransom',()=>{void load();}),[controller]);
  useLayoutEffect(()=>{if(!controller.isHosted()&&active&&!document.hidden)void load();},[s.hero,active]);
  useLayoutEffect(()=>{const c=confirmation.current;if(c&&(!allowed()||!c.owns()||c.quote!==quote(c.id))){confirmation.current=null;setConfirm(null);}},[s,rows,error,active]);
  const submit=async()=>{const c=confirmation.current;confirmation.current=null;setConfirm(null);if(!c||!allowed()||!c.owns()||c.quote!==quote(c.id))return;await controller.action(type,{captured_hero:c.id},{tail:'hero',successMessage:'Взнос принят. Освобождение героя подтвердит игра после сбора выкупа.'});if(mounted.current&&c.owns())controller.scheduleOwnedRead(1200,load);};
  return <section className="panel-card" aria-label="Выкуп пленных"><h2>Выкуп пленных</h2>{error&&<p role="alert">{error}</p>}{rows?rows.length?rows.map(c=><article key={c.captured_hero} data-captured={c.captured_hero}><h3>@{c.captured_hero}</h3><p>Пленитель: {c.captor_party||'Неизвестен'} · T{c.gear_tier} · уровень {c.level}</p><progress max={Math.max(1,c.ransom_cost)} value={Math.min(c.ransom_cost,c.pool_total)} aria-label={'Сбор выкупа для '+c.captured_hero}/><p>{c.pool_total} / {c.ransom_cost} 💎 · осталось {c.remaining} · взносов {c.contributors}</p><button type="button" className="bnr-ransom-pay" disabled={!allowed()} onClick={()=>{if(allowed())setConfirm({id:c.captured_hero,quote:quote(c.captured_hero),owns:controller.captureRequestOwner()});}}>Внести {validPrice(price())?price()+' 💎':'— цена не получена'}</button></article>):<p>Пленных зрителей нет.</p>:<p>Загружаем сборы выкупа…</p>}{confirm&&<ConfirmDialog title="Внести выкуп" cancel={()=>{confirmation.current=null;setConfirm(null);}} confirm={()=>void submit()}><p>Внести {price()} 💎 в выкуп @{confirm.id}?</p></ConfirmDialog>}</section>;
}
