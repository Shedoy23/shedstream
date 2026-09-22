"""Daily failure releases only its exact claim, never a replacement or other tenant."""
import asyncio, json, tempfile, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_action_ack_refund_order as base

async def run():
    with tempfile.TemporaryDirectory() as tmp:
        db=await base._build_db(str(Path(tmp)/'test.db'))
        try:
            async with db._connect() as c:
                cols={r[1] for r in await (await c.execute('PRAGMA table_info(bannerlord_daily_claims)')).fetchall()}
                if 'action_id' not in cols:
                    await c.execute('ALTER TABLE bannerlord_daily_claims ADD COLUMN action_id TEXT')
                await c.execute("INSERT INTO bannerlord_daily_claims(channel_id,username,claim_date,reward_type,action_id) VALUES (?, 'alice', DATE('now'), 'xp','daily-old')",(base.CHANNEL_ID,))
                await c.execute("INSERT INTO module_actions(channel_id,module_id,action_id,type,data,status) VALUES (?, 'bannerlord', 'daily-old','hero.add_skill',?,'dispatched')",(base.CHANNEL_ID,json.dumps({'initiated_by':'alice','_daily':True,'price':0})))
                await c.commit()
            await base._send_failed('daily-old','skill_xp_not_applied:Medicine')
            async with db._connect() as c:
                count=(await (await c.execute("SELECT count(*) FROM bannerlord_daily_claims WHERE action_id='daily-old'")).fetchone())[0]
                assert count==0,'failed daily consumed the claim'
                await c.execute("INSERT INTO bannerlord_daily_claims(channel_id,username,claim_date,reward_type,action_id) VALUES (?, 'alice', DATE('now'), 'gold','daily-new')",(base.CHANNEL_ID,))
                await c.commit()
            await base._send_failed('daily-old','skill_xp_not_applied:Medicine')
            async with db._connect() as c:
                count=(await (await c.execute("SELECT count(*) FROM bannerlord_daily_claims WHERE action_id='daily-new'")).fetchone())[0]
                assert count==1,'duplicate old failure erased replacement claim'
            print('PASS daily retry and late duplicate')
        finally:
            await db._pool.close()
if __name__=='__main__': asyncio.run(run())
