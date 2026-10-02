import { useEffect, useRef, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import { TwitchAuthStore, type TwitchHelper } from '../auth';
import { SkillgameController } from './controller';
import { HttpSkillgameTransport } from './transport';
import { DemoSkillgameTransport } from './demo';
import { SkillgameView } from './SkillgameView';
import { SkillgameUsage } from './usage';
import './style.css';
declare global { interface Window { Twitch?: { ext?: TwitchHelper & { environment?: string } } } }
const params = new URLSearchParams(window.location.search);
const demo = params.get('demo');
const isDemo = ['catalog', 'battleship', 'minesweeper'].includes(demo || '');
const auth = new TwitchAuthStore();
const helper = window.Twitch?.ext;
if (isDemo) auth.authorize({ token: 'local-fixture-never-sent', channelId: 'fixture', userId: 'fixture' });
else if (helper) auth.attach(helper);
// The release host supplies same-origin /api via its controlled routing. There is
// no query-string API destination, JWT input, production default, or legacy dispatcher.
const transport = isDemo ? new DemoSkillgameTransport(demo!) : new HttpSkillgameTransport('', auth);
const controller = new SkillgameController(transport, auth);
const usage = isDemo ? null : new SkillgameUsage(auth, window.location.pathname.endsWith('/mobile.html') ? 'mobile' : 'desktop');
function App() {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
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
  useEffect(() => { const timer = setInterval(() => { void usage?.flush(); }, 15000); return () => clearInterval(timer); }, []);
  useEffect(() => { controller.start(); return () => controller.stop(); }, []);
  useEffect(() => {
    const interval = state.data?.poll_interval_ms;
    // A bounded display polling fallback is not a game deadline or cooldown.
    const timer = setInterval(() => { if (!document.hidden) void controller.refresh(); }, typeof interval === 'number' && interval >= 250 ? interval : 5000);
    const visible = () => { if (!document.hidden) void controller.refresh(); };
    document.addEventListener('visibilitychange', visible);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
  }, [state.data?.poll_interval_ms]);
  return <SkillgameView state={state} demo={isDemo} localIntegration={helper?.environment === 'local-integration'} onSubmit={(endpoint, command) => {
    const game = endpoint === 'queue' ? 'battleship' : endpoint === 'start' ? command.game_type : state.data?.active_session?.game_type;
    const action = endpoint === 'action' ? command.action : endpoint;
    if (typeof game === 'string' && typeof action === 'string') usage?.record('action_attempt', `core:${game}.${action}`);
    void controller.submit(endpoint, command);
  }} onRefresh={() => { void controller.refresh(); }} onRetry={() => { void controller.retry(); }} />;
}
const root = document.getElementById('skillgame-root');
if (!root) throw new Error('Skillgame root is missing');
createRoot(root).render(<App />);
