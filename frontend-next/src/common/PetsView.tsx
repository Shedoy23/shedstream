import { useEffect, useRef, useState } from 'react';
import type { ViewerClient } from './client';
import { ConfirmDialog } from './ConfirmDialog';
import { PetIcon, PetStage, type PetItem } from './PetStage';
import './common.css';
interface PetData { success: boolean; message?: string; pet?: { pet_type?: string; name?: string | null }; inventory?: PetItem[]; equipped?: Record<string, PetItem> }
interface Catalog { success: boolean; message?: string; items?: PetItem[] }
interface Reply { success: boolean; message?: string; hatched?: boolean }
const validPrice = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
export function PetsView({ client }: { client: ViewerClient }) {
  const [data, setData] = useState<PetData | null>(null), [catalog, setCatalog] = useState<PetItem[]>([]), [tab, setTab] = useState<'pet' | 'catalog'>('pet');
  const [message, setMessage] = useState('Загрузка…'), [name, setName] = useState(''), [busy, setBusy] = useState(false), [choice, setChoice] = useState<PetItem | null>(null), [uncertain, setUncertain] = useState(false);
  const alive = useRef(false), seq = useRef(0), locked = useRef(false), timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined), current = useRef(data), latestCatalog = useRef(catalog); current.current = data; latestCatalog.current = catalog;
  const load = async () => {
    const issued = ++seq.current;
    try {
      const [pet, cat] = await Promise.all([client.read<PetData>('/api/pet/my'), client.read<Catalog>('/api/pet/catalog')]);
      if (!alive.current || issued !== seq.current) return;
      if (!pet.success || !cat.success || !Array.isArray(pet.inventory) || !Array.isArray(cat.items)) { setMessage(pet.message || cat.message || 'Не удалось загрузить питомца'); return; }
      setData(pet); setCatalog(cat.items); setName(pet.pet?.name || ''); setUncertain(false); setMessage(m => m === 'Загрузка…' ? '' : m);
    } catch (error) { if (alive.current && issued === seq.current) setMessage(error instanceof Error ? error.message : 'Ошибка сети'); }
  };
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; seq.current++; clearTimeout(timer.current); }; }, [client]);
  useEffect(() => { if (choice && !catalog.some(item => item.item_id === choice.item_id && item.price_crustics === choice.price_crustics && !item.owned)) setChoice(null); }, [choice, catalog]);
  const action = async (path: string, body: Record<string, unknown>, purchase = false) => {
    if (locked.current || uncertain || !data?.success) return;
    locked.current = true; setBusy(true);
    try {
      const reply = await client.post<Reply>(path, body);
      if (!alive.current) return;
      setMessage(reply.message || (reply.success ? 'Готово' : 'Сервер отказал в действии'));
      if (reply.success) { await load(); if (alive.current && reply.hatched) setTab('pet'); }
    } catch (error) { if (alive.current) { setUncertain(true); setMessage((error instanceof Error ? error.message : 'Ошибка сети') + '. Результат мог сохраниться — обнови состояние перед повтором.'); } }
    finally {
      if (purchase && alive.current) timer.current = setTimeout(() => { locked.current = false; if (alive.current) setBusy(false); }, 400);
      else { locked.current = false; if (alive.current) setBusy(false); }
    }
  };
  const buy = () => {
    const shown = choice; setChoice(null);
    if (shown && validPrice(shown.price_crustics) && latestCatalog.current.some(item => item.item_id === shown.item_id && item.price_crustics === shown.price_crustics && !item.owned)) void action('/api/pet/purchase', { item_id: shown.item_id }, true);
  };
  const equipped = data?.equipped || {}, worn = new Set(Object.values(equipped).map(item => item.item_id));
  return <section className="panel-card"><h1>Питомец</h1><nav className="panel-tabs" aria-label="Питомец"><button type="button" aria-pressed={tab === 'pet'} onClick={() => setTab('pet')}>Мой питомец</button><button type="button" aria-pressed={tab === 'catalog'} onClick={() => setTab('catalog')}>Магазин питомцев</button></nav>
    <p role="status">{message}</p><button type="button" disabled={busy} onClick={() => { void load(); }}>Обновить питомца</button>
    {data && tab === 'pet' && <><PetStage pet={data.pet} equipped={equipped} /><h2>{data.pet?.name || 'Без имени'}</h2><label>Имя питомца<input value={name} onInput={e => setName(e.currentTarget.value)} /></label><button type="button" disabled={busy || uncertain} onClick={() => { void action('/api/pet/name', { name: name.trim() || null }); }}>Сохранить имя</button>
      <h2>Надето</h2>{Object.entries(equipped).map(([slot, item]) => <article className="common-item" key={slot}><PetIcon item={item} /><div><strong>{item.name}</strong><p>{slot}</p></div><button type="button" disabled={busy || uncertain} aria-label={`Снять ${item.name}`} onClick={() => { if (current.current?.equipped?.[slot]?.item_id === item.item_id) void action('/api/pet/equip', { item_id: null, slot }); }}>Снять</button></article>)}
      <h2>Инвентарь</h2>{data.inventory?.filter(item => !worn.has(item.item_id)).map(item => <article className="common-item" key={item.item_id}><PetIcon item={item} /><strong>{item.name}</strong><button type="button" disabled={busy || uncertain} aria-label={`Надеть ${item.name}`} onClick={() => { void action('/api/pet/equip', { item_id: item.item_id }); }}>Надеть</button></article>)}</>}
    {tab === 'catalog' && <><p>Конкретная косметика за крустики. Цена и наличие приходят с сервера.</p>{catalog.map(item => <article className="common-item" key={item.item_id}><PetIcon item={item} /><div><strong>{item.name}</strong><p>{item.slot} · {item.rarity}</p><p>{validPrice(item.price_crustics) ? `${item.price_crustics.toLocaleString('ru-RU')} 💎` : 'Цена недоступна'}</p></div><button type="button" aria-label={`Купить ${item.name}`} disabled={busy || uncertain || item.owned || !validPrice(item.price_crustics)} onClick={() => setChoice({ ...item })}>{item.owned ? 'Уже есть' : 'Купить'}</button></article>)}{!catalog.length && <p>Каталог пуст.</p>}</>}
    {choice && <ConfirmDialog title={`Купить ${choice.name}?`} cancel={() => setChoice(null)} confirm={buy}><p>Будет списано {choice.price_crustics?.toLocaleString('ru-RU')} 💎.</p></ConfirmDialog>}
  </section>;
}
