import { useRef, useSyncExternalStore } from 'react';
import { actionKey, heroContext, validPrice, type HeroReply, type PanelConfig } from './contracts';
import { cooldownLabel } from './combat';
import type { PanelController } from './controller';
interface RetinueMember { slot_index: number; troop_id: string; troop_name?: string; tier: number; is_elite: boolean }
const fmt=(n:number)=>n.toLocaleString('ru-RU');
// Inherited approximate display rules, not authoritative upgrade eligibility.
// The game still resolves UpgradeTargets and the exact bulk training charge.
export function retinueEstimate(hero:HeroReply|null,config:PanelConfig|null){
  const slots=(Array.isArray(hero?.retinue)?hero.retinue:[]) as RetinueMember[];
  const cap=hero?.hero?.retinue_cap,gold=hero?.hero?.gold,costs=config?.recruit_tier_costs,mult=config?.recruit_elite_mult;
  const ready=typeof cap==='number' && Number.isInteger(cap) && cap>=0 && validPrice(gold) && Array.isArray(costs) && costs.length>0 && costs.every(validPrice) && validPrice(mult) && slots.every(s=>Number.isInteger(s.tier) && s.tier>=0);
  const full=typeof cap==='number' && slots.length>=cap;
  const cost=(tier:number,elite:boolean)=>ready?(costs as number[])[Math.min(tier,(costs as number[]).length-1)]*(elite?mult as number:1):null;
  const choices=[false,true].map(elite=>{const same=slots.filter(s=>!!s.is_elite===elite),maxed=same.length>0&&same.every(s=>s.tier>=(elite?6:5));const price=full&&!same.length?0:cost(full?Math.min(...same.map(s=>s.tier)):0,elite);return {elite,maxed,price,disabled:!ready||(full&&(!same.length||maxed))||price===null||gold!<price};});
  const train=ready?slots.reduce((sum,s)=>sum+(s.tier>=(s.is_elite?6:5)?0:cost(s.tier,!!s.is_elite)!),0):null;
  return {slots,cap,gold:validPrice(gold)?gold:0,ready,full,choices,train};
}
export function RetinueView({controller}:{controller:PanelController}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),m=retinueEstimate(s.hero,s.config),wasOpen=useRef(false);
  const canAct=s.canAct&&controller.ready()&&!s.mutationBlocked;
  const context=heroContext(s.hero),generation=s.generation;
  const act=(type:string,data:Record<string,unknown>)=>{
    const current=controller.snapshot(),model=retinueEstimate(current.hero,current.config);
    if(!controller.ready()||generation!==current.generation||context!==heroContext(current.hero)||!current.hero?.hero?.is_alive||!model.ready||current.mutationBlocked)return;
    if(type==='hero.recruit_troops' ? model.choices[data.is_elite?1:0].disabled||controller.cooldown(type)>0 : !model.slots.length||model.train===null||model.train<=0||model.gold<model.train||controller.cooldown(type)>0)return;
    void controller.action(type,data,{tail:'hero',quietCooldown:true});
  };
  const trainCd=Math.ceil(controller.cooldown('hero.train_troops'));
  return <div id="bnr-retinue-slot"><details className="panel-card panel-retinue" data-bnr-details="retinue" onToggle={e=>{const open=e.currentTarget.open;if(open&&!wasOpen.current)controller.trackSection('bannerlord:details.retinue');wasOpen.current=open;}}>
    <summary>🛡 Свита ({m.slots.length}/{typeof m.cap==='number'?m.cap:'—'}) {m.slots.some(s=>s.is_elite)&&<small>★{m.slots.filter(s=>s.is_elite).length}</small>}</summary>
    {!m.slots.length?<p className="panel-muted">пусто</p>:m.slots.map(slot=><div className="panel-summary" key={slot.slot_index}><span>{slot.is_elite?'★ ':''}{slot.troop_name||slot.troop_id}</span><span>T{slot.tier}★</span></div>)}
    {!m.ready&&<p className="panel-error" role="status">Сервер не передал цены или лимит свиты. Действия недоступны. <button type="button" disabled={!s.canAct} onClick={()=>{void controller.refreshConfig();}}>Обновить цены свиты</button></p>}
    <div className="panel-choices">{m.choices.map(({elite,maxed,price,disabled})=>{const data={is_elite:elite},cd=Math.ceil(controller.cooldown('hero.recruit_troops'));return <button type="button" key={String(elite)} id={`bnr-recruit-${elite?'elite':'basic'}-btn`} data-bnr-cd="hero.recruit_troops" disabled={!canAct||disabled||cd>0||s.busy.includes(actionKey('hero.recruit_troops',data))} title={price===null?'Цена недоступна':`Списать ${fmt(price)}💰 динаров у героя.`} onClick={()=>act('hero.recruit_troops',data)}>{cd>0?cooldownLabel(cd):maxed&&m.full?`✓ ${elite?'Elite':'Basic'} maxed`:<>{m.full?'⬆ Прокачать':elite?'★ Нанять':'➕ Нанять'} {elite?'elite':'basic'} <small>{price===null?'Цена недоступна':`${fmt(price)}💰${m.gold<price?` (не хватает ${fmt(price-m.gold)}💰)`:''}`}</small></>}</button>;})}</div>
    <button type="button" id="bnr-train-troops-btn" data-bnr-cd="hero.train_troops" disabled={!canAct||!m.ready||!m.slots.length||m.train===null||m.train<=0||m.gold<m.train||trainCd>0||s.busy.includes(actionKey('hero.train_troops',{}))} title={`Тренировать всю свиту: каждый слот апается на тир. Списать у героя ~${m.train===null?'—':fmt(m.train)}💰 динаров (точную сумму считает игра, maxed-слоты пропускаются).`} onClick={()=>act('hero.train_troops',{})}>{trainCd>0?cooldownLabel(trainCd):<>🎯 Тренировать свиту <small>{!m.slots.length?'свита пуста':m.train===null?'Цена недоступна':m.train<=0?'вся свита maxed':`~${fmt(m.train)}💰${m.gold<m.train?` (не хватает ${fmt(m.train-m.gold)}💰)`:''}`}</small></>}</button>
  </details></div>;
}
