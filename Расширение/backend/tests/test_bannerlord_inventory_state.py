"""Native baggage state, legacy clients, captivity and snapshot identity (real DB)."""
import asyncio
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'inventory.db'))
        try:
            from modules.bannerlord.equipment_shop import store_inventory, context, validate_tx
            from modules._base import ModuleEnvelope
            from routes import bannerlord as route
            from migrations import m127_bannerlord_inventory_state
            async with db._connect() as conn:
                await m127_bannerlord_inventory_state.apply(conn)
                await m127_bannerlord_inventory_state.apply(conn)
            import module_liveness
            async def live(*args):
                return False
            module_liveness.is_on_air = live
            route.require_jwt_user = lambda request: ('alice', CHANNEL_ID)
            async with db._connect() as conn:
                await conn.execute("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save')", (CHANNEL_ID,))
                await conn.execute("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session',1)", (CHANNEL_ID,))
                await conn.commit()
            response = await route.bannerlord_equipment_shop(_make_anon_request())
            assert response['reason'] == 'offline', 'Offline must not promise active synchronization'
            assert response['ready'] is False
            items = [dict(owned_id='body', item_id='armor', slot='body', source='equipped'),
                     dict(owned_id='party|sword|', item_id='sword', slot=None, source='party')]
            async def publish(seq, state=None, **extra):
                data = dict(username='alice', hero_id='test_hero_alice', save_id='save', equipment_session_id='session',
                            inventory_seq=seq, items=items, inventory_state=state, **extra)
                await store_inventory(db, CHANNEL_ID, ModuleEnvelope(id='snapshot', kind='event', type='hero.inventory_snapshot', ts=seq, data=data))
            async def ctx():
                async with db._connect() as conn:
                    return await context(conn, CHANNEL_ID, 'alice', require_party=True)
            # Legacy snapshots cannot establish ownership of a native party inventory.
            await publish(1)
            value = await ctx()
            assert value['party_inventory']['available'] is False
            assert value['reason'] == 'inventory_state_unknown'
            async with db._connect() as conn:
                assert (await context(conn, CHANNEL_ID, 'alice'))['reason'] is None, 'Baggage restrictions must not disable independent hero builds'
            assert all(x.get('source') != 'party' for x in value['inventory'])
            await publish(2, dict(party_available=False, party_reason='hero_prisoner'))
            value = await ctx()
            assert value['reason'] == 'hero_prisoner' and value['ready']
            assert len(value['inventory']) == 1, 'Captive snapshot must not expose party goods even from an old sender'
            async with db._connect() as conn:
                for kind in ('hero.buy_equipment', 'hero.equip_owned', 'hero.unequip_owned', 'hero.discard_owned'):
                    denied = await validate_tx(conn, CHANNEL_ID, 'alice', kind, {'owned_id':'body', 'slot':'body', 'party_available':True})
                    assert denied['reason'] == 'hero_prisoner', (kind, denied)
            await publish(3, dict(party_available=False, party_reason='no_party_inventory'))
            assert (await ctx())['reason'] == 'no_party_inventory'
            await publish(4, dict(party_available=True, party_id='own-party', party_name='Own party'))
            value = await ctx()
            assert value['reason'] is None and len(value['inventory']) == 2
            assert value['party_inventory']['party_id'] == 'own-party'
            # Out-of-order metadata may not turn an available roster into captivity.
            await publish(3, dict(party_available=False, party_reason='hero_prisoner'))
            assert (await ctx())['party_inventory']['available'] is True
            # Hero heartbeat may learn of capture before the next inventory snapshot.
            async with db._connect() as conn:
                await conn.execute("UPDATE bannerlord_heroes SET is_prisoner=1 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
                await conn.commit()
            value = await ctx()
            assert value['reason'] == 'hero_prisoner'
            assert len(value['inventory']) == 1
            print('PASS native inventory state: offline, legacy, captive, no party, ordered metadata, hostile actions')
        finally:
            await db._pool.close()


if __name__ == '__main__':
    asyncio.run(main())
