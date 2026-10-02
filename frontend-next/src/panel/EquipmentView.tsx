import { useCallback, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { heroContext } from './contracts';
import type { PanelController } from './controller';
import { categories, directPayload, equipmentPresentation, number, numericStats, paymentText, priceText, purchaseOption, slotNames, statNames, stats, tierName, validQuote, type EquipmentReply, type OwnedItem, type ShopItem } from './equipment';
import './equipment.css';
interface Confirmation {
  message: string; yes: string; opener: HTMLElement | null; generation: number; hero: string;
  action: 'hero.buy_equipment' | 'hero.discard_owned'; id: string; signature: string; data: Record<string, unknown>;
}
// The server's equipment reply has no save/session ID. Preserve the same
// observable hero fence for preload consumption and ordinary refreshes.
const heroIdentity = (controller: PanelController) => heroContext(controller.snapshot().hero);
const quoteSignature = (item: ShopItem, slots: Record<string, string>) => JSON.stringify([item.item_id, item.name, item.price_gold, item.purchase_mode, item.can_buy, item.unavailable, purchaseOption(item, slots)]);
function DangerDialog({ confirmation, accept, cancel }: { confirmation: Confirmation; accept: () => void; cancel: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const no = dialog.current?.querySelector<HTMLButtonElement>('#confirm-dyn-no'); no?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); cancel(); }
      if (event.key !== 'Tab') return;
      const buttons = [...(dialog.current?.querySelectorAll<HTMLButtonElement>('button') || [])];
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.removeEventListener('keydown', keydown); if (confirmation.opener?.isConnected) confirmation.opener.focus(); };
  }, []);
  return <div id="confirm-dyn-modal" className="bnr-eq-modal-backdrop" onClick={event => { if (event.target === event.currentTarget) cancel(); }}>
    <div ref={dialog} className="bnr-eq-modal" role="dialog" aria-modal="true" aria-labelledby="bnr-eq-confirm-title" aria-describedby="bnr-eq-confirm-message">
      <h3 id="bnr-eq-confirm-title">⚠️ Подтверди</h3><p id="bnr-eq-confirm-message">{confirmation.message}</p>
      <div className="bnr-eq-modal-actions"><button type="button" id="confirm-dyn-yes" onClick={accept}>{confirmation.yes}</button><button type="button" id="confirm-dyn-no" onClick={cancel}>❌ Нет</button></div>
    </div>
  </div>;
}
function ComparedStats({ item, equipped }: { item: OwnedItem; equipped?: OwnedItem }) {
  const current = numericStats(equipped);
  return <>{Object.entries(numericStats(item)).filter(([, value]) => value > 0).slice(0, 8).map(([key, value]) => {
    const delta = value - (current[key] || 0), useful = key === 'weight' ? -delta : delta;
    return <span key={key}>{statNames[key]} {value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}{equipped && Math.abs(delta) >= .001 && <> <span className={'bnr-eq-delta ' + (useful > 0 ? 'better' : 'worse')}>{delta > 0 ? '+' : ''}{delta.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}</span></>}</span>;
  })}</>;
}
export function EquipmentView({ controller, active = true }: { controller: PanelController; active?: boolean }) {
  const panel = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const presentation = equipmentPresentation(panel.config?.ui);
  const [snapshot, setSnapshot] = useState<EquipmentReply | null>(null), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [view, setView] = useState<'shop' | 'owned'>('shop');
  const [search, setSearch] = useState(''), [category, setCategory] = useState(''), [tier, setTier] = useState('');
  const [page, setPage] = useState(0), [ownedSlot, setOwnedSlot] = useState('weapon0');
  const [purchaseSlots, setPurchaseSlots] = useState<Record<string, string>>({});
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const dataRef = useRef(snapshot), busyRef = useRef(false), slotsRef = useRef(purchaseSlots), activeRef = useRef(active);
  const request = useRef(0), applied = useRef(0), revision = useRef(0), mounted = useRef(false);
  const flight = useRef<{ key: string; promise: Promise<void> } | null>(null);
  const generation = useRef(panel.generation), dialogRef = useRef(confirmation);
  const currentHero = heroIdentity(controller), observedHero = useRef(currentHero), dataHero = useRef(currentHero);
  activeRef.current = active; slotsRef.current = purchaseSlots; dialogRef.current = confirmation;
  const update = (data: EquipmentReply | null) => { dataRef.current = data; setSnapshot(data); };
  const close = () => { dialogRef.current = null; setConfirmation(null); };
  const manageable = () => activeRef.current && controller.ready() && dataHero.current === heroIdentity(controller) && !controller.snapshot().mutationBlocked && !!dataRef.current?.has_hero && !!dataRef.current.ready && !!dataRef.current.can_manage && !dataRef.current.pending && !busyRef.current;
  const valid = (pending: Confirmation) => {
    if (!manageable() || controller.identityGeneration() !== pending.generation || heroIdentity(controller) !== pending.hero) return false;
    const data = dataRef.current!;
    if (pending.action === 'hero.discard_owned') {
      const item = data.inventory.find(row => row.owned_id === pending.id);
      return !!data.party_inventory?.available && !!item && JSON.stringify(item) === pending.signature;
    }
    const item = data.items.find(row => row.item_id === pending.id);
    return !!item && item.can_buy && !item.unavailable && validQuote(item, purchaseOption(item, slotsRef.current)) && !!purchaseOption(item, slotsRef.current)?.can_buy && quoteSignature(item, slotsRef.current) === pending.signature;
  };
  const refresh = useCallback(() => {
    if (!mounted.current || !controller.ready()) return;
    const identity = controller.identityGeneration(), hero = heroIdentity(controller), actionRevision = revision.current;
    const key = JSON.stringify([identity, hero, actionRevision]);
    // Match the old loader's synchronous single flight only within this context.
    // A new viewer, hero or accepted action must still admit a fresh read.
    if (flight.current?.key === key) return flight.current.promise;
    const issued = ++request.current, pending = { key, promise: Promise.resolve() };
    flight.current = pending;
    const current = () => mounted.current && controller.ready() && identity === controller.identityGeneration() && hero === heroIdentity(controller) && issued > applied.current && actionRevision === revision.current;
    pending.promise = (async () => {
      try {
        const result = await controller.read<EquipmentReply>('/api/bannerlord/equipment-shop');
        if (!current()) return;
        if (!result.success) throw new Error(result.message || 'Не удалось загрузить снаряжение');
        applied.current = issued; dataHero.current = hero; update(result); setError('');
        controller.observeForgeEquipment(result, identity, hero);
      } catch (failure) {
        if (!current()) return;
        applied.current = issued; update(null); setError(failure instanceof Error ? failure.message : 'Не удалось загрузить магазин. Обнови данные.');
      } finally { if (flight.current === pending) flight.current = null; }
    })();
    return pending.promise;
  }, [controller]);
  useLayoutEffect(() => {
    mounted.current = true; const unregister = controller.registerEquipmentRefresh(refresh);
    return () => { mounted.current = false; flight.current = null; request.current++; revision.current++; unregister(); };
  }, [controller, refresh]);
  useLayoutEffect(() => {
    if (generation.current !== panel.generation) {
      generation.current = panel.generation; observedHero.current = currentHero; revision.current++; applied.current = ++request.current;
      update(null); busyRef.current = false; setBusy(false); close(); setError('');
      setView('shop'); setSearch(''); setCategory(''); setTier(''); setPage(0); setOwnedSlot('weapon0'); setPurchaseSlots({});
    }
    if (observedHero.current !== currentHero) {
      observedHero.current = currentHero; revision.current++; applied.current = ++request.current;
      update(null); close(); busyRef.current = false; setBusy(false);
    }
    if (!active || !panel.canAct) { close(); return; }
    void refresh();
  }, [controller, refresh, active, panel.canAct, panel.generation, currentHero]);
  useLayoutEffect(() => { if (dialogRef.current && !valid(dialogRef.current)) close(); }, [snapshot, panel, active]);
  async function perform(type: string, data: Record<string, unknown>) {
    if (!manageable()) return;
    const identity = controller.identityGeneration(), hero = heroIdentity(controller); busyRef.current = true; setBusy(true);
    try {
      const result = await controller.action(type, data, { tail: 'balance', successMessage: 'Заявка отправлена в игру. Инвентарь обновится после выполнения.' });
      if (mounted.current && identity === controller.identityGeneration() && hero === heroIdentity(controller) && result?.success) {
        // A pre-ack GET cannot overwrite the newer local pending flag. A GET
        // started after this revision remains authoritative and may release it.
        revision.current++;
        if (dataRef.current) update({ ...dataRef.current, pending: true });
      }
    } finally { if (mounted.current && identity === controller.identityGeneration() && hero === heroIdentity(controller)) { busyRef.current = false; setBusy(false); } }
  }
  function confirm(action: Confirmation['action'], id: string, signature: string, data: Record<string, unknown>, message: string, yes = '✅ Да') {
    setConfirmation({ action, id, signature, data, message, yes, opener: document.activeElement as HTMLElement | null, generation: controller.identityGeneration(), hero: heroIdentity(controller) });
  }
  function buy(id: string) {
    const item = dataRef.current?.items.find(row => row.item_id === id);
    if (!manageable() || !item?.can_buy || item.unavailable || !validQuote(item, purchaseOption(item, slotsRef.current))) return;
    if (item.purchase_mode !== 'equip') { void perform('hero.buy_equipment', { item_id: item.item_id }); return; }
    const option = purchaseOption(item, slotsRef.current); if (!option?.can_buy) return;
    confirm('hero.buy_equipment', item.item_id, quoteSignature(item, slotsRef.current), directPayload(item, option), `Купить и надеть «${item.name || item.item_id}» в «${slotNames[option.slot] || option.slot}»?${option.replace_owned_id ? ` «${option.replaced_name}» будет продан за ${number(option.trade_in_gold)} 💰 и исчезнет из снаряжения.` : ''} ${paymentText(option.net_price_gold)}.`);
  }
  function discard(id: string) {
    const item = dataRef.current?.inventory.find(row => row.owned_id === id);
    if (!manageable() || !item || !dataRef.current?.party_inventory?.available) return;
    confirm('hero.discard_owned', item.owned_id, JSON.stringify(item), { owned_id: item.owned_id }, `Выкинуть «${item.name || item.item_id}»? Предмет исчезнет навсегда${item.slot ? ' и будет снят с героя' : ''}. Динары не вернутся.`, 'Да, выкинуть');
  }
  function equip(id: string) {
    const item = dataRef.current?.inventory.find(row => row.owned_id === id);
    if (!manageable() || !item || item.slot || item.unavailable || !item.slots?.includes(ownedSlot) || !dataRef.current?.party_inventory?.available) return;
    void perform('hero.equip_owned', { owned_id: item.owned_id, slot: ownedSlot });
  }
  function unequip() { if (manageable() && dataRef.current?.party_inventory?.available && dataRef.current.inventory.some(item => item.slot === ownedSlot)) void perform('hero.unequip_owned', { slot: ownedSlot }); }
  const sourceItems = (view === 'owned' ? snapshot?.inventory : snapshot?.items) || [];
  const availableCategories = [...new Set(sourceItems.map(item => item.category).filter((value): value is string => !!value))];
  const effectiveCategory = availableCategories.includes(category) ? category : '';
  useLayoutEffect(() => { if (category !== effectiveCategory) setCategory(effectiveCategory); }, [category, effectiveCategory]);
  const query = search.trim().toLocaleLowerCase('ru-RU');
  const matches = (item: { name?: string; item_id: string }) => !query || (item.name || item.item_id).toLocaleLowerCase('ru-RU').includes(query);
  const filtered = (snapshot?.items || []).filter(item => (!effectiveCategory || item.category === effectiveCategory) && (!tier || String(item.tier) === tier) && matches(item));
  const pages = Math.max(1, Math.ceil(filtered.length / 20)), currentPage = Math.min(page, pages - 1);
  useLayoutEffect(() => { if (page !== currentPage) setPage(currentPage); }, [page, currentPage]);
  const blocked = !active || dataHero.current !== currentHero || !panel.canAct || panel.mutationBlocked || !snapshot?.ready || !snapshot.has_hero || !snapshot.can_manage || snapshot.pending || busy;
  const party = snapshot?.party_inventory, partyAvailable = !!party?.available, inventoryBlocked = blocked || !partyAvailable;
  const inventory = snapshot?.inventory || [], equipped = inventory.find(item => item.slot === ownedSlot);
  const candidates = inventory.filter(item => !item.slot && (item.source !== 'party' || partyAvailable) && item.slots?.includes(ownedSlot) && matches(item));
  const baggage = candidates.filter(item => item.source === 'party'), legacy = candidates.filter(item => item.source !== 'party');
  const candidate = (item: OwnedItem) => <article className="bnr-eq-candidate" key={item.owned_id} data-tier={item.tier || 1} style={presentation.tierStyle(item.tier || 1)}>
    <div className="bnr-eq-item-top"><strong>{item.name || item.item_id}{item.source === 'party' && Number(item.count) > 1 ? ` ×${number(item.count)}` : ''}</strong><span className="bnr-eq-tier">{tierName(item.tier)}</span></div>
    <div className="bnr-eq-source">{item.source === 'party' ? 'Инвентарь отряда (багаж)' : 'Старое хранилище мода — не багаж отряда'}</div>
    <div className="bnr-eq-compare"><ComparedStats item={item} equipped={equipped} /></div>
    <button type="button" className="bnr-eq-action secondary" data-bnr-eq-equip={item.owned_id} disabled={inventoryBlocked || item.unavailable} onClick={() => equip(item.owned_id)}>Надеть в «{slotNames[ownedSlot]}»</button>
    <button type="button" className="bnr-eq-action discard" data-bnr-eq-discard={item.owned_id} disabled={inventoryBlocked} onClick={() => discard(item.owned_id)}>{presentation.discard}</button>
    {item.unavailable && <div className="bnr-eq-reason">Предмет недоступен в текущей сборке игры.</div>}
  </article>;
  return <section id="bnr-equipment-shop" className="panel-equipment panel-card" aria-label="Снаряжение">
    <div className="card-header"><h2>🎒 Снаряжение</h2><span className="card-badge" data-bnr-eq-count>{snapshot ? view === 'shop' ? `${filtered.length} вещей` : snapshot.ready ? `${inventory.length} вещей` : 'Нет данных' : ''}</span></div>
    {error && <p role="alert" className="bnr-eq-empty">{error}</p>}
    {panel.message && <p role="status" className="panel-notice">{panel.message}</p>}
    {panel.error && <p role="alert" className="panel-error">{panel.error}</p>}
    {!snapshot && !error && <p role="status">Загружаем снаряжение…</p>}
    {snapshot && <>
      <div className="bnr-eq-summary"><span>Герой · ур. {number(snapshot.hero_level)}</span><strong>{number(snapshot.gold)} 💰</strong></div>
      <div className="bnr-eq-unlocks">{snapshot.tiers.map(t => <span key={t.tier} data-tier={t.tier} style={presentation.tierStyle(t.tier)} className={snapshot.hero_level >= t.required_level ? 'unlocked' : ''}>{tierName(t.tier)} · ур. {number(t.required_level)}</span>)}</div>
      <div className="bnr-eq-tabs" role="group" aria-label="Снаряжение">
        <button type="button" data-bnr-eq-view="shop" aria-pressed={view === 'shop'} onClick={() => { setView('shop'); setPage(0); }}>Магазин</button>
        <button type="button" data-bnr-eq-view="owned" aria-pressed={view === 'owned'} onClick={() => { setView('owned'); setPage(0); }}>Инвентарь{snapshot.ready ? '' : ' · нет данных'}</button>
      </div>
      <p className="bnr-eq-help">{view === 'shop' ? partyAvailable ? 'Покупка за динары героя. Вещь попадёт в инвентарь его отряда.' : 'Без багажа можно купить вещь сразу на героя. При замене старая вещь продаётся за указанную сумму. Покупка с надеванием доступна вне боя и сцен.' : 'Надетое снаряжение героя и доступные вещи для замены из общего багажа его отряда. Еда и торговые товары здесь не показаны.'}</p>
      {(snapshot.pending || busy) && <div className="bnr-eq-notice" role="status">Заявка отправлена — ждём результат из игры.</div>}
      {snapshot.reason && <div className="bnr-eq-notice" role="status">{snapshot.message || snapshot.reason}</div>}
      <div className="bnr-eq-filters"><input type="search" data-bnr-eq-search aria-label="Найти вещь" placeholder="Найти вещь…" value={search} onInput={event => { setSearch(event.currentTarget.value); setPage(0); }} />
        {view === 'shop' && <div><select data-bnr-eq-category aria-label="Категория" value={effectiveCategory} onChange={event => { setCategory(event.currentTarget.value); setPage(0); }}><option value="">Все категории</option>{availableCategories.map(c => <option key={c} value={c}>{categories[c] || c}</option>)}</select>
          <select data-bnr-eq-tier aria-label="Тир" value={tier} onChange={event => { setTier(event.currentTarget.value); setPage(0); }}><option value="">Все тиры</option>{snapshot.tiers.map(t => <option key={t.tier} value={String(t.tier)}>Тир {tierName(t.tier)}</option>)}</select></div>}
      </div>
      <div className="bnr-eq-results" data-bnr-eq-results>{view === 'shop' ? <div className="bnr-eq-shop-grid">{filtered.slice(currentPage * 20, (currentPage + 1) * 20).map(item => {
        const option = purchaseOption(item, purchaseSlots), quoteValid = validQuote(item, option);
        return <article className="bnr-eq-item" key={item.item_id} data-tier={item.tier >= 1 && item.tier <= 6 ? item.tier : 1} style={presentation.tierStyle(item.tier >= 1 && item.tier <= 6 ? item.tier : 1)}>
          <div className="bnr-eq-item-top"><strong>{item.name || item.item_id}</strong><span className="bnr-eq-tier">{tierName(item.tier)}</span></div>
          <div className="bnr-eq-meta">{categories[item.category || ''] || item.category || ''} · ур. {number(item.required_level)}</div>
          {stats(item) && <div className="bnr-eq-stats">{stats(item)}</div>}
          {item.purchase_mode === 'equip' ? <>
            <select aria-label={`Куда надеть ${item.name}`} data-bnr-eq-purchase-slot={item.item_id} disabled={blocked} value={option?.slot} onChange={event => setPurchaseSlots({ ...purchaseSlots, [item.item_id]: event.currentTarget.value })}>{item.purchase_options?.map(o => <option key={o.slot} value={o.slot}>{slotNames[o.slot] || o.slot} · {o.replace_owned_id ? `заменить ${o.replaced_name}` : 'пусто'}</option>)}</select>
            <div className="bnr-eq-meta">Цена {priceText(item.price_gold)} 💰{option?.replace_owned_id ? ` · Продажа старой вещи ${priceText(option.trade_in_gold)} 💰` : ''}</div>
            <button type="button" className="bnr-eq-action" data-bnr-eq-buy={item.item_id} disabled={blocked || !quoteValid || item.unavailable || !item.can_buy || !option?.can_buy} onClick={() => buy(item.item_id)}>Купить и надеть · {paymentText(option?.net_price_gold)}</button>
            {option?.reason && <div className="bnr-eq-reason">{option.message || option.reason}</div>}
          </> : <><button type="button" className="bnr-eq-action" data-bnr-eq-buy={item.item_id} disabled={blocked || !quoteValid || item.unavailable || !item.can_buy} onClick={() => buy(item.item_id)}>Купить · {priceText(item.price_gold)} 💰</button>{!item.can_buy && item.reason && <div className="bnr-eq-reason">{item.message || item.reason}</div>}</>}
          {!quoteValid && <div className="bnr-eq-reason">Сервер не передал корректную цену или условия замены. Покупка недоступна.</div>}
        </article>;
      })}{!filtered.length && <div className="bnr-eq-empty">{search || effectiveCategory || tier ? 'Ничего не найдено. Измени фильтры.' : 'Каталог появится, когда мод передаст вещи из игры.'}</div>}</div> : !snapshot.ready ? <div className="bnr-eq-empty">Данных о вещах героя пока нет.</div> : <>
        <h3>Надето на герое</h3><div className="bnr-eq-slots">{Object.entries(slotNames).map(([slot, name]) => <button type="button" key={slot} className="bnr-eq-slot" data-bnr-owned-slot={slot} aria-pressed={ownedSlot === slot} onClick={() => { setOwnedSlot(slot); setSearch(''); }}><span>{name}</span><strong>{inventory.find(item => item.slot === slot)?.name || 'Пусто'}</strong></button>)}</div>
        {equipped ? <article className="bnr-eq-current" data-tier={equipped.tier || 1} style={presentation.tierStyle(equipped.tier || 1)}><div><span>Сейчас надето</span><strong>{equipped.name || equipped.item_id}</strong></div><div className="bnr-eq-stats">{stats(equipped)}</div><div className="bnr-eq-current-actions"><button type="button" data-bnr-eq-unequip={ownedSlot} disabled={inventoryBlocked} onClick={unequip}>Снять</button><button type="button" className="discard" data-bnr-eq-discard={equipped.owned_id} disabled={inventoryBlocked} onClick={() => discard(equipped.owned_id)}>{presentation.discard}</button></div></article> : <div className="bnr-eq-current empty">Слот свободен</div>}
        <h3>Багаж отряда{partyAvailable && party?.party_name ? ` · ${party.party_name}` : ''}</h3>
        {!partyAvailable && <div className="bnr-eq-notice">{party?.message || 'Доступ к багажу ещё не подтверждён игрой.'}</div>}
        <div className="bnr-eq-slot-title"><strong>{slotNames[ownedSlot]}</strong>{partyAvailable && <span>{baggage.reduce((sum, item) => sum + Number(item.count || 1), 0)} доступно</span>}</div>
        <div className="bnr-eq-candidates">{baggage.map(candidate)}{!baggage.length && partyAvailable && <div className="bnr-eq-empty">Для слота «{slotNames[ownedSlot]}» подходящих вещей нет.</div>}</div>
        {!!legacy.length && <><h3>Старое хранилище мода</h3><div className="bnr-eq-candidates">{legacy.map(candidate)}</div></>}
      </>}</div>
      <div className="bnr-eq-pages" data-bnr-eq-pages>{view === 'shop' && pages > 1 && <><button type="button" data-bnr-eq-page="-1" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Назад</button><span>{currentPage + 1} / {pages}</span><button type="button" data-bnr-eq-page="1" disabled={currentPage + 1 === pages} onClick={() => setPage(currentPage + 1)}>Далее</button></>}</div>
    </>}
    {confirmation && <DangerDialog confirmation={confirmation} cancel={close} accept={() => { const pending = dialogRef.current; close(); if (pending && valid(pending)) void perform(pending.action, pending.data); }} />}
  </section>;
}
