"""Buy-and-equip quotes are save-bound, server-priced and slot-specific."""
import asyncio
import json
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'shop.db'))
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
            await sql("UPDATE bannerlord_heroes SET level=30,gold=500 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            def env(data):
                return ModuleEnvelope(id='test', kind='event', type='hero.inventory_snapshot', ts=1,
                    data=dict(save_id='save', equipment_session_id='session', **data))
            await store_catalog(db, CHANNEL_ID, env(dict(entries=[dict(item_id='sword', tier=1, price_gold=1000, slots=['weapon0', 'weapon1'])])))
            state = dict(party_available=False, party_reason='no_party_inventory', buy_equip_available=True, in_mission=False)
            item = dict(owned_id='old-id', item_id='old-sword', modifier_id='fine', name='Old sword', slot='weapon0', source='equipped', trade_in_gold=600)
            seq = 0
            async def publish():
                nonlocal seq
                seq += 1
                await store_inventory(db, CHANNEL_ID, env(dict(username='alice', hero_id='test_hero_alice', inventory_seq=seq, items=[item], inventory_state=state)))
            async def buy(**extra):
                data = dict(item_id='sword', equip_now=True, slot='weapon0', replace_owned_id='old-id', expected_trade_in_gold=600,
                            replace_item_id='old-sword', replace_modifier_id='fine', expected_price_gold=1000)
                data.update(extra)
                return await route._bannerlord_buy_action_locked(request, 'alice', CHANNEL_ID, 'hero.buy_equipment', data)
            await publish()
            response = await route.bannerlord_equipment_shop(request)
            assert response['can_manage'], response
            sword = response['items'][0]
            assert sword['can_buy'] and sword['purchase_mode'] == 'equip', sword
            options = sword['purchase_options']
            assert options[0]['net_price_gold'] == 400 and options[0]['can_buy'], options
            assert options[1]['reason'] == 'insufficient_gold', options
            assert (await buy(slot='head'))['reason'] == 'invalid_slot'
            assert (await buy(replace_owned_id='stale'))['reason'] == 'equipment_changed'
            assert (await buy(replace_item_id='other'))['reason'] == 'equipment_changed'
            assert (await buy(replace_modifier_id='other'))['reason'] == 'equipment_changed'
            assert (await buy(expected_price_gold=1))['reason'] == 'equipment_price_changed'
            assert (await buy(expected_trade_in_gold=99999))['reason'] == 'equipment_price_changed'
            assert (await buy(equip_now=False))['reason'] == 'purchase_slot_required'
            result = await buy(price_gold=1, trade_in_gold=99999, target='victim', expected_item_id='forged')
            assert result['success'], result
            payload = json.loads((await sql('SELECT data FROM module_actions WHERE action_id=?', (result['action_id'],)))[0][0])
            assert payload['price_gold'] == 1000 and payload['trade_in_gold'] == 600, payload
            assert payload['expected_item_id'] == 'old-sword' and payload['expected_modifier_id'] == 'fine'
            assert payload['target'] == 'alice' and payload['equip_now'] is True
            assert (await buy())['reason'] == 'pending'
            await sql("UPDATE module_actions SET status='done' WHERE channel_id=?", (CHANNEL_ID,))
            state['in_mission'] = True
            await publish()
            assert (await buy())['reason'] == 'in_mission'
            state['in_mission'] = False
            state['party_reason'] = 'hero_prisoner'
            await publish()
            assert (await buy())['reason'] == 'hero_prisoner'
            state['party_reason'] = 'no_party_inventory'
            state.pop('buy_equip_available')
            await publish()
            assert (await buy())['reason'] == 'no_party_inventory', 'Old mod must fail closed'
            state.update(party_available=True, party_reason=None, party_id='party')
            await publish()
            assert (await buy())['reason'] == 'inventory_state_changed'
            await sql("UPDATE bannerlord_heroes SET gold=2000 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            result = await buy(equip_now=False)
            assert result['success'], result
            payload = json.loads((await sql('SELECT data FROM module_actions WHERE action_id=?', (result['action_id'],)))[0][0])
            assert 'equip_now' not in payload and 'trade_in_gold' not in payload
            print('PASS no-party purchase: quotes, net funds, hostile payload, legacy mod, mission, captivity, party transition')
        finally:
            await db._pool.close()


if __name__ == '__main__':
    asyncio.run(main())
