import asyncio,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_action_ack_refund_order as base
from modules.bannerlord import reforge
from migrations import m129_reforge_rights
async def run():
    with tempfile.TemporaryDirectory() as tmp:
        db=await base._build_db(str(Path(tmp)/'db'))
        try:
            async with db._connect() as c:
                await m129_reforge_rights.apply(c)
                data={'initiated_by':'alice','price':20000,'_reforge':{'save_id':'s','hero_id':'h','slot':'head','item_id':'hat','modifier_id':'fine','rank':1}}
                await c.execute("INSERT INTO module_actions(channel_id,module_id,action_id,type,data,status) VALUES (?,'bannerlord','paid','hero.reforge_quality',?,'dispatched')",(base.CHANNEL_ID,json.dumps(data)))
                await reforge.reserve_tx(c,base.CHANNEL_ID,'alice','paid',data)
                await c.commit()
            await db.ack_action(base.CHANNEL_ID,'bannerlord','paid',True)
            async with db._connect() as c:
                rights=await reforge.rights_tx(c,base.CHANNEL_ID,'s')
                assert len(rights)==1,'successful paid action has no durable right'
                assert not await reforge.rights_tx(c,base.CHANNEL_ID+1,'s'),'tenant leak'
                assert not await reforge.rights_tx(c,base.CHANNEL_ID,'other-save'),'campaign leak'
            await base._send_failed('paid','test_refuse')
            async with db._connect() as c:
                assert not await reforge.rights_tx(c,base.CHANNEL_ID,'s'),'refunded quality still granted'
            await db.ack_action(base.CHANNEL_ID,'bannerlord','paid',True)
            async with db._connect() as c:
                assert not await reforge.rights_tx(c,base.CHANNEL_ID,'s'),'late ACK revived refunded quality'
            print('PASS paid right, failure, replay, tenant/save fences')
        finally: await db._pool.close()
if __name__=='__main__': asyncio.run(run())
