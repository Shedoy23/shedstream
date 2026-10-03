import { useEffect, useRef, useState } from 'react';
import type { ViewerClient } from './client';
interface Case { id: number; tier: string; source: string; opened_at?: string | null }
interface CaseList { success: boolean; message?: string; cases?: Case[]; unopened_counts?: Record<string, number>; lifetime_count?: number }
interface Tier { tier: string; label: string; reward_points: number }
interface Reply { success: boolean; message?: string; reward_points?: number }
export function CasesView({ client }: { client: ViewerClient }) {
  const [data, setData] = useState<CaseList | null>(null), [tiers, setTiers] = useState<Tier[]>([]), [message, setMessage] = useState('Загрузка…'), [busy, setBusy] = useState(false);
  const alive = useRef(false), sequence = useRef(0), locked = useRef(false), timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const load = async () => {
    const seq = ++sequence.current;
    try {
      const next = await client.read<CaseList>('/api/viewer/cases');
      if (!alive.current || seq !== sequence.current) return;
      if (!next.success || !Array.isArray(next.cases)) { setMessage(next.message || 'Не удалось загрузить кейсы'); return; }
      setData(next); setMessage(current => current === 'Загрузка…' ? '' : current);
    } catch (error) { if (alive.current && seq === sequence.current) setMessage(error instanceof Error ? error.message : 'Ошибка загрузки'); }
  };
  useEffect(() => {
    alive.current = true;
    void (async () => {
      await load();
      if (!alive.current) return;
      try {
        const preview = await client.read<{ success: boolean; tiers?: Tier[] }>('/api/case/preview', false);
        if (alive.current && preview.success && Array.isArray(preview.tiers)) setTiers(preview.tiers);
      } catch { if (alive.current) setMessage('Превью наград временно недоступно'); }
    })();
    return () => { alive.current = false; sequence.current++; timers.current.forEach(clearTimeout); timers.current = []; };
  }, [client]);
  const later = (callback: () => Promise<unknown>, ms: number) => {
    timers.current.push(setTimeout(() => { if (alive.current) void callback().catch(error => { if (alive.current) setMessage(error instanceof Error ? error.message : 'Ошибка обновления'); }); }, ms));
  };
  const open = async (id?: number) => {
    if (locked.current || !data?.success || (id !== undefined && !data.cases?.some(c => c.id === id && !c.opened_at))) return;
    locked.current = true; setBusy(true);
    try {
      const reply = id === undefined ? await client.post<Reply>('/api/viewer/cases/open-all') : await client.post<Reply>('/api/viewer/case/open', { case_id: id });
      if (!alive.current) return;
      if (!reply.success) { setMessage(reply.message || 'Не удалось открыть кейс'); return; }
      setMessage(reply.message || `Открыт кейс: +${reply.reward_points} 💎`);
      later(() => client.refreshUser(), 400);
      if (id === undefined) await load(); else later(load, 700);
    } catch (error) { if (alive.current) setMessage(error instanceof Error ? error.message : 'Ошибка сети. Проверь список кейсов перед повтором.'); }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  };
  const total = data?.unopened_counts?.total ?? 0;
  return <section className="panel-card"><h1>Кейсы</h1><p>Бесплатные награды за активность. Содержимое каждого тира указано ниже.</p><p role="status">{message}</p>
    <p>{data ? `${total} закрытых` : 'Загружаем список'}</p>
    {total > 1 && <button type="button" disabled={busy} onClick={() => { void open(); }}>Открыть все ({total})</button>}
    <div className="panel-grid">{data?.cases?.map(c => <article className="panel-card" key={c.id}><h2>{tiers.find(t => t.tier === c.tier)?.label || c.tier}</h2><p>{c.source}</p><button type="button" aria-label={`Открыть кейс ${c.id}`} disabled={busy || !!c.opened_at} onClick={() => { void open(c.id); }}>Открыть</button></article>)}</div>
    {data?.cases?.length === 0 && <p>{data.lifetime_count ? 'Все кейсы открыты!' : 'Пока нет кейсов. Выполняй квесты и держи streak.'}</p>}
    <details open><summary>Что внутри каждого тира?</summary>{tiers.map(t => <p key={t.tier}>{t.label}: {t.reward_points.toLocaleString('ru-RU')} 💎</p>)}</details>
  </section>;
}
