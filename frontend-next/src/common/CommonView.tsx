import { lazy, Suspense, useMemo, useState, useSyncExternalStore } from 'react';
import type { TwitchAuthStore } from '../auth';
import type { IdentityBootstrap } from '../skillgames/identity';
import { configuredApiOrigin } from '../skillgames/origin';
import { ViewerClient } from './client';
import type { ViewerRuntime } from './runtime';
import { ProfileView } from './ProfileView';
const Cases = lazy(() => import('./CasesView').then(m => ({ default: m.CasesView })));
const Pets = lazy(() => import('./PetsView').then(m => ({ default: m.PetsView })));
const Guilds = lazy(() => import('./GuildsView').then(m => ({ default: m.GuildsView })));
const Voting = lazy(() => import('./VotingView').then(m => ({ default: m.VotingView })));
const Family = lazy(() => import('./SocialFamilyView').then(m => ({ default: m.SocialFamilyView })));
const Games = lazy(() => import('./CommunityGamesView').then(m => ({ default: m.CommunityGamesView })));
export function CommonView({ auth, identity, viewerClient, runtime, openGame = () => {} }: { auth: TwitchAuthStore; identity: IdentityBootstrap; viewerClient?: ViewerClient; runtime?: ViewerRuntime; openGame?: () => void }) {
  const gate = useSyncExternalStore(identity.subscribe, identity.snapshot), authorization = useSyncExternalStore(auth.subscribe, auth.current);
  // Request authority comes from the current identity; section effects own
  // timers. A memoized client's lifetime must not grant an old token authority.
  const client = useMemo(() => viewerClient || (gate.status === 'ready' && gate.login && authorization ? new ViewerClient({ ...authorization, login: gate.login }, configuredApiOrigin, fetch, () => identity.snapshot().status === 'ready' && identity.snapshot().login === gate.login && auth.current()?.channelId === authorization.channelId && auth.current()?.token === authorization.token) : null), [viewerClient, gate.status, gate.login, authorization]);
  const [page, setPage] = useState<'menu' | 'cases' | 'pets' | 'guilds' | 'voting' | 'rps' | 'tictactoe' | 'tug' | 'family'>('menu');
  if (!client) return <p role="status">Для действий нужна подтверждённая личность Twitch.</p>;
  return <section><nav className="panel-tabs" aria-label="Разделы сообщества"><button type="button" onClick={() => setPage('menu')}>Профиль</button><button type="button" onClick={() => setPage('cases')}>Кейсы</button><button type="button" onClick={() => setPage('pets')}>Питомцы</button>{runtime && <><button type="button" onClick={() => setPage('guilds')}>Гильдии</button><button type="button" onClick={() => setPage('voting')}>Голосование</button><button type="button" onClick={() => setPage('family')}>Семья</button><button type="button" onClick={() => setPage('rps')}>Дуэли</button><button type="button" onClick={() => setPage('tictactoe')}>Крестики-нолики</button><button type="button" onClick={() => setPage('tug')}>Канат</button></>}</nav><Suspense fallback={<p role="status">Загрузка раздела…</p>}>{runtime && page === 'family' ? <Family runtime={runtime} onClose={() => setPage('menu')} /> : runtime && (page === 'rps' || page === 'tictactoe' || page === 'tug') ? <Games key={page + ':' + authorization?.channelId + ':' + gate.login} runtime={runtime} game={page} onClose={() => setPage('menu')} /> : page === 'cases' ? <Cases key={authorization?.channelId + ':' + gate.login} client={client} /> : page === 'pets' ? <Pets key={authorization?.channelId + ':' + gate.login} client={client} /> : page === 'voting' && runtime ? <Voting runtime={runtime} /> : page === 'guilds' && runtime ? <Guilds runtime={runtime} /> : runtime ? <ProfileView runtime={runtime} openGame={openGame} /> : <p>Выбери раздел сообщества.</p>}</Suspense></section>;
}

