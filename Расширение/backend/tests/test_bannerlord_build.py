"""Real SQLite cash register contract for save-owned builds; no live game claim."""
import asyncio
import json
import tempfile
import time
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'build.db'))
        try:
            from routes import bannerlord as route
            from modules.bannerlord.equipment_shop import store_inventory
            from modules._base import ModuleEnvelope
            request = _make_anon_request()
            async def sql(query, args=()):
                async with db._connect() as conn:
                    cur = await conn.execute(query, args)
                    rows = await cur.fetchall()
                    await conn.commit()
                    return rows
            async def buy(kind, **data):
                return await route._bannerlord_buy_action_locked(request, 'alice', CHANNEL_ID, kind, data)
            async def finish():
                await sql("UPDATE module_actions SET status='done'")
            build = {'version': 1, 'specialization':'guardian', 'selected_weapon_type':'one_handed',
                     'selected_power':'rage', 'starter_claimed':False, 'can_manage':True, 'in_battle':False,
                     'weapon_power_cooldown_until':0,
                     'specializations':[{'id':'guardian'},{'id':'assault'}],
                     'power_options':[{'weapon_type':'one_handed','power_key':'rage','available':True},
                                      {'weapon_type':'two_handed','power_key':'cleave','available':False}],
                     'starter_kits':[{'id':'infantry','available':True}]}
            async def snapshot(seq=1, **changes):
                data = {'username':'alice','save_id':'save-a','hero_id':'test_hero_alice',
                        'equipment_session_id':'session-a','inventory_seq':seq,'items':[],
                        'build':dict(build), **changes}
                await store_inventory(db, CHANNEL_ID, ModuleEnvelope(id='test', kind='event',
                    type='hero.inventory_snapshot', ts=seq, data=data))
            denied = await buy('hero.set_specialization', specialization='guardian')
            assert denied.get('reason') == 'inventory_not_ready', denied
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')", (CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)", (CHANNEL_ID,))
            await snapshot()
            result = await buy('hero.set_specialization', specialization='assault', price=99999,
                               target='victim', hero_id='evil', value=999, class_key='evil', client_action_id='build-1')
            assert result['success'] and result['charged']==0, result
            payload = json.loads((await sql('SELECT data FROM module_actions WHERE action_id=?', (result['action_id'],)))[0][0])
            assert payload['specialization']=='assault' and payload['target']=='alice'
            assert payload['hero_id']=='test_hero_alice' and payload['equipment_session_id']=='session-a'
            assert 'value' not in payload and 'class_key' not in payload
            assert (await buy('hero.claim_starter', starter_kit='infantry'))['reason']=='pending'
            assert (await buy('hero.set_specialization', specialization='assault', client_action_id='build-1'))['idempotent_replay']
            assert (await buy('hero.claim_starter', starter_kit='infantry', client_action_id='build-1'))['reason']=='client_action_conflict'
            await finish()
            assert (await buy('hero.set_specialization', specialization='evil'))['reason']=='invalid_specialization'
            assert (await buy('hero.select_weapon_power', weapon_type='two_handed'))['reason']=='weapon_unavailable'
            assert (await buy('hero.select_weapon_power', weapon_type='one_handed'))['success']
            await finish()
            assert (await buy('hero.claim_starter', starter_kit='infantry'))['success']
            await finish()
            build['starter_claimed']=True
            await snapshot(2)
            assert (await buy('hero.claim_starter', starter_kit='infantry'))['reason']=='starter_claimed'
            build['can_manage']=False
            build['in_battle']=True
            await snapshot(3)
            assert (await buy('hero.set_specialization', specialization='guardian'))['reason']=='in_battle'
            assert (await buy('power.activate', power_key='cleave', price=0))['reason']=='power_not_selected'
            result=await buy('power.activate', power_key='rage', price=0, weapon_type='two_handed', value=999)
            assert result['success'] and result['charged']==route.POWER_PRICES['rage'], result
            payload=json.loads((await sql('SELECT data FROM module_actions WHERE action_id=?',(result['action_id'],)))[0][0])
            assert payload['weapon_type']=='one_handed' and payload['hero_id']=='test_hero_alice' and 'value' not in payload
            await finish()
            # Changing selected power cannot bypass the shared cooldown.
            build['selected_weapon_type']='two_handed'; build['selected_power']='cleave'
            build['power_options'][1]['available']=True
            await snapshot(4)
            denied=await buy('power.activate',power_key='cleave')
            assert not denied['success'] and denied.get('cooldown_remaining_s',0)>0, denied
            from modules.bannerlord._adapter import _cooldowns
            _cooldowns.clear()
            build['weapon_power_cooldown_until']=time.time()+90
            await snapshot(5)
            denied=await buy('power.activate',power_key='cleave')
            assert not denied['success'] and denied.get('cooldown_remaining_s',0)>0, denied
            # Stale sequence / wrong session cannot reset the authoritative build.
            await snapshot(4,build={**build,'starter_claimed':False})
            await snapshot(100,equipment_session_id='evil',build={**build,'starter_claimed':False})
            route.require_jwt_user=lambda req:('alice',CHANNEL_ID)
            response=await route.bannerlord_build(request)
            assert response['build']['starter_claimed'] and response['build']['selected_power']=='cleave'
            assert response['build']['power_options'][1]['price']==route.POWER_PRICES['cleave']
            assert not response['can_manage']
            # The old class table has not been rewritten by specialization changes.
            assert not await sql("SELECT 1 FROM bannerlord_hero_class WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            print('PASS: build cash register, choices, free pricing, hostile payload, replay, battle gate, shared/persisted cooldown, snapshot identity')
        finally:
            await db._pool.close()

if __name__=='__main__':
    asyncio.run(main())
