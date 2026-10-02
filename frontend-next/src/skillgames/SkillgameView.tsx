import { useEffect, useRef, useState } from 'react';
import { isRecord } from '../contracts';
import { knownGame, terminal, type Command, type Endpoint, type GameCatalog, type Session } from './contracts';
import type { SkillgameViewState } from './controller';
type Submit = (endpoint: Endpoint, command: Command) => void;
interface Props { state: SkillgameViewState; onSubmit: Submit; onRefresh: () => void; onRetry: () => void; demo?: boolean; localIntegration?: boolean }
const coordinate = (cell: number, cols: number) => `${String.fromCharCode(65 + cell % cols)}${Math.floor(cell / cols) + 1}`;
const cells = (value: unknown): number[] => Array.isArray(value) ? value.filter((n): n is number => typeof n === 'number') : [];
const ships = (value: unknown): number[][] => Array.isArray(value) ? value.map(cells) : [];
const shots = (value: unknown) => new Map<number, string>((Array.isArray(value) ? value : []).filter(isRecord).filter(v => typeof v.cell === 'number' && typeof v.result === 'string').map(v => [v.cell as number, v.result as string]));
const modeName = (mode: string) => mode === 'ranked' ? 'Рейтинг' : mode === 'practice' ? 'Тренировка' : mode;
const timerName: Record<string, string> = { attempt_seconds: 'Партия', first_move_wait_seconds: 'До первого хода', setup_seconds: 'Расстановка', turn_seconds: 'Ход', total_seconds: 'Весь матч', grace_seconds: 'Запас при обрыве', queue_seconds: 'Поиск соперника' };
function Board({ rows, cols, label, renderCell }: { rows: number; cols: number; label: string; renderCell: (cell: number) => React.ReactNode }) {
  return <table className="sg-board" aria-label={label}><tbody>{Array.from({ length: rows }, (_, row) => <tr key={row}>{Array.from({ length: cols }, (_, col) => <td key={col}>{renderCell(row * cols + col)}</td>)}</tr>)}</tbody></table>;
}
function Mines({ session, disabled, act }: { session: Session; disabled: boolean; act: (command: Command) => void }) {
  const [mode, setMode] = useState<'open' | 'flag'>('open');
  const state = session.state; const opened = isRecord(state.opened) ? state.opened : {}; const flags = cells(state.flags);
  return <section aria-label="Сапёр"><div className="sg-segment" aria-label="Режим нажатия"><button aria-pressed={mode === 'open'} onClick={() => setMode('open')}>Открыть</button><button aria-pressed={mode === 'flag'} onClick={() => setMode('flag')}>Флаг</button></div>
    <p className="sg-hint">{mode === 'open' ? 'Нажмите клетку, чтобы открыть' : 'Нажмите клетку, чтобы поставить или снять флаг'}</p>
    <Board rows={state.rows} cols={state.cols} label="Поле сапёра" renderCell={cell => {
      const isOpen = Object.hasOwn(opened, String(cell)); const flag = flags.includes(cell); const number = opened[String(cell)];
      const description = isOpen ? `открыто, ${number}` : flag ? 'флаг' : 'закрыто';
      return <button className={`sg-cell ${isOpen ? 'opened' : ''} ${flag ? 'flagged' : ''}`} data-number={isOpen ? number : undefined} aria-label={`${coordinate(cell, state.cols)} — ${description}`} disabled={disabled || terminal(session) || isOpen || (mode === 'open' && flag) || session.status === 'generating'} onClick={() => act({ action: mode === 'flag' ? flag ? 'unflag' : 'flag' : 'open', cell })}>{isOpen ? (number === 0 ? '·' : String(number)) : flag ? '⚑' : <span className="sg-cell-dot">·</span>}</button>;
    }} />
    <p className="sg-hint">Открыто: {Object.keys(opened).length} · Флагов: {flags.length}</p>
    {session.status === 'generating' && <p role="status">Сервер подбирает поле, решаемое без угадывания…</p>}
  </section>;
}
function Battleship({ session, disabled, act }: { session: Session; disabled: boolean; act: (command: Command) => void }) {
  const state = session.state; const fleet = cells(state.fleet_sizes); const own = ships(state.own_ships);
  const [draft, setDraft] = useState<number[][]>(own); const [selected, setSelected] = useState(0); const [vertical, setVertical] = useState(false);
  const [ownBoard, setOwnBoard] = useState(false); const [placementError, setPlacementError] = useState('');
  useEffect(() => { setDraft(ships(session.state.own_ships)); setPlacementError(''); }, [session.id, session.version]);
  const placement = state.phase === 'placement'; const locked = disabled || state.ready === true;
  const draftSaved = JSON.stringify(draft) === JSON.stringify(own); const complete = fleet.length > 0 && fleet.every((size, i) => draft[i]?.length === size);
  function place(cell: number) {
    const size = fleet[selected]; if (!size || locked) return;
    const row = Math.floor(cell / state.cols), col = cell % state.cols;
    if ((vertical ? row + size > state.rows : col + size > state.cols)) { setPlacementError('Корабль выходит за поле. Выберите другую клетку или поверните его.'); return; }
    const next = Array.from({ length: fleet.length }, (_, i) => draft[i] || []);
    next[selected] = Array.from({ length: size }, (_, i) => cell + i * (vertical ? state.cols : 1));
    setDraft(next); setPlacementError('');
  }
  const showOwn = placement || ownBoard; const shotMap = shots(showOwn ? state.incoming : state.shots); const visibleFleet = (placement ? draft : own).flat();
  return <section aria-label="Морской бой"><p className="sg-hint">Соперник: {String(state.opponent || 'ожидание')}</p>
    {placement ? <><h2>Расставьте флот</h2><p className="sg-hint">Выберите корабль, направление и его первую клетку. Правильность расстановки проверит сервер.</p>
      <div className="sg-ships">{fleet.map((size, index) => <button key={index} disabled={locked} aria-pressed={selected === index} aria-label={`Корабль ${index + 1}, ${size} клетки`} onClick={() => setSelected(index)}>{Array.from({ length: size }, () => '■').join('')} <span>{index + 1}</span></button>)}</div>
      <div className="sg-segment"><button disabled={locked} aria-pressed={!vertical} onClick={() => setVertical(false)}>Горизонтально</button><button disabled={locked} aria-pressed={vertical} onClick={() => setVertical(true)}>Вертикально</button></div>
      {placementError && <p className="error" role="alert">{placementError}</p>}
    </> : <><div className="sg-turn" role="status">{terminal(session) ? 'Матч завершён' : state.your_turn ? 'Ваш ход' : 'Ход соперника'}</div><div className="sg-segment"><button aria-pressed={!ownBoard} onClick={() => setOwnBoard(false)}>Поле соперника</button><button aria-pressed={ownBoard} onClick={() => setOwnBoard(true)}>Моё поле</button></div></>}
    <Board rows={state.rows} cols={state.cols} label={showOwn ? 'Моё поле' : 'Поле соперника'} renderCell={cell => {
      const shot = shotMap.get(cell); const ship = showOwn && visibleFleet.includes(cell); const description = shot === 'hit' ? 'попадание' : shot === 'miss' ? 'промах' : ship ? 'корабль' : 'неизвестно';
      return <button className={`sg-cell ${ship ? 'ship' : ''} ${shot === 'hit' ? 'hit' : shot === 'miss' ? 'miss' : ''}`} aria-label={`${coordinate(cell, state.cols)} — ${description}`} disabled={placement ? locked : disabled || terminal(session) || showOwn || !state.your_turn || !!shot} onClick={() => placement ? place(cell) : act({ action: 'fire', cell })}>{shot === 'hit' ? '×' : shot === 'miss' ? '•' : ship ? '■' : <span className="sg-cell-dot">·</span>}</button>;
    }} />
    {placement ? <><div className="sg-actions"><button disabled={locked} onClick={() => act({ action: 'autoplace' })}>Авторасстановка</button><button disabled={locked || !complete || draftSaved} onClick={() => act({ action: 'place', ships: draft })}>Сохранить расстановку</button></div>
      <button className="sg-primary" disabled={locked || !complete || !draftSaved} onClick={() => act({ action: 'ready' })}>{state.ready ? 'Вы готовы' : 'Готов к бою'}</button>
      <p className="sg-hint">Соперник {state.opponent_ready ? 'готов' : 'расставляет корабли'}</p></> : <p className="sg-hint">Потоплено кораблей соперника: {String(state.sunk_count ?? '—')}</p>}
  </section>;
}
function CatalogCard({ game, rating, disabled, onSubmit }: { game: GameCatalog; rating?: number; disabled: boolean; onSubmit: Submit }) {
  const [difficulty, setDifficulty] = useState(game.difficulties[0]?.id || '');
  useEffect(() => { if (!game.difficulties.some(d => d.id === difficulty)) setDifficulty(game.difficulties[0]?.id || ''); }, [game.difficulties, difficulty]);
  return <article className="sg-game-card"><div className="sg-card-title"><span className="sg-game-icon" aria-hidden="true">{game.game_type === 'battleship' ? '⚓' : game.game_type === 'minesweeper' ? '⚑' : '◇'}</span><div><h2>{game.name}</h2><span className="sg-hint">Рейтинг канала: {rating ?? '—'}</span></div></div>
    <ul className="sg-rules">{game.rules.map((rule, index) => <li key={index}>{rule}</li>)}</ul>
    <p className="sg-timers">{Object.entries(game.timers).map(([key, seconds]) => `${timerName[key] || key}: ${seconds} с`).join(' · ')}</p>
    <p className="sg-rewards">{game.rewards.enabled ? 'Сезонные награды включены: ' : ''}{game.rewards.reason}</p>
    {!knownGame(game.game_type) ? <p className="sg-hint">Нужна более новая версия панели</p> : <>
      {game.difficulties.length > 0 && <label className="sg-difficulty">Сложность<select value={difficulty} onChange={event => setDifficulty(event.target.value)} disabled={disabled}>{game.difficulties.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}</select></label>}
      <div className="sg-actions">{game.modes.filter(mode => mode === 'ranked' || mode === 'practice').map(mode => <button className={mode === 'ranked' ? 'sg-primary' : ''} disabled={disabled} key={mode} onClick={() => game.game_type === 'battleship' ? onSubmit('queue', {}) : onSubmit('start', { game_type: game.game_type, mode, difficulty })}>{game.game_type === 'battleship' ? 'Найти соперника' : modeName(mode)}</button>)}</div>
    </>}
  </article>;
}
function Confirmation({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; cancel.current?.focus(); return () => { previous?.focus(); }; }, []);
  return <div className="sg-dialog-backdrop"><section className="sg-dialog" role="dialog" aria-modal="true" aria-labelledby="quit-title" onKeyDown={event => { if (event.key === 'Escape') onCancel(); if (event.key === 'Tab') { event.preventDefault(); const target = event.currentTarget.querySelectorAll('button'); (document.activeElement === target[0] ? target[1] : target[0]).focus(); } }}><h2 id="quit-title">Завершить эту партию?</h2><p>Выход после начала рейтинговой игры засчитывается как поражение. Закрытие панели само по себе не завершает игру; серверный срок продолжает идти.</p><div className="sg-actions"><button ref={cancel} onClick={onCancel}>Остаться</button><button className="sg-danger" onClick={onConfirm}>Подтвердить выход</button></div></section></div>;
}
export function SkillgameView({ state, onSubmit, onRefresh, onRetry, demo, localIntegration }: Props) {
  const [confirmQuit, setConfirmQuit] = useState(false); const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const data = state.data; const session = data?.active_session; const config = session?.rules || data?.catalog.find(game => game.game_type === session?.game_type);
  useEffect(() => setConfirmQuit(false), [session?.id]);
  const serverNow = (data?.server_time ?? state.receivedAt / 1000) + (now - state.receivedAt) / 1000;
  const remaining = session?.expires_at != null ? Math.max(0, Math.ceil(session.expires_at - serverNow)) : null;
  const act = (command: Command) => { if (session && state.canAct) onSubmit('action', { session_id: session.id, version: session.version, ...command }); };
  return <main className="sg-layout"><header className="sg-brand"><span className="sg-brand-mark">S</span><div><strong>ShedLink</strong><span>Мини-игры</span></div><span className="sg-host-label">NEXT</span></header>
    {demo && <aside className="sg-demo"><strong>ДЕМОНСТРАЦИЯ · вымышленные данные</strong><p>Локальный пример в памяти. Нет настоящего соперника, сервера, рейтинга или наград.</p></aside>}
    {localIntegration && !demo && <aside className="sg-demo"><strong>ЛОКАЛЬНЫЙ API-СТЕНД</strong><p>Настоящий локальный сервер и временная база. Тестовые Twitch-личности; production не подключён.</p></aside>}
    <nav className="sg-nav" aria-label="Раздел"><span aria-current="page">Мини-игры</span><a href="./tournament.html">Макет турнира</a></nav>
    <div className="sg-page-heading"><div><p className="sg-eyebrow">ДУМАЙ · ИГРАЙ</p><h1>Твой следующий ход</h1></div><button aria-label="Обновить состояние" disabled={state.pending} onClick={onRefresh}>↻</button></div>
    <p className="sg-subtitle">Бесплатные игры. Результат и рейтинг определяет сервер канала.</p>
    {state.error && <p className="sg-error" role="alert">{state.error}</p>}
    {state.notice && <p className="sg-notice" role="status">{state.notice}</p>}
    {state.pending && <p role="status" className="sg-hint">Ждём ответ сервера…</p>}
    {state.uncertain && <button className="sg-primary" disabled={state.pending} onClick={onRetry}>Безопасно повторить тот же запрос</button>}
    {state.loading && !data && <p className="sg-hint" role="status">Загружаем правила и сохранённую партию…</p>}
    {data?.queue.status === 'queued' && <section className="sg-session"><h2>Ищем соперника</h2><p className="sg-hint">Можно закрыть панель и вернуться. Поиск и его срок хранит сервер.</p><button disabled={!state.canAct} onClick={() => onSubmit('cancel', {})}>Отменить поиск</button></section>}
    {session && <article className="sg-session"><header className="sg-session-heading"><div><p className="sg-eyebrow">{modeName(session.mode)}</p><h2>{config?.name || session.game_type}</h2></div><span className="sg-version">#{session.version}</span></header>
      {remaining !== null && !terminal(session) && <p className="sg-expiry">{remaining ? `Осталось по времени сервера: ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}` : 'Срок по часам панели истёк. Ожидаем решение сервера.'}</p>}
      {config && <p className="sg-rewards">{config.rewards.reason}</p>}
      {session.game_type === 'minesweeper' ? <Mines session={session} disabled={!state.canAct} act={act} /> : session.game_type === 'battleship' ? <Battleship session={session} disabled={!state.canAct} act={act} /> : <p>Неизвестная игра. Обновите панель.</p>}
      {terminal(session) ? <div className="sg-result" role="status"><h3>{session.result?.outcome || 'Партия завершена'}</h3><p>{session.result?.reason || session.status}</p>{session.result?.rating && <p>Рейтинг: {session.result.rating.before} → {session.result.rating.after} ({session.result.rating.delta > 0 ? '+' : ''}{session.result.rating.delta})</p>}<p className="sg-hint">Следующую игру можно выбрать ниже</p></div> : <button className="sg-quit" disabled={!state.canAct} onClick={() => setConfirmQuit(true)}>Завершить партию</button>}
    </article>}
    {data && <section className="sg-catalog" aria-label="Выбор игры">{data.catalog.map(game => <CatalogCard key={game.game_type} game={game} rating={data.ratings[game.game_type]} disabled={!state.canAct || (!!session && !terminal(session)) || data.queue.status === 'queued'} onSubmit={onSubmit} />)}</section>}
    <footer className="sg-footer">Закрытие панели не означает выход. Вернитесь до серверного срока, чтобы продолжить.</footer>
    {confirmQuit && session && <Confirmation onCancel={() => setConfirmQuit(false)} onConfirm={() => { setConfirmQuit(false); act({ action: 'quit' }); }} />}
  </main>;
}
