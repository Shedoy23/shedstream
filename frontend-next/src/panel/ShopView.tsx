import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import {heroContext,validPrice} from './contracts';
import {isGoldPreset,type ShopItem} from './commerce';
import {progressionQuote,progressionReason} from './progression';
import type {PanelController} from './controller';
type Kind='gold'|'xp'|'catalog';
interface Choice {kind:Kind;id:string;type:string;body:Record<string,unknown>;label:string;price:number;quote:string;owns:()=>boolean}
const denied=['hero.add_skill','hero.add_focus','hero.add_attribute'];
const itemKey=(i:ShopItem)=>JSON.stringify([i.catalog_type,i.entry_id]);
export function ShopView({controller}:{controller:PanelController}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),[confirm,setConfirm]=useState<Choice|null>(null),confirmation=useRef(confirm);confirmation.current=confirm;
  const mounted=useRef(true);useLayoutEffect(()=>()=>{mounted.current=false;},[]);
  const presets=()=>{const p=controller.snapshot().config?.give_gold_presets;return Array.isArray(p)?p.filter(isGoldPreset):[];};
  const items=()=>controller.snapshot().shop?.success?(controller.snapshot().shop?.items||[]).filter(i=>!denied.includes(i.action_type||i.entry_id)):[];
  const offer=(kind:Kind,id:string)=>{
    const state=controller.snapshot();
    if(kind==='gold'){const p=presets().find(p=>String(p.crusticov)===id);return p?{type:'player.give_item',body:{price:p.crusticov,item_type:'gold'},price:p.crusticov,label:'+'+p.dinars.toLocaleString('ru-RU')+' динаров',source:p}:null;}
    if(kind==='xp'){const p=state.progression?.xp_offers?.find(p=>p.id===id),body=progressionQuote(state.progression,'xp',id,state.hero);return p&&body?{type:'hero.add_skill',body,price:p.price,label:'+'+p.xp+' XP в случайный навык',source:p}:null;}
    const p=items().find(p=>itemKey(p)===id),type=p?.action_type||p?.entry_id;return p&&type&&validPrice(p.price)?{type,body:{price:p.price},price:p.price,label:p.name||p.entry_id,source:p}:null;
  };
  const quote=(kind:Kind,id:string)=>JSON.stringify([controller.identityGeneration(),heroContext(controller.snapshot().hero),controller.snapshot().catalogs?.save_id,controller.snapshot().catalogs?.equipment_session_id,offer(kind,id)]);
  const allowed=(kind:Kind,id:string)=>{const o=offer(kind,id),state=controller.snapshot();return mounted.current&&controller.ready()&&!state.mutationBlocked&&!!o&&state.points!==null&&state.points>=o.price&&controller.cooldown(o.type)<=0&&!state.busy.some(k=>k.startsWith(o.type+':'));};
  useLayoutEffect(()=>{const c=confirmation.current;if(c&&(!allowed(c.kind,c.id)||!c.owns()||c.quote!==quote(c.kind,c.id))){confirmation.current=null;setConfirm(null);}},[s]);
  const choose=(kind:Kind,id:string)=>{const o=offer(kind,id);if(!o||!allowed(kind,id))return;setConfirm({kind,id,...o,quote:quote(kind,id),owns:controller.captureRequestOwner()});};
  const submit=()=>{const c=confirmation.current;confirmation.current=null;setConfirm(null);if(!c||!allowed(c.kind,c.id)||!c.owns()||c.quote!==quote(c.kind,c.id))return;void controller.action(c.type,c.body,{tail:/^(hero|player|power|tournament)\./.test(c.type)?'hero':'balance',successMessage:'Заявка принята. Ждём результата в игре.'});};
  return <section className="panel-card" aria-label="Магазин Bannerlord"><h2>Магазин Bannerlord</h2><p aria-label="Подключение Bannerlord">{s.status?.success?s.status.online?'🟢 Онлайн':'🔴 Оффлайн':'Статус подключения не получен'}</p>
    <h3>Динары герою</h3><div className="panel-choices">{presets().map(p=><button type="button" key={p.crusticov} data-bnr-givegold={p.crusticov} disabled={!allowed('gold',String(p.crusticov))} onClick={()=>choose('gold',String(p.crusticov))}>+{p.dinars.toLocaleString('ru-RU')} 💰 · {p.crusticov.toLocaleString('ru-RU')} 💎</button>)}</div>{!presets().length&&<p>Предложения динаров не получены.</p>}
    <h3>Опыт в случайный навык</h3><div className="panel-choices">{s.progression?.xp_offers?.map(p=><article key={p.id}><p>+{p.xp} XP · {validPrice(p.price)?p.price.toLocaleString('ru-RU')+' 💎':'Цена не получена'}</p><button type="button" data-bnr-skillxp={p.id} disabled={!allowed('xp',p.id)} onClick={()=>choose('xp',p.id)}>Купить опыт</button>{(!p.available||s.progression?.pending)&&<p>{s.progression?.pending?progressionReason(s.progression):p.reason_text||p.reason||'Предложение недоступно'}</p>}</article>)}</div>{!s.progression?.xp_offers?.length&&<p>{progressionReason(s.progression)}</p>}
    {s.shop?.success?items().map(i=><article key={itemKey(i)}><h3>{i.name||i.entry_id}</h3><p>{i.catalog_type}{i.description?' · '+i.description:''}</p><button type="button" data-bnr-buy={i.action_type||i.entry_id} disabled={!allowed('catalog',itemKey(i))} onClick={()=>choose('catalog',itemKey(i))}>{validPrice(i.price)?i.price.toLocaleString('ru-RU')+' 💎':'Цена не получена'}</button></article>):<p>{s.errors.shop||s.shop?.message||'Загружаем каталог…'}</p>}
    {confirm&&<ConfirmDialog title="Подтвердить покупку Bannerlord" cancel={()=>{confirmation.current=null;setConfirm(null);}} confirm={submit}><p>{confirm.label} · {confirm.price.toLocaleString('ru-RU')} 💎. Подтвердить?</p></ConfirmDialog>}
  </section>;
}
