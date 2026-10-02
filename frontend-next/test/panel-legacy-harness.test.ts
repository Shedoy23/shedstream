// @vitest-environment node
import { expect, it } from 'vitest';
import { createLegacyHarness, legacyResponses, legacySelectors } from './panel-legacy-harness';

it('executes actual old rendered progression click and all success follow-ups without unrelated hosts', async () => {
  const old = createLegacyHarness();
  try {
    await old.bootHero();
    expect(old.sourceFiles).toHaveLength(23);
    expect(old.trace.map(row => row.path)).toEqual([
      '/api/bannerlord/config', '/api/bannerlord/my-hero', '/api/bannerlord/classes',
      '/api/bannerlord/build', '/api/bannerlord/my-buffs',
    ]);
    expect(old.document.querySelectorAll('.bnr-prog-focus-btn')).toHaveLength(18);
    expect(old.document.querySelectorAll('.bnr-prog-attr-btn')).toHaveLength(6);
    expect(old.document.querySelector('#bnr-daily-slot')).toBeNull();
    old.trace.length = 0;
    await old.click(legacySelectors.focus('OneHanded'));
    expect(old.trace[0].body).toEqual({ action_type: 'hero.add_focus', data: {
      skill_key: 'OneHanded', amount: 1, client_action_id: expect.any(String),
    } });
    await old.advance(3500);
    expect(old.trace.map(row => `${row.method} ${row.path}${row.query}`)).toEqual([
      'POST /api/bannerlord/action', 'GET /api/bannerlord/my-hero', 'GET /api/viewer/stats/alice',
      'GET /api/user/level/alice', 'GET /api/duel/list', 'GET /api/bannerlord/my-hero', 'GET /api/bannerlord/build',
    ]);
  } finally { old.dispose(); }
});

it('real old build buttons and refusal DOM preserve server IDs/messages', async () => {
  const message = 'Новый неизвестный отказ сервера';
  const old = createLegacyHarness({ build: legacyResponses.build_ready, action: { success: false, message } });
  try {
    await old.bootHero();
    await old.click(legacySelectors.specialization('assault'));
    expect(old.trace.at(-1)?.body).toMatchObject({ action_type: 'hero.set_specialization', data: { specialization: 'assault' } });
    expect(old.document.querySelector(legacySelectors.notice)?.textContent).toContain(message);
  } finally { old.dispose(); }
});

it('fails unmatched routes even when old catch blocks swallow fetch errors', async () => {
  const old = createLegacyHarness();
  try {
    await old.bootHero();
    await old.window.fetch('/api/bannerlord/my-hero?unexpected=1').catch(() => undefined);
    await expect(old.settle()).rejects.toThrow('Unmatched legacy request: GET /api/bannerlord/my-hero?unexpected=1');
  } finally { old.dispose(); }
});

it('equipment-only old DOM captures the shared stats tail but no hero/build delayed tail', async () => {
  const old = createLegacyHarness({}, { scope: 'equipment' });
  try {
    await old.bootEquipment();
    expect(old.trace.map(row => row.path)).toEqual(['/api/bannerlord/equipment-shop']);
    await old.click('[data-bnr-eq-view="owned"]');
    await old.click('[data-bnr-eq-equip="party|sword|fine"]');
    await old.advance(3500);
    expect(old.trace.map(row => row.path)).toEqual([
      '/api/bannerlord/equipment-shop', '/api/bannerlord/action', '/api/viewer/stats/alice', '/api/user/level/alice', '/api/duel/list',
    ]);
    expect(old.trace[1].body).toMatchObject({ action_type: 'hero.equip_owned', data: { owned_id: 'party|sword|fine', slot: 'weapon0' } });
  } finally { old.dispose(); }
});

it('old equipment reset does not hide the reproduced stale discard confirmation defect', async () => {
  const old = createLegacyHarness({ action: { success: false, message: 'Тестовая запись запроса' } }, { scope: 'equipment' });
  try {
    await old.bootEquipment();
    await old.click('[data-bnr-eq-view="owned"]');
    await old.click('[data-bnr-eq-discard="party|sword|fine"]');
    expect(old.document.getElementById('confirm-dyn-modal')).not.toBeNull();
    await old.resetEquipment('carol', 'carol-token');
    await old.click('#confirm-dyn-yes');
    expect(old.trace.at(-1)?.token).toBe('carol-token');
    expect(old.trace.at(-1)?.body).toMatchObject({ action_type: 'hero.discard_owned', data: { owned_id: 'party|sword|fine' } });
  } finally { old.dispose(); }
});
