import { heroContext, validPrice, type HeroReply, type PanelState } from './contracts';
import { clanInfo, goldPrice, kingdomInfo } from './party';
// Existing DTO fields are the only available realm/role identity. In particular,
// /my-hero has no top-level kingdom_id and exports no game-session revision.
export const kingdomOwner=(hero:HeroReply|null)=>JSON.stringify([heroContext(hero),hero?.hero?.is_alive,hero?.hero?.is_prisoner,hero?.hero?.clan_name,clanInfo(hero)?.name,clanInfo(hero)?.is_leader,hero?.hero?.kingdom_name,kingdomInfo(hero)?.id,kingdomInfo(hero)?.is_ruler,kingdomInfo(hero)?.is_clan_leader]);
export const compact=(n:number)=>n>=1000000?(n/1000000).toFixed(n%1000000?1:0)+'M':n>=1000?(n/1000).toFixed(n%1000?1:0)+'K':String(n);
export function kingdomQuote(s:PanelState,type:string){const gold=goldPrice(s,type==='hero.create_kingdom'?'create_kingdom':type==='hero.join_kingdom'?'join_kingdom':'recruit_vassal'),crustics=type==='hero.create_kingdom'||type==='hero.join_kingdom'?0:s.config?.action_prices?.[type];return validPrice(gold)&&validPrice(crustics)?{gold,crustics}:null;}
export function quoteLabel(s:PanelState,type:string,full=false){const q=kingdomQuote(s,type),fmt=full?(n:number)=>n.toLocaleString('ru-RU'):compact;return q?(q.crustics?fmt(q.crustics)+'💎 + ':'')+fmt(q.gold)+'💰':'цена не загружена';}
// Unlike the inherited fallback, unverified join prices now fail closed.
export const joinLabel=(s:PanelState)=>quoteLabel(s,'hero.join_kingdom');
export function kingdomAllowed(s:PanelState,type:string){if(!s.canAct||s.mutationBlocked||!s.hero?.has_hero||!s.hero.hero?.is_alive||!clanInfo(s.hero)?.is_leader)return false;const has=!!s.hero.hero.kingdom_name,ki=kingdomInfo(s.hero);switch(type){case 'hero.create_kingdom':return (!has||!!ki&&!ki.is_ruler&&!!ki.is_clan_leader)&&!!kingdomQuote(s,type);case 'hero.join_kingdom':return !has&&!!kingdomQuote(s,type);case 'hero.leave_kingdom':return has;case 'hero.recruit_vassal_clan':return has&&!!ki?.is_ruler&&!!kingdomQuote(s,type);default:return false;}}
