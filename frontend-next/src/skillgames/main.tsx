import { useEffect, useRef, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import { TwitchAuthStore } from '../auth';
import { IdentityBootstrap, type IdentityHelper } from './identity';
import { IdentityGate } from './IdentityGate';
import { configuredApiOrigin } from './origin';
import { SkillgameController } from './controller';
import { HttpSkillgameTransport } from './transport';
import { DemoSkillgameTransport } from './demo';
import { SkillgameView } from './SkillgameView';
import { SkillgameUsage } from './usage';
import './style.css';
declare global { interface Window { Twitch?: { ext?: IdentityHelper } } }
const params = new URLSearchParams(window.location.search);
const demo = params.get('demo');
const isDemo = ['catalog', 'battleship', 'minesweeper'].includes(demo || '');
const auth = new TwitchAuthStore();
const helper = window.Twitch?.ext;
if (isDemo) auth.authorize({ token: 'local-fixture-never-sent', channelId: 'fixture', userId: 'fixture' });
const identity = new IdentityBootstrap(auth, configuredApiOrigin);
if (!isDemo && helper) identity.attach(helper);
// A validated build-time origin configures every EBS call and CSP together.
// Empty means same-origin local routing. No query host, production default or legacy dispatcher.
const transport = isDemo ? new DemoSkillgameTransport(demo!) : new HttpSkillgameTransport(configuredApiOrigin, auth);
const controller = new SkillgameController(transport, auth);
const usage = isDemo ? null : new SkillgameUsage(auth, window.location.pathname.endsWith('/mobile.html') ? 'mobile' : 'desktop', fetch, () => Date.now(), configuredApiOrigin);
function App() {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const identityState = useSyncExternalStore(identity.subscribe, identity.snapshot);
  const identityReady = isDemo || identityState.status === 'ready';
  const opened = useRef(new Set<string>());
  const owner = useRef('');
  useEffect(() => {
    const scope = JSON.stringify([auth.current()?.channelId, auth.current()?.userId]);
    if (owner.current !== scope) { owner.current = scope; opened.current.clear(); }
    if (!state.data) return;
    if (!opened.current.has('panel')) { opened.current.add('panel'); usage?.record('panel_view', 'core:panel'); }
    const game = state.data.active_session?.game_type;
    if (game && !opened.current.has(game)) { opened.current.add(game); usage?.record('section_open', `core:game.${game}`); }
  }, [state.data]);
  useEffect(() => {
    if (!identityReady) return;
    const timer = setInterval(() => { if (identity.snapshot().status === 'ready') void usage?.flush(); }, 15000);
    return () => clearInterval(timer);
  }, [identityReady]);
  useEffect(() => { if (identityReady) controller.start(); else controller.stop(); return () => controller.stop(); }, [identityReady]);
  useEffect(() => {
    if (!identityReady) return;
    const interval = state.data?.poll_interval_ms;
    // A bounded display polling fallback is not a game deadline or cooldown.
    const timer = setInterval(() => { if (!document.hidden) void controller.refresh(); }, typeof interval === 'number' && interval >= 250 ? interval : 5000);
    const visible = () => { if (!document.hidden) void controller.refresh(); };
    document.addEventListener('visibilitychange', visible);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
  }, [state.data?.poll_interval_ms, identityReady]);
  const currentOwner = controller.hasCurrentIdentity();
  const viewState = currentOwner ? { ...state, canAct: identityReady && state.canAct } : { ...state, data: null, canAct: false };
  return <>{!identityReady && <IdentityGate state={identityState} onRetry={() => { void identity.retry(); }} onShare={() => identity.requestShare()} localIntegration={helper?.environment === 'local-integration'} />}
    <div hidden={!identityReady || !currentOwner}><SkillgameView key={JSON.stringify([auth.current()?.channelId, auth.current()?.userId])} state={viewState} demo={isDemo} localIntegration={helper?.environment === 'local-integration'} onSubmit={(endpoint, command) => {
    if (!isDemo && identity.snapshot().status !== 'ready') return;
    const game = endpoint === 'queue' ? 'battleship' : endpoint === 'start' ? command.game_type : state.data?.active_session?.game_type;
    const action = endpoint === 'action' ? command.action : endpoint;
    if (typeof game === 'string' && typeof action === 'string') usage?.record('action_attempt', `core:${game}.${action}`);
    void controller.submit(endpoint, command);
  }} onRefresh={() => { void controller.refresh(); }} onRetry={() => { if (identityReady) void controller.retry(); }} /></div></>;
}
const root = document.getElementById('skillgame-root');
if (!root) throw new Error('Skillgame root is missing');
createRoot(root).render(<App />);
