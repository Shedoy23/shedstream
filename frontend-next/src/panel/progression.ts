import type { HeroReply } from './contracts';
export interface ContentEntry { id: string; name?: string; description?: string; available?: boolean; unavailable_reason?: string }
export interface ContentCatalog { available: boolean; reason?: string | null; entries: ContentEntry[]; catalog_seq?: number }
export interface ContentCatalogs { success: boolean; save_id?: string | null; equipment_session_id?: string | null; cultures?: ContentCatalog; workshop_types?: ContentCatalog; policies?: ContentCatalog; skills?: ContentCatalog; attributes?: ContentCatalog }
export interface ProgressionContext { save_id: string; equipment_session_id: string; hero_id: string }
export interface GoldOffer { amount: number; cost_gold: number; available: boolean; reason?: string | null; reason_text?: string | null }
export interface SkillProgression { id: string; attribute?: string; level?: number; focus: number; focus_limit?: number; native_focus_limit?: number; focus_options?: GoldOffer[]; xp_available?: boolean; xp_reason_text?: string | null }
export interface AttributeProgression { id: string; value: number; limit?: number; native_limit?: number; options?: GoldOffer[] }
export interface XpOffer { id: string; crusticov: number; price: number; xp: number; available: boolean; reason?: string | null; reason_text?: string | null }
export interface ProgressionReply { success: boolean; ready: boolean; pending?: boolean; reason?: string | null; message?: string | null; context?: ProgressionContext | null; progression?: { version: number; skills: SkillProgression[]; attributes: AttributeProgression[]; random_xp_available?: boolean }; xp_offers?: XpOffer[] }
export type ProgressionKind = 'focus' | 'attribute' | 'xp';
export const progressionMoney = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
export function progressionContext(snapshot: ProgressionReply | null | undefined, hero?: HeroReply | null) {
  const context = snapshot?.context;
  if (snapshot?.ready !== true || !snapshot.progression || !context || ![context.save_id, context.equipment_session_id, context.hero_id].every(x => typeof x === 'string' && !!x)) return null;
  if (hero?.hero?.hero_id && hero.hero.hero_id !== context.hero_id) return null;
  return {save_id:context.save_id, equipment_session_id:context.equipment_session_id, hero_id:context.hero_id};
}
export function contentEntries(catalog?: ContentCatalog | null): ContentEntry[] {
  if (catalog?.available !== true || !Array.isArray(catalog.entries)) return [];
  const seen = new Set<string>();
  return catalog.entries.filter(e => { if (!e || typeof e.id !== 'string' || !e.id || seen.has(e.id)) return false; seen.add(e.id); return true; });
}
export function contentName(catalog: ContentCatalog | null | undefined, id: string) {
  const entry = contentEntries(catalog).find(e => e.id === id);
  return typeof entry?.name === 'string' && entry.name ? entry.name : id;
}
export function progressionQuote(snapshot: ProgressionReply | null | undefined, kind: ProgressionKind, id: string, hero?: HeroReply | null): Record<string, unknown> | null {
  const context = progressionContext(snapshot, hero);
  if (!context || snapshot?.pending) return null;
  if (kind === 'xp') {
    const option = snapshot?.xp_offers?.find(o => o?.id === id);
    if (!option || option.available !== true || !progressionMoney(option.price) || !progressionMoney(option.crusticov) || !Number.isSafeInteger(option.xp) || option.xp <= 0) return null;
    return {price:option.crusticov, expected_platform_price:option.price, progression_context:context};
  }
  const entry = kind === 'focus' ? snapshot?.progression?.skills?.find(s => s?.id === id) : snapshot?.progression?.attributes?.find(a => a?.id === id);
  const value = kind === 'focus' ? (entry as SkillProgression | undefined)?.focus : (entry as AttributeProgression | undefined)?.value;
  const options = kind === 'focus' ? (entry as SkillProgression | undefined)?.focus_options : (entry as AttributeProgression | undefined)?.options;
  const option = Array.isArray(options) ? options.find(o => o?.amount === 1) : undefined;
  if (!entry || !Number.isSafeInteger(value) || value! < 0 || option?.available !== true || !progressionMoney(option.cost_gold)) return null;
  return {[kind === 'focus' ? 'skill_key' : 'attribute_key']:id, amount:1, expected_cost_gold:option.cost_gold, expected_value:value, progression_context:context};
}
export const progressionActionType = (kind: ProgressionKind) => kind === 'xp' ? 'hero.add_skill' : kind === 'focus' ? 'hero.add_focus' : 'hero.add_attribute';
export const progressionReason = (snapshot?: ProgressionReply | null) => snapshot?.pending ? 'Предыдущая заявка ещё выполняется в игре.' : snapshot?.message || snapshot?.reason || 'Игра ещё не передала предложения прокачки.';
