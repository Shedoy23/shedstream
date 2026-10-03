import { act, cleanup, fireEvent, render } from '@testing-library/preact';
import { afterEach, expect, it, vi } from 'vitest';
import { GuildsView } from '../src/common/GuildsView';
import { pair, flush, disposePairs } from './panel-shell-pair';
export const guildSkill = { skill_key: 'watch', name: 'Сила сообщества', description: 'Серверное описание', max_level: 3, cost_per_level: [12345, 23456, 34567], effect_per_level: [1, 2, 3] };
export const guildFixture = { guild_id: 29, name: 'Стражи', tagline: 'Вместе', master: 'alice', my_role: 'master', balance: 100000, member_count: 2, members: [{ username: 'alice', role: 'master' }, { username: 'bob', role: 'member' }], skills: { watch: 0 }, top_contributors: [{ username: 'alice', total: 4567 }] };
afterEach(() => { cleanup(); disposePairs(); vi.useRealTimers(); });
async function setup(member: false | 'master' | 'member' = false, refused = false) {
  let joined = Boolean(member); const guild = { ...guildFixture, my_role: member || 'master' };
  const p = await pair({
    'GET /api/guild/skills/config': { success: true, skills: [guildSkill] }, 'GET /api/guild/my': () => ({ success: true, in_guild: joined, ...(joined ? { guild } : {}) }),
    'GET /api/guild/list': { success: true, guilds: [guild] }, 'GET /api/guild/29': { success: true, guild },
    ...Object.fromEntries(['create', 'join', 'contribute', 'upgrade-skill', 'leave', 'disband'].map(action => ['POST /api/guild/' + action, () => { if (!refused) { if (action === 'create' || action === 'join') joined = true; if (action === 'leave' || action === 'disband') joined = false; } return { success: !refused, message: refused ? 'Новая причина отказа гильдии' : 'Готово на сервере' }; }])),
  });
  await p.old.click('[data-action="guilds"]'); document.dispatchEvent(new Event('click'));
  const ui = render(<GuildsView runtime={p.runtime} />); await act(flush); p.check();
  const click = async (old: string, label: string, confirm: 'added' | 'same' | false = false) => {
    await p.old.click(old); await act(async () => { ui.getByRole('button', { name: label, exact: true }).click(); await flush(); });
    if (confirm) { if (confirm === 'same') await p.old.click('#confirm-dyn-yes'); await act(async () => { ui.getByRole('button', { name: 'Подтвердить' }).click(); await flush(); }); }
  };
  const input = async (old: string, label: string, value: string) => { (p.old.document.querySelector(old) as HTMLInputElement).value = value; await act(async () => { fireEvent.input(ui.getByLabelText(label), { target: { value } }); }); };
  return { ...p, ui, click, input };
}
it('guild create preserves trimmed payload, personal balance and my-guild refresh including minute traffic', async () => {
  const p = await setup(); await p.input('#guild-create-name', 'Название гильдии', ' Стражи '); await p.input('#guild-create-tagline', 'Девиз', ' Вместе ');
  await p.click('#guild-create-btn', 'Создать за 1300 💎', 'added'); p.check(); await act(async () => { await p.advance(60000); }); p.check({ extraConfirmationClicks: 1 });
});
it('guild browse detail back and join keep guild IDs and every original read', async () => {
  const p = await setup(); await p.click('[data-guild-row="29"]', 'Открыть Стражи'); p.check(); expect(p.ui.getByText('@bob · member')).toBeTruthy();
  await p.click('#guild-back-btn', 'Назад'); p.check(); await p.click('[data-guild-row="29"]', 'Открыть Стражи'); await p.click('#guild-join-btn', 'Вступить'); p.check();
});
it('guild contribution sends the confirmed integer and preserves both refresh branches', async () => {
  const p = await setup('member'); await p.input('#guild-contrib-amt', 'Сумма вклада', '1234'); await p.click('#guild-contrib-btn', 'Внести', 'added'); p.check();
});
it('guild upgrade uses the actual configured skill key and guild refresh without personal stats', async () => {
  const p = await setup('master'); await p.click('[data-upgrade-skill="watch"]', 'Прокачать Сила сообщества за 12345 💎', 'added'); p.check();
});
for (const action of ['leave', 'disband'] as const) it(`guild ${action} keeps its confirmation and POST with no body`, async () => {
  const p = await setup(action === 'leave' ? 'member' : 'master'); await p.click('#guild-' + action + '-btn', action === 'leave' ? 'Покинуть гильдию' : 'Расформировать гильдию', 'same'); p.check();
  expect(p.trace.find(q => q.path === '/api/guild/' + action)?.rawBody).toBeNull();
});
it('guild unknown server refusal is shown without success-only follow-up reads', async () => {
  const p = await setup('master', true); await p.click('[data-upgrade-skill="watch"]', 'Прокачать Сила сообщества за 12345 💎', 'added'); p.check(); expect(p.ui.getByRole('status').textContent).toContain('Новая причина отказа гильдии');
});
it('guild confirmation cancellation sends no write', async () => {
  const p = await setup('master'); const before = p.trace.length;
  await act(async () => { p.ui.getByRole('button', { name: 'Прокачать Сила сообщества за 12345 💎' }).click(); });
  await act(async () => { p.ui.getByRole('button', { name: 'Отмена' }).click(); }); expect(p.trace).toHaveLength(before);
});
it('guild reopening retains the public skill cache and refreshes my guild just like the original shell', async () => {
  const p = await setup('member'); p.ui.unmount(); await p.old.click('#guilds-modal [data-action="close-modal"]'); document.dispatchEvent(new Event('click'));
  await p.old.click('[data-action="guilds"]'); document.dispatchEvent(new Event('click')); render(<GuildsView runtime={p.runtime} />); await act(flush); p.check();
  expect(p.trace.filter(q => q.path === '/api/guild/skills/config')).toHaveLength(1);
});
