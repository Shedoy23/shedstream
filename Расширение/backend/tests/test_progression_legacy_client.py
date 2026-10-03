"""02.10: панель 0.0.5 (заморожена на CDN Twitch) покупает прокачку без контекста и котировок.

Новый путь прокачки (0.0.6) требует progression_context и котировку из снимка игры. Панель
0.0.5 шлёт ровно {skill_key, amount:1} / {attribute_key, amount:1} / {price} — и без этой
совместимости все три кнопки у зрителей закрылись бы до следующего релиза. Сервер обязан:
  1. принять старые запросы, подставив контекст и котировку из снимка игры;
  2. передать моду ту же котировку, что и новой панели (мод сверяет её с игрой);
  3. по-прежнему отказывать НОВОЙ панели с устаревшим контекстом;
  4. отказывать старой панели там же, где и новой (опция недоступна, опыт недоступен).

Запуск:  python tests/test_progression_legacy_client.py
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID


async def run(db):
    from routes import bannerlord as route
    from modules.bannerlord.equipment_shop import store_inventory
    from modules._base import ModuleEnvelope
    from modules.bannerlord._adapter import _cooldowns

    async def sql(q, args=()):
        async with db._connect() as conn:
            rows = await (await conn.execute(q, args)).fetchall()
            await conn.commit()
            return rows

    context = dict(save_id='save-a', equipment_session_id='session-a', hero_id='test_hero_alice')
    progression = dict(version=1, random_xp_available=True, random_xp_reason=None,
        skills=[dict(id='Mod.Skill', level=120, focus=2, focus_limit=9, native_focus_limit=11, xp_available=True,
            focus_options=[dict(amount=1, cost_gold=7, available=True)])],
        attributes=[dict(id='Mod.Attribute', value=4, limit=18, native_limit=20,
            options=[dict(amount=1, cost_gold=9, available=True)])])
    seq = 0

    async def publish():
        nonlocal seq
        seq += 1
        payload = dict(username='alice', inventory_seq=seq, items=[], build=None, progression=progression, **context)
        await store_inventory(db, CHANNEL_ID, ModuleEnvelope(id='snapshot', kind='event',
                                                             type='hero.inventory_snapshot', ts=seq, data=payload))

    async def buy(kind, **data):
        _cooldowns.clear()
        return await route._bannerlord_buy_action_locked(_make_anon_request(), 'alice', CHANNEL_ID, kind, data)

    async def queued(result):
        row = (await sql('SELECT data FROM module_actions WHERE action_id=?', (result['action_id'],)))[0][0]
        await sql("UPDATE module_actions SET status='acked'")
        return json.loads(row)

    await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')", (CHANNEL_ID,))
    await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)", (CHANNEL_ID,))
    await publish()

    # 1-2. Фокус как шлёт 0.0.5: котировка подставлена из снимка, мод получит её же.
    r = await buy('hero.add_focus', skill_key='Mod.Skill', amount=1)
    assert r.get('success'), ('0.0.5 focus purchase refused', r)
    out = await queued(r)
    assert out['expected_cost_gold'] == 7 and out['expected_value'] == 2, out
    assert out['hero_id'] == context['hero_id'] and out['save_id'] == 'save-a', out
    print('OK   0.0.5: фокус {skill_key, amount} принят, мод получит котировку 7💰 при фокусе 2')

    r = await buy('hero.add_attribute', attribute_key='Mod.Attribute', amount=1)
    assert r.get('success'), ('0.0.5 attribute purchase refused', r)
    out = await queued(r)
    assert out['expected_cost_gold'] == 9 and out['expected_value'] == 4, out
    print('OK   0.0.5: атрибут {attribute_key, amount} принят, котировка 9💰 при значении 4')

    # 02.10, найдено пробой в игре: 0.0.5 шлёт 'Vigor' из своего списка, игра называет 'vigor'.
    progression['attributes'].append(dict(id='vigor', value=4, limit=10, native_limit=10,
                                          options=[dict(amount=1, cost_gold=50000, available=True)]))
    await publish()
    r = await buy('hero.add_attribute', attribute_key='Vigor', amount=1)
    assert r.get('success'), ('0.0.5 sends Vigor, game calls it vigor - refused', r)
    out = await queued(r)
    assert out['attribute_key'] == 'vigor' and out['expected_cost_gold'] == 50000 and out['expected_value'] == 4, out
    print("OK   0.0.5: атрибут 'Vigor' из панели найден как 'vigor' игры, в мод уходит id игры")
    r = await buy('hero.add_attribute', attribute_key='Vigor', amount=1, progression_context=dict(context),
                  expected_cost_gold=50000, expected_value=4)
    assert r.get('reason') == 'progression_option_not_found', r
    print('OK   новая панель с неверным регистром id — по-прежнему отказ (точное сравнение)')

    r = await buy('hero.add_skill', price=500)
    assert r.get('success'), ('0.0.5 random XP purchase refused', r)
    out = await queued(r)
    assert out['skill_key'] == '' and out['xp'] > 0, out
    print('OK   0.0.5: опыт {price} принят, навык выберет мод')

    # 3. Новая панель с устаревшим контекстом — по-прежнему отказ (защита не ослабла).
    r = await buy('hero.add_focus', skill_key='Mod.Skill', amount=1, expected_cost_gold=7, expected_value=2,
                  progression_context={**context, 'hero_id': 'other'})
    assert r.get('reason') == 'progression_changed', r
    print('OK   новая панель с чужим контекстом — отказ progression_changed')

    # 4. Старая панель упирается в те же отказы, что и новая.
    progression['skills'][0]['focus_options'][0].update(available=False, reason='custom_blocked')
    progression['random_xp_available'] = False
    progression['random_xp_reason'] = 'skill_learning_unavailable'
    await publish()
    r = await buy('hero.add_focus', skill_key='Mod.Skill', amount=1)
    assert r.get('reason') == 'custom_blocked', r
    r = await buy('hero.add_skill', price=500)
    assert r.get('reason') == 'skill_learning_unavailable', r
    print('OK   0.0.5: недоступная опция и недоступный опыт — те же отказы, что у новой панели')


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'legacy.db'))
        try:
            await run(db)
        finally:
            await db._pool.close()
    print('\nALL OK')


if __name__ == '__main__':
    asyncio.run(main())
