import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import {heroContext,validPrice,type PanelState} from './contracts';
import type {PanelController} from './controller';
interface Relative {hero_id?:string;name?:string;age?:number;is_female?:boolean;is_alive?:boolean;is_pregnant?:boolean}
interface Family {spouse?:Relative|null;father?:Relative|null;mother?:Relative|null;children?:Relative[];sibling_count?:number}
type Kind='gender'|'marry'|'divorce'|'baby';
const actionTypes:Record<Kind,string>={gender:'hero.set_gender',marry:'hero.marry',divorce:'hero.divorce',baby:'hero.make_baby'};
const family=(s:PanelState):Family=>(s.hero?.hero?.family_info as Family|null)||{};
const price=(s:PanelState,kind:Kind)=>kind==='gender'?s.config?.gender_swap_cost:kind==='baby'?s.config?.baby_cost:kind==='divorce'?s.config?.action_prices?.['hero.divorce']:(s.config?.hero_gold_costs as Record<string,unknown>|undefined)?.marry;
const cost=(s:PanelState,kind:Kind)=>validPrice(price(s,kind))?`${Number(price(s,kind)).toLocaleString('ru-RU')} ${kind==='divorce'?'💎':'💰'}`:'Цена не получена';
const observed=(s:PanelState,kind:Kind)=>JSON.stringify([s.generation,heroContext(s.hero),s.catalogs?.save_id,s.catalogs?.equipment_session_id,s.hero?.hero?.clan_name,s.hero?.hero?.is_female,s.hero?.hero?.spouse_name,family(s).spouse,kind==='baby'?family(s).children:undefined,price(s,kind)]);
function allowed(s:PanelState,kind:Kind){
  // Divorce is forced free by the server action handler, but has no quote in
  // config. Keep its danger confirmation and show no invented price.
  if(!s.canAct||s.mutationBlocked||!s.hero?.hero?.is_alive||(kind!=='divorce'&&!validPrice(price(s,kind)))||s.busy.some(k=>k.startsWith(actionTypes[kind]+':')))return false;
  const h=s.hero.hero;
  if(kind!=='divorce'&&(!validPrice(h.gold)||h.gold<Number(price(s,kind))))return false;
  if(kind==='gender')return true;
  if(kind==='divorce')return !!h.spouse_name;
  if(!h.clan_name)return false;
  return kind==='marry'?!h.spouse_name:!!family(s).spouse?.is_alive;
}
const relative=(p:Relative|null|undefined)=>p?<span>{p.is_female===true?'♀ ':p.is_female===false?'♂ ':''}{p.name||'Имя не получено'}{typeof p.age==='number'?` · ${p.age} лет`:''}{p.is_alive===false?' · умер(ла)':''}{p.is_pregnant?' · беременность':''}</span>:<span>Нет данных</span>;
export function HeroProfileView({controller,mode,active=true}:{controller:PanelController;mode:'gender'|'family';active?:boolean}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),h=s.hero?.hero,fi=family(s);
  const [confirmation,setConfirmation]=useState<{kind:Kind;gender?:'male'|'female';seen:string;message:string;owns:()=>boolean}|null>(null),pending=useRef(confirmation);pending.current=confirmation;
  const mounted=useRef(true),selected=useRef(active);selected.current=active;
  const can=(kind:Kind)=>active&&allowed(s,kind)&&controller.cooldown(actionTypes[kind])<=0;
  const valid=()=>{const c=pending.current;return !!c&&mounted.current&&selected.current&&controller.ready()&&c.owns()&&allowed(controller.snapshot(),c.kind)&&controller.cooldown(actionTypes[c.kind])<=0&&c.seen===observed(controller.snapshot(),c.kind);};
  const cancel=()=>{pending.current=null;setConfirmation(null);};
  useLayoutEffect(()=>()=>{mounted.current=false;pending.current=null;},[]);
  useLayoutEffect(()=>{if(pending.current&&!valid())cancel();},[s,active]);
  const ask=(kind:Kind,gender?:'male'|'female')=>{
    if(!can(kind)||!controller.ready()||observed(s,kind)!==observed(controller.snapshot(),kind))return;
    const message=kind==='gender'?`Изменить пол героя на ${gender==='female'?'женский':'мужской'} за ${cost(s,kind)}? При наличии супруга игра также проверит совместимость брака.`:kind==='marry'?`Создать брак с подходящим NPC за ${cost(s,kind)}? Супруга подберёт игра.`:kind==='baby'?`Отправить заявку на зачатие ребёнка за ${cost(s,kind)}? Лимит детей проверит игра. Результат и срок рождения определяет игра.`:`Развестись с ${String(h?.spouse_name)}? Вернуть супруга можно только новой свадьбой, она платная.`;
    setConfirmation({kind,gender,seen:observed(s,kind),message,owns:controller.captureRequestOwner()});
  };
  const submit=()=>{const c=pending.current,ok=valid();cancel();if(!c||!ok)return;const body=c.kind==='gender'?{gender:c.gender}:{};void controller.action(actionTypes[c.kind],body,{tail:'hero',successMessage:'Заявка принята. Ждём подтверждения игры.'});};
  if(!h?.is_alive)return null;
  const children=Array.isArray(fi.children)?fi.children:[];
  return <section className="panel-card" aria-label={mode==='gender'?'Пол героя':'Семья героя'}>
    {mode==='gender'?<><h2>Пол героя</h2><p>Текущий: {h.is_female===true?'Женский':h.is_female===false?'Мужской':'Нет данных'}</p><p>{cost(s,'gender')} · у героя {h.gold.toLocaleString('ru-RU')} 💰</p><div className="panel-choices">{(['male','female'] as const).map(g=><button type="button" className="bnr-gender-set" data-gender-set={g} key={g} disabled={!can('gender')} onClick={()=>ask('gender',g)}>{g==='male'?'♂ Мужской':'♀ Женский'}</button>)}</div></>:<><h2>Семья героя</h2>
      {h.spouse_name?<><p>Супруг(а): {String(h.spouse_name)}</p>{relative(fi.spouse)}<button type="button" id="bnr-divorce-btn" disabled={!can('divorce')} onClick={()=>ask('divorce')}>Развестись</button></>:<><p>Супруга подбирает игра из подходящих NPC.{!h.clan_name?' Сначала нужен клан.':''}</p><button type="button" id="bnr-marry-btn" disabled={!can('marry')} onClick={()=>ask('marry')}>Жениться / выйти замуж — {cost(s,'marry')}</button></>}
      <dl><dt>Отец</dt><dd>{relative(fi.father)}</dd><dt>Мать</dt><dd>{relative(fi.mother)}</dd>{typeof fi.sibling_count==='number'&&<><dt>Братья и сёстры</dt><dd>{fi.sibling_count}</dd></>}</dl>
      <h3>Дети ({children.filter(c=>c.is_alive).length} живых из {children.length})</h3>{children.length?<ul>{children.map((c,i)=><li key={c.hero_id||i}>{relative(c)}</li>)}</ul>:<p>Детей пока нет.</p>}
      <button type="button" id="bnr-make-baby-btn" disabled={!can('baby')} onClick={()=>ask('baby')}>Зачать ребёнка — {cost(s,'baby')}</button>{!h.clan_name?<p>Для рождения детей нужен клан.</p>:!fi.spouse?.is_alive?<p>Нужен живой супруг или супруга.</p>:null}<p>Лимит детей проверит игра. Возраст, беременность и рождение обновятся после синхронизации.</p>
    </>}
    {confirmation&&<ConfirmDialog title="Подтвердить действие героя" cancel={cancel} confirm={submit}><p>{confirmation.message}</p></ConfirmDialog>}
  </section>;
}
