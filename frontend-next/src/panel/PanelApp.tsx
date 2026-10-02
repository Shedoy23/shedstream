import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ComponentType } from 'react';
import type { IdentityBootstrap } from '../skillgames/identity';
import type { PanelController } from './controller';
import { HeroDevelopmentView } from './HeroDevelopmentView';
export function PanelApp({ controller, identity, Equipment }: { controller: PanelController; identity: IdentityBootstrap; Equipment?: ComponentType<{ controller: PanelController; active?: boolean }> }) {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const gate = useSyncExternalStore(identity.subscribe, identity.snapshot);
  const [tab, setTab] = useState<'development' | 'equipment'>('development');
  const currentTab = useRef(tab); currentTab.current = tab;
  useLayoutEffect(() => { void controller.start(); return () => controller.stop(); }, [controller]);
  useEffect(() => {
    if (!state.canAct) return;
    const snapshotTimer = setInterval(() => { if (!document.hidden) { void controller.refreshHero(); void controller.refreshClasses(); void controller.refreshBuild(); if (currentTab.current === 'equipment') void controller.refreshEquipment(); } }, 8000);
    const cooldownTimer = setInterval(() => { if (!document.hidden) void controller.refreshBuffs(); }, 2500);
    const ticker = setInterval(controller.tick, 1000);
    // Register selected-host pollers before recording its initial exposure,
    // matching the old module setup. Repeated tasks keep normal timer ordering.
    controller.trackVisiblePanels();
    const visible = controller.trackVisiblePanels;
    document.addEventListener('visibilitychange', visible);
    return () => { clearInterval(snapshotTimer); clearInterval(cooldownTimer); clearInterval(ticker); document.removeEventListener('visibilitychange', visible); };
  }, [controller, state.canAct]);
  const changeTab = (next: typeof tab) => {
    if (currentTab.current !== next) controller.trackSection(next === 'development' ? 'bannerlord:tab.hero' : 'bannerlord:tab.inventory');
    else if (next === 'equipment' && tab === next) void controller.refreshEquipment();
    currentTab.current = next; setTab(next);
  };
  return <main className="panel-layout"><header className="panel-brand"><span className="panel-brand-mark">S</span><div><strong>ShedLink</strong><span>Герой Bannerlord</span></div></header>
    {gate.status !== 'ready' && <section className="panel-card"><p className="panel-eyebrow">ВХОД ЧЕРЕЗ TWITCH</p><h1>Подключите свою личность</h1><p role="status">{gate.message}</p>
      {gate.canShare && <button type="button" disabled={gate.status === 'resolving' || gate.shareRequested} onClick={() => identity.requestShare()}>Поделиться Twitch ID</button>}
      {gate.status === 'blocked' && <button type="button" onClick={() => { void identity.retry(); }}>Повторить проверку</button>}
      {!gate.canShare && <p className="panel-muted">Откройте расширение на странице Twitch и проверьте вход в аккаунт.</p>}
    </section>}
    <div hidden={gate.status !== 'ready' || !state.canAct}>
      {Equipment && <nav className="panel-tabs" aria-label="Раздел героя"><button type="button" aria-pressed={tab === 'development'} onClick={() => changeTab('development')}>Развитие</button><button type="button" aria-pressed={tab === 'equipment'} onClick={() => changeTab('equipment')}>Снаряжение</button></nav>}
      <div hidden={tab !== 'development'}><HeroDevelopmentView controller={controller} /></div>
      {Equipment && <div hidden={tab !== 'equipment'}><Equipment key={state.generation} controller={controller} active={tab === 'equipment' && state.canAct} /></div>}
    </div>
  </main>;
}
