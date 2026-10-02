import {act} from '@testing-library/preact';
import {expect,it} from 'vitest';
import {kingdomPair,r,posts} from './panel-kingdom-support';
import saved from './panel-fixtures/party-responses.json';
import {flush} from './panel-combat-support';
const armyHero={...r.hero_ruler,hero:{...r.hero_ruler.hero,party_info:{size:25,in_army:1,has_army:1,army_party_count:3,cohesion:70}}};
const noArmyHero={...armyHero,hero:{...armyHero.hero,party_info:{...armyHero.hero.party_info,in_army:0,has_army:0}}};
const button=(p:Awaited<ReturnType<typeof kingdomPair>>,q:string)=>p.ui.container.querySelector(q) as HTMLButtonElement|null;
const click=async(p:Awaited<ReturnType<typeof kingdomPair>>,q:string)=>{await act(async()=>{button(p,q)?.click();await flush();});};
for(const state of [r.kingdom_other,r.kingdom_vassal])it(`army affirmative cannot use observed ${state.kingdom_id}/${state.is_king} contradiction`,async()=>{
 const p=await kingdomPair({hero:armyHero,action:saved.responses.army_disband.response});
 await p.click('[data-bnr-action="army_disband"]');const yes=button(p,'#confirm-dyn-yes')!;
 p.fixtures.kingdomState=state;await p.old.refreshDiplomacy();await p.old.click('#confirm-dyn-yes');expect(p.old.trace.filter(q=>q.path.endsWith('/action'))).toHaveLength(1);
 await act(async()=>{await p.controller.refreshDiplomacy();yes.click();await flush();});expect(posts(p)).toHaveLength(0);expect(p.ui.queryByRole('dialog')).toBeNull();expect(button(p,'[data-bnr-action="army_disband"]')?.disabled).toBe(true);
});
for(const state of [r.kingdom_other,r.kingdom_vassal])it(`army create saved button and controller admission reject ${state.kingdom_id}/${state.is_king} contradiction`,async()=>{
 const p=await kingdomPair({hero:noArmyHero,action:saved.responses.army_create.response}),send=button(p,'[data-bnr-action="army_create"]')!;
 p.fixtures.kingdomState=state;await act(async()=>{await p.controller.refreshDiplomacy();send.click();await p.controller.partyAction('hero.army_create',{});await flush();});expect(posts(p)).toHaveLength(0);expect(button(p,'[data-bnr-action="army_create"]')?.disabled).toBe(true);
});
it('agreement restores army create while previous contradiction sends nothing',async()=>{const p=await kingdomPair({hero:noArmyHero,action:saved.responses.army_create.response});p.fixtures.kingdomState=r.kingdom_other;await act(async()=>{await p.controller.refreshDiplomacy();});await click(p,'[data-bnr-action="army_create"]');expect(posts(p)).toHaveLength(0);p.fixtures.kingdomState=r.kingdom_ruler;await act(async()=>{await p.controller.refreshDiplomacy();});expect(button(p,'[data-bnr-action="army_create"]')?.disabled).toBe(false);await click(p,'[data-bnr-action="army_create"]');expect(posts(p)).toHaveLength(1);});
it('agreement does not revive old army affirmative; fresh consent works',async()=>{const p=await kingdomPair({hero:armyHero,action:saved.responses.army_disband.response});await click(p,'[data-bnr-action="army_disband"]');const yes=button(p,'#confirm-dyn-yes')!;p.fixtures.kingdomState=r.kingdom_other;await act(async()=>{await p.controller.refreshDiplomacy();});expect(p.ui.queryByRole('dialog')).toBeNull();p.fixtures.kingdomState=r.kingdom_ruler;await act(async()=>{await p.controller.refreshDiplomacy();yes.click();await flush();});expect(posts(p)).toHaveLength(0);await click(p,'[data-bnr-action="army_disband"]');await click(p,'#confirm-dyn-yes');expect(posts(p)).toHaveLength(1);});
it('unobserved diplomacy does not block previously valid army controls',async()=>{let resolve!:(v:typeof r.kingdom_ruler)=>void;const pending=new Promise<typeof r.kingdom_ruler>(r=>resolve=r);const p=await kingdomPair({hero:noArmyHero,kingdomState:()=>pending,action:saved.responses.army_create.response});expect(p.controller.snapshot().diplomacy).toBeNull();expect(button(p,'[data-bnr-action="army_create"]')?.disabled).toBe(false);resolve(r.kingdom_ruler);await act(flush);await p.old.settle();await p.click('[data-bnr-action="army_create"]');await p.advance(3500);p.check();});
it('observed kingdom quarantine leaves unrelated retinue recruitment usable',async()=>{const p=await kingdomPair({hero:noArmyHero,action:saved.responses.recruit_basic.response});p.fixtures.kingdomState=r.kingdom_other;await act(async()=>{await p.controller.refreshDiplomacy();});await p.tab('hero');expect(button(p,'#bnr-recruit-basic-btn')?.disabled).toBe(false);await click(p,'#bnr-recruit-basic-btn');expect(posts(p)).toHaveLength(1);expect((posts(p)[0].body as {action_type:string}).action_type).toBe('hero.recruit_troops');});
