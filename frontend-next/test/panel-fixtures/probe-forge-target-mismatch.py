"""Prove a stale client forge target using real routes and temporary SQLite.
Usage: python frontend-next/test/panel-fixtures/probe-forge-target-mismatch.py <output.json>
No network/game/real JWT. The two reads deliberately occur on different snapshots.
Adapted from the independent reviewer reproducer; backend source is unchanged.
"""
import asyncio,atexit,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUTPUT=Path(sys.argv[1]).resolve()
cfg=tempfile.TemporaryDirectory(prefix='forge-review-config-');atexit.register(cfg.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(cfg.name)/'unused-prices.json')
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID
from starlette.requests import Request

def decoded(x):return x if isinstance(x,dict) else json.loads(x.body)
async def main():
 with tempfile.TemporaryDirectory(prefix='forge-review-db-') as td:
  db=await _build_db(str(Path(td)/'fixture.db'))
  try:
   from routes import bannerlord as r
   from modules.bannerlord._adapter import BannerlordAdapter
   from modules._base import ModuleEnvelope
   from modules._loader import load_manifest
   from modules.bannerlord.equipment_shop import store_inventory
   import module_liveness
   r.require_jwt_user=lambda _:('alice',CHANNEL_ID)
   await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
   async def sql(q,args=()):
    async with db._connect() as c:
     rows=await(await c.execute(q,args)).fetchall();await c.commit();return rows
   def env(kind,data):return ModuleEnvelope(id='review-mismatch',kind='event',type=kind,ts=1,data=data)
   adapter=BannerlordAdapter(load_manifest(ROOT/'Расширение/backend/modules/bannerlord/manifest.yaml'))
   await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')",(CHANNEL_ID,))
   await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)",(CHANNEL_ID,))
   await adapter._on_equipment_changed(CHANNEL_ID,env('hero.equipment_changed',{'username':'alice','slot':'head','item_id':'helmet_A','item_name':'Visible helmet A','quality':'fine','tier':3,'stats':{}}))
   req=_make_anon_request()
   hero=decoded(await r.bannerlord_my_hero(req))
   await store_inventory(db,CHANNEL_ID,env('hero.inventory_snapshot',{'username':'alice','save_id':'save-a','hero_id':'test_hero_alice','equipment_session_id':'session-a','inventory_seq':2,'items':[{'source':'equipped','slot':'head','owned_id':'equipped|head','item_id':'helmet_B','name':'Actual helmet B','quality':None,'modifier_id':'','quality_rank':0,'reforge_options':[{'rank':1,'modifier_id':'fine_B'}]}],'inventory_state':{'party_available':True,'party_id':'p','in_mission':False}}))
   fresh_hero=decoded(await r.bannerlord_my_hero(req))
   equipment=decoded(await r.bannerlord_equipment_shop(req))
   body={'action_type':'hero.reforge_quality','data':{'slot':'head','client_action_id':'review-mismatch-head'}}
   async def receive():return {'type':'http.request','body':json.dumps(body).encode(),'more_body':False}
   actionreq=Request({'type':'http','method':'POST','path':'/api/bannerlord/action','headers':[],'query_string':b''},receive)
   before=(await sql("SELECT points FROM viewers WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0][0]
   result=decoded(await r.bannerlord_buy_action(actionreq))
   after=(await sql("SELECT points FROM viewers WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0][0]
   queued=json.loads((await sql('SELECT data FROM module_actions WHERE action_id=?',(result['action_id'],)))[0][0])
   evidence={'previous_my_hero_equipment':hero['equipment'],'fresh_my_hero_equipment':fresh_hero['equipment'],'equipment_inventory':equipment.get('inventory'),'equipment_keys':list(equipment),'request':body,'response':result,'balance_before':before,'balance_after':after,'queued':queued}
   OUTPUT.write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
   assert hero['equipment']['head']['item_id']=='helmet_A'
   assert queued['_reforge']['item_id']=='helmet_B'
   assert result['success'] and before-after==20000
   print('STALE_CLIENT_TARGET_CONFIRMED',json.dumps(evidence,ensure_ascii=False))
  finally:await db._pool.close()
asyncio.run(main())
