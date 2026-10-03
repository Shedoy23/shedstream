import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import type {PanelController} from './controller';
import {heroContext,validPrice} from './contracts';
import {clanInfo} from './party';
import {contentEntries} from './progression';
type Kind='workshop'|'caravan';
type ReadKey=Kind|'fiefs'|'inheritance';
interface Property {id:number;settlement_id?:string;settlement_name?:string;workshop_type?:string;workshop_type_name?:string;home_settlement_id?:string;home_settlement_name?:string;party_id?:string;status?:string;total_profit?:number;total_collected_dinars?:number}
interface Fief {id:number;fief_id:string;fief_name?:string;fief_type:string;total_collected_dinars:number;boost_active?:boolean}
interface Inheritance {id:number;asset_name?:string;asset_type:string;inherited_at:string;total_value:number}
interface Reply {success:boolean;message?:string;workshops?:Property[];caravans?:Property[];fiefs?:Fief[];items?:Inheritance[];max_workshops?:number;max_caravans?:number}
interface Town {id:string;name:string;type:string;faction_n?:string;faction?:string}
const paths:Record<ReadKey,string>={workshop:'/api/bannerlord/my-workshops',fiefs:'/api/bannerlord/my-fiefs',caravan:'/api/bannerlord/my-caravans',inheritance:'/api/bannerlord/inheritance-log?limit=15'};
const fmt=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)?n.toLocaleString('ru-RU'):'—';
const prefix=(kind:Kind)=>kind==='workshop'?'ws':'caravan';
const label=(kind:Kind)=>kind==='workshop'?'мастерскую':'караван';
const identity=(row:Property)=>JSON.stringify([row.id,row.settlement_id,row.workshop_type,row.home_settlement_id,row.party_id]);
export function PropertiesView({controller,active}:{controller:PanelController;active:boolean}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot);
  const [data,setData]=useState<Partial<Record<ReadKey,Reply>>>({}),latest=useRef(data);
  const dataContexts=useRef<Partial<Record<ReadKey,string>>>({});
  const [errors,setErrors]=useState<Partial<Record<ReadKey,string>>>({});
  const [forms,setForms]=useState({workshop:false,caravan:false}),[chosen,setChosen]=useState({workshop:'',caravan:'',type:''});
  const [towns,setTowns]=useState<Town[]>([]),townCache=useRef<{at:number;context:string;items:Town[]}|null>(null),townFlight=useRef<Promise<void>|null>(null);
  const mounted=useRef(true),selected=useRef(active);selected.current=active;
  const sequences=useRef<Record<ReadKey,number>>({workshop:0,caravan:0,fiefs:0,inheritance:0});
  const context=()=>JSON.stringify([controller.identityGeneration(),heroContext(controller.snapshot().hero),clanInfo(controller.snapshot().hero)?.is_leader,controller.snapshot().catalogs?.save_id,controller.snapshot().catalogs?.equipment_session_id]);
  const observed=context();
  const [confirm,setConfirm]=useState<{kind:Kind;buy:boolean;data:Record<string,unknown>;quote:string;message:string;owns:()=>boolean}|null>(null),confirmation=useRef(confirm);confirmation.current=confirm;
  const busy=useRef(false),[pending,setPending]=useState(false),details=useRef<Record<string,boolean>>({workshops:true,caravans:true,fiefs:true});
  const available=()=>mounted.current&&controller.ready()&&!!controller.snapshot().hero?.hero?.is_alive&&!!clanInfo(controller.snapshot().hero)?.is_leader;
  const read=async(key:ReadKey)=>{
    if(!available())return;
    const owns=controller.captureRequestOwner(),seen=context(),issued=++sequences.current[key];
    try{
      const reply=await controller.read<Reply>(paths[key]);
      if(!mounted.current||!owns()||seen!==context()||issued!==sequences.current[key])return;
      if(!reply?.success)throw Error(reply?.message||'Не удалось обновить данные');
      dataContexts.current[key]=seen;latest.current={...latest.current,[key]:reply};setData(latest.current);setErrors(e=>({...e,[key]:''}));
    }catch(error){if(mounted.current&&owns()&&seen===context()&&issued===sequences.current[key])setErrors(e=>({...e,[key]:error instanceof Error?error.message:'Ошибка сети'}));}
  };
  useLayoutEffect(()=>()=>{mounted.current=false;confirmation.current=null;},[]);
  useLayoutEffect(()=>{setForms({workshop:false,caravan:false});setChosen({workshop:'',caravan:'',type:''});setTowns([]);},[observed]);
  useLayoutEffect(()=>controller.registerDynastyRead('properties',()=>{void read('workshop');void read('fiefs');void read('caravan');void read('inheritance');}),[controller]);
  useLayoutEffect(()=>{if(!controller.isHosted()&&active&&!document.hidden&&available()){void read('workshop');void read('fiefs');void read('caravan');void read('inheritance');}},[s.hero,active]);
  const rows=(kind:Kind)=>{const reply=latest.current[kind];return (kind==='workshop'?reply?.workshops:reply?.caravans)||[];};
  const price=(kind:Kind)=>controller.snapshot().config?.[kind+'_price'];
  const limit=(kind:Kind)=>kind==='workshop'?latest.current[kind]?.max_workshops:latest.current[kind]?.max_caravans;
  const fresh=(kind:Kind)=>dataContexts.current[kind]===context();
  const mayBuy=(kind:Kind)=>fresh(kind)&&validPrice(price(kind))&&Number.isSafeInteger(limit(kind))&&rows(kind).length<limit(kind)!;
  const types=contentEntries(s.catalogs?.workshop_types);
  const quote=(kind:Kind,buy:boolean,body:Record<string,unknown>)=>JSON.stringify([context(),buy?price(kind):0,buy?limit(kind):null,buy?rows(kind).length:identity(rows(kind).find(r=>r.id===body[kind+'_id'])||{id:-1}),buy&&kind==='workshop'?controller.snapshot().catalogs?.workshop_types:null,buy?townCache.current?.items.find(t=>t.id===body[kind==='workshop'?'settlement_id':'home_settlement_id']):null]);
  const canConfirm=()=>{const c=confirmation.current;return !!c&&available()&&selected.current&&!controller.snapshot().mutationBlocked&&!busy.current&&c.owns()&&c.quote===quote(c.kind,c.buy,c.data)&&(!c.buy||mayBuy(c.kind));};
  useLayoutEffect(()=>{if(confirmation.current&&!canConfirm()){confirmation.current=null;setConfirm(null);}},[s,data,active]);
  const loadTowns=async()=>{
    const seen=context(),cache=townCache.current;
    if(cache&&cache.context===seen&&Date.now()-cache.at<60000){setTowns(cache.items);return;}
    if(townFlight.current)return townFlight.current;
    const owns=controller.captureRequestOwner();
    const flight=(async()=>{
      try{
        const reply=await controller.read<{success:boolean;settlements?:Town[]}>('/api/bannerlord/settlements');
        if(!mounted.current||!owns()||seen!==context())return;
        const items=reply.success&&Array.isArray(reply.settlements)?reply.settlements.filter(t=>t&&typeof t.id==='string'&&t.type==='town').sort((a,b)=>(a.name||'').localeCompare(b.name||'','ru')):[];
        townCache.current={context:seen,at:Date.now(),items};setTowns(items);
      }catch{if(mounted.current&&owns()&&seen===context()){townCache.current=null;setTowns([]);}}
    })();townFlight.current=flight;
    try{await flight;}finally{if(townFlight.current===flight)townFlight.current=null;}
  };
  const track=(name:string,open:boolean,section=false)=>{if(open&&!details.current[name])controller.trackSection('bannerlord:'+(section?'section.':'details.')+name);details.current[name]=open;};
  const toggle=(kind:Kind,open:boolean)=>{track(prefix(kind)+'-buy',open);if(open&&!forms[kind]){setChosen(c=>({...c,[kind]:'',type:kind==='workshop'?(types.find(t=>t.available!==false)?.id||''):c.type}));void loadTowns();}setForms(f=>({...f,[kind]:open}));};
  const ask=(kind:Kind,buy:boolean,row?:Property)=>{
    if(!available()||!selected.current||!fresh(kind)||controller.snapshot().mutationBlocked||pending||observed!==context())return;
    let body:Record<string,unknown>,message:string;
    if(buy){
      const town=townCache.current?.items.find(t=>t.id===chosen[kind]);
      const type=contentEntries(controller.snapshot().catalogs?.workshop_types).find(t=>t.id===chosen.type&&t.available!==false);
      if(!mayBuy(kind)||townCache.current?.context!==context()||!town||kind==='workshop'&&!type)return;
      body=kind==='workshop'?{settlement_id:town.id,settlement_name:town.name||town.id,workshop_type:type!.id,workshop_type_name:type!.name||type!.id}:{home_settlement_id:town.id,home_settlement_name:town.name||town.id};
      message=`Купить ${label(kind)} в ${town.name||town.id} за ${fmt(price(kind))} 💎? Динары героя не списываются. Итог подтвердит игра.`;
    }else{
      if(!row||!rows(kind).some(r=>identity(r)===identity(row)))return;
      body=kind==='workshop'?{workshop_id:row.id}:{caravan_id:row.id};message=`Продать ${label(kind)}? Отменить нельзя. Сумму возврата определит игра.`;
    }
    setConfirm({kind,buy,data:body,quote:quote(kind,buy,body),message,owns:controller.captureRequestOwner()});
  };
  const submit=async()=>{
    const c=confirmation.current,valid=canConfirm();confirmation.current=null;setConfirm(null);if(!c||!valid)return;
    busy.current=true;setPending(true);if(c.buy)setForms(f=>({...f,[c.kind]:false}));
    await controller.action(`hero.${c.buy?'buy':'sell'}_${c.kind}`,c.data,{tail:'hero',successMessage:'Заявка принята. Ждём подтверждения изменения имущества в игре.'});
    if(!mounted.current||!c.owns())return;
    busy.current=false;setPending(false);controller.scheduleOwnedRead(c.buy?2000:1500,()=>read(c.kind));
  };
  const property=(kind:Kind)=>{
    const reply=data[kind],items=kind==='workshop'?reply?.workshops:reply?.caravans,max=limit(kind),p=price(kind),key=prefix(kind);
    return <details className="panel-card" data-bnr-section={kind==='workshop'?'workshops':'caravans'} open onToggle={e=>track(kind==='workshop'?'workshops':'caravans',e.currentTarget.open,true)}><summary>{kind==='workshop'?'🏭 Мои мастерские':'🐪 Мои караваны'} ({items?.length??'—'}/{max??'—'})</summary>
      <p>Доход в динарах накапливается у героя. Крустики пассивно не выдаются.{kind==='caravan'?' Бандиты могут уничтожить караван.':''}</p>{errors[kind]&&<p role="alert">{errors[kind]}</p>}
      {!fresh(kind)&&<p role="status">Ждём данные имущества текущего сохранения.</p>}
      {!reply?<p role="status">Загружаем имущество…</p>:<>{items?.map(row=><article key={row.id} {...{['data-'+kind+'-id']:row.id}}><h3>{kind==='workshop'?row.workshop_type_name||row.workshop_type:row.home_settlement_name||row.home_settlement_id}</h3>{kind==='workshop'&&<p>{row.settlement_name||row.settlement_id}</p>}<p>Заработано: {fmt(kind==='workshop'?row.total_profit:row.total_collected_dinars)} 💰</p><button type="button" className={'bnr-'+key+'-sell'} disabled={!active||!s.canAct||s.mutationBlocked||pending||!fresh(kind)} onClick={()=>ask(kind,false,row)}>Продать</button></article>)}
      {Number.isSafeInteger(max)&&items&&items.length>=max!?<p>Достигнут лимит: {max}</p>:<details data-bnr-details={key+'-buy'} open={forms[kind]} onToggle={e=>toggle(kind,e.currentTarget.open)}><summary>Купить {label(kind)} — {validPrice(p)?fmt(p)+' 💎':'цена недоступна'}</summary>{forms[kind]&&<div>
        {kind==='workshop'&&(!types.length?<p role="status">Каталог типов мастерских недоступен. Ждём данные игры.</p>:types.map(t=><label className="panel-party-radio" key={t.id}><input type="radio" name="bnr-ws-type" value={t.id} checked={chosen.type===t.id} disabled={t.available===false} onChange={()=>setChosen(c=>({...c,type:t.id}))}/>{t.name||t.id}{t.description&&<span> — {t.description}</span>}</label>))}
        <label>Город<select id={kind==='workshop'?'bnr-ws-town':'bnr-caravan-home'} value={chosen[kind]} onChange={e=>setChosen(c=>({...c,[kind]:e.currentTarget.value}))}><option value="">Выбери город из игры</option>{towns.map(t=><option key={t.id} value={t.id}>{t.name||t.id}</option>)}</select></label>{!towns.length&&<p>Игра ещё не передала города.</p>}
        <button type="button" id={'bnr-'+key+'-buy-confirm'} disabled={!active||!s.canAct||s.mutationBlocked||pending||!mayBuy(kind)||!chosen[kind]||kind==='workshop'&&!types.some(t=>t.id===chosen.type&&t.available!==false)} onClick={()=>ask(kind,true)}>Купить — {validPrice(p)?fmt(p)+' 💎':'цена недоступна'}</button>
      </div>}</details>}</>}
    </details>;
  };
  const days=new Map<string,Inheritance[]>();for(const item of data.inheritance?.items||[]){const day=item.inherited_at?.slice(0,10)||'';days.set(day,[...(days.get(day)||[]),item]);}
  return <section aria-label="Имущество и наследование">{property('workshop')}
    <details className="panel-card" data-bnr-section="fiefs" open onToggle={e=>track('fiefs',e.currentTarget.open,true)}><summary>🏰 Мои владения</summary>{errors.fiefs&&<p role="alert">{errors.fiefs}</p>}{data.fiefs?.fiefs?.length?data.fiefs.fiefs.map(f=><article key={f.id} data-fief-id={f.id}><h3>{f.fief_name||f.fief_id}</h3><p>{({town:'Город',castle:'Замок',village:'Деревня'} as Record<string,string>)[f.fief_type]||f.fief_type}{f.boost_active?' · BOOST':''}</p><p>Заработано: {fmt(f.total_collected_dinars)} 💰</p></article>):<p>Сведений о владениях пока нет.</p>}<p>Динары поступают герою. Платный бустер дохода недоступен.</p></details>
    {property('caravan')}<section className="panel-card" aria-label="Наследие"><h2>Наследие</h2>{errors.inheritance&&<p role="alert">{errors.inheritance}</p>}{days.size?[...days].map(([day,items])=><div key={day}><h3>{day||'Последнее наследование'}</h3><p>Всего: {fmt(items.reduce((n,i)=>n+(i.total_value||0),0))} динаров</p>{items.map(i=><p key={i.id}>{i.asset_name||i.asset_type} · {fmt(i.total_value)} динаров</p>)}</div>):<p>Переход имущества наследникам ещё не зарегистрирован.</p>}</section>
    {confirm&&<ConfirmDialog title={confirm.buy?'Подтвердить покупку имущества':'Подтвердить продажу имущества'} cancel={()=>{confirmation.current=null;setConfirm(null);}} confirm={()=>void submit()}><p>{confirm.message}</p></ConfirmDialog>}
  </section>;
}
