import { useSyncExternalStore } from 'react';
import type { ViewerRuntime } from './runtime';
export function StatisticsView({ runtime }: { runtime: ViewerRuntime }) {
  const { statistics: data } = useSyncExternalStore(runtime.subscribe, runtime.snapshot);
  return <section className="panel-card"><h1>Статистика зрителя</h1><button type="button" onClick={() => { void runtime.loadStatistics(); }}>Обновить статистику</button>
    {!data ? <p role="status">Загрузка статистики…</p> : <><dl className="panel-grid">{[
      ['Просмотр сегодня', Math.round((data.stats.watch_time_today || 0) / 60) + ' мин'], ['Просмотр всего', Math.round((data.stats.watch_time_total || 0) / 60) + ' мин'],
      ['Сообщений сегодня', data.stats.chat_messages_today || 0], ['Сообщений всего', data.stats.chat_messages_total || 0], ['Символов сегодня', data.stats.chat_length_today || 0], ['Стримов подряд', data.streak.current_streak ?? '—'], ['Рекорд серии', data.streak.max_streak ?? '—'],
    ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><h2>Достижения</h2>{data.achievements.length ? data.achievements.map((item, index) => <article className="panel-card" key={item.key || index}><h3>{item.emoji} {item.name} {item.unlocked ? '✓' : '🔒'}</h3><p>{item.description}</p>{typeof item.reward === 'number' && <p>Награда: {item.reward} 💎</p>}</article>) : <p>Пока нет достижений.</p>}</>}
  </section>;
}
