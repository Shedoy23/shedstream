import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import {heroContext,validPrice} from './contracts';
import {observedEquipment} from './commerce';
import {qualities,qualityKey} from './forge';
import {slotNames,statNames} from './equipment';
import type {PanelController} from './controller';
const type='hero.discard_item';
export function LegacyInventoryView({controller,active}:{controller:PanelController;active:boolean}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),[confirm,setConfirm]=useState<{slot:string;name:string;seen:string;owns:()=>boolean}|null>(null),confirmation=useRef(confirm);confirmation.current=confirm;
  const mounted=useRef(true),selected=useRef(active);selected.current=active;useLayoutEffect(()=>()=>{mounted.current=false;},[]);
  const item=(slot:string)=>observedEquipment(controller.snapshot().hero).find(([key])=>key===slot)?.[1];
  const price=()=>controller.snapshot().config?.action_prices?.[type];
  const identity=(slot:string)=>JSON.stringify([controller.identityGeneration(),heroContext(controller.snapshot().hero),controller.snapshot().catalogs?.save_id,controller.snapshot().catalogs?.equipment_session_id,item(slot),price()]);
  const allowed=(slot:string)=>mounted.current&&selected.current&&controller.ready()&&!controller.snapshot().mutationBlocked&&!controller.snapshot().hero?.equipment_shop_ready&&!!controller.snapshot().hero?.hero?.is_alive&&!!item(slot)&&validPrice(price())&&controller.cooldown(type)<=0&&!controller.snapshot().busy.some(key=>key.startsWith(type+':'));
  useLayoutEffect(()=>{const c=confirmation.current;if(c&&(!allowed(c.slot)||!c.owns()||c.seen!==identity(c.slot))){confirmation.current=null;setConfirm(null);}},[s,active]);
  const submit=async()=>{const c=confirmation.current;confirmation.current=null;setConfirm(null);if(!c||!allowed(c.slot)||!c.owns()||c.seen!==identity(c.slot))return;await controller.action(type,{slot:c.slot},{tail:'hero',successMessage:'Заявка на удаление вещи принята. Ждём подтверждения игры.'});if(mounted.current&&c.owns()){controller.scheduleOwnedRead(1200,()=>controller.refreshHero());controller.scheduleOwnedRead(3500,()=>controller.refreshHero());}};
  if(!s.hero?.has_hero||s.hero.equipment_shop_ready)return null;
  const rows=observedEquipment(s.hero);
  return <section className="panel-card" aria-label="Надетые вещи прежнего режима"><h2>Надетые вещи</h2>{rows.length?rows.map(([slot,it])=><article key={slot}><h3>{slotNames[slot]||slot} · {it.item_name||it.item_id}{typeof it.tier==='number'?' · T'+(it.tier+1):''}</h3>{it.quality&&<p>{qualities[qualityKey(it)]?.label||it.quality}</p>}<p>{Object.entries(it.stats||{}).filter(([,value])=>value!==null).map(([key,value])=>(statNames[key]||key)+': '+(typeof value==='object'?JSON.stringify(value):String(value))).join(' · ')}</p><button type="button" className="bnr-discard-btn" data-slot={slot} disabled={!allowed(slot)} onClick={()=>{if(allowed(slot))setConfirm({slot,name:it.item_name||it.item_id,seen:identity(slot),owns:controller.captureRequestOwner()});}}>Выбросить</button></article>):<p>Нет экипировки.</p>}{confirm&&<ConfirmDialog title="Выбросить вещь" cancel={()=>{confirmation.current=null;setConfirm(null);}} confirm={submit}><p>Выбросить «{confirm.name}»? Предмет пропадёт навсегда. Стоимость действия {price()} 💎, стоимость вещи не возвращается.</p></ConfirmDialog>}</section>;
}
