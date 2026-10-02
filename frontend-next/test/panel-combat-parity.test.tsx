import { act } from '@testing-library/preact';
import { expect, it } from 'vitest';
import { c, f, combatPair, flush, usageEvents } from './panel-combat-support';
import type { LegacyJson } from './panel-legacy-harness';
const orders = ['hero.detach_hold','hero.detach_charge','hero.detach_skirmish','hero.detach_raid','hero.attach','hero.detach_walls','hero.detach_gate','hero.detach'];
const selector = (attribute: string, value: string) => `[${attribute}="${value}"]`;
const posts = (p: Awaited<ReturnType<typeof combatPair>>) => p.trace.filter(r => r.path.endsWith('/action'));
it('actual host has combat startup balance reads and one active-transition buffs read', async () => {
  const p = await combatPair(); p.check();
  expect(p.old.sourceFiles).toHaveLength(23);
  expect(p.ui.getByRole('button',{name:'Боевые действия'}).getAttribute('aria-pressed')).toBe('true');
  expect(p.trace.map(r => r.path)).toEqual(['/api/bannerlord/config','/api/bannerlord/my-hero','/api/bannerlord/classes','/api/bannerlord/build','/api/bannerlord/my-buffs','/api/viewer/stats/alice','/api/user/level/alice','/api/duel/list','/api/bannerlord/battle-status','/api/bannerlord/my-buffs']);
  expect(p.ui.queryByText('Турнир зрителей')).toBeNull();
});
for (const type of orders) it(`old rendered ${type} matches full exact payload and delayed hidden-equipment tail`, async () => {
  const p = await combatPair({ build: c.build_combat_bow }); await p.tab('combat');
  await p.click(selector('data-det-act', type)); await p.advance(3500); p.check();
  expect(posts(p)[0].body).toMatchObject({ action_type: type, data: { price: c.config.action_prices[type as keyof typeof c.config.action_prices] } });
  expect(p.trace.filter(r => r.path.endsWith('/equipment-shop'))).toHaveLength(1);
});
for (const stance of ['defensive','balanced','aggressive']) it(`old rendered stance ${stance}, including current, has no price or preflight`, async () => {
  const p = await combatPair(); await p.tab('combat'); await p.click(selector('data-stance', stance)); await p.advance(3500); p.check();
  expect(posts(p)[0].body).toMatchObject({ action_type:'hero.set_combat_stance',data:{stance} });
  expect(Object.keys((posts(p)[0].body as {data:object}).data).sort()).toEqual(['client_action_id','stance']);
});
for (const side of ['player','enemy']) it(`old rendered ${side} summon preserves its separate price and side`, async () => {
  const p = await combatPair(); await p.tab('combat'); await p.click('#bnr-summon-' + (side === 'player' ? 'ally' : 'enemy') + '-btn'); await p.advance(3500); p.check();
  expect(posts(p)[0].body).toMatchObject({action_type:'player.spawn',data:{side,price:c.config.spawn_prices[side as 'player'|'enemy']}});
});
const seen = new Set<string>();
for (const [classKey, classes] of Object.entries(c.classes_by_key)) for (const power of classes.current_powers) {
  if (seen.has(power.power_key)) continue; seen.add(power.power_key);
  it(`actual ${classKey} legacy ability ${power.power_key} sends exact price+key and full tail`, async () => {
    const p = await combatPair({ classes }); await p.tab('combat'); await p.click(selector('data-bnr-power',power.power_key)); await p.advance(3500); p.check();
    expect(posts(p)[0].body).toMatchObject({action_type:'power.activate',data:{price:power.price,power_key:power.power_key}});
  });
}
for (const power of c.build_choices.build.power_options) {
  it(`actual weapon choice ${power.weapon_type} keeps weapon_type distinct from power_key`, async () => {
    const current = power.weapon_type === 'one_handed' ? c.build_combat_bow.build : c.build_choices.build;
    const p = await combatPair({ build: { ...c.build_choices, build:{...c.build_choices.build,selected_weapon_type:current.selected_weapon_type,selected_power:current.selected_power} } });
    await p.tab('combat'); await p.click(selector('data-bnr-build-select',power.weapon_type)); await p.advance(3500); p.check();
    expect(posts(p)[0].body).toMatchObject({action_type:'hero.select_weapon_power',data:{weapon_type:power.weapon_type}});
  });
  it(`actual selected ${power.weapon_type} ability sends only key+id, never legacy price`, async () => {
    const build = (c as unknown as Record<string,LegacyJson>)['build_combat_'+power.weapon_type];
    const p = await combatPair({ build }); await p.tab('combat'); await p.click(selector('data-bnr-build-activate',power.power_key)); await p.advance(3500); p.check();
    expect(Object.keys((posts(p)[0].body as {data:object}).data).sort()).toEqual(['client_action_id','power_key']);
  });
}
it('common heal has an independent action and exact new-build payload', async () => {
  const p = await combatPair({ build:c.build_combat_bow,buffs:c.buffs_build_bow }); await p.tab('combat');
  expect((p.ui.container.querySelector('[data-bnr-build-activate="explosive_arrows"]') as HTMLButtonElement).disabled).toBe(true);
  await p.click('[data-bnr-build-activate="heal_burst"]'); await p.advance(3500); p.check();
  expect(Object.keys((posts(p)[0].body as {data:object}).data).sort()).toEqual(['client_action_id','power_key']);
});
it('field siege buttons disabled and legacy knight keeps inherited absent raid', async () => {
  const p = await combatPair({battle:c.battle_field,classes:c.classes_by_key.knight}); await p.tab('combat');
  for (const type of ['hero.detach_walls','hero.detach_gate']) { const q=selector('data-det-act',type); expect((p.ui.container.querySelector(q) as HTMLButtonElement).disabled).toBe(true); await p.click(q); }
  expect(p.ui.container.querySelector('[data-det-act="hero.detach_raid"]')).toBeNull(); await p.advance(3500); p.check(); expect(posts(p)).toEqual([]);
});
for (const [name,battle] of Object.entries({idle:c.battle_idle,unspawned:c.battle_not_spawned,dead:c.battle_dead})) it(`${name} viewer cannot send legacy or new powers or orders`, async () => {
  const p = await combatPair({battle}); await p.tab('combat');
  expect(p.ui.container.querySelector('[data-det-act]')).toBeNull();
  for (const button of p.old.document.querySelectorAll('[data-bnr-power]')) await p.click(selector('data-bnr-power',(button as HTMLElement).dataset.bnrPower!));
  await p.advance(3500); p.check(); expect(posts(p)).toEqual([]);
});
for (const [name,build] of Object.entries({pending:c.build_pending_bow,syncing:c.build_syncing,legacy_session:c.build_legacy_session,prisoner:c.build_prisoner,unavailable:c.build_unavailable})) it(`${name} build cannot select unavailable choices or expose legacy fallback`, async () => {
  const p = await combatPair({ build }); await p.tab('combat'); expect(p.ui.container.querySelector('[data-bnr-power]')).toBeNull();
  for(const button of p.old.document.querySelectorAll('[data-bnr-build-select]')) await p.click(selector('data-bnr-build-select',(button as HTMLElement).dataset.bnrBuildSelect!));
  await p.advance(3500); p.check(); expect(posts(p)).toEqual([]);
});
it('same-frame opposite summons remain independent', async () => {
  let release!:(value:LegacyJson)=>void; const pending=new Promise<LegacyJson>(r=>release=r);
  const p=await combatPair({action:()=>pending}); await p.tab('combat');
  for(const id of ['#bnr-summon-ally-btn','#bnr-summon-enemy-btn']) (p.old.document.querySelector(id) as HTMLElement).click(); await p.old.settle();
  await act(async()=>{ for(const id of ['#bnr-summon-ally-btn','#bnr-summon-enemy-btn']) (p.ui.container.querySelector(id) as HTMLElement).click(); await flush(); });
  expect(posts(p)).toHaveLength(2); release(c.spawn_player.response); await p.advance(3500); p.check();
});
it('combat timer/visibility/tab lifecycle and telemetry use actual host and unchanged collector', async () => {
  const p=await combatPair(); await p.tab('hero'); await p.tab('combat'); await p.tab('combat'); await p.click('[data-stance="aggressive"]');
  await p.advance(3000); await p.tab('inventory'); await p.advance(5000); await p.tab('hero'); await p.advance(22000); p.check();
  expect(usageEvents(p.trace)).toContainEqual({kind:'section_open',feature:'bannerlord:tab.combat',count:1});
  expect(usageEvents(p.trace)).toContainEqual({kind:'action_attempt',feature:'bannerlord:hero.set_combat_stance',count:1});
  await p.hide(true); const n=p.trace.length; await p.advance(16000); expect(p.trace).toHaveLength(n); p.check();
  await p.hide(false); await p.advance(8000); p.check();
});
it('server refuses visibly with no success refresh tail', async()=>{
  const p=await combatPair({action:c.order_poor_refuse.response}); await p.tab('combat'); await p.click('[data-det-act="hero.detach_charge"]'); await p.advance(3500); p.check();
  expect(p.controller.snapshot().message).toBe(c.order_poor_refuse.response.message); expect(p.trace.some(r=>r.path.endsWith('equipment-shop'))).toBe(false);
});
it('safety deviation: refusal restores confirmed stance rather than leaving optimistic legacy highlight', async()=>{
  const p=await combatPair({action:c.order_poor_refuse.response}); await p.tab('combat'); await p.click('[data-stance="aggressive"]');
  expect((p.old.document.querySelector('[data-stance="aggressive"]') as HTMLElement).style.color).toBe('rgb(251, 191, 36)');
  expect(p.ui.container.querySelector('[data-stance="balanced"]')?.getAttribute('aria-pressed')).toBe('true');
  expect(p.ui.container.querySelector('[data-stance="aggressive"]')?.getAttribute('aria-pressed')).toBe('false'); p.check();
});
for(const [q,reply] of [['[data-bnr-power="rage"]',c.legacy_power_rage.response],['#bnr-summon-ally-btn',c.spawn_player.response],['#bnr-summon-enemy-btn',c.spawn_enemy.response]] as const) it(`safety deviation: ${q} immediately respects the acknowledged semantic cooldown`,async()=>{
  const p=await combatPair({action:reply}); await p.tab('combat'); await p.click(q);
  expect((p.old.document.querySelector(q) as HTMLButtonElement).disabled).toBe(false);
  expect((p.ui.container.querySelector(q) as HTMLButtonElement).disabled).toBe(true); p.check();
});
it('same-frame distinct legacy powers remain independent, unlike new-build family lock', async()=>{
  let release!:(value:LegacyJson)=>void;const pending=new Promise<LegacyJson>(r=>release=r);
  const p=await combatPair({action:()=>pending});await p.tab('combat');
  const qs=['[data-bnr-power="rage"]','[data-bnr-power="heal_burst"]'];
  for(const q of qs)(p.old.document.querySelector(q) as HTMLElement).click();await p.old.settle();
  await act(async()=>{for(const q of qs)(p.ui.container.querySelector(q) as HTMLElement).click();await flush();});
  expect(posts(p)).toHaveLength(2);release(c.legacy_power_rage.response);await p.advance(3500);p.check();
});
for(const qs of [ ['[data-bnr-build-select="bow"]','[data-bnr-build-select="crossbow"]'],['[data-bnr-build-activate="rage"]','[data-bnr-build-activate="heal_burst"]'] ]) it(`new-build shared synchronous lock: ${qs.join(' then ')}`,async()=>{
  let release!:(value:LegacyJson)=>void;const pending=new Promise<LegacyJson>(r=>release=r);
  const p=await combatPair({build:qs[0].includes('select')?c.build_choices:c.build_combat_one_handed,action:()=>pending});await p.tab('combat');
  for(const q of qs)(p.old.document.querySelector(q) as HTMLElement).click();await p.old.settle();
  await act(async()=>{for(const q of qs)(p.ui.container.querySelector(q) as HTMLElement).click();await flush();});
  expect(posts(p)).toHaveLength(1);release(c.build_power_one_handed.response);await p.advance(3500);p.check();
});
for(const [name,battle,expected] of [['spectator',c.battle_not_spawned,'В игре идёт бой'],['live',c.battle_siege,'После боя: ≈100–120💰'],['routed',c.battle_routed,'Бежит'],['killed',c.battle_killed,'Погиб'],['unconscious',c.battle_dead,'Без сознания'],['legacy',c.battle_legacy_payout,'+50💰'],['paid',c.battle_final_paid,'Получено: 154 800💰'],['failed',c.battle_final_failed,'Не удалось начислить награду'],['unavailable',c.battle_final_unavailable,'Нет подтверждённого итога боя']] as const) it(`battle ${name} presents actual snapshot`,async()=>{
  const p=await combatPair({battle});await p.tab('combat');expect(p.old.document.querySelector('#bnr-battle-banner-slot')?.textContent).toContain(expected);expect(p.ui.container.querySelector('#bnr-battle-banner-slot')?.textContent).toContain(expected);p.check();
});
it('unknown active buff is text and disables its exact known-key control until absolute expiry',async()=>{
  const p=await combatPair({buffs:c.buffs_active});await p.tab('combat');
  expect(p.ui.container.querySelector('#bnr-buff-hud')?.textContent).toContain('Ярость');
  await p.click('[data-bnr-power="rage"]');expect(posts(p)).toHaveLength(0);p.check();
});
it('server UI permutation, visibility, labels apply only to known combat sections',async()=>{
  const config={...f.config,ui:{version:1,combat_order:['weapon_choice','tournament','active_powers','summon'],combat_visible:{summon:false},labels:{weapon_choice:'Выбор <оружия>',active_powers:'<b>Активные</b>',summon_ally:'Вызвать союзника'}}};
  const p=await combatPair({config,build:c.build_choices});await p.tab('combat');
  const order=(host:ParentNode)=>[...host.querySelectorAll('[data-bnr-ui-section]')].map(e=>e.getAttribute('data-bnr-ui-section'));
  expect(order(p.ui.container)).toEqual(order(p.old.document));
  expect((p.ui.container.querySelector('[data-bnr-ui-section="summon"]') as HTMLElement).hidden).toBe(true);
  expect(p.ui.container.textContent).toContain('<b>Активные</b>');expect(p.ui.container.querySelector('#bnr-active-powers-slot b')).toBeNull();p.check();
});
it('real asynchronous mod refusal is shown once globally for six seconds, with exact old text',async()=>{
  const p=await combatPair();p.fixtures.hero=c.hero_refund_legacy_power_rage;
  await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();await flush();});
  const message='❌ Твой герой ещё не вышел на поле боя — крустики возвращены';
  expect(p.old.document.querySelector('.notification')?.textContent).toContain(message);
  expect(p.ui.getAllByText(message)).toHaveLength(1);await p.tab('hero');expect(p.ui.getAllByText(message)).toHaveLength(1);
  await p.old.refreshHero();await act(async()=>{await p.controller.refreshHero();await flush();});expect(p.ui.getAllByText(message)).toHaveLength(1);p.check();
  await p.advance(6300);expect(p.ui.queryByText(message)).toBeNull();p.check();
});
for(const [q,type,build] of [['[data-det-act="hero.detach_hold"]','hero.detach_hold',c.build_combat_bow],['#bnr-summon-enemy-btn','player.spawn',c.build_no_session],['[data-bnr-power="rage"]','power.activate',c.build_no_session],['[data-bnr-build-select="thrown"]','hero.select_weapon_power',c.build_choices],['[data-bnr-build-activate="rage"]','power.activate',c.build_combat_one_handed]] as const)it(`actual collector counts combat family ${type} through rendered ${q}`,async()=>{
  const p=await combatPair({build});await p.click(q);await p.advance(30000);p.check();expect(usageEvents(p.trace)).toContainEqual({kind:'action_attempt',feature:'bannerlord:'+type,count:1});
});
for(const ui of [{version:2,combat_order:['summon']},{version:1,combat_order:['summon','summon','active_powers','weapon_choice'],labels:{active_powers:'bad\nlabel'}},{version:1,combat_order:['unknown','summon','active_powers','weapon_choice'],labels:{weapon_choice:'x'.repeat(65)}},null])it(`malformed presentation keeps known defaults: ${JSON.stringify(ui)}`,async()=>{
  const p=await combatPair({config:{...f.config,ui},build:c.build_choices});expect([...p.ui.container.querySelectorAll('[data-bnr-ui-section]')].map(e=>e.getAttribute('data-bnr-ui-section'))).toEqual(['summon','active_powers','weapon_choice']);expect(p.ui.container.textContent).toContain('Активки');p.check();
});
it('real offline build disables weapon selection with server reason',async()=>{
  const p=await combatPair({build:c.build_offline});for(const option of c.build_choices.build.power_options)await p.click(`[data-bnr-build-select="${option.weapon_type}"]`);expect(posts(p)).toHaveLength(0);expect(p.ui.container.textContent).toContain(c.build_offline.message);p.check();
});
it('60-second actual balance interval refreshes passive affordability even while hidden',async()=>{
  const p=await combatPair({build:c.build_combat_one_handed,stats:{...f.stats,points:299}});expect((p.ui.container.querySelector('[data-bnr-build-activate="rage"]') as HTMLButtonElement).disabled).toBe(true);
  await p.advance(30000);p.fixtures.stats={...f.stats,points:300};await p.hide(true);await p.advance(29999);p.check();expect((p.ui.container.querySelector('[data-bnr-build-activate="rage"]') as HTMLButtonElement).disabled).toBe(true);
  await p.advance(1);p.check();expect((p.ui.container.querySelector('[data-bnr-build-activate="rage"]') as HTMLButtonElement).disabled).toBe(false);expect(p.trace.filter(r=>r.path==='/api/viewer/stats/alice')).toHaveLength(2);await p.hide(false);await p.advance(60000);p.check();
});
for(const [q,buffs] of [['[data-det-act="hero.detach_hold"]',c.buffs_order],['#bnr-summon-enemy-btn',c.buffs_spawn_enemy]] as const)it(`legacy cooldown text and 1-second countdown for ${q}`,async()=>{
  const p=await combatPair({buffs});await p.advance(1000);const text=(node:Element|null)=>node?.textContent?.replace(/\s+/g,' ').trim();expect(text(p.ui.container.querySelector(q))).toBe(text(p.old.document.querySelector(q)));p.check();
});
it('server zero prices stay valid for orders, summons and legacy powers',async()=>{
  const config={...f.config,action_prices:{...f.config.action_prices,'hero.detach_hold':0},spawn_prices:{player:0,enemy:0}};
  const classes={...c.classes_by_key.tank,current_powers:c.classes_by_key.tank.current_powers.map(p=>({...p,price:0}))};
  const p=await combatPair({config,classes});for(const q of ['[data-det-act="hero.detach_hold"]','#bnr-summon-enemy-btn','[data-bnr-power="rage"]'])await p.click(q);await p.advance(3500);p.check();expect(posts(p)).toHaveLength(3);for(const row of posts(p))expect((row.body as {data:{price:number}}).data.price).toBe(0);
});
it('new-build zero-priced ability is allowed with a verified zero balance and still omits price',async()=>{
  const build={...c.build_combat_one_handed,build:{...c.build_combat_one_handed.build,power_options:c.build_combat_one_handed.build.power_options.map(p=>({...p,price:0}))}};
  const p=await combatPair({build,stats:{...f.stats,points:0}});await p.click('[data-bnr-build-activate="rage"]');await p.advance(3500);p.check();expect(posts(p)).toHaveLength(1);expect((posts(p)[0].body as {data:object}).data).not.toHaveProperty('price');
});
for(const [saved,label] of [['combat','Боевые действия'],['hero','Развитие'],['inventory','Снаряжение']] as const)it(`restored ${saved} initial selected-host request trace matches actual old initialization`,async()=>{
  const p=await combatPair({},false,saved);p.check();expect(p.ui.getByRole('button',{name:label}).getAttribute('aria-pressed')).toBe('true');
  expect(p.trace.filter(r=>r.path.endsWith('/equipment-shop'))).toHaveLength(saved==='inventory'?1:0);
  await p.advance(8000);p.check();await p.tab('combat');await p.advance(8000);p.check();await p.tab('inventory');p.check();
});
