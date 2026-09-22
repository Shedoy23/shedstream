import asyncio,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_action_ack_refund_order as base
from modules._loader import get_module,discover_modules
from modules._base import ModuleEnvelope
from routes.bannerlord_diplomacy import _derive_kingdom
async def run():
    with tempfile.TemporaryDirectory() as tmp:
        db=await base._build_db(str(Path(tmp)/'db'))
        try:
            adapter=get_module('bannerlord') or discover_modules()['bannerlord']
            for event in ('player.state_update','hero.kingdom_left','hero.clan_left'):
                async with db._connect() as c:
                    await c.execute("INSERT OR REPLACE INTO bannerlord_heroes(channel_id,username,hero_id,display_name,is_alive,kingdom_id,kingdom_name,is_king,is_clan_leader,kingdom_info_json,clan_info_json) VALUES (?,'alice','h','Alice',1,'old','Old',1,1,?,?)",(base.CHANNEL_ID,json.dumps({'id':'old','is_ruler':True,'is_clan_leader':True}),json.dumps({'name':'Old'})))
                    await c.commit()
                await adapter.handle_event(base.CHANNEL_ID,ModuleEnvelope(id=event,kind='event',type=event,ts=0,data={'username':'alice','kingdom_info':None,'clan_info':None}))
                async with db._connect() as c:
                    row=await (await c.execute("SELECT kingdom_id,kingdom_name,is_king,is_clan_leader,kingdom_info_json FROM bannerlord_heroes WHERE channel_id=? AND username='alice'",(base.CHANNEL_ID,))).fetchone()
                    derived=_derive_kingdom(*row)
                    assert not derived[0] and not derived[2],event+' retained departed kingdom authority'
            print('PASS explicit null and leave events revoke membership')
        finally: await db._pool.close()
if __name__=='__main__': asyncio.run(run())
