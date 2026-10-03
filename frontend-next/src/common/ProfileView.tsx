import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ViewerRuntime } from './runtime';
import { ConfirmDialog } from './ConfirmDialog';
import './common.css';
type Quest = { name?: string; emoji?: string; current?: number; target?: number; reward?: number; completed?: boolean };
type FirstStep = { title?: string; text?: string; cta?: string; enabled?: boolean };
export function ProfileView({ runtime, openGame }: { runtime: ViewerRuntime; openGame: () => void }) {
  const state = useSyncExternalStore(runtime.subscribe, runtime.snapshot), { client, stats, config, level } = state;
  const [page, setPage] = useState<'profile' | 'quests' | 'promo' | 'tts' | 'bug'>('profile'), [text, setText] = useState(''), [message, setMessage] = useState(''), [busy, setBusy] = useState(false), [confirmation, setConfirmation] = useState<{ text: string; cost: number } | null>(null);
  const alive = useRef(true), lastPromo = useRef(-Infinity); useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, [client]);
  const quests = Array.isArray(stats?.quests) ? stats.quests as Quest[] : [], first = stats?.first_step as FirstStep | null;
  const quote = typeof config?.tts_cost === 'number' && Number.isFinite(config.tts_cost) && config.tts_cost >= 0 ? config.tts_cost : null;
  const limit = typeof config?.tts_max_len === 'number' && config.tts_max_len > 0 ? config.tts_max_len : null;
  const select = (next: typeof page) => { setPage(next); setText(''); setMessage(''); setConfirmation(null); };
  async function submit(kind: 'promo' | 'tts' | 'bug', shown?: { text: string; cost: number }) {
    if (!client || busy) return; const value = (shown?.text ?? text).trim(); if (!value) { setMessage('Введи текст'); return; }
    if (kind === 'tts' && (!shown || quote !== shown.cost || limit === null || value.length > limit)) { setConfirmation(null); setMessage('Условия изменились. Проверь сообщение и цену ещё раз.'); return; }
    if (kind === 'promo') { if (Date.now() - lastPromo.current < 3000) { setMessage('Подожди немного перед повтором.'); return; } lastPromo.current = Date.now(); }
    setConfirmation(null); setBusy(true); setMessage('');
    try {
      const result = await client.post<{ success?: boolean; message?: string }>(kind === 'promo' ? '/api/promo/use' : kind === 'tts' ? '/api/tts/submit' : '/api/bug-report', kind === 'promo' ? { code: value.toUpperCase() } : { message: value });
      if (!alive.current || runtime.snapshot().client !== client) return;
      setMessage((kind === 'tts' && result.success ? 'Заявка принята. Озвучка появится в очереди стримера. ' : '') + (result.message || (result.success ? 'Готово' : 'Сервер отказал в действии')));
      if (result.success && kind !== 'bug') await client.refreshUser();
      if (result.success && kind === 'tts') setPage('profile');
    } catch (error) { if (alive.current && runtime.snapshot().client === client) setMessage(error instanceof Error ? error.message : 'Сеть недоступна. Результат запроса неизвестен.'); }
    finally { if (alive.current && runtime.snapshot().client === client) setBusy(false); }
  }
  return <section className="panel-card"><h2>Профиль</h2>
    {level && <div><strong>Уровень {level.level ?? '—'} · {level.title}</strong>{typeof level.exp === 'number' && typeof level.exp_needed === 'number' && <><progress max={level.exp_needed || 1} value={level.exp} /><p>{level.exp} / {level.exp_needed} EXP{level.bonus_pct ? ` · +${level.bonus_pct}% доход` : ''}</p></>}</div>}
    {first?.title && <div className="panel-card"><h3>{first.title}</h3><p>{first.text}</p><button type="button" disabled={first.enabled === false} onClick={openGame}>{first.cta || 'Открыть'}</button></div>}
    <nav className="panel-tabs" aria-label="Профиль и награды">{([['quests', 'Квесты'], ['promo', 'Промокод'], ['tts', 'Озвучить сообщение'], ['bug', 'Сообщить о баге']] as const).map(([key, label]) => <button type="button" disabled={busy} aria-pressed={page === key} onClick={() => select(key)} key={key}>{label}</button>)}</nav>
    {message && <p role="status">{message}</p>}
    {page === 'quests' && <div><h3>Квесты · {quests.filter(q => q.completed).length}/{quests.length}</h3>{quests.length ? quests.map((quest, index) => <article className="panel-card" key={index}><strong>{quest.emoji} {quest.name}</strong><p>{quest.current ?? 0}/{quest.target ?? 0} {quest.completed ? '✓' : ''}</p><progress value={quest.current || 0} max={quest.target || 1} />{typeof quest.reward === 'number' && <p>Награда: +{quest.reward} 💎</p>}</article>) : <p>Нет активных квестов.</p>}</div>}
    {page === 'promo' && <div><label>Промокод<input value={text} onInput={e => setText(e.currentTarget.value)} /></label><button type="button" disabled={busy} onClick={() => { void submit('promo'); }}>Активировать</button></div>}
    {page === 'tts' && <div><p>Стример услышит сообщение через озвучку на оверлее.</p><label>Текст для озвучки<textarea value={text} maxLength={limit ?? undefined} onInput={e => setText(e.currentTarget.value)} /></label><p>{text.length} / {limit ?? '—'} символов</p>{quote === null || limit === null ? <p>Цена или лимит озвучки ещё не получены от сервера.</p> : <button type="button" disabled={busy || !text.trim() || typeof stats?.points !== 'number' || stats.points < quote} onClick={() => setConfirmation({ text: text.trim(), cost: quote })}>Озвучить за {quote} 💎</button>}</div>}
    {page === 'bug' && <div><p>Описание будет отправлено стримеру.</p><label>Что сломалось?<textarea value={text} onInput={e => setText(e.currentTarget.value)} /></label><button type="button" disabled={busy || !text.trim()} onClick={() => { void submit('bug'); }}>Отправить</button></div>}
    {page !== 'profile' && <button type="button" disabled={busy} onClick={() => select('profile')}>Закрыть</button>}
    {confirmation && <ConfirmDialog title="Подтвердить озвучку" confirm={() => { void submit('tts', confirmation); }} cancel={() => setConfirmation(null)}><p>{confirmation.text}</p><p>Стоимость: {confirmation.cost} 💎</p></ConfirmDialog>}
  </section>;
}
