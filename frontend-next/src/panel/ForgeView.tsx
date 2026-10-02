import { useRef, useState, useSyncExternalStore } from 'react';
import type { PanelController } from './controller';
import { actionKey, validPrice } from './contracts';
import { forgeAllowed, forgeContext, forgeDisagreement, forgeItem, forgeSlots, nextQuality, qualities, qualityKey } from './forge';
import './forge.css';
export function ForgeView({ controller, active }: { controller: PanelController; active: boolean }) {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const [open, setOpen] = useState(false), wasOpen = useRef(false);
  const price = state.config?.reforge_price, authenticated = controller.forgeAuthenticated();
  if (!state.hero?.has_hero || !state.hero.hero?.is_alive) return null;
  return <details className="panel-card panel-forge" data-bnr-details="inv-forge" open={open} onToggle={event => {
    const next = event.currentTarget.open;
    if (next && !wasOpen.current) controller.trackSection('bannerlord:details.inv-forge');
    wasOpen.current = next; setOpen(next);
  }}><summary>🔨 Кузница (трофеи)</summary><div id="bnr-forge-slot">{open && (authenticated ? <>
    <p className="panel-muted">🔨 Поднимай качество надетой экипировки по ступеням: <strong>◆ Хорошее → ★ Шикарное → ✦ Легендарное</strong> (буст урона/брони/скорости). Каждое нажатие — <strong>+1 ступень</strong> за <strong>{validPrice(price) ? price.toLocaleString('ru-RU') + '💎' : 'Цена недоступна'}</strong>. База (тир) остаётся твоя, апается только качество.<br />На потолке (Легендарное) → крустики возвращаются. Доступно вне боя.</p>
    {!validPrice(price) && <button type="button" id="bnr-forge-price-retry" disabled={!active || !state.canAct} onClick={() => { void controller.refreshConfig(); }}>Обновить цену кузницы</button>}
    {forgeSlots.map(([slot, emoji, label]) => {
      const item = forgeItem(state.hero, slot), next = item ? nextQuality(item) : null, quality = item ? qualities[qualityKey(item)] : undefined, context = forgeContext(state, slot);
      const shield = slot.startsWith('weapon') && item?.stats?.hp != null && item?.stats?.body != null;
      return <div className="panel-forge-row" key={slot} data-forge-slot={slot}>
        <span className="panel-forge-item" title={item?.item_name || item?.item_id || label}><span aria-label={shield ? 'Щит' : label}>{shield ? '🛡' : emoji}</span> {item ? item.item_name || item.item_id : <em>пусто</em>}{item && typeof item.tier === 'number' && item.tier >= 0 && <strong className="panel-forge-tier">T{item.tier + 1}★</strong>}{quality && <span className="panel-forge-quality" title={'Качество: ' + quality.label} style={{ color: quality.color }}>{quality.icon} {quality.label}</span>}</span>
        {forgeDisagreement(state, slot) && <span role="status">Данные вещи обновляются</span>}
        {!item ? <span>—</span> : !next ? <strong title="Уже максимальное качество (Легендарное)">✦ макс</strong> : <button type="button" className="bnr-reforge-btn" data-slot={slot} style={{ color: next.color }} disabled={!active || !authenticated || !forgeAllowed(state, slot, context) || state.busy.includes(actionKey('hero.reforge_quality', { slot }))} title={validPrice(price) ? `Поднять «${item.item_name || item.item_id}» на одну ступень → ${next.label} за ${price}💎. На потолке → крустики вернутся.` : 'Цена недоступна'} onClick={() => { void controller.forgeAction(slot, context); }}>⚒ → {next.icon} {next.label}</button>}
      </div>;
    })}
  </> : <p>Войдите через Twitch</p>)}</div></details>;
}
