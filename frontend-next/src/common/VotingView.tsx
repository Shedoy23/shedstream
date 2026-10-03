import { useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ViewerRuntime } from './runtime';
import { ConfirmDialog } from './ConfirmDialog';
import './common.css';
interface Option { id: number; label: string; description?: string; pool: number }
interface Vote { event_id: number; template_name?: string; ends_at: string; total_pool: number; allow_proposals?: boolean; options: Option[] }
interface Status { success?: boolean; message?: string; active_event?: Vote | null; pool_units?: number; threshold?: number; pool_pct?: number; has_default_template?: boolean; top_bidders?: { username: string; total: number }[] }
interface Selection { kind: 'bid' | 'propose'; event: number; option?: Option }
export function VotingView({ runtime }: { runtime: ViewerRuntime }) {
  const { client, config } = useSyncExternalStore(runtime.subscribe, runtime.snapshot);
  const [data, setData] = useState<Status | null>(null), [winner, setWinner] = useState<Option | null | undefined>(undefined), [remaining, setRemaining] = useState(0), [message, setMessage] = useState('');
  const [selection, setSelection] = useState<Selection | null>(null), [amount, setAmount] = useState(''), [label, setLabel] = useState(''), [busy, setBusy] = useState(false);
  const live = useRef(false), locked = useRef(false), lockTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined), snapshot = useRef<Status | null>(null), selected = useRef(selection); selected.current = selection;
  const refreshRef = useRef<() => Promise<void>>(async () => {}), dismissRef = useRef<() => void>(() => {});
  useLayoutEffect(() => {
    live.current = true; let resultActive = false, revision = 0, expiry = ''; let poll: ReturnType<typeof setInterval> | undefined, ticker: ReturnType<typeof setInterval> | undefined; const unsubs: (() => void)[] = [];
    const current = () => live.current && runtime.snapshot().client === client;
    const stopTicker = () => { clearInterval(ticker); ticker = undefined; };
    const refresh = async () => {
      if (!client || !current()) return; const seq = ++revision;
      try {
        const next = await client.read<Status>('/api/voting/status'); if (!current() || seq !== revision) return;
        if (!next.success) throw new Error(next.message || 'Голосование недоступно');
        snapshot.current = next;
        const chosen = selected.current, event = next.active_event;
        if (chosen && (!event || chosen.event !== event.event_id || (chosen.kind === 'bid' && !event.options.some(option => option.id === chosen.option?.id && option.label === chosen.option.label)) || (chosen.kind === 'propose' && !event.allow_proposals))) { setSelection(null); setMessage('Раунд или выбранный вариант изменился. Выбери заново.'); }
        if (event) {
          resultActive = false; setWinner(undefined); setData(next); stopTicker();
          const tick = () => { const left = Math.max(0, Date.parse(event.ends_at) - Date.now()); setRemaining(left); if (!left) { stopTicker(); const key = event.event_id + ':' + event.ends_at; if (expiry !== key) { expiry = key; void refresh(); } } };
          tick(); if (Date.parse(event.ends_at) > Date.now()) ticker = setInterval(tick, 1000);
        } else { stopTicker(); if (!resultActive) { setWinner(undefined); setData(next); } }
      } catch (error) { if (current()) { snapshot.current = null; setMessage(error instanceof Error ? error.message : 'Сеть недоступна'); } }
    };
    refreshRef.current = refresh; dismissRef.current = () => { resultActive = false; setWinner(undefined); void refresh(); };
    void refresh().then(() => { if (!current()) return; poll = setInterval(() => { void refresh(); }, 30000);
      unsubs.push(runtime.realtime.subscribe('vote_started', () => { resultActive = false; void refresh(); }), runtime.realtime.subscribe('vote_tick', () => { void refresh(); }), runtime.realtime.subscribe('vote_ended', value => { if (!current()) return; const result = value as { event_id?: number; winner?: Option } | null; if (typeof result?.event_id === 'number' && snapshot.current?.active_event && result.event_id !== snapshot.current.active_event.event_id) return; resultActive = true; stopTicker(); setSelection(null); setWinner(result?.winner && typeof result.winner.label === 'string' && typeof result.winner.pool === 'number' ? result.winner : null); }));
    });
    return () => { live.current = false; revision++; stopTicker(); clearInterval(poll); clearTimeout(lockTimer.current); locked.current = false; unsubs.forEach(fn => fn()); refreshRef.current = async () => {}; };
  }, [client, runtime]);
  const event = data?.active_event;
  const min = selection?.kind === 'bid' ? config?.voting_min_bid : config?.voting_min_pledge;
  const presets = selection?.kind === 'bid' ? config?.voting_bid_presets : config?.voting_pledge_presets;
  const open = (value: Selection) => { setSelection(value); setAmount(''); setLabel(''); setMessage(''); };
  async function submit() {
    if (!client || !selection || locked.current || !live.current || runtime.snapshot().client !== client) return;
    const currentEvent = snapshot.current?.active_event, amountValue = parseInt(amount, 10);
    if (!currentEvent || currentEvent.event_id !== selection.event || Date.parse(currentEvent.ends_at) <= Date.now() || (selection.kind === 'bid' && !currentEvent.options.some(option => option.id === selection.option?.id && option.label === selection.option.label)) || (selection.kind === 'propose' && !currentEvent.allow_proposals)) { setSelection(null); setMessage('Раунд изменился. Выбери заново.'); return; }
    if (typeof min !== 'number' || !Number.isFinite(amountValue) || amountValue < min || (selection.kind === 'propose' && !label.trim())) { setMessage(typeof min === 'number' ? `Укажи текст и сумму не меньше ${min} 💎.` : 'Минимальная сумма ещё не получена от сервера.'); return; }
    locked.current = true; setBusy(true); const kind = selection.kind;
    try {
      const result = await client.post<{ success?: boolean; message?: string }>('/api/voting/' + kind, kind === 'bid' ? { option_id: selection.option!.id, amount: amountValue } : { label: label.trim(), pledge: amountValue });
      if (!live.current || runtime.snapshot().client !== client) return;
      setSelection(null); setMessage((result.success ? kind === 'bid' ? 'Заявка принята. Итог голосования станет известен позже. ' : 'Заявка принята. Ждём одобрения стримера; вклад спишется только после одобрения. ' : '') + (result.message || (result.success ? '' : 'Сервер отказал в действии')));
      if (result.success && kind === 'bid') { void client.refreshUser().catch(error => { if (live.current) setMessage(error.message); }); await refreshRef.current(); }
    } catch (error) { if (live.current) setMessage(error instanceof Error ? error.message : 'Сеть недоступна. Результат неизвестен.'); }
    finally { lockTimer.current = setTimeout(() => { locked.current = false; if (live.current) setBusy(false); }, 500); }
  }
  const seconds = Math.floor(remaining / 1000);
  return <section className="panel-card"><h2>Голосование за следующую игру</h2>{message && <p role="status">{message}</p>}
    {winner !== undefined ? <div><h3>{winner ? winner.label : 'Раунд завершён — голосов нет'}</h3>{winner && <p>{winner.pool} 💎 вложено</p>}<button type="button" onClick={() => dismissRef.current()}>К копилке</button></div> : event ? <><h3>{event.template_name || 'Голосование'}</h3><p>Осталось: {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')} · Всего {event.total_pool} 💎</p>
      {[...event.options].sort((a, b) => b.pool - a.pool).map(option => <article className="panel-card" key={option.id}><h4>{option.label}</h4><p>{option.description}</p><progress value={option.pool} max={event.total_pool || 1} /><p>{option.pool} 💎</p><button type="button" disabled={busy || remaining <= 0} onClick={() => open({ kind: 'bid', event: event.event_id, option })}>Голосовать за {option.label}</button></article>)}
      {event.allow_proposals && <button type="button" disabled={busy || remaining <= 0} onClick={() => open({ kind: 'propose', event: event.event_id })}>Предложить свою игру</button>}
      {!!data?.top_bidders?.length && <details><summary>Участники голосования</summary>{data.top_bidders.map(person => <p key={person.username}>@{person.username} · {person.total} 💎</p>)}</details>}
    </> : data ? <div><p>Активного голосования сейчас нет. Копилка наполняется за активность на стриме.</p><p>{data.pool_units ?? '—'} / {data.threshold ?? '—'}</p>{typeof data.threshold === 'number' && <progress value={data.pool_units || 0} max={data.threshold || 1} />}<p>{data.pool_pct ?? '—'}% до запуска</p>{!data.has_default_template && <p>Стример ещё не настроил шаблон голосования.</p>}</div> : <p>Загрузка…</p>}
    {selection && <ConfirmDialog title={selection.kind === 'bid' ? `Голосовать за ${selection.option?.label}` : 'Предложить игру'} confirm={() => { void submit(); }} cancel={() => setSelection(null)}>
      {selection.kind === 'propose' && <label>Название игры<input value={label} onInput={e => setLabel(e.currentTarget.value)} /></label>}
      <label>{selection.kind === 'bid' ? 'Сумма голоса' : 'Вклад после одобрения'}<input type="number" value={amount} min={typeof min === 'number' ? min : undefined} onInput={e => setAmount(e.currentTarget.value)} /></label>
      <div className="panel-choices">{Array.isArray(presets) && presets.filter((value): value is number => typeof value === 'number' && Number.isFinite(value)).map(value => <button type="button" key={value} onClick={() => setAmount(String(value))}>{value} 💎</button>)}</div>
      <p>{selection.kind === 'bid' ? 'Вклад будет списан с твоего баланса. Исход голосования станет известен позже.' : 'Вклад спишется только если стример одобрит игру. Крустики виртуальны, возврата нет.'}</p>
    </ConfirmDialog>}
  </section>;
}

