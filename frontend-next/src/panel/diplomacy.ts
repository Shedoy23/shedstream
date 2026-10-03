import {contentEntries} from './progression';
import { validPrice, type PanelState } from './contracts';
import { clanInfo, kingdomInfo } from './party';
import { kingdomConflicted, kingdomOwner } from './kingdom';
export interface PolicyStatus { policy_id:string; policy_name?:string; status?:string; [key:string]:unknown }
export interface DiplomacyReply { success:boolean; has_hero:boolean; kingdom_id?:string|null; kingdom_name?:string|null; is_king?:boolean; is_clan_leader?:boolean; kingdom_tax_pct?:number; policies_enacted?:PolicyStatus[]; policies_pending?:PolicyStatus[]; [key:string]:unknown }
export const diplomacyOwner=(s:PanelState)=>JSON.stringify([kingdomOwner(s.hero),s.diplomacy?.has_hero,s.diplomacy?.kingdom_id,s.diplomacy?.is_king,s.diplomacy?.is_clan_leader]);
export function diplomacyPrice(s:PanelState,type:string){const raw=s.config?.action_prices?.[type];return validPrice(raw)?raw:null;}
export function diplomacyLabel(s:PanelState,type:string){const price=diplomacyPrice(s,type);return price===null?'Цена не загружена':price+'💎';}
export const proposalTargets=(s:PanelState,peace:boolean)=>{const all=kingdomInfo(s.hero)?.all_kingdoms;return Array.isArray(all)?all.filter((k):k is NonNullable<typeof k>=>!!k&&!!k.at_war===peace):[];};
export function diplomacyAllowed(s:PanelState,type:string,data:Record<string,unknown>={},now=Date.now()){
  const d=s.diplomacy,ki=kingdomInfo(s.hero);
  if(!s.canAct||s.mutationBlocked||kingdomConflicted(s)||!s.hero?.has_hero||!s.hero.hero?.is_alive||!clanInfo(s.hero)?.is_leader||!d?.has_hero||!d.kingdom_id||!ki?.id||d.kingdom_id!==ki.id)return false;
  if(type!=='kingdom.set_tax_rate'&&diplomacyPrice(s,type)===null)return false;
  const lead=!!(d.is_king||d.is_clan_leader);
  switch(type){
    case 'hero.enact_policy':return lead&&contentEntries(s.catalogs?.policies).some(p=>p.id===data.policy_id&&(p.name||p.id)===data.policy_name&&p.available!==false)&&!d.policies_pending?.some(p=>p.policy_id===data.policy_id);
    case 'hero.make_peace':case 'kingdom.set_tax_rate':return !!d.is_king&&!!ki.is_ruler;
    case 'kingdom.propose_war':case 'kingdom.propose_peace':return lead&&(s.cooldowns[type]||0)<=now&&proposalTargets(s,type==='kingdom.propose_peace').some(k=>k.id.trim()===data.target_kingdom_id);
    default:return false;
  }
}
