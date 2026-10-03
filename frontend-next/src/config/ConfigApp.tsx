import { useEffect, useRef, useState } from 'react';
import type { TwitchAuthorization, TwitchHelper } from '../auth';
export function ConfigApp({ helper, baseUrl = '', fetcher = fetch, search = '' }: { helper?: TwitchHelper; baseUrl?: string; fetcher?: typeof fetch; search?: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null), [status, setStatus] = useState('Загрузка…'), [busy, setBusy] = useState(false);
  const auth = useRef<TwitchAuthorization | null>(null), generation = useRef(0), locked = useRef(false);
  useEffect(() => {
    let active = true;
    const load = async (channel: number, owner: number) => {
      if (!Number.isSafeInteger(channel) || channel <= 0) { setStatus('Нет канала Twitch'); return; }
      try {
        const response = await fetcher(`${baseUrl}/api/overlay/pets?channel_id=${channel}`), data = await response.json();
        if (!active || owner !== generation.current) return;
        if (!response.ok || typeof data.enabled !== 'boolean') throw new Error(data.message || 'Не удалось загрузить статус');
        setEnabled(data.enabled); setStatus('');
      } catch (error) { if (active && owner === generation.current) setStatus(error instanceof Error ? error.message : 'Не удалось загрузить статус'); }
    };
    if (helper) helper.onAuthorized(next => {
      if (!active) return;
      auth.current = { ...next }; const owner = ++generation.current;
      locked.current = false; setBusy(false); setEnabled(null); setStatus('Загрузка…');
      void load(Number.parseInt(next.channelId, 10), owner);
    });
    else {
      const channel = Number.parseInt(new URLSearchParams(search).get('channel_id') || '0', 10);
      if (channel > 0) void load(channel, ++generation.current);
      else setStatus('Открой настройки расширения на Twitch');
    }
    return () => { active = false; generation.current++; auth.current = null; };
  }, [helper, baseUrl, fetcher, search]);
  const toggle = async () => {
    if (!auth.current?.token) { setStatus('Нет авторизации Twitch'); return; }
    if (locked.current || enabled === null) return;
    const owner = generation.current, token = auth.current.token;
    locked.current = true; setBusy(true);
    try {
      const response = await fetcher(`${baseUrl}/api/streamer/pets/overlay-toggle`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': token }, body: JSON.stringify({ enabled: !enabled }),
      });
      if (owner !== generation.current) return;
      if (response.status === 401 || response.status === 403) { setStatus('Открой настройки от имени бродкастера канала'); return; }
      const data = await response.json();
      if (owner !== generation.current) return;
      if (response.ok && data.success === true && typeof data.enabled === 'boolean') { setEnabled(data.enabled); setStatus('Сохранено'); }
      else setStatus(typeof data.message === 'string' ? data.message : 'Ошибка');
    } catch { if (owner === generation.current) setStatus('Ошибка сети. Состояние могло измениться; проверь настройки перед повтором.'); }
    finally { if (owner === generation.current) { locked.current = false; setBusy(false); } }
  };
  return <main className="panel-layout"><header className="panel-brand"><span className="panel-brand-mark">S</span><h1>Настройки расширения</h1></header>
    <section className="panel-card"><h2>Питомцы зрителей в overlay</h2><p>Показывать питомцев активных зрителей внизу overlay.</p><strong id="pets-toggle-label">{enabled === null ? 'Состояние неизвестно' : enabled ? 'Включено' : 'Выключено'}</strong>
      <button id="pets-toggle-btn" type="button" disabled={busy || enabled === null} onClick={() => { void toggle(); }}>{enabled ? 'Выключить' : 'Включить'}</button><p id="pets-toggle-status" role="status">{status}</p>
    </section><section className="panel-card"><p>Полное управление каналом — в кабинете стримера: модерация озвучки, автосообщения и настройки интеграции. Вход через Twitch.</p><a href={`${baseUrl}/streamer`} target="_blank" rel="noopener noreferrer">Открыть кабинет стримера</a><p className="panel-muted">Ссылка ведёт на внешний сайт — вы покинете Twitch.<br />This link opens an external website — you are leaving Twitch.</p></section>
  </main>;
}
