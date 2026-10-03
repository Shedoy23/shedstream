import {useLayoutEffect,useState,useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import type {PanelController} from './controller';
import {actionKey,heroContext,type PanelState} from './contracts';
import {contentEntries} from './progression';

const observation=(s:PanelState)=>JSON.stringify([s.generation,heroContext(s.hero),s.hero?.hero?.is_alive,s.catalogs?.save_id,s.catalogs?.equipment_session_id,s.catalogs?.cultures]);
function creationData(s:PanelState,culture?:string):Record<string,unknown>|null {
  if(!s.hero || s.hero.has_hero)return null;
  const catalog=s.catalogs?.cultures,entries=contentEntries(catalog).filter(c=>c.available!==false);
  // Missing catalogs retain the existing random-only compatibility path. An
  // available empty catalog is an explicit game refusal, not a random fallback.
  if(catalog?.available===true){
    if(!entries.length||!s.catalogs?.save_id||!s.catalogs?.equipment_session_id)return null;
    if(culture&&!entries.some(c=>c.id===culture))return null;
    return {price:0,...(culture?{culture}:{}),content_context:{save_id:s.catalogs.save_id,equipment_session_id:s.catalogs.equipment_session_id}};
  }
  return culture?null:{price:0};
}
export function HeroLifecycleView({controller}:{controller:PanelController}) {
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),seen=observation(s);
  const [respawn,setRespawn]=useState<string|null>(null);
  const canAct=s.canAct&&!s.mutationBlocked&&controller.cooldown('hero.create')<=0;
  const dead=!!s.hero?.has_hero&&s.hero.hero?.is_alive===false;
  useLayoutEffect(()=>{if(respawn&&(!canAct||!dead||respawn!==seen))setRespawn(null);},[respawn,canAct,dead,seen]);
  const submit=(culture?:string)=>{
    const current=controller.snapshot(),data=creationData(current,culture);
    if(!controller.ready()||current.mutationBlocked||seen!==observation(current)||!data)return;
    void controller.action('hero.create',data,{tail:'hero',successMessage:'Заявка на создание героя отправлена. Ждём появления героя в игре.'});
  };
  if(!s.hero)return null;
  if(!s.hero.has_hero){
    const entries=contentEntries(s.catalogs?.cultures);
    return <section className="panel-card" aria-label="Создание героя"><h2>Герой ещё не создан</h2><p>Выбери культуру из текущей игры или доверь выбор игре.</p>
      {!s.catalogs?.cultures?.available?<p role="status">Каталог культур пока недоступен. Дождись связи с игрой.</p>:!entries.length?<p role="status">Игра передала пустой список культур.</p>:null}
      <div className="panel-choices">{entries.map(c=>{const data=creationData(s,c.id);return <button type="button" key={c.id} data-bnr-culture={c.id} title={c.description||''} disabled={!canAct||!data||s.busy.includes(actionKey('hero.create',data||{}))} onClick={()=>submit(c.id)}>{c.name||c.id}</button>;})}</div>
      <button type="button" id="bnr-adopt-random" disabled={!canAct||!creationData(s)||s.busy.includes(actionKey('hero.create',creationData(s)||{}))} onClick={()=>submit()}>Пусть выберет игра</button>
    </section>;
  }
  if(!dead)return null;
  return <section className="panel-card" aria-label="Возрождение героя"><h2>Начать заново</h2><p>Прежнего героя вернуть нельзя — новый начнёт с 0 уровня, без снаряжения и клана. Имя останется тем же.</p>
    <button type="button" id="bnr-heir-respawn" disabled={!canAct||s.busy.includes(actionKey('hero.create',{price:0}))} onClick={()=>setRespawn(seen)}>Новый герой с 0 уровня · бесплатно</button>
    {respawn&&<ConfirmDialog title="Начать заново?" cancel={()=>setRespawn(null)} confirm={()=>{
      const shown=respawn;setRespawn(null);const current=controller.snapshot();
      if(shown!==observation(current)||!controller.ready()||current.mutationBlocked||current.hero?.hero?.is_alive!==false)return;
      void controller.action('hero.create',{price:0},{tail:'hero',successMessage:'Заявка на создание героя отправлена. Ждём нового героя в игре.'});
    }}><p>Прежнего героя вернуть нельзя — новый начнёт с 0 уровня, без снаряжения и клана. Создание нового героя бесплатно.</p></ConfirmDialog>}
  </section>;
}
