import { lazy, Suspense, useEffect, useState, useSyncExternalStore } from 'react';
import type { TwitchAuthStore } from '../auth';
import type { IdentityBootstrap } from '../skillgames/identity';
import type { PanelController } from '../panel/controller';
import type { ViewerRuntime } from './runtime';
import type { RimworldController } from '../rimworld/controller';
import type {ColonyController} from '../colony/controller';
const Rimworld = lazy(() => import('../rimworld/RimworldView').then(m => ({ default: m.RimworldView })));
const Bannerlord = lazy(() => import('./bannerlord-entry'));
const Colony = lazy(() => import('../colony/ColonyView').then(m => ({ default: m.ColonyView })));
const Community = lazy(() => import('./CommonView').then(m => ({ default: m.CommonView })));
const Statistics = lazy(() => import('./StatisticsView').then(m => ({ default: m.StatisticsView })));
export function ViewerShell({ auth, identity, controller, runtime, rimworld,colony }: { auth: TwitchAuthStore; identity: IdentityBootstrap; controller: PanelController; runtime: ViewerRuntime; rimworld?: RimworldController;colony?:ColonyController }) {
  const gate = useSyncExternalStore(identity.subscribe, identity.snapshot), state = useSyncExternalStore(runtime.subscribe, runtime.snapshot);
  const [tab, setTab] = useState<'integration' | 'bot' | 'stats'>('bot');
  const { stats, client, perks } = state;
  useEffect(() => { controller.syncHostBalance(); }, [controller, stats]);
  useEffect(() => { const root=document.documentElement, previous=root.style.background; if(!state.panelVisible) root.style.background='transparent'; return () => {root.style.background=previous;}; }, [state.panelVisible]);
  const changeTab = (next: typeof tab) => { runtime.selectTab(next); setTab(next); };
  const module = stats?.active_module, role = perks?.role === 'broadcaster' ? '👑 Стример' : perks?.role === 'moderator' ? '🛡 Модер' : perks ? 'Зритель' : '';
  return <main className="panel-layout"><button className="panel-collapse" type="button" aria-expanded={state.panelVisible} onClick={() => runtime.setPanelVisible(!state.panelVisible)}>{state.panelVisible ? 'Свернуть панель' : 'Развернуть панель'}</button><div hidden={!state.panelVisible}><header className="panel-brand"><span className="panel-brand-mark">S</span><div><strong>ShedLink · {gate.login || 'Панель зрителя'}</strong><span>{typeof stats?.points === 'number' ? `${stats.points.toLocaleString('ru-RU')} 💎 · +${stats.income_per_min ?? '—'} в минуту` : 'Проверяем профиль…'}</span><small>{role} {perks?.twitch_sub_tier ? `· Twitch ${perks.twitch_sub_tier}` : ''} {perks?.boosty_tier ? `· Boosty ${perks.boosty_tier}` : ''}</small></div></header>
    {gate.status !== 'ready' ? <section className="panel-card"><p role="status">{gate.message}</p>{gate.canShare && <button type="button" disabled={gate.shareRequested} onClick={() => identity.requestShare()}>Поделиться Twitch ID</button>}{gate.status === 'blocked' && <button type="button" onClick={() => { void identity.retry(); }}>Повторить проверку</button>}</section> : <>
      <nav className="panel-tabs" aria-label="Панель зрителя"><button type="button" aria-pressed={tab === 'bot'} onClick={() => changeTab('bot')}>Сообщество</button><button type="button" aria-pressed={tab === 'integration'} onClick={() => changeTab('integration')}>Игра</button><button type="button" aria-pressed={tab === 'stats'} onClick={() => changeTab('stats')}>Статистика</button></nav>
      {state.error && <p role="alert">{state.error}</p>}{state.notices.map(notice => <div className="panel-notice" role="status" key={notice.id}>{notice.text} <button type="button" aria-label="Закрыть уведомление" onClick={() => runtime.dismissNotice(notice.id)}>×</button></div>)}
      <Suspense fallback={<p role="status">Загрузка раздела…</p>}>
        <div hidden={tab !== 'integration'}>{module === 'bannerlord' ? <Bannerlord controller={controller} identity={identity} /> : module === 'shedcolony' && client ? <Colony key={client.identity.channelId + ':' + gate.login} client={client} controller={colony} /> : module === 'rimworld' && rimworld ? <Rimworld controller={rimworld} /> : <p>{stats ? 'На канале не выбрана игровая интеграция.' : 'Определяем игру канала…'}</p>}</div>
        {tab === 'bot' && client && <Community auth={auth} identity={identity} viewerClient={client} runtime={runtime} openGame={() => changeTab('integration')} />}
        {tab === 'stats' && <Statistics runtime={runtime} />}
      </Suspense>
    </>}
  </div></main>;
}
