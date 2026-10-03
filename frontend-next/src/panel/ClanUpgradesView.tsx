import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import {heroContext,validPrice} from './contracts';
import {clanInfo} from './party';
import type {PanelController} from './controller';
interface Upgrade {upgrade_id:string;name:string;description:string;tier:number;required_upgrade_id:string|null;gold_cost:number;effects:Record<string,unknown>;owned:boolean;pending:boolean;locked:boolean}
interface Catalog {success:boolean;upgrades:Upgrade[];hero_gold:number;message?:string}
const effects:Record<string,string>={renown_daily:'Слава в день',influence_daily:'Влияние в день',party_size_bonus:'Размер отряда',retinue_size_bonus:'Размер свиты',party_speed_bonus:'Скорость отряда',party_amount_bonus:'Лимит отрядов',army_speed_bonus:'Скорость армии'};
export function ClanUpgradesView({controller,active}:{controller:PanelController;active:boolean}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),[catalog,setCatalog]=useState<Catalog|null>(null),data=useRef(catalog),[error,setError]=useState('');
  const [open,setOpen]=useState(false),opened=useRef(false),[chosen,setChosen]=useState<string[]>([]),selection=useRef(chosen);selection.current=chosen;
  const mounted=useRef(true),selected=useRef(active),sequence=useRef(0),observed=useRef(''),pending=useRef(false),[busy,setBusy]=useState(false);selected.current=active;
  const context=()=>JSON.stringify([controller.identityGeneration(),heroContext(controller.snapshot().hero),clanInfo(controller.snapshot().hero)?.name,clanInfo(controller.snapshot().hero)?.is_leader,controller.snapshot().catalogs?.save_id,controller.snapshot().catalogs?.equipment_session_id]);
  const [confirm,setConfirm]=useState<{ids:string[];quote:string;owns:()=>boolean}|null>(null),confirmation=useRef(confirm);confirmation.current=confirm;
  const owner=context();
  const available=()=>mounted.current&&selected.current&&controller.ready()&&!!controller.snapshot().hero?.hero?.is_alive&&!!clanInfo(controller.snapshot().hero)?.is_leader;
  const rows=()=>[...(data.current?.upgrades||[])].sort((a,b)=>a.tier-b.tier);
  const affordable=(u:Upgrade)=>!u.owned&&!u.pending&&!u.locked&&validPrice(u.gold_cost)&&validPrice(data.current?.hero_gold)&&u.gold_cost<=data.current!.hero_gold;
  const picked=(ids=selection.current)=>rows().filter(u=>ids.includes(u.upgrade_id));
  const total=(ids=selection.current)=>picked(ids).reduce((n,u)=>n+u.gold_cost,0);
  const quote=(ids:string[])=>JSON.stringify([context(),data.current?.hero_gold,controller.snapshot().hero?.hero?.gold,picked(ids)]);
  const mayBuy=(ids=selection.current)=>available()&&observed.current===context()&&!controller.snapshot().mutationBlocked&&!pending.current&&ids.length>0&&picked(ids).length===ids.length&&picked(ids).every(affordable)&&total(ids)<=data.current!.hero_gold&&(!validPrice(controller.snapshot().hero?.hero?.gold)||total(ids)<=Number(controller.snapshot().hero!.hero!.gold));
  const load=async()=>{if(!available())return;const owns=controller.captureRequestOwner(),seen=context(),seq=++sequence.current;selection.current=[];setChosen([]);setError('');setCatalog(null);data.current=null;
    try{const r=await controller.read<Catalog>('/api/bannerlord/clan-upgrades');if(!mounted.current||!owns()||seen!==context()||seq!==sequence.current)return;if(!r.success||!Array.isArray(r.upgrades)||!validPrice(r.hero_gold))throw Error(r.message||'Не удалось загрузить улучшения');observed.current=seen;data.current=r;setCatalog(r);}catch(e){if(mounted.current&&owns()&&seen===context()&&seq===sequence.current)setError(e instanceof Error?e.message:'Ошибка сети');}
  };
  useLayoutEffect(()=>()=>{mounted.current=false;},[]);
  const previous=useRef(owner);
  useLayoutEffect(()=>{if(previous.current!==owner){previous.current=owner;sequence.current++;data.current=null;setCatalog(null);selection.current=[];setChosen([]);opened.current=false;setOpen(false);}},[owner]);
  useLayoutEffect(()=>{const c=confirmation.current;if(c&&(!mayBuy(c.ids)||!c.owns()||c.quote!==quote(c.ids))){confirmation.current=null;setConfirm(null);}},[s,catalog,active]);
  const toggle=(next:boolean)=>{if(next===opened.current)return;opened.current=next;setOpen(next);if(next){controller.trackSection('bannerlord:details.dyn-upgrades');void load();}};
  const prepare=()=>{if(!mayBuy())return;const ids=picked().map(u=>u.upgrade_id);setConfirm({ids,quote:quote(ids),owns:controller.captureRequestOwner()});};
  const submit=async()=>{const c=confirmation.current;confirmation.current=null;setConfirm(null);if(!c||!mayBuy(c.ids)||!c.owns()||c.quote!==quote(c.ids))return;pending.current=true;setBusy(true);const seen=context();
    const reply=await controller.post('/api/bannerlord/clan-upgrades/buy',{upgrade_ids:c.ids},'Заявка принята. Ждём подтверждения улучшений в игре.');
    if(!mounted.current)return;pending.current=false;setBusy(false);if(!c.owns()||seen!==context())return;
    // The legacy direct purchase starts the catalog read before the hero read;
    // it has neither the generic dispatcher tail nor a balance refresh.
    if(reply?.success){void load();void controller.refreshHero();}
  };
  return <details className="panel-card" data-bnr-details="dyn-upgrades" open={open} onToggle={e=>toggle(e.currentTarget.open)}><summary>Улучшения клана</summary>{open&&<>{error&&<p role="alert">{error}</p>}{!catalog&&!error?<p>Загружаем улучшения…</p>:catalog&&<><p>Доступно {catalog.hero_gold.toLocaleString('ru-RU')} 💰</p>{rows().map(u=><article key={u.upgrade_id} data-upgrade={u.upgrade_id}><h3>{u.name} · ступень {u.tier}</h3><p>{u.description}</p><p>{Object.entries(u.effects||{}).map(([key,value])=>(effects[key]||key)+': '+String(value)).join(' · ')}</p>{u.pending?<p>Ждём подтверждения игры</p>:u.owned?<p>Уже приобретено</p>:u.locked?<p>Нужно предыдущее улучшение: {catalog.upgrades.find(v=>v.upgrade_id===u.required_upgrade_id)?.name||u.required_upgrade_id}</p>:!validPrice(u.gold_cost)?<p>Цена не получена</p>:affordable(u)?<label><input type="checkbox" className="bnr-upg-check" data-bnr-upg-id={u.upgrade_id} checked={chosen.includes(u.upgrade_id)} disabled={busy||!active} onChange={e=>{selection.current=e.currentTarget.checked?[...selection.current,u.upgrade_id]:selection.current.filter(id=>id!==u.upgrade_id);setChosen(selection.current);}}/>Выбрать «{u.name}» · {u.gold_cost.toLocaleString('ru-RU')} 💰</label>:<p>Нужно {u.gold_cost.toLocaleString('ru-RU')} 💰</p>}</article>)}{!catalog.upgrades.length&&<p>Каталог улучшений пуст.</p>}<p>Выбрано: {chosen.length} · стоимость {total().toLocaleString('ru-RU')} 💰</p><button type="button" className="bnr-bulk-buy" disabled={!mayBuy()} onClick={prepare}>Купить выбранные улучшения</button></>}</>}{confirm&&<ConfirmDialog title="Купить улучшения клана" cancel={()=>{confirmation.current=null;setConfirm(null);}} confirm={()=>void submit()}><p>{picked(confirm.ids).map(u=>u.name).join(', ')}</p><p>Стоимость {total(confirm.ids).toLocaleString('ru-RU')} 💰. Подтвердить?</p></ConfirmDialog>}</details>;
}
