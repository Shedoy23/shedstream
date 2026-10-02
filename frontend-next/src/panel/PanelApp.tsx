import { useEffect, useLayoutEffect, useState, useSyncExternalStore, type ComponentType } from 'react';
import type { IdentityBootstrap } from '../skillgames/identity';
import type { PanelController } from './controller';
import { HeroDevelopmentView } from './HeroDevelopmentView';
export function PanelApp({ controller, identity, Equipment }: { controller: PanelController; identity: IdentityBootstrap; Equipment?: ComponentType<{ controller: PanelController }> }) {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const gate = useSyncExternalStore(identity.subscribe, identity.snapshot);
  const [tab, setTab] = useState<'development' | 'equipment'>('development');
  useLayoutEffect(() => { void controller.start(); return () => controller.stop(); }, [controller]);
  useEffect(() => {
    if (!state.canAct) return;
    const snapshotTimer = setInterval(() => { if (!document.hidden) { void controller.refreshHero(); void controller.refreshClasses(); void controller.refreshBuild(); void controller.refreshEquipment(); } }, 8000);
    const cooldownTimer = setInterval(() => { if (!document.hidden) void controller.refreshBuffs(); }, 2500);
    const ticker = setInterval(controller.tick, 1000);
    const visible = () => { if (!document.hidden) void controller.refresh(); };
    document.addEventListener('visibilitychange', visible);
    return () => { clearInterval(snapshotTimer); clearInterval(cooldownTimer); clearInterval(ticker); document.removeEventListener('visibilitychange', visible); };
  }, [controller, state.canAct]);
  return <main className="panel-layout"><header className="panel-brand"><span className="panel-brand-mark">S</span><div><strong>ShedLink</strong><span>Герой Bannerlord</span></div></header>
    {gate.status !== 'ready' && <section className="panel-card"><p className="panel-eyebrow">ВХОД ЧЕРЕЗ TWITCH</p><h1>Подключите свою личность</h1><p role="status">{gate.message}</p>
      {gate.canShare && <button type="button" disabled={gate.status === 'resolving' || gate.shareRequested} onClick={() => identity.requestShare()}>Поделиться Twitch ID</button>}
      {gate.status === 'blocked' && <button type="button" onClick={() => { void identity.retry(); }}>Повторить проверку</button>}
      {!gate.canShare && <p className="panel-muted">Откройте расширение на странице Twitch и проверьте вход в аккаунт.</p>}
    </section>}
    <div hidden={gate.status !== 'ready' || !state.canAct}>
      {Equipment && <nav className="panel-tabs" aria-label="Раздел героя"><button type="button" aria-pressed={tab === 'development'} onClick={() => setTab('development')}>Развитие</button><button type="button" aria-pressed={tab === 'equipment'} onClick={() => setTab('equipment')}>Снаряжение</button></nav>}
      <div hidden={tab !== 'development'}><HeroDevelopmentView controller={controller} /></div>
      {Equipment && <div hidden={tab !== 'equipment'}><Equipment controller={controller} /></div>}
    </div>
  </main>;
}
