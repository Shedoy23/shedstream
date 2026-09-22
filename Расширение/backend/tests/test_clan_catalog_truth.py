import asyncio,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_action_ack_refund_order as base
async def run():
    with tempfile.TemporaryDirectory() as tmp:
        db=await base._build_db(str(Path(tmp)/'db'))
        try:
            async with db._connect() as c:
                rows=await (await c.execute('SELECT effects_json FROM bannerlord_clan_upgrades_catalog')).fetchall()
                assert rows
                assert all('max_vassals_bonus' not in json.loads(r[0]) for r in rows),'catalog sells nonexistent vassal capacity'
                assert any(json.loads(r[0]).get('party_amount_bonus') for r in rows),'real party effect removed'
            print('PASS catalog advertises implemented effects')
        finally: await db._pool.close()
if __name__=='__main__': asyncio.run(run())
