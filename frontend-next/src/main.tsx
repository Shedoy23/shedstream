import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import { TwitchAuthStore } from './auth';
import { TournamentController } from './controller';
import { TournamentView } from './TournamentView';
import { PreviewTransport, type Scenario } from './preview';
import './style.css';

function PreviewPanel({ scenario }: { scenario: Scenario }) {
  const controller = useMemo(() => {
    const auth = new TwitchAuthStore();
    // This synthetic identity is only consumed by PreviewTransport, never HTTP.
    auth.authorize({ token: 'local-fixture', channelId: 'fixture', userId: 'fixture' });
    return new TournamentController(new PreviewTransport(scenario), auth);
  }, [scenario]);
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  useEffect(() => {
    controller.start();
    const timer = setInterval(() => { if (!document.hidden) void controller.refresh(); }, 3000);
    return () => { clearInterval(timer); controller.stop(); };
  }, [controller]);
  return <TournamentView state={state} onAction={action => { void controller.submit(action); }} onRefresh={() => { void controller.refresh(); }} />;
}
function App() {
  const [scenario, setScenario] = useState<Scenario>('queue');
  return <main className="layout"><header className="brand"><span className="brand-icon">S</span><div><strong>ShedLink</strong><span>Frontend reliability pilot</span></div><span className="pilot-label">LOCAL PREVIEW</span></header>
    <aside className="preview-warning"><strong>Только локальный макет</strong><p>Вымышленные данные. Кнопки меняют пример в памяти; запросов к игровому серверу и списаний нет.</p></aside>
    <label className="scenario-picker">Проверить состояние <select value={scenario} onChange={event => setScenario(event.currentTarget.value as Scenario)}>
      <option value="queue">Очередь</option><option value="empty">Пустая очередь</option><option value="running">Турнир идёт</option><option value="joined">Уже в очереди</option><option value="predicted">Прогноз сделан</option><option value="refusal">Отказ сервера</option><option value="offline">Ошибка загрузки</option><option value="uncertain">Неизвестный исход заявки</option>
    </select></label>
    <PreviewPanel key={scenario} scenario={scenario} />
    <p className="scope-note">Пилот: очередь, участники и бесплатный прогноз. Не заменяет выпущенное Twitch-расширение.</p>
  </main>;
}
const root = document.getElementById('tournament-pilot-root');
if (!root) throw new Error('Pilot root is missing');
// No runtime switch to live EBS. Serving this artifact elsewhere cannot activate mutations.
createRoot(root).render(<App />);
