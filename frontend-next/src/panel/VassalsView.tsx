import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import {heroContext,validPrice} from './contracts';
import {clanInfo,goldPrice} from './party';
import type {PanelController} from './controller';
interface Vassal {id:number;vassal_clan_id:string;vassal_leader_hero_id:string;vassal_name:string;income_share_pct:number}
interface Heir {hero_id:string;name:string}
interface Observation {vassals:Vassal[];heirs:Heir[];context:string}
interface Edit {kind:'create'|'rename';id?:number;context:string;owns:()=>boolean}
const kind=(e:Edit)=>e.kind==='create'?'hero.create_vassal_clan':'hero.rename_vassal';
export function VassalsView({controller,active}:{controller:PanelController;active:boolean}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot);
  const [data,setData]=useState<Observation|null>(null),current=useRef(data),[error,setError]=useState('');
  const [editor,setEditor]=useState<Edit|null>(null),editing=useRef(editor);editing.current=editor;
  const [draft,setDraft]=useState({name:'',heir:''}),values=useRef(draft);values.current=draft;
  const [confirm,setConfirm]=useState<{edit:Edit;quote:string;body:Record<string,unknown>}|null>(null),confirmation=useRef(confirm);confirmation.current=confirm;
  const mounted=useRef(true),selected=useRef(active),sequence=useRef(0),pending=useRef(false),[busy,setBusy]=useState(false);selected.current=active;
  const context=()=>JSON.stringify([controller.identityGeneration(),heroContext(controller.snapshot().hero),clanInfo(controller.snapshot().hero)?.name,clanInfo(controller.snapshot().hero)?.is_leader,controller.snapshot().catalogs?.save_id,controller.snapshot().catalogs?.equipment_session_id]);
  const available=()=>mounted.current&&controller.ready()&&!!controller.snapshot().hero?.hero?.is_alive&&!!clanInfo(controller.snapshot().hero)?.is_leader;
  const quote=(e:Edit)=>JSON.stringify([context(),controller.snapshot().config?.action_prices?.[kind(e)],e.kind==='create'?goldPrice(controller.snapshot(),'create_vassal_clan'):current.current?.vassals.find(v=>v.id===e.id)]);
  const canEdit=(e:Edit)=>available()&&selected.current&&!controller.snapshot().mutationBlocked&&e.owns()&&e.context===context()&&current.current?.context===context()&&(e.kind==='create'||current.current.vassals.some(v=>v.id===e.id));
  const cost=(e:Edit)=>e.kind==='create'?goldPrice(controller.snapshot(),'create_vassal_clan'):controller.snapshot().config?.action_prices?.[kind(e)];
  const allowed=(e:Edit)=>canEdit(e)&&validPrice(cost(e))&&validPrice(controller.snapshot().config?.action_prices?.[kind(e)])&&controller.cooldown(kind(e))<=0&&(e.kind!=='create'||Number(controller.snapshot().hero?.hero?.gold)>=Number(cost(e)));
  const priceText=(e:Edit)=>validPrice(cost(e))?Number(cost(e)).toLocaleString('ru-RU')+(e.kind==='create'?' 💰':' 💎'):'Цена не получена';
  const close=()=>{editing.current=null;setEditor(null);confirmation.current=null;setConfirm(null);};
  const load=async()=>{
    // Preserve the legacy editor's read pause; owner/context changes still close it.
    if(!available()||editing.current)return;
    const owns=controller.captureRequestOwner(),seen=context(),seq=++sequence.current;
    try{const [v,h]=await Promise.all([controller.read<{success:boolean;vassals:Vassal[]}>('/api/bannerlord/vassals'),controller.read<{success:boolean;heirs:Heir[]}>('/api/bannerlord/eligible-heirs')]);
      if(!mounted.current||!owns()||seen!==context()||seq!==sequence.current||editing.current)return;
      if(!v.success||!h.success||!Array.isArray(v.vassals)||!Array.isArray(h.heirs))throw Error('Не удалось обновить вассалов');
      current.current={vassals:v.vassals,heirs:h.heirs,context:seen};setData(current.current);setError('');
    }catch(e){if(mounted.current&&owns()&&seen===context()&&seq===sequence.current){current.current=null;setError(e instanceof Error?e.message:'Ошибка сети');}}
  };
  useLayoutEffect(()=>()=>{mounted.current=false;},[]);
  useLayoutEffect(()=>controller.registerDynastyRead('vassals',()=>{void load();}),[controller]);
  useLayoutEffect(()=>{if(editing.current&&!canEdit(editing.current))close();if(!controller.isHosted()&&active&&!document.hidden)void load();},[s.hero,active]);
  useLayoutEffect(()=>{if(editing.current&&!canEdit(editing.current)||confirmation.current&&(!canEdit(confirmation.current.edit)||confirmation.current.quote!==quote(confirmation.current.edit))){close();}},[s,active,data]);
  const fresh=(type:Edit['kind'],id?:number):Edit=>({kind:type,id,context:context(),owns:controller.captureRequestOwner()});
  const begin=(type:Edit['kind'],id?:number)=>{const e=fresh(type,id);if(!allowed(e)||pending.current)return;sequence.current++;values.current={name:type==='rename'?current.current!.vassals.find(v=>v.id===id)!.vassal_name:'',heir:current.current!.heirs[0]?.hero_id||''};setDraft(values.current);editing.current=e;setEditor(e);setError('');};
  const update=(key:'name'|'heir',value:string)=>{values.current={...values.current,[key]:value};setDraft(values.current);};
  const prepare=()=>{const e=editing.current,d=values.current,name=d.name.trim();if(!e||!allowed(e)||pending.current||!name||name.length>50)return;
    if(e.kind==='rename'&&name===current.current!.vassals.find(v=>v.id===e.id)!.vassal_name){close();return;}
    if(e.kind==='create'&&(name.length<2||!current.current!.heirs.some(h=>h.hero_id===d.heir)))return;
    const body=e.kind==='create'?{heir_hero_id:d.heir,vassal_name:name}:{vassal_id:e.id!,new_name:name};
    setConfirm({edit:e,body,quote:quote(e)});
  };
  const submit=async()=>{const c=confirmation.current;confirmation.current=null;setConfirm(null);if(!c||!allowed(c.edit)||c.quote!==quote(c.edit)||pending.current)return;
    const e=c.edit;pending.current=true;setBusy(true);if(e.kind==='create'){editing.current=null;setEditor(null);}
    const result=await controller.action(kind(e),c.body,{tail:'hero',successMessage:'Заявка принята. Ждём изменения вассального клана в игре.'});
    if(!mounted.current)return;pending.current=false;setBusy(false);
    if(!e.owns()){close();if(available())void load();return;}
    if(e.context!==context())return;
    if(e.kind==='create')controller.scheduleOwnedRead(2000,load);
    else if(result?.success){close();controller.scheduleOwnedRead(1500,load);}
    else setError(result?.message||controller.snapshot().message||'Не удалось отправить переименование');
  };
  return <section className="panel-card" aria-label="Вассальные кланы"><h2>Вассальные кланы</h2>{error&&<p role="alert">{error}</p>}{!data?<p>Загружаем вассалов…</p>:<>
    {data.vassals.map(v=><article key={v.id} data-vassal-id={v.id}><h3>{v.vassal_name}</h3><p>Доля дохода: {v.income_share_pct}%</p>{editor?.kind==='rename'&&editor.id===v.id?<form data-bnr-vassal-rename-form onSubmit={e=>{e.preventDefault();prepare();}}><label>Новое имя клана<input name="name" value={draft.name} maxLength={50} disabled={busy} onInput={e=>update('name',e.currentTarget.value)}/></label><button type="submit" disabled={busy||!allowed(editor)}>Сохранить · {priceText(editor)}</button><button type="button" disabled={busy} onClick={close}>Отмена</button></form>:<button type="button" className="bnr-vas-rename" disabled={busy||!allowed(fresh('rename',v.id))} onClick={()=>begin('rename',v.id)}>Переименовать · {priceText(fresh('rename',v.id))}</button>}</article>)}
    {!data.vassals.length&&<p>Подтверждённых вассалов пока нет.</p>}
    {!!data.heirs.length&&<details data-bnr-details="vas-create" open={editor?.kind==='create'} onToggle={e=>{if(e.currentTarget.open&&editing.current?.kind!=='create'){controller.trackSection('bannerlord:details.vas-create');begin('create');}else if(!e.currentTarget.open&&editing.current?.kind==='create')close();}}><summary>Создать вассальный клан · {priceText(fresh('create'))}</summary>{editor?.kind==='create'&&<><p>Выдели взрослого наследника в отдельный клан. Доступность и лимит проверит сервер.</p><label>Наследник<select id="bnr-vas-heir-pick" value={draft.heir} onChange={e=>update('heir',e.currentTarget.value)}>{data.heirs.map(h=><option key={h.hero_id} value={h.hero_id}>{h.name}</option>)}</select></label><label>Имя нового клана<input id="bnr-vas-name-input" value={draft.name} maxLength={50} onInput={e=>update('name',e.currentTarget.value)}/></label><button type="button" id="bnr-vas-confirm" disabled={busy||!allowed(editor)||draft.name.trim().length<2} onClick={prepare}>Создать · {priceText(editor)}</button></>}</details>}
  </>}{confirm&&<ConfirmDialog title="Подтвердить действие с вассалом" cancel={()=>{confirmation.current=null;setConfirm(null);}} confirm={()=>void submit()}><p>{confirm.edit.kind==='create'?'Создать клан':'Переименовать клан'} «{String(confirm.body.vassal_name||confirm.body.new_name)}» за {priceText(confirm.edit)}?</p></ConfirmDialog>}</section>;
}
