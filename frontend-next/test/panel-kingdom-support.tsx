import saved from './panel-fixtures/kingdom-responses.json';
import { combatPair } from './panel-combat-support';
import type { LegacyFixtures,LegacyJson,LegacyRequest } from './panel-legacy-harness';
export { toggle,input,posts,normalized } from './panel-party-support';
export const r=saved.responses;
const action=(q:LegacyRequest):LegacyJson=>{const b=q.body as {action_type:string;data:Record<string,string|number>};const key=({'hero.create_kingdom':'create','hero.join_kingdom':'join','hero.leave_kingdom':'leave','hero.recruit_vassal_clan':'recruit','hero.enact_policy':'policy_enact','hero.make_peace':'direct_peace','kingdom.propose_war':'war','kingdom.propose_peace':'peace_vote'} as Record<string,string>)[b.action_type]||(b.action_type==='kingdom.set_tax_rate'?'tax_'+b.data.tax_rate_pct:'');const entry=(r as unknown as Record<string,{response:LegacyJson}>)[key];if(!entry)throw new Error('Unknown kingdom action '+JSON.stringify(b));return entry.response;};
export const kingdomPair=(overrides:Partial<LegacyFixtures>={},tab:'hero'|'dynasty'='dynasty')=>combatPair({config:r.config,hero:r.hero_ruler,action,...overrides},false,tab,false,true);
