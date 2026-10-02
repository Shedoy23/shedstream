import saved from './panel-fixtures/forge-tournament-responses.json';
import { combatPair } from './panel-combat-support';
import type { LegacyFixtures, LegacyJson, LegacyRequest } from './panel-legacy-harness';
export { toggle, posts, normalized } from './panel-party-support';
export { flush } from './panel-combat-support';
export const r = saved.responses;
const action = (q: LegacyRequest): LegacyJson => {
  const b = q.body as { action_type: string; data: { slot: string } };
  const row = (r as unknown as Record<string, { response: LegacyJson }>)['reforge_slot_' + b.data.slot];
  if (b.action_type !== 'hero.reforge_quality' || !row) throw new Error('Unknown forge request ' + JSON.stringify(b));
  return row.response;
};
export const forgePair = (overrides: Partial<LegacyFixtures> = {}, tab: 'hero' | 'inventory' | 'combat' = 'inventory') => combatPair({ config: r.config, hero: r.hero_forge, equipment: r.equipment_forge, action, ...overrides }, false, tab, false, false, { forgeHost: true });
