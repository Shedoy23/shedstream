import { useEffect, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import { TwitchAuthStore, type TwitchHelper } from '../auth';
import { SkillgameController } from './controller';
import { HttpSkillgameTransport } from './transport';
import { DemoSkillgameTransport } from './demo';
import { SkillgameView } from './SkillgameView';
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
function App() {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  useEffect(() => { controller.start(); return () => controller.stop(); }, []);
  useEffect(() => {
    const interval = state.data?.poll_interval_ms;
    // A bounded display polling fallback is not a game deadline or cooldown.
    const timer = setInterval(() => { if (!document.hidden) void controller.refresh(); }, typeof interval === 'number' && interval >= 250 ? interval : 5000);
    const visible = () => { if (!document.hidden) void controller.refresh(); };
    document.addEventListener('visibilitychange', visible);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
  }, [state.data?.poll_interval_ms]);
  return <SkillgameView state={state} demo={isDemo} localIntegration={helper?.environment === 'local-integration'} onSubmit={(endpoint, command) => { void controller.submit(endpoint, command); }} onRefresh={() => { void controller.refresh(); }} onRetry={() => { void controller.retry(); }} />;
}
const root = document.getElementById('skillgame-root');
if (!root) throw new Error('Skillgame root is missing');
createRoot(root).render(<App />);
