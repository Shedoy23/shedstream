import saved from './panel-fixtures/kingdom-responses.json';
import { combatPair } from './panel-combat-support';
import type { LegacyFixtures,LegacyJson,LegacyRequest } from './panel-legacy-harness';
export { toggle,input,posts,normalized } from './panel-party-support';
export const r=saved.responses;
const action=(q:LegacyRequest):LegacyJson=>{const b=q.body as {action_type:string;data:Record<string,string|number>};const key=({'hero.create_kingdom':'create','hero.join_kingdom':'join','hero.leave_kingdom':'leave','hero.recruit_vassal_clan':'recruit','hero.enact_policy':'policy_enact','hero.make_peace':'direct_peace','kingdom.propose_war':'war','kingdom.propose_peace':'peace_vote'} as Record<string,string>)[b.action_type]||(b.action_type==='kingdom.set_tax_rate'?'tax_'+b.data.tax_rate_pct:'');const entry=(r as unknown as Record<string,{response:LegacyJson}>)[key];if(!entry)throw new Error('Unknown kingdom action '+JSON.stringify(b));return entry.response;};
export const kingdomPair=(overrides:Partial<LegacyFixtures>={},tab:'hero'|'dynasty'='dynasty')=>{
  // Use consistent real handler snapshots by default. Split-source tests must
  // opt into their contradiction explicitly instead of inheriting fake rulers.
  const h=(overrides.hero as {hero?:{kingdom_name?:string|null;kingdom_info?:{id?:string;is_ruler?:boolean;is_clan_leader?:boolean}|null}}|undefined)?.hero,ki=h?.kingdom_info;
  const kingdomState=!h?r.kingdom_ruler:!h.kingdom_name?r.kingdom_independent:ki?.id==='fixture_other_kingdom'?r.kingdom_other:ki?.is_ruler?r.kingdom_ruler:ki?.is_clan_leader?r.kingdom_vassal:r.kingdom_member;
  return combatPair({config:r.config,hero:r.hero_ruler,kingdomState,action,...overrides},false,tab,false,true);
};
