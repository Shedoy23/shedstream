"""Real SQLite, full migrations and real cash register: equipment safety contract."""
import asyncio
import json
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'equipment.db'))
        try:
            from routes import bannerlord as route
            from modules.bannerlord.equipment_shop import store_catalog, store_inventory, context
            from modules._base import ModuleEnvelope
            from modules.bannerlord._adapter import BannerlordAdapter
            request = _make_anon_request()
            async def buy(kind='hero.buy_equipment', user='alice', channel=CHANNEL_ID, **data):
                return await route._bannerlord_buy_action_locked(request, user, channel, kind, data)
            async def sql(statement, args=()):
                async with db._connect() as conn:
                    cur = await conn.execute(statement, args)
                    rows = await cur.fetchall()
                    await conn.commit()
                    return rows
            def envelope(data, ts=100):
                data = {'equipment_session_id':'session-a', **data, 'inventory_seq': ts}
                return ModuleEnvelope(id='test', kind='event', type='hero.inventory_snapshot', ts=ts, data=data)
            def inventory(items, **changes):
                return {'username':'alice','save_id':'save-a','hero_id':'test_hero_alice','items':items,
                        'inventory_state': {'party_available':True, 'party_id':'alice-party'}, **changes}
            async def finish():
                await sql("UPDATE module_actions SET status='done' WHERE module_id='bannerlord'")
            result = await buy(item_id='sword', price=-500)
            assert result.get('reason') == 'inventory_not_ready', result
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')", (CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)",(CHANNEL_ID,))
            sword = {'id':'sword','item_id':'sword','name':'Sword','tier':4,'required_level':1,'price_gold':1000,'category':'one_handed','slots':['weapon0'],'stats':{}}
            five = {**sword,'id':'tier5','item_id':'tier5','tier':5}
            await store_catalog(db, CHANNEL_ID, envelope({'save_id':'save-a','entries':[sword,five]}))
            owned = {'owned_id':'party|sword|fine','item_id':'sword','name':'Sword','tier':4,'slot':None,'slots':['weapon0'],'modifier_id':'fine','source':'party','count':2}
            adapter=BannerlordAdapter(None)
            await adapter.handle_event(CHANNEL_ID,envelope(inventory([owned])))
            await adapter._on_catalog_update(CHANNEL_ID,envelope({'catalog':'equipment','save_id':'save-a','entries':[sword,five]}))
            await sql("UPDATE bannerlord_heroes SET level=24 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            assert (await buy(item_id='sword', required_level=0, tier=1, price_gold=0))['reason']=='level_locked'
            await sql("UPDATE bannerlord_heroes SET level=25 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            assert (await buy(item_id='does-not-exist'))['reason']=='item_not_found'
            assert (await buy(kind='hero.equip_owned', owned_id='victim-item', slot='weapon0'))['reason']=='not_owned'
            assert (await buy(kind='hero.discard_owned', owned_id='victim-item'))['reason']=='not_owned'
            assert (await buy(kind='hero.equip_owned', owned_id='party|sword|fine', slot='head'))['reason']=='invalid_slot'
            result = await buy(item_id='sword', price=-999, price_gold=0, hero_gold_cost=-1, target='victim', hero_id='victim', save_id='evil', client_action_id='same')
            assert result['success'], result
            row = (await sql("SELECT data FROM module_actions WHERE action_id=?", (result['action_id'],)))[0]
            payload = json.loads(row[0])
            assert payload['target']=='alice' and payload['initiated_by']=='alice'
            assert payload['price']==0 and payload['price_gold']==1000 and payload['required_level']==25
            assert payload['equipment_session_id']=='session-a'
            assert payload['hero_id']=='test_hero_alice' and payload['save_id']=='save-a'
            assert 'hero_gold_cost' not in payload
            assert (await sql("SELECT points FROM viewers WHERE channel_id=? AND username='alice'", (CHANNEL_ID,)))[0][0]==100000
            assert (await sql("SELECT gold FROM bannerlord_heroes WHERE channel_id=? AND username='alice'", (CHANNEL_ID,)))[0][0]==500000
            assert (await buy(item_id='sword'))['reason']=='pending'
            assert (await buy(item_id='sword', client_action_id='same'))['idempotent_replay']
            assert (await buy(kind='hero.equip_owned', owned_id='party|sword|fine', slot='weapon0', client_action_id='same'))['reason']=='client_action_conflict'
            for legacy in ('hero.reequip_gear', 'hero.upgrade_gear'):
                denied=await route._charge_execute_enqueue(legacy, {}, 0, 'alice', CHANNEL_ID)
                assert denied.get('reason')=='equipment_shop_enabled', denied
            await finish()
            await sql("UPDATE bannerlord_heroes SET level=29 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            assert (await buy(item_id='tier5'))['reason']=='level_locked'
            await sql("UPDATE bannerlord_heroes SET level=30,gold=999 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            assert (await buy(item_id='tier5'))['reason']=='insufficient_gold'
            await sql("UPDATE bannerlord_heroes SET gold=1000 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            assert (await buy(item_id='tier5'))['success']
            await finish()
            equip = await buy(kind='hero.equip_owned', owned_id='party|sword|fine', slot='weapon0')
            assert equip['success']
            payload = json.loads((await sql("SELECT data FROM module_actions WHERE action_id=?", (equip['action_id'],)))[0][0])
            assert payload['source']=='party' and payload['item_id']=='sword' and payload['modifier_id']=='fine'
            await finish()
            discard = await buy(kind='hero.discard_owned', owned_id='party|sword|fine', slot='head', target='victim', price=500)
            assert discard['success'], discard
            payload = json.loads((await sql("SELECT data FROM module_actions WHERE action_id=?", (discard['action_id'],)))[0][0])
            assert payload['owned_id']=='party|sword|fine' and payload['source']=='party' and payload['item_id']=='sword'
            assert payload['modifier_id']=='fine' and payload['target']=='alice' and payload['price']==0
            assert 'slot' not in payload
            assert (await buy(kind='hero.discard_owned', owned_id='party|sword|fine'))['reason']=='pending'
            await finish()
            # Older or wrong-save/generation snapshots cannot erase ownership.
            await store_inventory(db, CHANNEL_ID, envelope(inventory([]), ts=99))
            await store_inventory(db, CHANNEL_ID, envelope(inventory([],save_id='other'), ts=200))
            await store_inventory(db, CHANNEL_ID, envelope(inventory([],hero_id='other'), ts=200))
            async with db._connect() as conn:
                ctx=await context(conn,CHANNEL_ID,'alice')
            assert ctx['inventory']==[owned]
            # A different tenant has neither our catalog nor our ownership.
            await sql("INSERT INTO channels(channel_id,login,display_name,tier) VALUES(123,'other','Other','free')")
            await sql("INSERT INTO bannerlord_heroes(channel_id,username,hero_id,display_name,level,gold) VALUES(123,'alice','other_hero','Other',30,100000)")
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(123,'save-a')")
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(123,'session-a',1)")
            await store_inventory(db,123,envelope(inventory([],hero_id='other_hero')))
            assert (await buy(channel=123,item_id='sword'))['reason']=='item_not_found'
            assert (await buy(channel=123,kind='hero.equip_owned',owned_id='owned-1',slot='weapon0'))['reason']=='not_owned'
            assert (await buy(channel=123,kind='hero.discard_owned',owned_id='owned-1'))['reason']=='not_owned'
            await store_inventory(db,CHANNEL_ID,envelope(inventory([{**owned,'slot':'weapon0'}]),ts=101))
            assert (await buy(kind='hero.unequip_owned',slot='weapon0'))['success']
            await finish()
            # Save change invalidates old inventory even before fresh snapshots.
            await sql("UPDATE bannerlord_channel_state SET current_save_id='save-b' WHERE channel_id=?",(CHANNEL_ID,))
            assert (await buy(item_id='sword'))['reason']=='inventory_not_ready'
            await store_catalog(db,CHANNEL_ID,envelope({'save_id':'save-a','entries':[]}))
            assert len(await sql("SELECT * FROM module_catalogs WHERE channel_id=? AND catalog_type='equipment'",(CHANNEL_ID,)))==2
            # The legacy frozen client must never see new equipment catalog rows.
            route.require_jwt_user=lambda req:('alice',CHANNEL_ID)
            assert not (await route.bannerlord_shop(request))['items']
            endpoint=json.loads((await route.bannerlord_equipment_shop(request)).body)
            assert len(endpoint['items'])==2 and not endpoint['can_manage']
            route.require_jwt_user=lambda req:('carol',CHANNEL_ID)
            endpoint=json.loads((await route.bannerlord_equipment_shop(request)).body)
            assert not endpoint['has_hero'] and len(endpoint['items'])==2
            assert all(not item['can_buy'] for item in endpoint['items'])
            # Failed campaign handshake ts100 retried after a delayed boot ts110:
            # campaign authority must supersede boot even with an older timestamp.
            await sql("DELETE FROM bannerlord_equipment_sessions WHERE channel_id=?",(CHANNEL_ID,))
            await adapter._on_session_start(CHANNEL_ID,envelope({'save_id':'boot_retry','equipment_session_id':''},ts=110))
            await adapter._on_session_start(CHANNEL_ID,envelope({'save_id':'save-b','equipment_session_id':'session-retry'},ts=100))
            assert (await sql("SELECT session_id,session_ts FROM bannerlord_equipment_sessions WHERE channel_id=?",(CHANNEL_ID,)))[0]==('session-retry',100)
            # Equal epoch-ms boot/campaign start must install the real nonce.
            await sql("DELETE FROM bannerlord_equipment_sessions WHERE channel_id=?",(CHANNEL_ID,))
            await adapter._on_session_start(CHANNEL_ID,envelope({'save_id':'boot_test','equipment_session_id':''},ts=299))
            await adapter._on_session_start(CHANNEL_ID,envelope({'save_id':'save-b','equipment_session_id':'session-equal'},ts=299))
            assert (await sql("SELECT session_id FROM bannerlord_equipment_sessions WHERE channel_id=?",(CHANNEL_ID,)))[0][0]=='session-equal'
            # Same-save reload: new nonce rejects old snapshots even at larger seq;
            # the restored save is permitted to restart from lower inventory_seq.
            await adapter._on_session_start(CHANNEL_ID,envelope({'save_id':'save-b','equipment_session_id':'session-b'},ts=300))
            await store_inventory(db,CHANNEL_ID,envelope(inventory([owned],save_id='save-b'),ts=999))
            async with db._connect() as conn:
                assert not (await context(conn,CHANNEL_ID,'alice'))['ready']
            await store_inventory(db,CHANNEL_ID,envelope(inventory([owned],save_id='save-b',equipment_session_id='session-b'),ts=1))
            await adapter._on_session_start(CHANNEL_ID,envelope({'save_id':'save-a','equipment_session_id':'session-a'},ts=299))
            await adapter._on_session_start(CHANNEL_ID,envelope({'save_id':'save-b','equipment_session_id':'session-b'},ts=301))
            await adapter._on_session_start(CHANNEL_ID,envelope({'save_id':'boot_late','equipment_session_id':''},ts=999))
            async with db._connect() as conn:
                fresh=await context(conn,CHANNEL_ID,'alice')
                assert fresh['ready'] and fresh['session_id']=='session-b' and fresh['inventory']==[owned]
            print('PASS: equipment catalog, level gates, gold, malicious payload, ownership, tenant isolation, replay, pending, snapshot order and legacy shop')
        finally:
            await db._pool.close()

if __name__ == '__main__':
    asyncio.run(main())
