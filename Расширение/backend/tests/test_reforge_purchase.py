"""Real cash-register, session snapshots and paid-right activation across a save reload."""
import asyncio,json,tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID
async def run():
    with tempfile.TemporaryDirectory() as tmp:
        db=await _build_db(str(Path(tmp)/'db'))
        try:
            from routes import bannerlord as route
            from modules.bannerlord.equipment_shop import store_inventory
            from modules.bannerlord.reforge import rights_tx
            from modules._base import ModuleEnvelope
            from modules.bannerlord._adapter import clear_cooldown
            async def sql(query,args=()):
                async with db._connect() as c:
                    rows=await (await c.execute(query,args)).fetchall();await c.commit();return rows
            await sql("UPDATE viewers SET points=1000000 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)",(CHANNEL_ID,))
            row={'source':'equipped','slot':'head','owned_id':'hat-instance','item_id':'hat','modifier_id':None,'quality_rank':0,'reforge_options':[{'rank':1,'modifier_id':'fine'}]}
            async def snapshot(session):
                env=ModuleEnvelope(id=session,kind='event',type='hero.inventory_snapshot',ts=0,data={'username':'alice','save_id':'save-a','hero_id':'test_hero_alice','equipment_session_id':session,'inventory_seq':1,'items':[row],'inventory_state':{'party_available':True,'party_id':'p'}})
                await store_inventory(db,CHANNEL_ID,env)
            await snapshot('session-a')
            request=_make_anon_request()
            payload={'slot':'head','price':0,'_reforge':{'rank':3,'hero_id':'victim'}}
            result=await route._bannerlord_buy_action_locked(request,'alice',CHANNEL_ID,'hero.reforge_quality',payload)
            assert result.get('success'),result
            action=result['action_id']
            persisted=json.loads((await sql('SELECT data FROM module_actions WHERE action_id=?',(action,)))[0][0])
            assert persisted['price']==20000 and persisted['_reforge']['rank']==1 and persisted['_reforge']['hero_id']=='test_hero_alice',persisted
            assert (await sql("SELECT points FROM viewers WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0][0]==980000
            await db.ack_action(CHANNEL_ID,'bannerlord',action,True)
            await sql("UPDATE bannerlord_equipment_sessions SET session_id='session-b' WHERE channel_id=?",(CHANNEL_ID,))
            await snapshot('session-b') # old save says common again
            async with db._connect() as c:
                assert len(await rights_tx(c,CHANNEL_ID,'save-a'))==1,'resync erased paid right'
            from routes import streamer
            from starlette.requests import Request
            streamer.MODULE_TOKEN_SECRET='local-reforge-test-secret'
            async def rights_request(token='',save='save-a'):
                return await route.bannerlord_reforge_rights(Request({'type':'http','method':'GET','path':'/',
                    'query_string':('save_id='+save).encode(),'headers':[(b'authorization',('Bearer '+token).encode())]}))
            assert not (await rights_request()).get('success'),'anonymous read'
            assert not (await rights_request('invalid')).get('success'),'bad token read'
            assert not (await rights_request(streamer.issue_module_token(CHANNEL_ID,'rimworld'))).get('success'),'cross-module read'
            assert len((await rights_request(streamer.issue_module_token(CHANNEL_ID,'bannerlord')))['rights'])==1
            assert not (await rights_request(streamer.issue_module_token(CHANNEL_ID+1,'bannerlord')))['rights'],'cross-tenant read'
            assert not (await rights_request(streamer.issue_module_token(CHANNEL_ID,'bannerlord'),'other-save'))['rights'],'cross-save read'
            clear_cooldown(CHANNEL_ID,'alice','hero.reforge_quality')
            result=await route._bannerlord_buy_action_locked(request,'alice',CHANNEL_ID,'hero.reforge_quality',{'slot':'head'})
            assert not result.get('success'),'paid rollback sold the same step twice'
            assert (await sql("SELECT points FROM viewers WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0][0]==980000
            print('PASS hostile payload, server price, receipt, rollback, no second charge')
        finally: await db._pool.close()
if __name__=='__main__': asyncio.run(run())
