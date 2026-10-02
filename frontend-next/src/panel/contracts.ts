import type { ForgeObservation } from './forge';
import type { DiplomacyReply } from './diplomacy';
import type { PartyOrdersReply } from './party';
// Wire contracts are server-owned. Unknown fields survive parsing; no economy
// defaults or game catalog enums are synthesized by this presentation layer.
export interface RefundNotice { action_id: string; type: string; reason?: string; refunded: boolean }
export interface HeroReply { recent_refunds?: RefundNotice[]; success: boolean; has_hero: boolean; equipment_shop_ready?: boolean; hero?: { hero_id: string; display_name: string; is_alive: boolean | number; is_prisoner?: boolean | number; is_wounded?: boolean | number; level: number; gold: number; [key: string]: unknown }; skills?: { skill_key: string; level: number; focus: number; xp?: number }[]; attributes?: Record<string, number>; [key: string]: unknown }
export interface PanelConfig { action_prices?: Record<string, unknown>; spawn_prices?: Record<string, unknown>; ui?: unknown; focus_tier_costs?: unknown[]; attribute_cost?: unknown; [key: string]: unknown }
export interface PowerOption { power_key: string; weapon_type?: string; label?: string; description?: string; skill?: string; skill_level?: number; rank?: number; value?: number; available?: boolean; reason?: string | null; price?: unknown }
export interface BattleStats { hp?: number; hp_max?: number; alive?: boolean; state?: string; order_status?: string; kills?: number; xp_earned?: number; gold_earned?: number; payout_version?: number; payout_status?: string; payout_estimate_min?: number; payout_estimate_max?: number; payout_participation?: number; payout_personal?: number; payout_retinue?: number; [key: string]: unknown }
export interface BattleReply { success: boolean; in_battle: boolean; is_siege?: boolean; participant_count?: number; my_stats?: BattleStats | null; last_payout?: BattleStats | null }
export interface BuildReply { success: boolean; enabled: boolean; has_hero: boolean; ready: boolean; pending: boolean; can_manage: boolean; reason?: string | null; message?: string | null; cooldown_remaining_s?: number; build?: { power_options?: PowerOption[]; common_powers?: PowerOption[]; selected_weapon_type?: string; selected_power?: string; is_mounted?: boolean; weapon_power_cooldown_until?: number; version?: number; specialization?: string; starter_claimed?: boolean; in_battle?: boolean; specializations?: { id: string; label: string; description: string }[]; starter_kits?: { id: string; label: string; items?: { item_id: string; name?: string }[]; available: boolean; reason?: string | null }[]; [key: string]: unknown }; [key: string]: unknown }
export interface ClassesReply { success: boolean; current_powers?: PowerOption[]; classes: { class_key: string; name: string; description?: string; [key: string]: unknown }[]; current: null | { class_key: string; class_level?: number; primary_skill?: string; primary_skill_level?: number; next_threshold?: number | null }; [key: string]: unknown }
export interface BuffsReply { success: boolean; buffs: { power_key: string; remaining_s: number }[]; cooldowns: { power_key: string; remaining_s: number }[] }
export interface ActionReply { action_id?: string; success: boolean; message?: string; cooldown_applied_s?: number; cooldown_remaining_s?: number; required_role?: string; [key: string]: unknown }
export interface ActionOptions { quietCooldown?: boolean; buildFamily?: boolean; cooldownKey?: string; tail: 'hero' | 'balance'; immediateHero?: boolean; successMessage?: string }
export interface PanelState { forgeEquipment: ForgeObservation | null; diplomacy: DiplomacyReply | null; partyOrders: PartyOrdersReply | null; refundNotices: { id: string; message: string }[]; battle: BattleReply | null; buffs: Record<string, number>; buffsReady: boolean; points: number | null; newBuild: boolean; buildBusy: boolean; buildCooldownUntil: number; optimisticStance: string | null; hero: HeroReply | null; config: PanelConfig | null; build: BuildReply | null; classes: ClassesReply | null; loading: boolean; canAct: boolean; mutationBlocked: boolean; message: string; error: string; errors: Record<string, string>; buildPending: boolean; busy: readonly string[]; cooldowns: Record<string, number>; now: number; generation: number }
export interface PanelTransport { mutationBlock?(): string | null; read<T>(path: string, signal?: AbortSignal): Promise<T>; action(type: string, data: Record<string, unknown>): Promise<ActionReply | null> }
export const validPrice = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
export const heroContext = (data: HeroReply | null) => JSON.stringify([data?.has_hero, data?.hero?.hero_id, data?.hero?.iteration, data?.hero?.adopted_at]);
export const actionKey = (type: string, data: Record<string, unknown>) => type + ':' + Object.keys(data).sort().filter(key => key !== 'client_action_id').map(key => key + '=' + String(data[key])).join('&');

// These five positions reflect the inherited UI cap, not a newly invented price table.
export const hasProgressionPrices = (config: PanelConfig | null) => validPrice(config?.attribute_cost) && Array.isArray(config?.focus_tier_costs) && config.focus_tier_costs.length >= 5 && config.focus_tier_costs.slice(0, 5).every(validPrice);

export class UnknownActionOutcomeError extends Error {
  constructor() { super('Исход предыдущей заявки неизвестен: она могла дойти до сервера. Новые действия этой личности заблокированы в этой открытой панели. Обновление данных доступно; не повторяйте покупку вслепую.'); }
}
