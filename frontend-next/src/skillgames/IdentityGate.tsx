import type { IdentityState } from './identity';
export function IdentityGate({ state, onRetry, onShare, localIntegration }: { state: IdentityState; onRetry: () => void; onShare: () => void; localIntegration?: boolean }) {
  return <main className="sg-layout"><header className="sg-brand"><span className="sg-brand-mark">S</span><div><strong>ShedLink</strong><span>Мини-игры</span></div></header>
    {localIntegration && <aside className="sg-demo"><strong>ЛОКАЛЬНЫЙ API-СТЕНД</strong><p>Тестовые Twitch-личности и временная база; production не подключён.</p></aside>}
    <section className="sg-session"><p className="sg-eyebrow">ВХОД ЧЕРЕЗ TWITCH</p><h1>Подключите свою личность</h1>
      <p className="sg-hint">Сервер должен подтвердить ваш Twitch ID, чтобы сохранять партию и рейтинг канала. Логин и пароль вводить здесь не нужно.</p>
      <p className={state.status === 'blocked' ? 'sg-error' : 'sg-notice'} role="status">{state.message}</p>
      {state.canShare && <button className="sg-primary" disabled={state.status === 'resolving' || state.shareRequested} onClick={onShare}>Поделиться Twitch ID</button>}
      {state.status === 'blocked' && <button className="sg-quit" onClick={onRetry}>Повторить проверку</button>}
      {!state.canShare && <p className="sg-hint">Запрос передачи ID недоступен в этом окружении. Откройте расширение на странице Twitch и проверьте вход в аккаунт.</p>}
    </section><a href="./tournament.html">Отдельный макет турнира</a>
  </main>;
}
