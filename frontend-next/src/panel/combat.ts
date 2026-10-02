import { validPrice, type PanelState, type PowerOption } from './contracts';
// Presentation vocabulary inherited from the shipped client, not an ability
// catalog. Only entries actually emitted by classes/build can become controls.
export const powerLabels: Record<string, { icon: string; label: string; desc: string }> = {
  heal_burst:{icon:'💊',label:'Лечение',desc:'+50 HP'},
  shield_break_burst:{icon:'🛡️',label:'Ломать щиты',desc:'твои удары ломают щиты, 45с'},
  rage:{icon:'🔥',label:'Ярость',desc:'твой урон умножается, 45с'},
  retribution_toggle:{icon:'🌫',label:'Невидимость',desc:'враги теряют цель, 45с'},
  poison_dot:{icon:'☠',label:'Яд',desc:'твои попадания травят, 45с'},
  disarm_burst:{icon:'💥',label:'Обезоружить',desc:'Случ. враг роняет оружие'},
  berserker_charge:{icon:'💨',label:'Берсерк-рывок',desc:'бежишь быстрее, 45с'},
  lifesteal_burst:{icon:'🩸',label:'Вампиризм',desc:'часть урона лечит тебя, 45с'},
  ironskin_toggle:{icon:'🛡',label:'Железная кожа',desc:'входящий урон меньше, 45с'},
  explosive_arrows:{icon:'🧨',label:'Взрывные стрелы',desc:'попадания взрываются, 45с'},
  cleave:{icon:'⚔️',label:'Рассечение',desc:'удар задевает соседей, 45с'},
};
export const orders = [
  ['hero.detach_hold','⛔ Стоять','Стоять на текущей позиции. Полезно archer\'ам — sniper-mode не отступает.'],
  ['hero.detach_charge','⚔ Вблизи','Сближаться с противником для ближнего боя. Пеший герой предпочитает пехоту и не преследует уезжающих всадников.'],
  ['hero.detach_skirmish','🏹 Перестрелка','🏹 Бой на расстоянии: держать дистанцию ~22м и стрелять, не подпуская врага вплотную. Лучникам/арбалетчикам.'],
  ['hero.detach_raid','🐎 Набег','🐎 Набег: конный кружит вокруг ближайшего врага, рубя/стреляя на проходе. Нужен конь.'],
  ['hero.attach','🔄 В строй','Снять индивидуальный приказ и вернуть обычное управление героя в строю.'],
  ['hero.detach_walls','🪜 К стенам','Двигаться к позиции у стен. Автоматический подъём по лестнице не обеспечивается.'],
  ['hero.detach_gate','🚪 К воротам','Двигаться к воротам. Приказ не открывает и не ломает их автоматически.'],
  ['hero.detach','🚶 Отделиться','Включить индивидуальное управление героем и удерживать текущую позицию. Остальные приказы тоже включают его автоматически.'],
] as const;
export const orderLabels: Record<string,string> = {formation:'В строю',hold:'Держит позицию',approaching:'Сближается',engaged:'В ближнем бою',walls:'Движется к стенам',gate:'Движется к воротам',arrived:'Прибыл на позицию',blocked:'Путь недоступен',waiting_target:'Ожидает доступного противника',skirmish:'Ведёт перестрелку',raid:'Выполняет набег'};
export const stances = [['defensive','🛡 Оборона','выше блок/парри, меньше атаки'],['balanced','⚖ Баланс','обычное поведение в бою'],['aggressive','⚔ Натиск','выше атака, ниже защита']] as const;
export const liveParticipant = (state: PanelState) => !!(state.battle?.in_battle && state.battle.my_stats?.alive);
export const remaining = (until: number | undefined, now: number) => Math.max(0, Math.ceil(((until || 0) - now) / 1000));
export function orderVisible(state: PanelState, type: string) {
  const build = state.build?.build, key = state.classes?.current?.class_key || '';
  if (type === 'hero.detach_raid') return state.newBuild ? !!(state.build?.ready && build?.is_mounted) : ['cavalry','camel_cavalry','horse_archer','camel_archer'].includes(key);
  if (type === 'hero.detach_skirmish') return state.newBuild ? !!(state.build?.ready && build?.power_options?.some(p => ['bow','crossbow'].includes(p.weapon_type || '') && p.available)) : ['archer','heavy_archer','crossbow','heavy_crossbow','horse_archer','camel_archer'].includes(key);
  return true;
}
export const semanticCooldown = (type: string, data: Record<string,unknown>, buildFamily = false) => type === 'player.spawn' ? 'player.spawn:' + data.side : type === 'power.activate' ? (buildFamily && data.power_key !== 'heal_burst' ? 'weapon_power' : String(data.power_key)) : type;
export function powerCooldown(state: PanelState, power: PowerOption, weapon: boolean, now = state.now) {
  return remaining(weapon ? Math.max(state.cooldowns.weapon_power || 0, state.buildCooldownUntil) : state.cooldowns[power.power_key], now);
}
export function combatAllowed(state: PanelState, type: string, data: Record<string, unknown>, buildFamily = false, now = state.now) {
  if (!state.canAct || state.mutationBlocked) return false;
  if (type === 'hero.set_combat_stance') return !!state.hero?.hero && stances.some(s => s[0] === data.stance);
  if (!state.buffsReady) return false;
  if (type === 'player.spawn') {
    const price = state.config?.spawn_prices?.[String(data.side)];
    return ['player','enemy'].includes(String(data.side)) && validPrice(price) && data.price === price && !remaining(state.cooldowns[semanticCooldown(type,data)],now);
  }
  if (orders.some(o => o[0] === type)) {
    const price = state.config?.action_prices?.[type];
    return liveParticipant(state) && orderVisible(state,type) && validPrice(price) && data.price === price && !remaining(state.cooldowns[type],now) && (!['hero.detach_walls','hero.detach_gate'].includes(type) || state.battle?.is_siege === true);
  }
  const reply = state.build, build = reply?.build;
  if (type === 'hero.select_weapon_power') return !!(buildFamily && state.newBuild && reply?.ready && reply.can_manage && !reply.pending && !state.buildPending && !state.buildBusy && !build?.in_battle && build?.power_options?.some(p => p.weapon_type === data.weapon_type && p.available && p.weapon_type !== build.selected_weapon_type));
  if (type !== 'power.activate' || !reply || !liveParticipant(state)) return false;
  if (buildFamily) {
    if (!state.newBuild || !reply.ready || reply.pending || state.buildPending || state.buildBusy || !build || 'price' in data) return false;
    const weapon = build.power_options?.find(p => p.weapon_type === build.selected_weapon_type && p.power_key === build.selected_power && p.power_key === data.power_key);
    const power = weapon || build.common_powers?.find(p => p.power_key === data.power_key);
    return !!power && (!weapon || !!weapon.available) && validPrice(power.price) && state.points !== null && state.points >= power.price && powerCooldown(state,power,!!weapon,now) === 0 && !remaining(state.buffs[power.power_key],now);
  }
  if (state.newBuild || !Object.hasOwn(powerLabels,String(data.power_key))) return false;
  const power = state.classes?.current_powers?.find(p => p.power_key === data.power_key);
  return !!power && validPrice(power.price) && data.price === power.price && !remaining(state.cooldowns[power.power_key],now) && !remaining(state.buffs[power.power_key],now);
}
export const combatSections = ['summon','active_powers','tournament','weapon_choice'] as const;
export function combatPresentation(raw: unknown) {
  const labels: Record<string,string> = { active_powers:'Активки',weapon_choice:'Оружейная способность',summon_ally:'📯 Призвать за стримера',summon_enemy:'⚔️ Призвать против стримера' };
  let order: readonly string[] = combatSections;
  const visible: Record<string,boolean> = Object.fromEntries(combatSections.map(id => [id,true]));
  if (raw && typeof raw === 'object' && !Array.isArray(raw) && 'version' in raw && raw.version === 1) {
    const ui = raw as Record<string,unknown>, proposed=ui.combat_order;
    if (Array.isArray(proposed) && proposed.length === combatSections.length && proposed.every(id => combatSections.includes(id)) && new Set(proposed).size === combatSections.length) order=proposed;
    for (const id of combatSections) if (ui.combat_visible && typeof ui.combat_visible === 'object' && id in ui.combat_visible) { const value=(ui.combat_visible as Record<string,unknown>)[id]; if (typeof value === 'boolean') visible[id]=value; }
    for (const id of Object.keys(labels)) if (ui.labels && typeof ui.labels === 'object') { const value=(ui.labels as Record<string,unknown>)[id]; if (typeof value === 'string' && value.length>=1 && value.length<=64 && !/[\u0000-\u001f\u007f]/.test(value)) labels[id]=value; }
  }
  return {labels,visible,order:order.filter(id=>id!=='tournament')};
}
