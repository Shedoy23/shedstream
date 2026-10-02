import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { TournamentAction } from './contracts';
import type { TournamentViewState } from './controller';
interface Props { state: TournamentViewState; onAction(action: TournamentAction): void; onRefresh(): void }
export function TournamentView({ state, onAction, onRefresh }: Props) {
  const [target, setTarget] = useState<string | null>(null);
  const data = state.data;
  const contextKey = JSON.stringify([data?.my_username, data?.state.status, data?.state.current_round, data?.state.started_at, data?.state.participants, data?.my_prediction]);
  useLayoutEffect(() => { setTarget(null); }, [contextKey, state.canAct]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setTarget(null); };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, []);
  const eligibleTarget = target && data?.state.status === 'running' && data.state.participants.includes(target) && !data.my_prediction && state.canAct;
  const confirmation = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    if (!eligibleTarget) return;
    const previous = document.activeElement as HTMLElement | null;
    confirmation.current?.focus();
    return () => { previous?.focus(); };
  }, [eligibleTarget]);
  return <section className="tournament-card" aria-labelledby="tournament-heading" aria-busy={state.loading}>
    <header className="card-heading"><div><p className="eyebrow">BANNERLORD</p><h1 id="tournament-heading">Турнир зрителей</h1></div><span className="status-chip">{data?.state.status === 'running' ? `Раунд ${data.state.current_round + 1}` : data?.state.status === 'idle' ? 'Очередь' : 'Ожидание'}</span></header>
    {state.error && <p className="error" role="alert">{state.error}{data && ' · Показан последний полученный снимок; действия недоступны.'}</p>}
    {state.loading && <p className="muted" role="status">Обновляем состояние…</p>}
    {!data && !state.loading && !state.error && <p className="muted">Состояние ещё не получено</p>}
    {data && <>
      {data.state.status === 'idle' ? <>
        <p className="muted">Очередь из игры. Турнир запускает стример.</p>
        <h2>В очереди <span className="count">{data.queue.length}</span></h2>
        {data.queue.length ? <ol className="players">{data.queue.map((entry, index) => <li key={`${entry.username}-${index}`} className={entry.username === data.my_username ? 'current-viewer' : ''}><span>{entry.username}</span>{entry.class_key && <span className="muted">{entry.class_key}</span>}</li>)}</ol> : <p className="empty">Очередь пока пуста</p>}
        {data.in_queue ? <p className="success">Вы в очереди. Ждём запуска турнира.</p> : data.config.join_price === 0 ? <button className="primary" disabled={!state.canAct} onClick={() => onAction({ action_type: 'hero.join_tournament', data: { price: 0 } })}>Вступить в турнир · бесплатно</button> : <p className="muted">Сервер сообщил цену {data.config.join_price}. В этом пилоте платный вход отключён.</p>}
      </> : data.state.status === 'running' ? <>
        <p className="muted">Турнир идёт. Состояние и результат приходят с сервера.</p>
        {data.my_prediction ? <p className="success">Ваш прогноз: <strong>{data.my_prediction.target}</strong></p> : <>
          <h2>Прогноз победителя</h2><p className="muted">Бесплатно. Крустики не списываются.</p>
          <ul className="players participants">{data.state.participants.map((participant, index) => <li key={`${participant}-${index}`}><span>{participant}</span><button disabled={!state.canAct} onClick={() => setTarget(participant)}>Прогноз</button></li>)}</ul>
        </>}
      </> : <p role="status">Неизвестное состояние: {data.state.status}. Действия недоступны.</p>}
      {data.state.last_winner && <p className="last-winner">Прошлый победитель: <strong>{data.state.last_winner}</strong></p>}
    </>}
    {state.notice && <p className="notice" role="status">{state.notice}</p>}
    {state.pending && <p className="muted" role="status">Отправляем заявку. Не нажимайте повторно.</p>}
    <footer><button className="secondary" onClick={onRefresh} disabled={state.loading}>Обновить состояние</button></footer>
    {eligibleTarget && <div className="dialog-backdrop" onClick={event => { if (event.target === event.currentTarget) setTarget(null); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="prediction-title" className="dialog">
        <h2 id="prediction-title">Победит {target}?</h2><p>Бесплатный прогноз. Решение проверяет сервер.</p>
        <div className="dialog-actions"><button ref={confirmation} className="primary" onClick={() => { if (eligibleTarget) onAction({ action_type: 'tournament.predict', data: { target: target! } }); setTarget(null); }}>Подтвердить прогноз</button><button onClick={() => setTarget(null)}>Отмена</button></div>
      </section>
    </div>}
  </section>;
}
