import { act } from '@testing-library/preact';
import { expect,it,vi } from 'vitest';
import { partyPair,r,toggle,choose,input,posts } from './panel-party-support';
import { flush } from './panel-combat-support';
import type { LegacyJson } from './panel-legacy-harness';
const deferred=<T,>()=>{let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};};
const button=(p:Awaited<ReturnType<typeof partyPair>>,q:string)=>p.ui.container.querySelector(q) as HTMLButtonElement;
const click=async(p:Awaited<ReturnType<typeof partyPair>>,q:string)=>{await act(async()=>{button(p,q).click();await flush();});};
it('actual old party response reversal is reproduced while Preact keeps latest applied result',async()=>{
  const p=await partyPair(),a=deferred<LegacyJson>(),b=deferred<LegacyJson>();p.fixtures.partyOrders=(_,call)=>call===2?a.promise:b.promise;
  const oa=p.old.refreshPartyOrders(),na=p.controller.refreshPartyOrders(),ob=p.old.refreshPartyOrders(),nb=p.controller.refreshPartyOrders();b.resolve(r.orders_patrol);await act(async()=>{await Promise.all([ob,nb]);});a.resolve(r.orders_siege);await act(async()=>{await Promise.all([oa,na]);});
  expect(p.old.document.querySelector('#bnr-party-orders-slot')?.textContent).toContain('Осада');expect(p.controller.snapshot().partyOrders?.active?.order_type).toBe('patrol');
});
it('slow healthy party responses are not starved by later issued reads',async()=>{
  const p=await partyPair(),a=deferred<LegacyJson>(),b=deferred<LegacyJson>();p.fixtures.partyOrders=()=>a.promise;const first=p.controller.refreshPartyOrders();p.fixtures.partyOrders=()=>b.promise;const second=p.controller.refreshPartyOrders();a.resolve(r.orders_patrol);await act(async()=>{await first;});expect(p.controller.snapshot().partyOrders?.active?.order_type).toBe('patrol');b.resolve(r.orders_siege);await act(async()=>{await second;});expect(p.controller.snapshot().partyOrders?.active?.order_type).toBe('siege');
});
it('unchanged legacy writes after stop; owned Preact read cannot repopulate stopped host',async()=>{
  const p=await partyPair(),pending=deferred<LegacyJson>();p.fixtures.partyOrders=()=>pending.promise;const a=p.old.refreshPartyOrders(),b=p.controller.refreshPartyOrders();p.old.stop();p.controller.stop();pending.resolve(r.orders_patrol);await act(async()=>{await Promise.all([a,b]);});expect(p.old.document.querySelector('#bnr-party-orders-slot')?.textContent).toContain('Патруль');expect(p.controller.snapshot().partyOrders).toBeNull();
});
it('ignored pre-identity hero completion cannot launch a fresh party read for a new owner',async()=>{
  const p=await partyPair(),pending=deferred<LegacyJson>();p.fixtures.hero=()=>pending.promise;const a=p.controller.refreshHero();p.fixtures.hero=r.hero_party;
  await act(async()=>{p.authorize({token:'other-owner',channelId:'channel-a',userId:'opaque-other'});await flush();});const before=p.trace.length;pending.resolve(r.hero_army_leader);await act(async()=>{await a;await flush();});expect(p.trace.slice(before)).toEqual([]);
});
for(const [hero,q] of [[r.hero_army_leader,'[data-bnr-action="army_disband"]'],[r.hero_clan_member,'.bnr-locked-leave'],[r.hero_party,'.bnr-clan-leave']] as const)it(`${q} original confirmation cannot authorize changed observable viewer`,async()=>{
  const p=await partyPair({hero});await click(p,q);const yes=button(p,'#confirm-dyn-yes');expect(yes).not.toBeNull();await act(async()=>{p.authorize({token:'other-owner',channelId:'channel-a',userId:'opaque-other'});yes.click();await flush();});expect(posts(p)).toHaveLength(0);expect(p.ui.queryByRole('dialog')).toBeNull();
});
for(const change of ['hero','clan','army','quote'])it(`army confirmation invalidates changed ${change}`,async()=>{
  const p=await partyPair({hero:r.hero_army_leader});await click(p,'[data-bnr-action="army_disband"]');const yes=button(p,'#confirm-dyn-yes');
  if(change==='quote'){p.fixtures.config={...r.config,action_prices:{...r.config.action_prices,'hero.army_disband':1}};await act(async()=>{await p.controller.refreshConfig();yes.click();});}else{const hero=structuredClone(r.hero_army_leader);if(change==='hero')hero.hero.hero_id='fixture_successor';if(change==='clan')hero.hero.clan_name='fixture_other_clan';if(change==='army')hero.hero.party_info.army_party_count++;p.fixtures.hero=hero;await act(async()=>{await p.controller.refreshHero();yes.click();});}
  expect(posts(p)).toHaveLength(0);expect(p.ui.queryByRole('dialog')).toBeNull();
});
it('same-viewer JWT renewal retains draft and permits a fresh affirmative with current JWT',async()=>{
  const p=await partyPair({hero:r.hero_army_leader});await click(p,'[data-bnr-action="army_disband"]');await act(async()=>{p.authorize({token:'rotated',channelId:'channel-a',userId:'opaque-alice'});await flush();});await click(p,'#confirm-dyn-yes');expect(posts(p).at(-1)?.token).toBe('rotated');
});
for(const delay of [1500,2000])it(`local ${delay}ms tail cannot follow stop and new JWT; original legacy hole stays measured`,async()=>{
  const p=await partyPair({partyOrders:r.orders_siege});if(delay===1500)await p.click('#bnr-order-cancel');else{await toggle(p,'party-order');await p.click('#bnr-order-confirm');}
  p.old.stop();p.old.setIdentity('alice','changed-token');p.controller.stop();const oldBefore=p.old.trace.length,newBefore=p.trace.length;await p.old.advance(delay);await act(async()=>{await vi.advanceTimersByTimeAsync(delay);await flush();});expect(p.old.trace.slice(oldBefore).some(q=>q.path.endsWith('/party-orders')&&q.token==='changed-token')).toBe(true);expect(p.trace.slice(newBefore)).toEqual([]);
});
it('same-viewer token changed during pending order cannot schedule old local tail',async()=>{
  const pending=deferred<LegacyJson>(),p=await partyPair({action:()=>pending.promise});await toggle(p,'party-order');await click(p,'#bnr-order-confirm');await act(async()=>{p.authorize({token:'rotated',channelId:'channel-a',userId:'opaque-alice'});await flush();});pending.resolve(r.order_siege.response);await act(flush);await p.hide(true);const before=p.trace.length;await act(async()=>{await vi.advanceTimersByTimeAsync(3500);await flush();});expect(p.trace.slice(before).filter(q=>q.path.endsWith('/party-orders'))).toHaveLength(0);
});
it('read before accepted set cannot resurrect the old order after acknowledgement',async()=>{
  const p=await partyPair(),pending=deferred<LegacyJson>();p.fixtures.partyOrders=()=>pending.promise;const read=p.controller.refreshPartyOrders();await toggle(p,'party-order');await click(p,'#bnr-order-confirm');pending.resolve(r.orders_patrol);await act(async()=>{await read;});expect(p.controller.snapshot().partyOrders?.active).toBeNull();
});
it('party error preserves the last confirmed snapshot and text, then retry recovers',async()=>{
  const p=await partyPair({partyOrders:r.orders_siege});p.fixtures.partyOrders={success:false,message:'Сервер временно недоступен'};await act(async()=>{await p.controller.refreshPartyOrders();});expect(p.controller.snapshot().partyOrders?.active?.order_type).toBe('siege');expect(p.ui.container.textContent).toContain('Сервер временно недоступен');p.fixtures.partyOrders=r.orders_patrol;await act(async()=>{await p.controller.refreshPartyOrders();});expect(p.controller.snapshot().partyOrders?.active?.order_type).toBe('patrol');
});
it('army member retains inherited disband affordance and real server owns eligibility',async()=>{const p=await partyPair({hero:r.hero_army_member});expect(button(p,'[data-bnr-action="army_disband"]').disabled).toBe(false);await p.click('[data-bnr-action="army_disband"]');await p.click('#confirm-dyn-yes');await p.advance(3500);p.check();});
for(const kind of ['clan','join','party','army','order'])it(`missing ${kind} price is unavailable without fake free quote`,async()=>{
  const config=structuredClone(r.config),isLocked=['clan','join'].includes(kind);if(['clan','join','party'].includes(kind))delete (config.hero_gold_costs as Record<string,unknown>)[{clan:'create_clan',join:'join_clan',party:'create_party'}[kind as 'clan'|'join'|'party']];else delete(config.action_prices as Record<string,unknown>)[kind==='army'?'hero.army_create':'hero.party_order_set'];
  const p=await partyPair({hero:isLocked?r.hero_clanless:r.hero_no_party,config});if(isLocked)await toggle(p,kind==='clan'?'locked-create':'locked-join');if(kind==='order')await toggle(p,'party-order');const q=({clan:'#bnr-clan-confirm',join:'#bnr-j-confirm',party:'.bnr-clan-party',army:'[data-bnr-action="army_create"]',order:'#bnr-order-confirm'} as Record<string,string>)[kind];expect(button(p,q).disabled).toBe(true);await click(p,q);expect(posts(p)).toHaveLength(0);
});
it('create/join open drafts survive ordinary hero/config polls and Enter uses latest synchronous text',async()=>{const p=await partyPair({hero:r.hero_clanless});await toggle(p,'locked-join');await input(p,'#bnr-join-name-input','Fixture Existing Clan');await p.advance(8000);expect((button(p,'#bnr-join-name-input') as unknown as HTMLInputElement).value).toBe('Fixture Existing Clan');await p.click('#bnr-j-confirm');await p.advance(3500);p.check();});
it('unknown-outcome lock crosses order, clan, army and retinue controls',async()=>{const p=await partyPair({action:null});await click(p,'[data-bnr-action="army_create"]');expect(p.controller.snapshot().mutationBlocked).toBe(true);expect(button(p,'.bnr-clan-leave').disabled).toBe(true);await toggle(p,'party-order');expect(button(p,'#bnr-order-confirm').disabled).toBe(true);expect(button(p,'#bnr-recruit-basic-btn').disabled).toBe(true);expect(posts(p)).toHaveLength(1);});
it('dismiss by backdrop or Escape sends nothing and can reopen with current context',async()=>{const p=await partyPair({hero:r.hero_army_leader});await click(p,'[data-bnr-action="army_disband"]');await click(p,'#confirm-dyn-modal');expect(posts(p)).toHaveLength(0);await click(p,'[data-bnr-action="army_disband"]');await act(async()=>{document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));});expect(p.ui.queryByRole('dialog')).toBeNull();expect(posts(p)).toHaveLength(0);});
it('collapsed army and order cards remain collapsed without suppressing active reads',async()=>{const p=await partyPair();for(const host of [p.old.document,p.ui.container])for(const key of ['army','partyorders']){const d=host.querySelector(`[data-bnr-section="${key}"]`) as HTMLDetailsElement;d.open=false;d.dispatchEvent(new (host===p.old.document?p.old.window.Event:Event)('toggle'));}await p.advance(8000);for(const key of ['army','partyorders'])expect((p.ui.container.querySelector(`[data-bnr-section="${key}"]`) as HTMLDetailsElement).open).toBe(false);p.check();});
it('read-owned clan switch clears previous order and does not preserve stale target draft',async()=>{const p=await partyPair({partyOrders:r.orders_siege});await toggle(p,'party-order');await choose(p,'patrol');p.fixtures.hero=r.hero_clan_member;await act(async()=>{await p.controller.refreshHero();});expect(p.ui.container.querySelector('#bnr-order-confirm')).toBeNull();expect(p.controller.snapshot().partyOrders).toBeNull();});
