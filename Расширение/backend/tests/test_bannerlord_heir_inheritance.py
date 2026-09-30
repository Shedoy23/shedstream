import asyncio,json,tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db,CHANNEL_ID
from modules._base import ModuleEnvelope
from modules._loader import get_module,discover_modules
async def main():
 failures=[];checks=0
 def check(value,label):
  nonlocal checks
  checks+=1;print(('PASS ' if value else 'FAIL ')+label)
  if not value:failures.append(label)
 with tempfile.TemporaryDirectory() as tmp:
  db=await _build_db(str(Path(tmp)/'inheritance.db'))
  try:
   adapter=get_module('bannerlord') or discover_modules()['bannerlord']
   async def sql(q,args=()):
    async with db._connect() as c:
     r=await c.execute(q,args);rows=await r.fetchall();await c.commit();return rows
   async def send(kind,**data):
    await adapter.handle_event(CHANNEL_ID,ModuleEnvelope(id=kind,kind='event',type=kind,ts=0,data={'username':'alice',**data}))
   await sql("INSERT INTO bannerlord_heirs(channel_id,parent_username,heir_hero_id,heir_name,alive,activated) VALUES (?,'alice','heir','Volg',1,0)",(CHANNEL_ID,))
   await sql("INSERT INTO bannerlord_fiefs(channel_id,owner_username,fief_id,fief_name,fief_type) VALUES (?,'alice','castle','Castle','castle')",(CHANNEL_ID,))
   await send('player.died')
   logs=await sql("SELECT asset_type FROM bannerlord_inheritance_log WHERE channel_id=? AND parent_username='alice'",(CHANNEL_ID,))
   check(not any(x[0]=='fief' for x in logs),'death does not claim old clan fiefs were inherited')
   actions=await sql("SELECT data FROM module_actions WHERE channel_id=? AND type='hero.activate_heir'",(CHANNEL_ID,))
   check(len(actions)==1 and json.loads(actions[0][0])['heir_hero_id']=='heir','real heir activation stays queued')
   await send('player.respawned',hero_id='heir',via_heir=True)
   check((await sql("SELECT hero_id,is_alive FROM bannerlord_heroes WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0]==('heir',1),'game activation supplies new hero identity')
   await send('player.state_update',hero_id='heir',clan_name='Other clan',clan_info={'name':'Other clan','is_leader':True,'fiefs_count':0},kingdom_info=None)
   row=(await sql("SELECT is_clan_leader,clan_info_json FROM bannerlord_heroes WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0]
   check(row[0]==1 and json.loads(row[1])['fiefs_count']==0,'native clan leader mirrored without kingdom')
   await send('player.state_update',hero_id='heir',clan_info={'name':'Other clan','is_leader':False,'fiefs_count':0})
   check((await sql("SELECT is_clan_leader FROM bannerlord_heroes WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0][0]==0,'leadership loss revokes native flag')
   await send('player.state_update',hero_id='heir',clan_info=None)
   check((await sql("SELECT clan_name,is_clan_leader FROM bannerlord_heroes WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0]==(None,0),'no clan clears mirror')
   await send('hero.properties_snapshot',fiefs=[],workshops=[],caravans=[])
   check(not await sql("SELECT fief_id FROM bannerlord_fiefs WHERE channel_id=? AND owner_username='alice'",(CHANNEL_ID,)),'actual fief snapshot removes former ownership')
  finally:await db._pool.close()
 print(str(checks)+' checks / '+str(len(failures))+' failures')
 if failures:raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
