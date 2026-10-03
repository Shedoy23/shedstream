import { act } from '@testing-library/preact';
import { expect,it } from 'vitest';
import { kingdomPair,toggle,posts } from './panel-kingdom-support';
import { gameResponses as g } from './panel-legacy-harness';
it('game policy catalog supplies custom IDs/names/descriptions and exact unchanged old action bytes',async()=>{
  const p=await kingdomPair({catalogs:g.catalogs});
  expect(p.ui.container.querySelectorAll('.bnr-diplo-policy-row')).toHaveLength(1);
  expect(p.ui.container.querySelector('[data-policy-id="Mod.Policy-X"]')?.textContent).toContain('Текст закона из игры');
  await toggle(p,'diplo-policy');
  await p.old.click('[data-policy-id="Mod.Policy-X"]');
  await act(async()=>{(p.ui.container.querySelector('[data-policy-id="Mod.Policy-X"]') as HTMLElement).click();});
  expect(posts(p)).toHaveLength(0);
  await act(async()=>{p.ui.getByRole('button',{name:'Подтвердить',exact:true}).click();});
  await p.advance(3500);p.check();
  const old=p.old.trace.find(q=>q.path.endsWith('/action'))!,next=posts(p)[0];
  expect(JSON.parse(next.rawBody!).data.policy_id).toBe('Mod.Policy-X');
  expect(next.rawBody!.replace(/"client_action_id":"[^"]+"/,'"client_action_id":"random"')).toBe(old.rawBody!.replace(/"client_action_id":"[^"]+"/,'"client_action_id":"random"'));
});
it('missing policy catalog has no guessed choices and admits no policy intent',async()=>{
  const p=await kingdomPair({catalogs:g.catalogs_missing});
  expect(p.ui.container.querySelectorAll('.bnr-diplo-policy-row')).toHaveLength(0);
  expect(await p.controller.diplomacyAction('hero.enact_policy',{policy_id:'policy_royal_guard',policy_name:'Guess'})).toBeNull();
  expect(posts(p)).toHaveLength(0);p.check();
});
it('changed game policy catalog cancels the paid confirmation for the displayed choice',async()=>{
  const p=await kingdomPair({catalogs:g.catalogs});await toggle(p,'diplo-policy');
  await act(async()=>{(p.ui.container.querySelector('[data-policy-id="Mod.Policy-X"]') as HTMLElement).click();});
  expect(p.ui.queryByRole('dialog')).not.toBeNull();
  p.fixtures.catalogs={...g.catalogs,equipment_session_id:'next-session',policies:{available:true,entries:[]}};
  await act(async()=>{await p.controller.refreshCatalogs();});
  expect(p.ui.queryByRole('dialog')).toBeNull();expect(posts(p)).toHaveLength(0);
});
