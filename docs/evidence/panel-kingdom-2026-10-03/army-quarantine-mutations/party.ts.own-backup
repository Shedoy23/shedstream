import { kingdomConflicted } from './kingdom';
import { heroContext, validPrice, type HeroReply, type PanelState } from './contracts';
export interface Settlement { id:string; name?:string; type?:string; days?:number|null }
export interface ClanInfo { name?:string; is_leader?:boolean; tier?:number; renown?:number; members_count?:number; parties_count?:number; fiefs_count?:number }
export interface KingdomInfo { id?:string; name?:string; ruler_name?:string; is_ruler?:boolean; clans_count?:number; fiefs_count?:number; at_war_count?:number; at_war_names?:string[]; rebellion_supporters?:{id:string;name?:string;fiefs_count?:number}[]; rebellion_supporters_required?:number; rebellion_relation_required?:number; all_kingdoms?:({id:string;name?:string;at_war?:boolean}|null)[]|null; own_settlements?:Settlement[]|null; enemy_settlements?:Settlement[]|null; is_clan_leader?:boolean }
export interface PartyInfo { size?:number; task?:string; target?:string; in_army?:boolean|number; has_army?:boolean|number; army_party_count?:number; cohesion?:number }
export interface PartyOrder { id:number; order_type:string; target_settlement_id:string; target_settlement_name:string; issued_at:string; expires_at:string }
export interface PartyOrdersReply { success:boolean; active:PartyOrder|null }
export const clanInfo=(hero:HeroReply|null)=>(hero?.hero?.clan_info||null) as ClanInfo|null;
export const kingdomInfo=(hero:HeroReply|null)=>(hero?.hero?.kingdom_info||null) as KingdomInfo|null;
export const partyInfo=(hero:HeroReply|null)=>(hero?.hero?.party_info||null) as PartyInfo|null;
export const partyOwner=(hero:HeroReply|null)=>JSON.stringify([heroContext(hero),hero?.hero?.is_alive,hero?.hero?.clan_name,clanInfo(hero)?.name,clanInfo(hero)?.is_leader,hero?.hero?.kingdom_name,kingdomInfo(hero)?.id]);
export const partyTypes=[['siege','🏰','Осада','Атаковать поселение врага'],['defend','🛡','Защита','Защищать поселение'],['raid','🔥','Грабёж','Налёт на деревню (требуется война)'],['garrison','🏛','Гарнизон','Войти в поселение и стоять'],['patrol','🐎','Патруль','Патрулировать вокруг поселения'],['recruit','🪖','Собирать отряд','Ездить по мирным землям и нанимать добровольцев']] as const;
export const targetLabel=(s:Settlement)=>`${s.name||s.id} (${({town:'город',castle:'замок',village:'деревня'} as Record<string,string>)[s.type||'']||'?'}${s.days!=null&&s.days>0?', ~'+s.days+' дн':''})`;
export function targetsFor(type:string,ki:KingdomInfo|null){const own=Array.isArray(ki?.own_settlements)?ki.own_settlements:[],enemy=Array.isArray(ki?.enemy_settlements)?ki.enemy_settlements:[];return (type==='siege'?enemy.filter(s=>s&&s.type!=='village'):type==='raid'?enemy.filter(s=>s&&s.type==='village'):type==='garrison'?own.filter(s=>s&&s.type!=='village'):type==='recruit'?[]:own).slice().sort((a,b)=>(a.days??9999)-(b.days??9999));}
export const goldPrice=(s:PanelState,key:string)=>(s.config?.hero_gold_costs as Record<string,unknown>|undefined)?.[key];
export function partyAllowed(s:PanelState,type:string){
  if(!s.canAct||s.mutationBlocked||!s.hero?.has_hero||!s.hero.hero?.is_alive)return false;
  // Existing realm-sensitive commands must respect observations from the
  // politics card; unrelated clan, cancel and retinue paths remain usable.
  if(['hero.army_create','hero.army_disband','hero.party_order_set'].includes(type)&&kingdomConflicted(s))return false;
  const leader=!!clanInfo(s.hero)?.is_leader,hasClan=!!s.hero.hero.clan_name;
  switch(type){
    case 'hero.create_clan':return !hasClan&&validPrice(goldPrice(s,'create_clan'));
    case 'hero.join_clan':return !hasClan&&validPrice(goldPrice(s,'join_clan'));
    case 'hero.leave_clan':return hasClan;
    case 'hero.create_party':return leader&&!(clanInfo(s.hero)?.parties_count||0)&&validPrice(goldPrice(s,'create_party'));
    case 'hero.army_create':return leader&&!!s.hero.hero.kingdom_name&&!partyInfo(s.hero)?.in_army&&validPrice(s.config?.action_prices?.[type]);
    // Preserve the inherited in_army UI gate. Server/game owns actual leadership.
    case 'hero.army_disband':return leader&&!!s.hero.hero.kingdom_name&&!!partyInfo(s.hero)?.in_army&&validPrice(s.config?.action_prices?.[type]);
    case 'hero.party_order_set':return leader&&validPrice(s.config?.action_prices?.[type]);
    case 'hero.party_order_release':return leader&&!!s.partyOrders?.active&&validPrice(s.config?.action_prices?.[type]);
    default:return false;
  }
}
export const dangerContext=(s:PanelState,type:string)=>JSON.stringify([s.generation,partyOwner(s.hero),s.hero?.hero?.is_prisoner,type==='hero.army_disband'?partyInfo(s.hero):null,s.config?.action_prices?.[type]]);
