import type { EquipmentReply } from './equipment';
import { heroContext, validPrice, type HeroReply, type PanelState } from './contracts';
// These are the ten inherited UI positions, not an equipment/modifier catalog.
export const forgeSlots = [
  ['weapon0', '🗡', 'Оружие 1'], ['weapon1', '⚔', 'Оружие 2'], ['weapon2', '🏹', 'Оружие 3'], ['weapon3', '🛡', 'Оружие 4'],
  ['head', '🪖', 'Шлем'], ['body', '👕', 'Торс'], ['leg', '👖', 'Ноги'], ['gloves', '🧤', 'Руки'], ['cape', '🧥', 'Плащ'], ['horse', '🐎', 'Конь'],
] as const;
export interface ForgeItem { item_id: string; item_name?: string; tier?: number; quality?: string | null; stats?: Record<string, unknown>; [key: string]: unknown }
export const qualities: Record<string, { label: string; icon: string; color: string }> = {
  legendary: { label: 'Легендарное', icon: '✦', color: '#fbbf24' }, masterwork: { label: 'Шикарное', icon: '★', color: '#c084fc' },
  fine: { label: 'Хорошее', icon: '◆', color: '#60a5fa' }, inferior: { label: 'Низкое', icon: '▽', color: 'var(--muted)' }, poor: { label: 'Сломанное', icon: '▽', color: '#f87171' },
};
export const qualityKey = (item: ForgeItem) => typeof item.quality === 'string' ? item.quality.toLowerCase() : '';
export const nextQuality = (item: ForgeItem) => qualityKey(item) === 'legendary' ? null : qualities[qualityKey(item) === 'fine' ? 'masterwork' : qualityKey(item) === 'masterwork' ? 'legendary' : 'fine'];
export function forgeItem(hero: HeroReply | null, slot: string): ForgeItem | null {
  const equipment = hero?.equipment;
  if (!equipment || typeof equipment !== 'object' || Array.isArray(equipment)) return null;
  const item = (equipment as Record<string, unknown>)[slot];
  return item && typeof item === 'object' && !Array.isArray(item) && 'item_id' in item && typeof item.item_id === 'string' && item.item_id ? item as ForgeItem : null;
}
// my-hero uses zero-based tiers while equipment-shop uses one-based tiers.
// Compare only their shared paid-target identity, never display tiers or names.
export interface ForgeObservation { hero: string; slots: Record<string, { item: string; quality: string }> }
const observedQuality = (quality: unknown) => typeof quality === 'string' ? quality.toLowerCase() : '';
export function forgeObservation(reply: EquipmentReply, hero: string): ForgeObservation | null {
  if (reply.success !== true || reply.ready !== true || reply.has_hero !== true || !Array.isArray(reply.inventory)) return null;
  const slots: ForgeObservation['slots'] = {};
  for (const item of reply.inventory) if (item.slot && typeof item.item_id === 'string') {
    slots[item.slot] = { item: item.item_id, quality: observedQuality((item as unknown as Record<string, unknown>).quality) };
  }
  return { hero, slots };
}
export function forgeDisagreement(state: PanelState, slot: string) {
  const observation = state.forgeEquipment;
  if (!observation || observation.hero !== heroContext(state.hero)) return false;
  const heroItem = forgeItem(state.hero, slot), shopItem = observation.slots[slot];
  return !!heroItem !== !!shopItem || !!heroItem && !!shopItem &&
    (heroItem.item_id !== shopItem.item || observedQuality(heroItem.quality) !== shopItem.quality);
}
// A rendered click belongs to this accepted item/quality/quote, not merely slot.
export const forgeContext = (state: PanelState, slot: string) => JSON.stringify([state.generation, heroContext(state.hero), forgeItem(state.hero, slot), state.config?.reforge_price]);
export function forgeAllowed(state: PanelState, slot: string, context: string) {
  const item = forgeItem(state.hero, slot);
  return state.canAct && !state.mutationBlocked && !state.errors.hero && !!state.hero?.has_hero && !!state.hero.hero?.is_alive &&
    forgeSlots.some(([key]) => key === slot) && !forgeDisagreement(state, slot) && !!item && !!nextQuality(item) && validPrice(state.config?.reforge_price) && context === forgeContext(state, slot);
}
