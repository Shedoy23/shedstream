import { useSyncExternalStore } from 'react';
import { actionKey, validPrice, type BattleStats, type PowerOption } from './contracts';
import type { PanelController } from './controller';
import { combatAllowed, combatPresentation, liveParticipant, orderLabels, orders, orderVisible, powerCooldown, powerLabels, remaining, stances } from './combat';
import './combat.css';
const number = (value: unknown, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const amount = (value: unknown) => Math.max(0,Math.floor(number(value))).toLocaleString('ru-RU');
function payout(stats: BattleStats) {
  if(stats.payout_version!==2) return `+${amount(stats.gold_earned)}💰`;
  if(stats.payout_status==='paid') return `Получено: ${amount(stats.gold_earned)}💰`;
  if(stats.payout_status==='failed') return 'Не удалось начислить награду';
  if(stats.payout_status==='unavailable') return 'Нет подтверждённого итога боя';
  return `После боя: ≈${amount(stats.payout_estimate_min)}–${amount(stats.payout_estimate_max)}💰`;
}
const skills: Record<string,string> = {OneHanded:'Одноручное',TwoHanded:'Двуручное',Polearm:'Древковое',Bow:'Лук',Crossbow:'Арбалет',Throwing:'Метательное',Riding:'Верховая езда',Athletics:'Атлетика'};
function strength(power: PowerOption) {
  const value=Number(power.value);if(!Number.isFinite(value))return '';
  switch(power.power_key){case 'rage':return `Урон +${Math.round((value-1)*100)}%`;case 'cleave':return `${Math.round(value*100)}% урона удара соседним врагам`;case 'shield_break_burst':return `${value}% шанс разбить щит при попадании`;case 'explosive_arrows':return `До ${value} урона соседним врагам`;case 'poison_dot':return `${value} урона в секунду от яда`;case 'ironskin_toggle':return `Входящий урон −${value}% со щитом в руке`;default:return '';}
}
export function CombatView({controller}:{controller:PanelController}) {
  const s=useSyncExternalStore(controller.subscribe,controller.snapshot), battle=s.battle, my=battle?.my_stats, build=s.build?.build;
  const ui=combatPresentation(s.config?.ui), live=liveParticipant(s), newBuild=s.newBuild;
  const act=(type:string,data:Record<string,unknown>,family=false)=>{void controller.combatAction(type,data,family);};
  const allowed=(type:string,data:Record<string,unknown>,family=false)=>combatAllowed(s,type,data,family) && !s.busy.includes(actionKey(type,data));
  const affordability=(price:unknown,title:string)=>({ title:validPrice(price) && price>(s.points || 0)?`Не хватает:\n  • 💎: нужно ${price.toLocaleString('ru-RU')}, есть ${(s.points || 0).toLocaleString('ru-RU')}`:title, className:validPrice(price) && price>(s.points || 0)?'bnr-cant-afford':'' });
  const current=build?.power_options?.find(p=>p.weapon_type===build.selected_weapon_type && p.power_key===build.selected_power);
  const hp=Math.max(0,number(my?.hp)),hpMax=Math.max(1,number(my?.hp_max,100)),alive=!!my?.alive && hp>0;
  const states:Record<string,string>={active:'⚔️ В бою',routed:'🏃 Бежит',unconscious:'💤 Без сознания',killed:'💀 Погиб'};
  const active=(power:PowerOption,weapon:boolean)=>{
    const data={power_key:power.power_key},cd=powerCooldown(s,power,weapon),buff=remaining(s.buffs[power.power_key],s.now);
    return <button type="button" key={power.power_key} data-bnr-build-activate={power.power_key} disabled={!allowed('power.activate',data,true)} title={power.description} onClick={()=>act('power.activate',data,true)}>{power.label || power.power_key} · {validPrice(power.price)?power.price.toLocaleString('ru-RU'):'—'} 💎{cd>0?` · ${cd} с`:buff?' · действует':''}</button>;
  };
  const contents:Record<string,unknown>={
    summon:<div className="panel-summons">{(['player','enemy'] as const).map(side=>{
      const price=s.config?.spawn_prices?.[side],data={price,side},cd=remaining(s.cooldowns['player.spawn:'+side],s.now);
      return <button type="button" key={side} id={'bnr-summon-'+(side==='player'?'ally':'enemy')+'-btn'} disabled={!allowed('player.spawn',data)} {...affordability(price,side==='player'?'Призвать героя в бой на сторону стримера':'Призвать героя ПРОТИВ стримера (на сторону противника)')} onClick={()=>act('player.spawn',data)}>{ui.labels[side==='player'?'summon_ally':'summon_enemy']} <span>{cd>0?`${cd} с`:validPrice(price)?`${price}💎`:'Цена недоступна'}</span></button>;
    })}</div>,
    active_powers:newBuild ? !s.build?.ready || !build ? <p role="status">{s.build?.message || 'Ждём актуальные способности героя из игры.'}</p> : <><h2>{ui.labels.active_powers}</h2><div className="panel-combat-actions">{current?active(current,true):<p>Надень оружие и выбери способность ниже.</p>}{current && !current.available && current.reason && <p>{current.reason}</p>}{build.common_powers?.map(p=>active(p,false))}</div>{!live && <p className="panel-muted">Активация доступна, когда твой герой находится на поле боя.</p>}</> : s.build && s.classes ? <><h2>⚡ Способности</h2><div className="panel-combat-actions">{s.classes.current_powers?.filter(p=>Object.hasOwn(powerLabels,p.power_key)).map(p=>{
      const meta=powerLabels[p.power_key],data={price:p.price,power_key:p.power_key},cd=remaining(s.cooldowns[p.power_key],s.now);
      return <button type="button" key={p.power_key} data-bnr-power={p.power_key} disabled={!allowed('power.activate',data)} {...affordability(p.price,live?meta.desc:'Доступно, когда твой герой находится на поле боя')} onClick={()=>act('power.activate',data)}>{meta.icon} {meta.label} <span>{cd>0?`${cd} с`:validPrice(p.price)?`${p.price}💎`:'Цена недоступна'}</span></button>;
    })}</div>{!s.classes.current_powers?.length && <p>Способности появятся после выбора класса (Прокачка → Класс)</p>}</> : null,
    weapon_choice:newBuild && s.build?.ready && build ? <><h2>{ui.labels.weapon_choice}</h2><p className="panel-muted">Выбери одну способность перед боем. Доступность зависит от надетого оружия, сила — от навыка. Смена выбора не сбрасывает перезарядку.</p>
      {(s.buildPending || s.build.pending || s.buildBusy)?<p role="status">Заявка отправлена — ждём подтверждения из игры.</p>:(s.build.message || s.build.reason)?<p role="status">{s.build.message || s.build.reason}</p>:null}
      <div className="panel-choices">{build.power_options?.map(p=>{
        const data={weapon_type:p.weapon_type};return <button type="button" key={p.weapon_type} data-bnr-build-select={p.weapon_type} aria-pressed={build.selected_weapon_type===p.weapon_type} disabled={!allowed('hero.select_weapon_power',data,true)} onClick={()=>act('hero.select_weapon_power',data,true)}><strong>{p.label}</strong><span>{p.description}</span><span>{strength(p)}</span><span>Ранг {p.rank} · {skills[p.skill || ''] || p.skill} {p.skill_level}</span>{number(p.skill_level)>=0 && number(p.skill_level)<150 && <span>Следующее усиление: навык {number(p.skill_level)<50?50:150}</span>}{!p.available && p.reason && <span>{p.reason}</span>}</button>;
      })}</div></> : null,
  };
  return <section className="panel-combat" aria-label="Боевые действия"><div className="panel-section-heading"><div><p className="panel-eyebrow">BANNERLORD</p><h1>Боевые действия</h1></div></div>
    {s.error && <p className="panel-error" role="alert">{s.error}</p>}{s.message && <p className="panel-notice" role="status">{s.message}</p>}
    <div id="bnr-battle-banner-slot">{battle?.in_battle ? my ? <article className="panel-card panel-battle-banner"><div className="panel-summary"><strong>{states[my.state || ''] || (alive?'⚔️ В бою':'💀 Погиб')}</strong><span>{amount(battle.participant_count)} участ.</span></div><div className="panel-hp" role="progressbar" aria-label="Здоровье" aria-valuemin={0} aria-valuemax={hpMax} aria-valuenow={Math.min(hp,hpMax)}><span style={{width:Math.max(0,Math.min(100,hp/hpMax*100))+'%'}} /></div><div className="panel-battle-stats"><span>❤ {hp}/{hpMax}</span><span>☠ {amount(my.kills)}</span><span>{payout(my)}</span><span>+{amount(my.xp_earned)} XP</span></div></article> : <p className="panel-card panel-battle-banner">⚔️ В игре идёт бой — {amount(battle.participant_count)} участ.</p> : battle?.last_payout?.payout_version===2 ? <article className="panel-card"><strong>{payout(battle.last_payout)}</strong>{battle.last_payout.payout_status==='paid' && <p>Участие: {amount(battle.last_payout.payout_participation)} · Герой: {amount(battle.last_payout.payout_personal)} · Свита: {amount(battle.last_payout.payout_retinue)}</p>}</article>:null}</div>
    <div id="bnr-combat-stance-slot">{s.hero?.hero && <section className="panel-card"><h2>⚔ Стойка боя</h2><div className="panel-combat-actions">{stances.map(([key,label,tip])=><button type="button" key={key} data-stance={key} aria-pressed={(s.optimisticStance || s.hero?.hero?.combat_stance || 'balanced')===key} disabled={!allowed('hero.set_combat_stance',{stance:key})} title={label+' — '+tip} onClick={()=>act('hero.set_combat_stance',{stance:key})}>{label}</button>)}</div></section>}</div>
    <div id="bnr-buff-hud" aria-label="Активные эффекты">{Object.entries(s.buffs).filter(([,expiry])=>remaining(expiry,s.now)>0).map(([key,expiry])=><span className="panel-buff" key={key}>{powerLabels[key]?.icon || '✨'} {powerLabels[key]?.label || key} {remaining(expiry,s.now)}с</span>)}</div>
    <div id="bnr-detachment-slot">{live && <section className="panel-card"><h2>🎯 Приказы герою</h2><p className="panel-muted">Управляй своим героем в бою</p><p>{orderLabels[my?.order_status || ''] || 'Статус приказа неизвестен'}</p><div className="panel-orders">{orders.filter(([type])=>orderVisible(s,type)).map(([type,label,tip])=>{
      const price=s.config?.action_prices?.[type],data={price},cd=remaining(s.cooldowns[type],s.now);return <button type="button" key={type} data-det-act={type} disabled={!allowed(type,data)} title={['hero.detach_walls','hero.detach_gate'].includes(type) && battle?.is_siege!==true?'Доступно только во время осады.':tip} onClick={()=>act(type,data)}>{label} <span>{cd>0?`${cd} с`:validPrice(price)?`(${price}💎)`:'Цена недоступна'}</span></button>;
    })}</div></section>}</div>
    {ui.order.map(id=><section className="panel-card" key={id} id={id==='summon'?'bnr-summon-slot':id==='active_powers'?'bnr-active-powers-slot':'bnr-build-choice-slot'} data-bnr-ui-section={id} hidden={!ui.visible[id]}>{contents[id] as import('react').ReactNode}</section>)}
    <p className="panel-muted">Турниры доступны в действующей панели.</p>
  </section>;
}
