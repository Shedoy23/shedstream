"""Behavioral contract: game-owned content, session freshness and exact IDs."""
import asyncio
import json
import os
import tempfile
from pathlib import Path

from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID, _set_points, _get_points


async def run(db):
    from routes import bannerlord as route
    from modules.bannerlord._adapter import BannerlordAdapter
    from modules._base import ModuleEnvelope
    adapter = BannerlordAdapter(None)
    async def sql(statement, args=()):
        async with db._connect() as conn:
            cur = await conn.execute(statement, args)
            rows = await cur.fetchall()
            await conn.commit()
            return rows
    async def publish(kind='cultures', seq=1, entries=None, channel=CHANNEL_ID, **changes):
        data = dict(catalog=kind, catalog_seq=seq, entries=entries if entries is not None else [
            dict(id='Mod.Culture-X', name='Mod culture', description='From loaded game', available=True),
            dict(id='NoTemplate', name='Unavailable', available=False, unavailable_reason='no_template')],
            save_id='save-a', equipment_session_id='session-a')
        data.update(changes)
        await adapter._on_catalog_update(channel, ModuleEnvelope(id='catalog', kind='event',
            type='module.catalog_update', ts=100, data=data))
    await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')", (CHANNEL_ID,))
    await publish()  # Early publication cannot stick before session registration.
    assert not await sql('SELECT 1 FROM bannerlord_content_catalogs')
    await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)", (CHANNEL_ID,))
    await publish()
    data = {'culture': 'Mod.Culture-X', 'save_id': 'evil', 'equipment_session_id': 'evil'}
    refusal = await route._prepare_action('carol', CHANNEL_ID, 'hero.create', data)
    assert refusal is None, ('runtime mod culture rejected', refusal)
    assert data['culture'] == 'Mod.Culture-X', ('opaque ID modified', data)
    assert data['save_id'] == 'save-a' and data['equipment_session_id'] == 'session-a'
    assert data['content_catalog_seq'] == 1
    route.require_jwt_user = lambda request: ('carol', CHANNEL_ID)
    request = _make_anon_request()
    state = await route.bannerlord_content_catalogs(request)
    # 03.10: the panel gets only cultures the game can create; the hidden one is still refused below.
    assert state['cultures']['available'] and [c['id'] for c in state['cultures']['entries']] == ['Mod.Culture-X'], state
    for value, reason in [('mod.culture-x', 'culture_not_found'), ('NoTemplate', 'culture_unavailable')]:
        result = await route._prepare_action('carol', CHANNEL_ID, 'hero.create', {'culture': value})
        assert result['reason'] == reason, result
    await publish(seq=2, entries=[])
    await publish(seq=1)  # out-of-order cannot resurrect removed choices
    state = await route.bannerlord_content_catalogs(request)
    assert state['cultures']['available'] and state['cultures']['entries'] == [], state
    await publish(seq=3, save_id='wrong-save')
    await publish(seq=3, equipment_session_id='old-session')
    await publish(seq=3, channel=123)
    await publish(seq=True)  # bool is not a sequence number
    await publish(seq=3, entries=[{'id': 'partial'}, {'id': ''}])
    assert (await route.bannerlord_content_catalogs(request))['cultures']['entries'] == []
    # 03.10: workshop types come from the game too (the old panel hard-coded ten ids).
    for kind in ('policies', 'skills', 'attributes', 'workshop_types'):
        await publish(kind=kind, entries=[dict(id='Custom.ID', name='Localized', description='Metadata')])
        assert (await route.bannerlord_content_catalogs(request))[kind]['entries'][0]['id'] == 'Custom.ID'
    # A disabled culture must be revalidated before charge, even in the same session.
    await _set_points(db, CHANNEL_ID, 'carol', 2000)
    before = await _get_points(db, CHANNEL_ID, 'carol')
    await publish(seq=3)
    disabled = {'culture': 'Mod.Culture-X'}
    assert await route._prepare_action('carol', CHANNEL_ID, 'hero.create', disabled) is None
    await publish(seq=4, entries=[dict(id='Mod.Culture-X', available=False)])
    result = await route._charge_execute_enqueue('hero.create', disabled, 500, 'carol', CHANNEL_ID)
    assert result['reason'] == 'culture_unavailable', result
    assert await _get_points(db, CHANNEL_ID, 'carol') == before
    assert not await sql("SELECT 1 FROM module_actions WHERE channel_id=? AND type='hero.create'", (CHANNEL_ID,))
    # Race: prepare while valid, switch session before atomic enqueue.
    await publish(seq=5)
    prepared = {'culture': 'Mod.Culture-X'}
    assert await route._prepare_action('carol', CHANNEL_ID, 'hero.create', prepared) is None
    await sql("UPDATE bannerlord_equipment_sessions SET session_id='session-b' WHERE channel_id=?", (CHANNEL_ID,))
    result = await route._charge_execute_enqueue('hero.create', prepared, 500, 'carol', CHANNEL_ID)
    assert result['reason'] == 'content_catalog_not_ready', result
    assert await _get_points(db, CHANNEL_ID, 'carol') == before
    assert not await sql("SELECT 1 FROM module_actions WHERE channel_id=? AND type='hero.create'", (CHANNEL_ID,))
    state = await route.bannerlord_content_catalogs(request)
    assert all(not state[k]['available'] for k in ('cultures', 'policies', 'skills', 'attributes', 'workshop_types'))
    # A new nonce may restart sequence at 1; old nonce cannot overwrite it.
    await publish(seq=1, equipment_session_id='session-b')
    await publish(seq=100, entries=[], equipment_session_id='session-a')
    assert len((await route.bannerlord_content_catalogs(request))['cultures']['entries']) == 1
    # The displayed session must not silently retarget the same culture ID in a newer session.
    stale = {'culture': 'Mod.Culture-X', 'content_context': dict(save_id='save-a', equipment_session_id='session-a')}
    result = await route._prepare_action('carol', CHANNEL_ID, 'hero.create', stale)
    assert result and result['reason'] == 'content_catalog_changed', result
    current = {'culture': 'Mod.Culture-X', 'content_context': dict(save_id='save-a', equipment_session_id='session-b')}
    assert await route._prepare_action('carol', CHANNEL_ID, 'hero.create', current) is None
    assert 'content_context' not in current and current['equipment_session_id'] == 'session-b'
    result = await route._bannerlord_buy_action_locked(request, 'carol', CHANNEL_ID, 'hero.create', {'culture':'Mod.Culture-X'})
    assert result['success'], result
    payload = json.loads((await sql("SELECT data FROM module_actions WHERE action_id=?", (result['action_id'],)))[0][0])
    assert payload['culture'] == 'Mod.Culture-X' and payload['equipment_session_id'] == 'session-b'
    assert payload['content_catalog_seq'] == 1
    # Missing metadata never exposes the other tenant. Random is old-mod-compatible.
    route.require_jwt_user = lambda request: ('carol', 123)
    assert not (await route.bannerlord_content_catalogs(request))['cultures']['available']
    random = {'culture':'', 'save_id':'spoof', 'equipment_session_id':'spoof', 'content_catalog_seq':99}
    assert await route._prepare_action('carol', 123, 'hero.create', random) is None
    assert not any(k in random for k in ('save_id', 'equipment_session_id', 'content_catalog_seq'))
    route.require_jwt_user = lambda request: None
    assert not (await route.bannerlord_content_catalogs(request))['success']
    print('PASS content catalogs: exact IDs, full/empty, ordering, tenant/session, atomic create, auth')


async def equipment(db):
    from modules.bannerlord.equipment_shop import store_catalog, catalog
    from types import SimpleNamespace
    async with db._connect() as conn:
        await conn.execute("INSERT OR REPLACE INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'eq-save')", (CHANNEL_ID,))
        await conn.execute("INSERT OR REPLACE INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'eq-session',1)", (CHANNEL_ID,))
        await conn.commit()
    await store_catalog(db, CHANNEL_ID, SimpleNamespace(data=dict(save_id='eq-save', equipment_session_id='eq-session', entries=[
        dict(item_id='game-item', tier=4, price_gold=1000, required_level=12),
        dict(item_id='legacy-item', tier=4, price_gold=1000),
    ])))
    async with db._connect() as conn:
        items = {x['item_id']:x for x in await catalog(conn, CHANNEL_ID)}
    assert items['game-item']['required_level'] == 12, ('game requirement overwritten', items)
    assert items['legacy-item']['required_level'] == 25, 'legacy fallback must remain compatible'
    print('PASS equipment: preserve game required_level, retain legacy fallback')


async def opaque_state_ids(db):
    from routes import bannerlord as route
    from modules.bannerlord._adapter import BannerlordAdapter
    from modules._base import ModuleEnvelope
    async with db._connect() as conn:
        await conn.execute('INSERT INTO bannerlord_attributes(channel_id,username,attribute,value) VALUES(?,?,?,?)',
                           (CHANNEL_ID, 'alice', 'ArcanePower', 7))
        await conn.commit()
    route.require_jwt_user = lambda request: ('alice', CHANNEL_ID)
    hero = await route.bannerlord_my_hero(_make_anon_request())
    assert hero['attributes'].get('ArcanePower') == 7, ('game attribute ID modified', hero['attributes'])
    await BannerlordAdapter(None)._on_skill_changed(CHANNEL_ID, ModuleEnvelope(
        id='skill', kind='event', type='hero.skill_changed', ts=100,
        data=dict(username='alice', skill_key='ArcaneSkill', level=12)))
    hero = await route.bannerlord_my_hero(_make_anon_request())
    assert any(s['skill_key'] == 'ArcaneSkill' for s in hero['skills']), ('game skill ID modified', hero['skills'])
    print('PASS opaque game state identifiers')


async def short_policy_ids(db):
    from routes.bannerlord_diplomacy import handle_enact_policy
    async with db._connect() as conn:
        await conn.execute("UPDATE bannerlord_heroes SET kingdom_id='mod-kingdom',is_king=1 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
        for key in ('x', 'p1', ' Mod.Policy '):
            result = await handle_enact_policy(conn, CHANNEL_ID, 'alice', {'policy_id': key})
            assert result['success'], ('runtime policy rejected', key, result)
            row = await (await conn.execute("SELECT data FROM module_actions WHERE channel_id=? AND type='hero.enact_policy' ORDER BY rowid DESC LIMIT 1", (CHANNEL_ID,))).fetchone()
            assert json.loads(row[0])['policy_id'] == key, ('policy ID changed', row)
        for key in (None, '', '   ', 7, ['x'], 'x' * 257):
            result = await handle_enact_policy(conn, CHANNEL_ID, 'alice', {'policy_id': key})
            assert not result['success'], ('invalid policy accepted', key)
        await conn.rollback()
    print('PASS short/opaque policy IDs; invalid inputs refused')


async def main():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['DB_PATH'] = str(Path(tmp) / 'import.db')
        db = await _build_db(str(Path(tmp) / 'catalogs.db'))
        try:
            for check in (run, equipment, opaque_state_ids, short_policy_ids):
                try:
                    await check(db)
                except Exception as error:
                    failures.append(f'{check.__name__}: {type(error).__name__}: {error}')
        finally:
            await db._pool.close()
    assert not failures, '\n'.join(failures)


if __name__ == '__main__':
    asyncio.run(main())
