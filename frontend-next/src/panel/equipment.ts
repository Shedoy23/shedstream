// Equipment wire shapes preserve the server's exact owned IDs and quote fields.
export interface PurchaseOption {
  slot: string; replace_owned_id: string; replace_item_id: string; replace_modifier_id: string;
  replaced_name?: string | null; trade_in_gold: number; net_price_gold: number; can_buy: boolean;
  reason?: string | null; message?: string | null;
}
export interface EquipmentItem {
  item_id: string; name?: string; tier: number; category?: string; stats?: Record<string, unknown>; weight?: number;
  slots?: string[]; unavailable?: boolean;
}
export interface ShopItem extends EquipmentItem {
  id?: string; required_level: number; price_gold: number; purchase_mode: string; can_buy: boolean;
  purchase_options?: PurchaseOption[]; reason?: string | null; message?: string | null;
}
export interface OwnedItem extends EquipmentItem {
  owned_id: string; slot?: string | null; modifier_id?: string; source?: string; count?: number; trade_in_gold?: number;
}
export interface EquipmentReply {
  success: boolean; items: ShopItem[]; inventory: OwnedItem[]; tiers: { tier: number; required_level: number }[];
  hero_level: number; gold: number; has_hero: boolean; ready: boolean; pending: boolean; can_manage: boolean;
  reason?: string | null; message?: string | null;
  party_inventory?: { available: boolean; reason?: string | null; message?: string | null; party_id?: string | null; party_name?: string | null };
}
export const slotNames: Record<string, string> = { weapon0: 'Оружие 1', weapon1: 'Оружие 2', weapon2: 'Оружие 3', weapon3: 'Оружие 4', head: 'Шлем', body: 'Доспех', leg: 'Обувь', gloves: 'Перчатки', cape: 'Плечи', horse: 'Конь', horseharness: 'Броня коня' };
export const categories: Record<string, string> = { one_handed: 'Одноручное', two_handed: 'Двуручное', polearm: 'Древковое', bow: 'Луки', crossbow: 'Арбалеты', thrown: 'Метательное', shield: 'Щиты', arrows: 'Стрелы', bolts: 'Болты', head: 'Шлемы', body: 'Доспехи', leg: 'Обувь', gloves: 'Перчатки', cape: 'Наплечники', horse: 'Лошади', horseharness: 'Сбруя' };
export const statNames: Record<string, string> = { weight: 'Вес', head: 'Голова', body: 'Тело', leg: 'Ноги', arm: 'Руки', swing_dmg: 'Урон руб.', thrust_dmg: 'Урон кол.', swing_spd: 'Скорость руб.', thrust_spd: 'Скорость кол.', length: 'Длина', missile_spd: 'Скорость снаряда', accuracy: 'Точность', stack: 'Боезапас', speed: 'Скорость', maneuver: 'Манёвренность', charge: 'Урон натиска', hp: 'Прочность', armor: 'Защита', dmg: 'Урон' };
export const number = (value: unknown) => Number(value || 0).toLocaleString('ru-RU');
export const tierName = (value: number) => ['—', 'I', 'II', 'III', 'IV', 'V', 'VI'][value] || String(value);
export const paymentText = (value: number | undefined) => Number(value) < 0 ? `Получишь ${number(-Number(value))} 💰` : `К оплате ${number(value)} 💰`;
export const purchaseOption = (item: ShopItem, slots: Record<string, string>) => item.purchase_options?.find(option => option.slot === slots[item.item_id]) || item.purchase_options?.find(option => option.can_buy) || item.purchase_options?.[0];
export function stats(item: EquipmentItem) {
  const raw = item.weight ?? item.stats?.weight;
  const weight = raw != null && Number.isFinite(Number(raw)) && Number(raw) >= 0 ? `Вес ${Number(raw).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} кг` : '';
  const rest = Object.entries(item.stats || {}).filter(([key, value]) => key !== 'weight' && statNames[key] && Number.isFinite(Number(value)) && Number(value) > 0).map(([key, value]) => `${statNames[key]} ${String(value)}`);
  return [weight, ...rest].filter(Boolean).slice(0, 6).join(' · ');
}
export function numericStats(item?: EquipmentItem) {
  const values = { ...item?.stats }; if (item?.weight != null) values.weight = item.weight;
  return Object.fromEntries(Object.entries(values).filter(([key, value]) => statNames[key] && Number.isFinite(Number(value))).map(([key, value]) => [key, Number(value)]));
}
export function directPayload(item: ShopItem, option: PurchaseOption) {
  return { item_id: item.item_id, equip_now: true, slot: option.slot, replace_owned_id: option.replace_owned_id,
    replace_item_id: option.replace_item_id, replace_modifier_id: option.replace_modifier_id,
    expected_price_gold: item.price_gold, expected_trade_in_gold: option.trade_in_gold };
}
