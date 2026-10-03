import {act} from '@testing-library/preact';
import {expect,it,vi} from 'vitest';
import {heroPair} from './panel-hero-support';
import saved from './panel-fixtures/hero-lifecycle-responses.json';
import {gameResponses as g,legacyResponses as f} from './panel-legacy-harness';
const h=saved.responses;
for(const [name,q,response] of [
  ['culture','[data-bnr-culture="Mod.Culture-X"]',h.create_culture.response],
  ['random','#bnr-adopt-random',h.create_random.response],
] as const)it(`hero ${name} creation uses the game catalog and exact complete legacy traffic`,async()=>{
  const p=await heroPair({hero:h.hero_absent,action:response,config:h.config});p.check();
  expect(p.ui.container.querySelector('[data-bnr-culture="Mod.Culture-X"]')?.textContent).toContain('Культура из игры');
  await p.old.click(q);await p.newClick(q);await p.finish();
  expect(p.trace.find(q=>q.method==='POST')?.body).toMatchObject(name==='culture'?h.create_culture.request:h.create_random.request);
  expect(p.ui.container.textContent).toContain('Заявка на создание героя отправлена');
});
it('random creation remains compatible with a missing catalog and sends no fabricated context',async()=>{
  const p=await heroPair({hero:h.hero_absent,catalogs:g.catalogs_missing,action:h.create_random.response,config:h.config});
  expect(p.ui.container.querySelectorAll('[data-bnr-culture]')).toHaveLength(0);
  await p.old.click('#bnr-adopt-random');await p.newClick('#bnr-adopt-random');await p.finish();
  expect(p.trace.find(q=>q.method==='POST')?.body).toMatchObject({action_type:'hero.create',data:{price:0}});
  expect((p.trace.find(q=>q.method==='POST')?.body as {data:object}).data).not.toHaveProperty('content_context');
});
it('an available empty culture catalog refuses creation without guessing cultures',async()=>{
  const p=await heroPair({hero:h.hero_absent,catalogs:{...g.catalogs,cultures:{available:true,entries:[]}},config:h.config});
  expect((p.ui.container.querySelector('#bnr-adopt-random') as HTMLButtonElement).disabled).toBe(true);
  await p.old.click('#bnr-adopt-random');await p.newClick('#bnr-adopt-random');await p.finish();
  expect(p.trace.some(q=>q.method==='POST')).toBe(false);
});
for(const confirm of [false,true])it(`dead hero respawn confirmation ${confirm} restores the warning bypassed by old _bnrConfirm`,async()=>{
  const p=await heroPair({hero:h.hero_dead,action:h.respawn.response,config:h.config});
  const startup=p.trace.length;
  await p.old.click('#bnr-heir-respawn');await p.newClick('#bnr-heir-respawn');
  expect(p.old.trace.filter(q=>q.method==='POST')).toHaveLength(1); // Old _bnrConfirm resolves true without a dialog.
  expect(p.trace.some(q=>q.method==='POST')).toBe(false);
  expect(p.ui.getByRole('dialog').textContent).toContain('Прежнего героя вернуть нельзя');
  await act(async()=>{p.ui.getByRole('button',{name:confirm?'Подтвердить':'Отмена',exact:true}).click();});
  if(confirm)await p.finish();else {await act(async()=>{await vi.advanceTimersByTimeAsync(3510);});expect(p.trace).toHaveLength(startup);}
  expect(p.trace.filter(q=>q.method==='POST')).toHaveLength(confirm?1:0);
});
it('a newly observed living hero invalidates the old respawn confirmation',async()=>{
  const p=await heroPair({hero:h.hero_dead,action:h.respawn.response,config:h.config});await p.newClick('#bnr-heir-respawn');
  p.fixtures.hero=f.hero;await act(async()=>{await p.controller.refreshHero();});
  expect(p.ui.queryByRole('dialog')).toBeNull();expect(p.trace.some(q=>q.method==='POST')).toBe(false);
});
it('a detached culture button cannot use its former catalog session',async()=>{
  const p=await heroPair({hero:h.hero_absent,action:h.create_culture.response,config:h.config});
  const before=p.ui.container.querySelector('[data-bnr-culture="Mod.Culture-X"]') as HTMLElement;expect(before).not.toBeNull();
  p.fixtures.catalogs={...g.catalogs,equipment_session_id:'next-session',cultures:{available:true,entries:[{id:'Next.Culture',name:'Другой выбор'}]}};
  await act(async()=>{await p.controller.refreshCatalogs();});
  await act(async()=>{before.click();});expect(p.trace.some(q=>q.method==='POST')).toBe(false);
});
it('hero creation preserves the current server refusal without a success tail',async()=>{
  const p=await heroPair({hero:h.hero_absent,action:h.create_stale.response,config:h.config});
  await p.old.click('[data-bnr-culture="Mod.Culture-X"]');await p.newClick('[data-bnr-culture="Mod.Culture-X"]');await p.finish();
  expect(p.ui.container.textContent).toContain(h.create_stale.response.message);
});
