import asyncio,json,tempfile
from pathlib import Path
from unittest.mock import patch
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID
async def run():
    with tempfile.TemporaryDirectory() as tmp:
        db=await _build_db(str(Path(tmp)/'db'))
        try:
            from routes import bannerlord as route
            async with db._connect() as c:
                await c.execute("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'s')",(CHANNEL_ID,))
                await c.execute("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session',1)",(CHANNEL_ID,))
                await c.execute("INSERT INTO bannerlord_inventory_snapshots(channel_id,username,save_id,session_id,hero_id,inventory_seq,items_json) VALUES(?,'alice','s','session','test_hero_alice',1,?)",(CHANNEL_ID,json.dumps([{'slot':'weapon0','source':'equipped','item_id':'bow','name':'Bow','tier':5,'quality':'fine'}])))
                await c.commit()
            with patch.object(route,'require_jwt_user',return_value=('alice',CHANNEL_ID)):
                result=await route.bannerlord_my_hero(_make_anon_request())
            assert result['equipment'].get('weapon0',{}).get('tier')==4,'hero and inventory display different native tier'
            assert result['equipment']['weapon0']['quality']=='fine'
            print('PASS one current snapshot supplies both equipment views')
        finally: await db._pool.close()
if __name__=='__main__': asyncio.run(run())
