import {useSyncExternalStore} from 'react';
import {observedEquipment} from './commerce';
import type {PanelController} from './controller';
const finite=(x:unknown)=>typeof x==='number'&&Number.isFinite(x)?x:0;
const fmt=(x:unknown)=>typeof x==='number'&&Number.isFinite(x)?x.toLocaleString('ru-RU'):'—';
export function HeroSummaryView({controller}:{controller:PanelController}){
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot),h=s.hero?.hero;if(!h)return null;
  const armor=observedEquipment(s.hero).filter(([slot])=>['head','body','leg','gloves','cape'].includes(slot)),totals=Object.fromEntries(['head','body','leg','arm'].map(key=>[key,armor.reduce((sum,[,item])=>sum+finite(item.stats?.[key]),0)]));
  const tiers=armor.map(([,item])=>item.tier).filter((tier):tier is number=>typeof tier==='number'&&Number.isFinite(tier)&&tier>=0);
  return <section className="panel-card panel-hero" aria-label="Карточка героя"><p className="panel-eyebrow">ВАШ ГЕРОЙ</p><h2>{h.display_name}</h2><div className="panel-summary"><span>Уровень {fmt(h.level)}</span><strong>{fmt(h.gold)} 💰</strong></div><p>{!h.is_alive?'Герой погиб':h.is_prisoner?'В плену':h.is_wounded?'Ранен':'Жив'}{h.culture?' · '+String(h.culture):''}{h.location?' · 📍 '+String(h.location):''}</p><dl><dt>Клан</dt><dd>{String(h.clan_name||'Не вступил')}</dd><dt>Королевство</dt><dd>{String(h.kingdom_name||'Не вступил')}</dd><dt>Снаряжение</dt><dd>{s.hero?.equipment_shop_ready?'Своя сборка · Инвентарь':'T'+fmt(h.gear_tier)}</dd><dt>Броня по зонам</dt><dd>Голова: {totals.head} · Тело: {totals.body} · Ноги: {totals.leg} · Руки: {totals.arm}{tiers.length?' · ~T'+(Math.round(tiers.reduce((a,b)=>a+b,0)/tiers.length)+1):''}</dd></dl>{finite(h.tournament_wins)>0&&<p>Побед в турнирах: {fmt(h.tournament_wins)}</p>}</section>;
}
