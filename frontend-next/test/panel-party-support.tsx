import { act } from '@testing-library/preact';
import { expect } from 'vitest';
import saved from './panel-fixtures/party-responses.json';
import { combatPair, flush, normalized } from './panel-combat-support';
import type { LegacyFixtures,LegacyJson,LegacyRequest } from './panel-legacy-harness';
const r=saved.responses;
const action=(q:LegacyRequest):LegacyJson=>{const b=q.body as {action_type:string;data:{order_type:string}};const key=b.action_type==='hero.party_order_set'?'order_'+b.data.order_type:({'hero.party_order_release':'order_release','hero.army_create':'army_create','hero.army_disband':'army_disband','hero.create_clan':'clan_create','hero.join_clan':'clan_join','hero.leave_clan':'clan_leave','hero.create_party':'create_party'} as Record<string,string>)[b.action_type];const item=(r as unknown as Record<string,{response:LegacyJson}>)[key];if(!item)throw new Error('Unknown party action '+JSON.stringify(b));return item.response;};
export const partyPair=(overrides:Partial<LegacyFixtures>={},tab:'hero'|'dynasty'='dynasty')=>combatPair({config:r.config,hero:r.hero_party,kingdomState:r.kingdom_party,action,...overrides},false,tab,false,true);
type Pair=Awaited<ReturnType<typeof partyPair>>;
const hosts=(p:Pair):ParentNode[]=>[p.old.document,p.ui.container];
async function toggle(p:Pair,key:string,open=true){for(const host of hosts(p)){const n=host.querySelector<HTMLDetailsElement>(`[data-bnr-details="${key}"]`);expect(n).not.toBeNull();n!.open=open;n!.dispatchEvent(new (host===p.old.document?p.old.window.Event:Event)('toggle'));}await p.old.settle();await act(flush);}
async function choose(p:Pair,type:string){for(const host of hosts(p)){const n=host.querySelector<HTMLInputElement>(`input[name="bnr-order-type"][value="${type}"]`);expect(n).not.toBeNull();n!.checked=true;n!.dispatchEvent(new (host===p.old.document?p.old.window.Event:Event)('change',{bubbles:true}));}await p.old.settle();await act(flush);}
async function input(p:Pair,q:string,value:string,enter=false){for(const host of hosts(p)){const n=host.querySelector<HTMLInputElement>(q);expect(n).not.toBeNull();n!.value=value;n!.dispatchEvent(new (host===p.old.document?p.old.window.Event:Event)('input',{bubbles:true}));if(enter)n!.dispatchEvent(new (host===p.old.document?(p.old.window as unknown as Window&{KeyboardEvent:typeof KeyboardEvent}).KeyboardEvent:KeyboardEvent)('keydown',{key:'Enter',bubbles:true}));}await p.old.settle();await act(flush);}
const posts=(p:Pair)=>p.trace.filter(q=>q.path.endsWith('/action'));

export {r, toggle,choose,input,posts,normalized};
