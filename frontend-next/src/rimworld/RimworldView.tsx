import {useSyncExternalStore} from 'react';
import {ConfirmDialog} from '../common/ConfirmDialog';
import {CommerceView} from './CommerceView';
import {actualPrice,type RimworldController,type RimItem,type PawnAction} from './controller';
const text=(v:unknown):string=>typeof v==='string'||typeof v==='number'?String(v):Array.isArray(v)?v.map(text).join(', '):v&&typeof v==='object'?Object.entries(v).map(([k,value])=>k+': '+text(value)).join('; '):'';
export function RimworldView({controller:c}:{controller:RimworldController}){
  const s=useSyncExternalStore(c.subscribe,c.snapshot),p=s.pawn,q=s.confirmation;
  const action=(kind:PawnAction,label:string,key:string,item?:RimItem)=>{const price=s.config?.[key];return <button type="button" aria-label={label} disabled={s.busy||!actualPrice(price)||kind==='heal'&&(s.healPending||s.cooldownUntil>s.now)} onClick={()=>void c.choose(kind,item)}>{label} · {actualPrice(price)?`${price} 💎`:'цена не получена'}</button>;};
  return <section aria-label="RimWorld"><header className="panel-card"><h2>RimWorld</h2><p>{s.online===null?'Проверяем связь':s.online?'🟢 Онлайн':'🔴 Оффлайн'}</p></header>{s.message&&<p role="status">{s.message}</p>}<section className="panel-card"><h3>Колонисты</h3><p>Всего: {s.colonists.length} · живы: {s.colonists.filter(x=>x.is_alive).length}</p>{s.colonists.map(x=><p key={x.username}>{x.pawn_name} · @{x.username} · {x.is_alive?`${x.health}%`:'погиб'}</p>)}</section>
    <section className="panel-card"><h3>Моя пешка</h3><button type="button" onClick={()=>void c.refreshPawn()}>Обновить пешку</button>{!p?<p>Загрузка…</p>:p.auth_required?<p>Нужно подтвердить личность Twitch.</p>:!p.exists?<>{p.error&&<p>{p.error}</p>}{action('create','Создать пешку','spawn_cost')}</>:<><h4>{p.pawn_name}</h4><p>{p.is_alive?'Жива':'Погибла'} · {typeof p.health==='number'?Math.round(p.health>1?p.health:p.health*100)+'%':'Здоровье неизвестно'} · {p.world_name||p.world_id||'Мир не передан'}</p>{p.is_alive?action('heal','Лечить','heal_cost'):action('resurrect','Воскресить','resurrect_cost')}{s.healPending?<p>Проверяем результат лечения…</p>:s.cooldownUntil>s.now?<p>Лечение через {Math.ceil((s.cooldownUntil-s.now)/1000)} с</p>:null}
    <h4>Снаряжение</h4>{p.equipment?.map((x,i)=><details key={x.slot||i}><summary>{x.label||x.name||x.item_def} · {x.slot} · {x.hp??'—'}/{x.max_hp??'—'}</summary>{Object.entries(x).filter(([k])=>!['label','name','slot','hp','max_hp','def_name','item_def'].includes(k)).map(([k,v])=><p key={k}>{k}: {text(v)}</p>)}</details>)}
    <div className="panel-choices"><button type="button" onClick={()=>void c.openModal('passion')}>Огоньки страсти</button><button type="button" onClick={()=>void c.openModal('neurotrainer')}>Нейротренеры</button><button type="button" onClick={()=>void c.openModal('xenotype')}>Ксенотипы</button></div>
    <h4>Навыки</h4>{p.skills?.map(x=><p key={x.def_name}>{x.label||x.name||x.def_name}: {x.level} · страсть {x.passion} {x.is_disabled||x.disabled?'· недоступен':''} {x.xp!==undefined?`· опыт ${x.xp}`:''}</p>)}
    <h4>Черты</h4>{p.traits?.map(x=><article key={x.def_name+':'+x.degree}><p>{x.label||x.def_name}: {x.desc||x.description}</p>{action('remove-trait','Удалить черту '+(x.label||x.def_name),'trait_remove_cost',x)}</article>)}
    <h4>Гены</h4>{p.genes?.map(x=><article key={x.def_name}><p>{x.label||x.def_name} · {x.xenogene?'ксеноген':'эндоген'} · {x.is_active?'активен':'неактивен'} {x.gene_class}</p>{action('remove-gene','Удалить ген '+(x.label||x.def_name),'gene_remove_cost',x)}</article>)}
    <h4>Здоровье и импланты</h4>{p.hediffs?.map((x,i)=><p key={i}>{x.label} · {x.part} · {x.severity} {x.is_paired?(x.is_left===true?'левая сторона':x.is_left===false?'правая сторона':'сторона не передана'):''}</p>)}
    </>}</section>
    <CommerceView controller={c}/>
    {q&&<ConfirmDialog title="Подтверждение RimWorld" cancel={()=>c.cancel()} confirm={()=>void c.confirm()}><p>{q.label}: {q.price} 💎</p>{q.kind==='remove-gene'&&<p>Удаляется выбранный ген, включая подавленный. Итог подтвердит игра.</p>}{q.kind==='xeno'&&<p>Все текущие ксеногены будут заменены. Эндогены остаются.</p>}</ConfirmDialog>}
  </section>;
}
