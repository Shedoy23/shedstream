"""Личный сундук героя без своего отряда (25.09.2026, решение владельца).

Панель заморожена на ревью Twitch, поэтому сундук обязан работать через её
существующие кнопки: бэкенд показывает сундук как доступный багаж, но в заявку
мода уходит настоящий источник вещи. Здесь проверяется, что кнопки открыты,
10 мест держатся на бэкенде, покупка идёт в сундук (а не в слот с продажей
перекованной вещи), а старый мод без сундука ведёт себя по-прежнему.
"""
import asyncio
import json
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'stash.db'))
        try:
            from modules.bannerlord.equipment_shop import store_inventory, store_catalog
            from modules._base import ModuleEnvelope
            from routes import bannerlord as route
            import module_liveness
            async def live(*args): return True
            module_liveness.is_on_air = live
            route.require_jwt_user = lambda req: ('alice', CHANNEL_ID)
            request = _make_anon_request()
            async def sql(query, args=()):
                async with db._connect() as conn:
                    cur = await conn.execute(query, args)
                    rows = await cur.fetchall()
                    await conn.commit()
                    return rows
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save')", (CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session',1)", (CHANNEL_ID,))
            await sql("UPDATE bannerlord_heroes SET level=30,gold=5000 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            def env(data):
                return ModuleEnvelope(id='test', kind='event', type='hero.inventory_snapshot', ts=1,
                    data=dict(save_id='save', equipment_session_id='session', **data))
            await store_catalog(db, CHANNEL_ID, env(dict(entries=[dict(item_id='axe', tier=1, price_gold=300, slots=['weapon0', 'weapon1'])])))
            state = dict(party_available=False, party_reason='no_party_inventory', buy_equip_available=True,
                         in_mission=False, stash_available=True, stash_count=1, stash_capacity=10)
            worn = dict(owned_id='worn', item_id='sword', modifier_id='legendary_sword', name='Sword',
                        slot='weapon0', source='equipped', slots=['weapon0', 'weapon1'], trade_in_gold=900)
            stored = dict(owned_id='st1', item_id='mace', modifier_id='legendary_mace', name='Mace',
                          slot=None, source='legacy', slots=['weapon0', 'weapon1'])
            seq = 0
            async def publish():
                nonlocal seq
                seq += 1
                await store_inventory(db, CHANNEL_ID, env(dict(username='alice', hero_id='test_hero_alice',
                    inventory_seq=seq, items=[worn, stored], inventory_state=state)))
            async def act(action, **data):
                return await route._bannerlord_buy_action_locked(request, 'alice', CHANNEL_ID, action, data)
            async def payload(result):
                return json.loads((await sql('SELECT data FROM module_actions WHERE action_id=?', (result['action_id'],)))[0][0])
            async def settle():
                await sql("UPDATE module_actions SET status='done' WHERE channel_id=?", (CHANNEL_ID,))

            await publish()
            shop = await route.bannerlord_equipment_shop(request)
            party = shop['party_inventory']
            assert shop['can_manage'] and party['available'] is True, shop
            assert party['party_name'] == 'Личный сундук героя (1/10)', party
            assert shop['items'][0]['purchase_mode'] == 'inventory' and shop['items'][0]['can_buy'], shop['items'][0]
            shown = next(x for x in shop['inventory'] if x['owned_id'] == 'st1')
            assert shown['source'] == 'party', 'frozen panel lists stash under the baggage buttons'

            result = await act('hero.buy_equipment', item_id='axe', price_gold=1)
            assert result['success'], result
            sent = await payload(result)
            assert sent['price_gold'] == 300 and 'equip_now' not in sent, sent
            await settle()

            result = await act('hero.unequip_owned', slot='weapon0')
            assert result['success'], result
            await settle()

            result = await act('hero.equip_owned', owned_id='st1', slot='weapon1', source='party')
            assert result['success'], result
            sent = await payload(result)
            assert sent['source'] == 'legacy', 'mod must get the real source, not the panel label'
            await settle()

            result = await act('hero.discard_owned', owned_id='st1')
            assert result['success'], result
            await settle()

            state['stash_count'] = 10
            await publish()
            shop = await route.bannerlord_equipment_shop(request)
            assert shop['party_inventory']['party_name'] == 'Личный сундук героя (10/10)'
            assert shop['items'][0]['reason'] == 'stash_full', shop['items'][0]
            assert (await act('hero.buy_equipment', item_id='axe'))['reason'] == 'stash_full'
            assert (await act('hero.unequip_owned', slot='weapon0'))['reason'] == 'stash_full'
            result = await act('hero.equip_owned', owned_id='st1', slot='weapon0')
            assert result['success'], 'swap from a full stash frees a place — allowed'
            await settle()

            state.pop('stash_available')
            await publish()
            shop = await route.bannerlord_equipment_shop(request)
            assert shop['party_inventory']['available'] is False and shop['items'][0]['purchase_mode'] == 'equip', \
                'old mod without stash keeps the 21.09 buy-and-wear behaviour'
            assert (await act('hero.unequip_owned', slot='weapon0'))['reason'] == 'no_party_inventory'
            print('PASS personal stash: frozen panel buttons, real source to mod, 10 places, purchase to stash, old mod unchanged')
        finally:
            await db._pool.close()


if __name__ == '__main__':
    asyncio.run(main())
