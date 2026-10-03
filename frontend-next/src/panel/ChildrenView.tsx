import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import {heroContext,validPrice} from './contracts';
import {clanInfo} from './party';
import type {PanelController} from './controller';
interface Child {hero_id:string;name:string;came_of_age_at?:string}
interface Proposal {id:number;proposer_username?:string;target_username?:string;proposer_child_name:string;target_child_name:string;created_at?:string;expires_at?:string}
type Kind='rename'|'looks'|'respec'|'propose'|'respond'|'cancel';
const types:Record<Kind,string>={rename:'hero.rename_child',looks:'hero.change_child_looks',respec:'hero.respec_child_skills',propose:'hero.propose_marriage',respond:'hero.respond_marriage_proposal',cancel:'hero.cancel_proposal'};
const titles:Record<Kind,string>={rename:'Переименовать ребёнка',looks:'Изменить внешность ребёнка',respec:'Сбросить навыки ребёнка',propose:'Предложить брак детей',respond:'Ответить на предложение',cancel:'Отозвать предложение'};
interface Family {children:Child[];incoming:Proposal[];outgoing:Proposal[];context:string}
interface Choice {kind:Kind;child?:Child;proposal?:Proposal;accept?:boolean;seen:string;owns:()=>boolean}
const username=(value:string)=>value.trim().toLowerCase().replace(/^@/,'');
export function ChildrenView({controller,active}:{controller:PanelController;active:boolean}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot);
  const [family,setFamily]=useState<Family|null>(null),current=useRef(family),[heirs,setHeirs]=useState<Child[]|null>(null),[error,setError]=useState('');
  const familySeq=useRef(0),heirSeq=useRef(0),lookupSeq=useRef(0),mounted=useRef(true),selected=useRef(active);selected.current=active;
  const context=()=>JSON.stringify([controller.identityGeneration(),heroContext(controller.snapshot().hero),clanInfo(controller.snapshot().hero)?.name,clanInfo(controller.snapshot().hero)?.is_leader,controller.snapshot().catalogs?.save_id,controller.snapshot().catalogs?.equipment_session_id]);
  const alive=()=>mounted.current&&controller.ready()&&!!controller.snapshot().hero?.hero?.is_alive&&!!clanInfo(controller.snapshot().hero)?.is_leader;
  const loadHeirs=async()=>{if(!alive())return;const owns=controller.captureRequestOwner(),seen=context(),seq=++heirSeq.current;try{const r=await controller.read<{success:boolean;heirs:Child[]}>('/api/bannerlord/heirs');if(mounted.current&&owns()&&seen===context()&&seq===heirSeq.current&&r.success&&Array.isArray(r.heirs))setHeirs(r.heirs);}catch{/* A previous valid list remains readable. */}};
  const loadFamily=async()=>{
    if(!alive())return;const owns=controller.captureRequestOwner(),seen=context(),seq=++familySeq.current;
    try{const [children,proposals]=await Promise.all([controller.read<{success:boolean;children:Child[];message?:string}>('/api/bannerlord/my-children'),controller.read<{success:boolean;incoming:Proposal[];outgoing:Proposal[];message?:string}>('/api/bannerlord/proposals')]);
      if(!mounted.current||!owns()||seen!==context()||seq!==familySeq.current)return;
      if(!children.success||!proposals.success||!Array.isArray(children.children)||!Array.isArray(proposals.incoming)||!Array.isArray(proposals.outgoing))throw Error(children.message||proposals.message||'Не удалось обновить семью');
      current.current={children:children.children,incoming:proposals.incoming,outgoing:proposals.outgoing,context:seen};setFamily(current.current);setError('');
    }catch(e){if(mounted.current&&owns()&&seen===context()&&seq===familySeq.current){current.current=null;setError(e instanceof Error?e.message:'Ошибка сети');}}
  };
  useLayoutEffect(()=>()=>{mounted.current=false;lookupSeq.current++;},[]);
  useLayoutEffect(()=>controller.registerDynastyRead('children',()=>{void loadHeirs();void loadFamily();}),[controller]);
  useLayoutEffect(()=>{if(!controller.isHosted()&&active&&!document.hidden&&alive()){void loadHeirs();void loadFamily();}},[s.hero,active]);
  const [editor,setEditor]=useState<Choice|null>(null),[confirmation,setConfirmation]=useState<(Choice&{body:Record<string,unknown>;message:string})|null>(null);
  const editRef=useRef(editor),confirmRef=useRef(confirmation);editRef.current=editor;confirmRef.current=confirmation;
  const [draft,setDraft]=useState({text:'',username:'',target:''}),draftRef=useRef(draft);draftRef.current=draft;
  const [targets,setTargets]=useState<{username:string;children:Child[]}|null>(null),targetRef=useRef(targets);targetRef.current=targets;
  const [looking,setLooking]=useState(false),[lookupError,setLookupError]=useState('');
  const price=(kind:Kind)=>controller.snapshot().config?.action_prices?.[types[kind]];
  const quoted=(kind:Kind)=>validPrice(price(kind))?Number(price(kind)).toLocaleString('ru-RU')+' 💎':'Цена не получена';
  const allowed=(kind:Kind)=>selected.current&&alive()&&!controller.snapshot().mutationBlocked&&current.current?.context===context()&&validPrice(price(kind))&&!controller.snapshot().busy.some(x=>x.startsWith(types[kind]+':'))&&controller.cooldown(types[kind])<=0;
  const identity=(c:Pick<Choice,'kind'|'child'|'proposal'>)=>JSON.stringify([context(),price(c.kind),c.child?current.current?.children.find(x=>x.hero_id===c.child!.hero_id):null,c.proposal?(c.kind==='cancel'?current.current?.outgoing:current.current?.incoming)?.find(x=>x.id===c.proposal!.id):null]);
  const valid=(c:Choice)=>allowed(c.kind)&&c.owns()&&c.seen===identity(c)&&(!c.child||current.current!.children.some(x=>x.hero_id===c.child!.hero_id))&&(!c.proposal||(c.kind==='cancel'?current.current!.outgoing:current.current!.incoming).some(x=>x.id===c.proposal!.id));
  const cancel=()=>{editRef.current=null;confirmRef.current=null;setEditor(null);setConfirmation(null);lookupSeq.current++;setLooking(false);};
  useLayoutEffect(()=>{if(editRef.current&&!valid(editRef.current)||confirmRef.current&&!valid(confirmRef.current))cancel();},[s,family,active,error]);
  const run=async(c:Choice,body:Record<string,unknown>)=>{
    if(!valid(c))return;
    // Incoming responses register this continuation at click time in legacy;
    // prompt-based actions register it after their dispatcher promise resolves.
    if(c.kind==='respond')controller.scheduleOwnedRead(1500,loadFamily);
    const queued=['rename','looks','respec'].includes(c.kind)||c.kind==='respond'&&c.accept;
    await controller.action(types[c.kind],body,{tail:'hero',...(queued?{successMessage:'Заявка принята. Ждём изменения семьи в игре.'}:{})});
    if(mounted.current&&c.owns()&&c.kind!=='respec'&&c.kind!=='respond')controller.scheduleOwnedRead(1500,loadFamily);
  };
  const begin=(kind:Kind,child?:Child,proposal?:Proposal,accept?:boolean)=>{
    if(!allowed(kind))return;
    const c:Choice={kind,child,proposal,accept,seen:'',owns:controller.captureRequestOwner()};c.seen=identity(c);if(!valid(c))return;
    if(kind==='respond'){void run(c,{proposal_id:proposal!.id,accept:!!accept});return;}
    if(kind==='cancel'||kind==='respec'){
      setConfirmation({...c,body:kind==='cancel'?{proposal_id:proposal!.id}:{child_hero_id:child!.hero_id},message:kind==='cancel'?`Отозвать предложение «${proposal!.proposer_child_name} ❤ ${proposal!.target_child_name}»?`:`Сбросить все навыки «${child!.name}» за ${quoted(kind)}? Уровни обнулятся, вернуть их нельзя.`});return;
    }
    draftRef.current={text:kind==='rename'?child!.name:'',username:'',target:''};setDraft(draftRef.current);targetRef.current=null;setTargets(null);setLookupError('');setEditor(c);
  };
  const update=(key:keyof typeof draft,value:string)=>{draftRef.current={...draftRef.current,[key]:value};setDraft(draftRef.current);if(key==='username'){lookupSeq.current++;targetRef.current=null;setTargets(null);setLooking(false);}};
  const find=async()=>{
    const c=editRef.current,user=username(draftRef.current.username);if(!c||!valid(c)||!user)return;
    const seq=++lookupSeq.current;setLooking(true);setLookupError('');targetRef.current=null;setTargets(null);
    try{const reply=await controller.read<{success:boolean;target_username:string;children:Child[];message?:string}>('/api/bannerlord/public-children?username='+encodeURIComponent(user));
      if(!mounted.current||!valid(c)||seq!==lookupSeq.current||editRef.current!==c||user!==username(draftRef.current.username))return;
      if(!reply.success||reply.target_username!==user||!Array.isArray(reply.children))throw Error(reply.message||'Не удалось загрузить детей зрителя');
      targetRef.current={username:user,children:reply.children};setTargets(targetRef.current);update('target','');if(!reply.children.length)setLookupError('У этого зрителя нет взрослых детей.');
    }catch(e){if(mounted.current&&seq===lookupSeq.current)setLookupError(e instanceof Error?e.message:'Ошибка сети');}finally{if(mounted.current&&seq===lookupSeq.current)setLooking(false);}
  };
  const body=()=>{
    const c=editRef.current,d=draftRef.current;if(!c||!valid(c))return null;
    if(c.kind==='rename')return d.text&&d.text!==c.child!.name?{child_hero_id:c.child!.hero_id,new_name:d.text}:null;
    if(c.kind==='looks')return d.text.trim().length>=8?{child_hero_id:c.child!.hero_id,body_code:d.text.trim()}:null;
    const target=targetRef.current?.children.find(t=>t.hero_id===d.target),user=username(d.username);
    return target&&targetRef.current?.username===user?{price:price('propose'),proposer_child_hero_id:c.child!.hero_id,target_username:user,target_child_hero_id:target.hero_id}:null;
  };
  const prepare=()=>{const c=editRef.current,payload=body();if(!c||!payload)return;editRef.current=null;setEditor(null);setConfirmation({...c,body:payload,message:`${titles[c.kind]}: «${c.child!.name}»${c.kind==='propose'?' → @'+targetRef.current!.username+' / '+targetRef.current!.children.find(t=>t.hero_id===draft.target)!.name:''}. Стоимость ${quoted(c.kind)}. Подтвердить?`});};
  const submit=()=>{const c=confirmRef.current,ok=!!c&&valid(c);confirmRef.current=null;setConfirmation(null);if(c&&ok)void run(c,c.body);};
  return <><section className="panel-card" aria-label="Наследники"><h2>Наследники</h2>{heirs?.length?<><p>После смерти героя наследника активирует игра.</p><ol>{heirs.map(h=><li key={h.hero_id}>{h.name}</li>)}</ol></>:<p>{heirs?'Взрослых наследников пока нет.':'Загружаем наследников…'}</p>}</section>
    <section className="panel-card" aria-label="Взрослые дети и предложения"><h2>Взрослые дети и предложения</h2>{error&&<p role="alert">{error}</p>}
      {family?.incoming.map(p=><article key={p.id} data-proposal-id={p.id}><h3>Предложение от @{p.proposer_username}</h3><p>{p.proposer_child_name} ❤ {p.target_child_name}</p><div className="panel-choices"><button type="button" className="bnr-prop-accept" disabled={!allowed('respond')} onClick={()=>begin('respond',undefined,p,true)}>Принять</button><button type="button" className="bnr-prop-reject" disabled={!allowed('respond')} onClick={()=>begin('respond',undefined,p,false)}>Отклонить</button></div></article>)}
      {family?.outgoing.map(p=><article key={p.id} data-proposal-id={p.id}><h3>Предложение к @{p.target_username}</h3><p>{p.proposer_child_name} ❤ {p.target_child_name}</p><button type="button" className="bnr-fam-cancel" disabled={!allowed('cancel')} onClick={()=>begin('cancel',undefined,p)}>Отозвать</button></article>)}
      {!family?<p role="status">Загружаем детей и предложения…</p>:family.children.length?family.children.map(c=><article key={c.hero_id} data-child-id={c.hero_id}><h3>{c.name}</h3><div className="panel-choices">{(['rename','looks','respec','propose'] as const).map(kind=><button type="button" className={'bnr-fam-'+kind} key={kind} disabled={!allowed(kind)} onClick={()=>begin(kind,c)}>{titles[kind]} · {quoted(kind)}</button>)}</div></article>):<p>Взрослых детей пока нет.</p>}
    </section>
    {editor&&<ConfirmDialog title={titles[editor.kind]} cancel={cancel} confirm={prepare} confirmLabel="Продолжить" confirmDisabled={!body()}>{editor.kind==='propose'?<><label>Зритель для предложения<input value={draft.username} onInput={e=>update('username',e.currentTarget.value)}/></label><button type="button" disabled={looking||!username(draft.username)} onClick={()=>void find()}>Найти детей</button>{looking&&<p role="status">Загружаем…</p>}{lookupError&&<p role="alert">{lookupError}</p>}{targets&&<label>Ребёнок другого зрителя<select value={draft.target} onChange={e=>update('target',e.currentTarget.value)}><option value="">Выбери ребёнка</option>{targets.children.map(c=><option key={c.hero_id} value={c.hero_id}>{c.name}</option>)}</select></label>}</>:<label>{editor.kind==='rename'?'Новое имя ребёнка':'Код внешности ребёнка'}<input value={draft.text} onInput={e=>update('text',e.currentTarget.value)}/></label>}</ConfirmDialog>}
    {confirmation&&<ConfirmDialog title="Подтвердить действие с ребёнком" cancel={cancel} confirm={submit}><p>{confirmation.message}</p></ConfirmDialog>}
  </>;
}
