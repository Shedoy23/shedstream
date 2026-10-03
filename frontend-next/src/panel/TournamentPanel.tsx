import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { PanelController } from './controller';
import { validPrice } from './contracts';
import { tournamentAllowed, tournamentContext } from './tournament';
import './tournament.css';
export default function TournamentPanel({ controller }: { controller: PanelController }) {
  const s = useSyncExternalStore(controller.subscribe, controller.snapshot), t = s.tournament;
  const [choice, setChoice] = useState<{ target: string; context: string; generation: number } | null>(null);
  const cancel = useRef<HTMLButtonElement>(null), dialog = useRef<HTMLDivElement>(null);
  useEffect(() => { if (choice) cancel.current?.focus(); }, [choice]);
  useEffect(() => { if (choice && (choice.generation !== s.generation || !tournamentAllowed(s, 'tournament.predict', choice.target, choice.context))) setChoice(null); }, [s, choice]);
  const predict = (target: string) => setChoice({ target, context: tournamentContext(t), generation: s.generation });
  const amount = (v: number) => v.toLocaleString('ru-RU');
  return <div aria-label="Турнир зрителей">
    <h2>Турнир зрителей <span id="bannerlord-tournament-status">{t?.state.status === 'running' ? `Раунд ${(t.state.current_round || 0) + 1}` : t ? `Очередь (${t.queue.length})` : ''}</span></h2>
    <div id="bannerlord-tournament-body">{!t ? <p role="status">{s.errors.tournament || 'Загружаем турнир…'}</p> : t.state.status === 'running' ? <>
      {t.my_prediction ? <p>Твой прогноз: <strong>{t.my_prediction.target}</strong></p> : <><p>Выбери победителя. Прогноз бесплатный, результат появится после турнира.</p><div className="panel-choices">{t.state.participants?.map(target => <button type="button" key={target} className="bnr-predict-btn" data-target={target} disabled={!tournamentAllowed(s, 'tournament.predict', target, tournamentContext(t))} onClick={() => predict(target)}>Прогноз: {target}</button>)}</div></>}
    </> : <>
      <p>Турнир начнётся, когда его запустит стример.{validPrice(s.config?.tournament_prize_gold) && ` Награда победителю: ${amount(s.config.tournament_prize_gold)} динаров.`}{validPrice(s.config?.tournament_round_gold) && ` За победу в раунде: ${amount(s.config.tournament_round_gold)} динаров.`}</p>
      {t.queue.length ? <ol>{t.queue.map((q, i) => <li key={q.username + ':' + i}>{q.username}{q.class_key ? ` · ${q.class_key}` : ''}</li>)}</ol> : <p>Очередь пуста</p>}
      {t.in_queue ? <p>Ты в очереди, ждём запуска турнира.</p> : <button id="bnr-join-tournament-btn" type="button" disabled={!tournamentAllowed(s, 'hero.join_tournament')} onClick={() => { void controller.tournamentAction('hero.join_tournament'); }}>Вступить в турнир{t.config?.join_price === 0 ? ' (бесплатно)' : ' — условия недоступны'}</button>}
    </>}{t?.state.last_winner && <p>Прошлый победитель: <strong>{t.state.last_winner}</strong></p>}</div>
    {choice && <div className="panel-modal-backdrop"><div ref={dialog} className="panel-card" role="dialog" aria-modal="true" aria-labelledby="tournament-confirm-title" onKeyDown={e => {
      if (e.key === 'Escape') { e.preventDefault(); setChoice(null); }
      if (e.key === 'Tab') { const buttons = dialog.current?.querySelectorAll('button'); if (!buttons?.length) return; const first = buttons[0], last = buttons[buttons.length - 1]; if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); } }
    }}><h3 id="tournament-confirm-title">Прогноз: победит {choice.target}?</h3><p>Крустики не списываются. Исход станет известен позже.</p><button id="bnr-predict-confirm" type="button" onClick={() => { const shown = choice; setChoice(null); void controller.tournamentAction('tournament.predict', shown.target, shown.context); }}>Сделать прогноз</button><button ref={cancel} id="bnr-predict-cancel" type="button" onClick={() => setChoice(null)}>Отмена</button></div></div>}
  </div>;
}
