import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ComponentType } from 'react';
import type { IdentityBootstrap } from '../skillgames/identity';
import type { PanelController } from './controller';
import { CombatView } from './CombatView';
import { HeroDevelopmentView } from './HeroDevelopmentView';
export function PanelApp({ controller, identity, Equipment, combat = false }: { controller: PanelController; identity: IdentityBootstrap; combat?: boolean; Equipment?: ComponentType<{ controller: PanelController; active?: boolean }> }) {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const gate = useSyncExternalStore(identity.subscribe, identity.snapshot);
  const [tab, setTab] = useState<'development' | 'equipment' | 'combat'>(() => {
    if (!combat) return 'development';
    try { const saved = localStorage.getItem('bnr_active_tab'); if (saved === 'hero') return 'development'; if (saved === 'inventory' && Equipment) return 'equipment'; } catch { /* Storage may be unavailable inside Twitch. */ }
    return 'combat';
  });
  const currentTab = useRef(tab); currentTab.current = tab;
  useLayoutEffect(() => { if (combat) controller.enableCombat(); void controller.start(); return () => controller.stop(); }, [controller, combat]);
  useEffect(() => {
    if (!state.canAct) return;
    const snapshotTimer = setInterval(() => { if (!document.hidden) { void controller.refreshHero(); void controller.refreshClasses(); void controller.refreshBuild(); if (currentTab.current === 'equipment') void controller.refreshEquipment(); } }, 8000);
    const battleTimer = combat ? setInterval(() => { if (!document.hidden) void controller.refreshBattle(); }, 2000) : undefined;
    const cooldownTimer = setInterval(() => { if (!document.hidden) void controller.refreshBuffs(); }, 2500);
    const ticker = setInterval(controller.tick, 1000);
    // Register selected-host pollers before recording its initial exposure,
    // matching the old module setup. Repeated tasks keep normal timer ordering.
    controller.trackVisiblePanels();
    const visible = controller.trackVisiblePanels;
    document.addEventListener('visibilitychange', visible);
    return () => { clearInterval(snapshotTimer); clearInterval(battleTimer); clearInterval(cooldownTimer); clearInterval(ticker); document.removeEventListener('visibilitychange', visible); };
  }, [controller, state.canAct, combat]);
  const changeTab = (next: typeof tab) => {
    if (currentTab.current !== next) controller.trackSection(next === 'development' ? 'bannerlord:tab.hero' : next === 'combat' ? 'bannerlord:tab.combat' : 'bannerlord:tab.inventory');
    else if (next === 'equipment' && tab === next) void controller.refreshEquipment();
    if (combat) { try { localStorage.setItem('bnr_active_tab', next === 'development' ? 'hero' : next === 'equipment' ? 'inventory' : 'combat'); } catch { /* Optional tab persistence. */ } }
    currentTab.current = next; setTab(next);
  };
  return <main className="panel-layout"><header className="panel-brand"><span className="panel-brand-mark">S</span><div><strong>ShedLink</strong><span>Герой Bannerlord</span></div></header>
    {gate.status !== 'ready' && <section className="panel-card"><p className="panel-eyebrow">ВХОД ЧЕРЕЗ TWITCH</p><h1>Подключите свою личность</h1><p role="status">{gate.message}</p>
      {gate.canShare && <button type="button" disabled={gate.status === 'resolving' || gate.shareRequested} onClick={() => identity.requestShare()}>Поделиться Twitch ID</button>}
      {gate.status === 'blocked' && <button type="button" onClick={() => { void identity.retry(); }}>Повторить проверку</button>}
      {!gate.canShare && <p className="panel-muted">Откройте расширение на странице Twitch и проверьте вход в аккаунт.</p>}
    </section>}
    <div hidden={gate.status !== 'ready' || !state.canAct}>
      {state.refundNotices.map(notice => <p className="panel-notice" role="alert" key={notice.id}>{notice.message}</p>)}
      {(Equipment || combat) && <nav className="panel-tabs" aria-label="Раздел героя"><button type="button" aria-pressed={tab === 'development'} onClick={() => changeTab('development')}>Развитие</button>{Equipment && <button type="button" aria-pressed={tab === 'equipment'} onClick={() => changeTab('equipment')}>Снаряжение</button>}{combat && <button type="button" aria-pressed={tab === 'combat'} onClick={() => changeTab('combat')}>Боевые действия</button>}</nav>}
      {combat && <div hidden={tab !== 'combat'}><CombatView controller={controller} /></div>}
      <div hidden={tab !== 'development'}><HeroDevelopmentView controller={controller} /></div>
      {Equipment && <div hidden={tab !== 'equipment'}><Equipment key={state.generation} controller={controller} active={tab === 'equipment' && state.canAct} /></div>}
    </div>
  </main>;
}
