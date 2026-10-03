import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import {heroContext,validPrice} from './contracts';
import type {PanelController} from './controller';
type Kind='upgrade'|'reequip';
const action=(kind:Kind)=>kind==='upgrade'?'hero.upgrade_gear':'hero.reequip_gear';
export function LegacyGearView({controller}:{controller:PanelController}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),[confirm,setConfirm]=useState<{kind:Kind;quote:string;owns:()=>boolean}|null>(null),confirmation=useRef(confirm);confirmation.current=confirm;
  const mounted=useRef(true);useLayoutEffect(()=>()=>{mounted.current=false;},[]);
  const tier=()=>Number(controller.snapshot().hero?.hero?.gear_tier??0);
  const price=(kind:Kind)=>kind==='upgrade'?(controller.snapshot().config?.gear_upgrade_costs as Record<string,unknown>|undefined)?.[String(tier()+1)]:controller.snapshot().config?.action_prices?.[action(kind)];
  const quote=(kind:Kind)=>JSON.stringify([controller.identityGeneration(),heroContext(controller.snapshot().hero),controller.snapshot().classes?.current?.class_key,controller.snapshot().hero?.equipment_shop_ready,controller.snapshot().hero?.equipment,tier(),price(kind)]);
  const allowed=(kind:Kind)=>mounted.current&&controller.ready()&&!controller.snapshot().mutationBlocked&&!!controller.snapshot().hero?.hero?.is_alive&&!controller.snapshot().hero?.equipment_shop_ready&&!!controller.snapshot().classes?.current?.class_key&&(kind==='reequip'||validPrice(price(kind)))&&(kind!=='upgrade'||Number(controller.snapshot().hero?.hero?.gold)>=Number(price(kind)))&&controller.cooldown(action(kind))<=0&&!controller.snapshot().busy.some(k=>k.startsWith(action(kind)+':'));
  useLayoutEffect(()=>{const c=confirmation.current;if(c&&(!allowed(c.kind)||!c.owns()||c.quote!==quote(c.kind))){confirmation.current=null;setConfirm(null);}},[s]);
  const choose=(kind:Kind)=>{if(allowed(kind))setConfirm({kind,quote:quote(kind),owns:controller.captureRequestOwner()});};
  const submit=()=>{const c=confirmation.current;confirmation.current=null;setConfirm(null);if(c&&allowed(c.kind)&&c.owns()&&c.quote===quote(c.kind))void controller.action(action(c.kind),{},{tail:'hero',successMessage:'Заявка принята. Ждём обновления снаряжения в игре.'});};
  if(!s.hero?.hero?.is_alive||s.hero.equipment_shop_ready)return null;
  return <section className="panel-card" aria-label="Снаряжение прежнего режима"><h2>Снаряжение · T{tier()}</h2>{!s.classes?.current?.class_key?<p>Сначала выбери класс героя.</p>:<><div className="panel-choices">{validPrice(price('upgrade'))?<button type="button" id="bnr-inline-upgrade-btn" disabled={!allowed('upgrade')} onClick={()=>choose('upgrade')}>Улучшить до T{tier()+1} · {Number(price('upgrade')).toLocaleString('ru-RU')} 💰</button>:<p>Следующее улучшение не передано сервером.</p>}<button type="button" id="bnr-reequip-btn" disabled={!allowed('reequip')} onClick={()=>choose('reequip')}>Пересобрать снаряжение</button></div></>}{confirm&&<ConfirmDialog title="Изменить снаряжение" cancel={()=>{confirmation.current=null;setConfirm(null);}} confirm={submit}><p>{confirm.kind==='upgrade'?`Улучшить снаряжение до T${tier()+1} за ${Number(price('upgrade')).toLocaleString('ru-RU')} 💰?`:`Пересобрать снаряжение текущего тира?`}</p></ConfirmDialog>}</section>;
}
