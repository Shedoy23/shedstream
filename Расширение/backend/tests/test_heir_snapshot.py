import asyncio, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import aiosqlite
from modules.bannerlord.heir_snapshot import reconcile_heir_snapshot

async def main():
 async with aiosqlite.connect(':memory:') as c:
  await c.execute("CREATE TABLE bannerlord_heirs(channel_id INTEGER,parent_username TEXT,heir_hero_id TEXT,heir_name TEXT,alive INTEGER DEFAULT 1,activated INTEGER DEFAULT 0,came_of_age_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(channel_id,heir_hero_id))")
  await reconcile_heir_snapshot(c,1,'alice',[{'hero_id':'a','name':'Adult'}])
  assert (await (await c.execute('SELECT heir_name,alive,activated FROM bannerlord_heirs')).fetchone())==('Adult',1,0)
  await reconcile_heir_snapshot(c,2,'alice',[{'hero_id':'a','name':'Other tenant'}])
  await reconcile_heir_snapshot(c,1,'bob',[{'hero_id':'a','name':'Not owned'}])
  assert (await (await c.execute('SELECT parent_username FROM bannerlord_heirs WHERE channel_id=1')).fetchone())[0]=='alice'
  await reconcile_heir_snapshot(c,1,'alice',None)
  await reconcile_heir_snapshot(c,1,'alice',[{}])
  assert (await (await c.execute('SELECT alive FROM bannerlord_heirs WHERE channel_id=1')).fetchone())[0]==1
  await reconcile_heir_snapshot(c,1,'alice',[])
  assert (await (await c.execute('SELECT alive FROM bannerlord_heirs WHERE channel_id=1')).fetchone())[0]==0
  assert (await (await c.execute('SELECT alive FROM bannerlord_heirs WHERE channel_id=2')).fetchone())[0]==1
  await reconcile_heir_snapshot(c,1,'alice',[{'hero_id':'a','name':'Restored'}])
  assert (await (await c.execute('SELECT alive,heir_name FROM bannerlord_heirs WHERE channel_id=1')).fetchone())==(1,'Restored')
 print('heir snapshot: PASS')
asyncio.run(main())
