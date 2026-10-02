import type { PanelState } from './contracts';
import { clanInfo, kingdomInfo } from './party';
import { kingdomOwner } from './kingdom';
export interface PolicyStatus { policy_id:string; policy_name?:string; status?:string; [key:string]:unknown }
export interface DiplomacyReply { success:boolean; has_hero:boolean; kingdom_id?:string|null; kingdom_name?:string|null; is_king?:boolean; is_clan_leader?:boolean; kingdom_tax_pct?:number; policies_enacted?:PolicyStatus[]; policies_pending?:PolicyStatus[]; [key:string]:unknown }
// Existing curated legacy catalog: the server does not export policy options or
// descriptions. Keep IDs (including land_grands) verbatim; do not invent an API.
export const policies = [
    { id: 'policy_forgiveness_of_debts', name: 'Прощение долгов',
      desc: 'Лояльность всех городов +1, но налоговый доход королевства −10%. Подарок беднякам: народ доволен, казна беднее.' },
    { id: 'policy_land_grands_for_veteran', name: 'Земля ветеранам',
      desc: 'Отряды растут за счёт ветеранов и рекрутов (+5 к размеру партии). Милитаристский курс — у лордов больше войск.' },
    { id: 'policy_precarial_land_tenure', name: 'Условное землевладение',
      desc: 'Знать (нотабли) получает +5 влияния за каждый фьеф. Усиливает местную элиту, ослабляет центральную власть короля.' },
    { id: 'policy_royal_guard', name: 'Королевская гвардия',
      desc: 'Правитель королевства получает +80 кавалерии в личную дружину. Силовая опора трона.' },
    { id: 'policy_sacred_majesty', name: 'Священное величие',
      desc: 'Король: +2 влияния в день. Все остальные лидеры кланов: −1 в день. Жёсткая централизация власти у короля.' },
    { id: 'policy_trial_by_jury', name: 'Суд присяжных',
      desc: 'Лояльность во всех фьефах +0.5, безопасность +1. Народная справедливость — в городах спокойнее.' },
    { id: 'policy_imperial_towns', name: 'Имперские города',
      desc: 'Доход и процветание (prosperity) городов +5%. Города богатеют.' },
    { id: 'policy_noble_retinues', name: 'Дружины знати',
      desc: 'Размер отрядов лидеров кланов +20 бойцов. Твои и союзные лорды водят армии крупнее.' },
    { id: 'policy_lords_privy_council', name: 'Тайный совет лордов',
      desc: 'Все лидеры кланов королевства: +1 влияния в день. Феодальная децентрализация — власть лордам.' },
    { id: 'policy_council_of_the_commons', name: 'Совет общин',
      desc: 'Горожане получают +0.5 влияния в день и +1 к лояльности. Голос простого народа в политике.' },
    { id: 'policy_serfdom', name: 'Крепостное право',
      desc: 'Рост деревень (очаги и процветание) +2 в день, доход с деревень +10%. Крестьяне крепче привязаны к земле.' },
    { id: 'policy_citizenship', name: 'Гражданство',
      desc: 'Лояльность в городах своей культуры +1. Культурная интеграция — единоверцы держатся крепче.' },
];
export const diplomacyOwner=(s:PanelState)=>JSON.stringify([kingdomOwner(s.hero),s.diplomacy?.has_hero,s.diplomacy?.kingdom_id,s.diplomacy?.is_king,s.diplomacy?.is_clan_leader]);
export function diplomacyPrice(s:PanelState,type:string){const fallback=type==='hero.enact_policy'?1500:type==='kingdom.propose_peace'?3000:2000,raw=s.config?.action_prices?.[type];return raw==null||raw===''||!Number.isFinite(Number(raw))?fallback:Number(raw);}
export const proposalTargets=(s:PanelState,peace:boolean)=>{const all=kingdomInfo(s.hero)?.all_kingdoms;return Array.isArray(all)?all.filter((k):k is NonNullable<typeof k>=>!!k&&!!k.at_war===peace):[];};
export function diplomacyAllowed(s:PanelState,type:string,data:Record<string,unknown>={},now=Date.now()){
  const d=s.diplomacy,ki=kingdomInfo(s.hero);
  if(!s.canAct||s.mutationBlocked||!s.hero?.has_hero||!s.hero.hero?.is_alive||!clanInfo(s.hero)?.is_leader||!d?.has_hero||!d.kingdom_id||!ki?.id||d.kingdom_id!==ki.id)return false;
  const lead=!!(d.is_king||d.is_clan_leader);
  switch(type){
    case 'hero.enact_policy':return lead&&!d.policies_pending?.some(p=>p.policy_id===data.policy_id);
    case 'hero.make_peace':case 'kingdom.set_tax_rate':return !!d.is_king&&!!ki.is_ruler;
    case 'kingdom.propose_war':case 'kingdom.propose_peace':return lead&&(s.cooldowns[type]||0)<=now&&proposalTargets(s,type==='kingdom.propose_peace').some(k=>k.id.trim()===data.target_kingdom_id);
    default:return false;
  }
}
