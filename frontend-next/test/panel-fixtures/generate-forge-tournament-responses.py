"""Frontend fixture generation: real handlers on temporary full-migration SQLite.
Run from any directory with /tmp/preact-backend-venv/bin/python.
All writes are isolated fixture state and this frontend JSON; no game/network.
"""
import asyncio, atexit, copy, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
REPO=Path(__file__).resolve().parents[3]; OUT=Path(__file__).parent
cfg=tempfile.TemporaryDirectory(prefix='forge-tournament-config-'); atexit.register(cfg.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(cfg.name)/'unused-prices.json')
sys.dont_write_bytecode=True
sys.path[:0]=[str(REPO/'Расширение/backend/tests'),str(REPO/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID
from starlette.requests import Request

def decoded(x):return x if isinstance(x,dict) else json.loads(x.body)
async def main():
    b={}
    with tempfile.TemporaryDirectory(prefix='forge-tournament-db-') as td:
        db=await _build_db(str(Path(td)/'fixture.db'))
        try:
            from routes import bannerlord as r
            from modules.bannerlord._adapter import _cooldowns,BannerlordAdapter
            from modules._base import ModuleEnvelope
            from modules._loader import load_manifest
            from modules.bannerlord.equipment_shop import store_inventory
            from modules.bannerlord.tournament_queue import store_snapshot
            import module_liveness
            adapter=BannerlordAdapter(load_manifest(REPO/'Расширение/backend/modules/bannerlord/manifest.yaml'))
            who='alice'; req=_make_anon_request()
            r.require_jwt_user=lambda _:(who,CHANNEL_ID) if who else None
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            async def sql(q,args=()):
                async with db._connect() as c:
                    cur=await c.execute(q,args); out=await cur.fetchall(); await c.commit();return out
            async def finish():await sql("UPDATE module_actions SET status='done'");_cooldowns.clear()
            async def action(label,kind,data={},ok=None):
                submitted={'action_type':kind,'data':{**data,'client_action_id':'forge-tournament-'+label}}
                async def receive():return {'type':'http.request','body':json.dumps(submitted).encode(),'more_body':False}
                areq=Request({'type':'http','method':'POST','path':'/api/bannerlord/action','headers':[],'query_string':b''},receive)
                before=(await sql('SELECT points FROM viewers WHERE channel_id=? AND username=?',(CHANNEL_ID,who)))[0][0] if who else None
                response=decoded(await r.bannerlord_buy_action(areq))
                record={'request':submitted,'response':response,'balance_before':before}
                if who:record['balance_after']=(await sql('SELECT points FROM viewers WHERE channel_id=? AND username=?',(CHANNEL_ID,who)))[0][0]
                if response.get('action_id'):
                    queued=await sql('SELECT type,data FROM module_actions WHERE action_id=?',(response['action_id'],))
                    record['queued']=[{'type':x,'data':json.loads(y)} for x,y in queued]
                b[label]=record
                if ok is not None:assert bool(response.get('success'))==ok,(label,response)
                return response
            def env(kind,data,seq=1):return ModuleEnvelope(id='forge-tournament-local-'+str(seq),kind='event',type=kind,ts=seq,data=data)
            b['config']=decoded(await r.bannerlord_config())
            who=None;b['tournament_unauthorized']=decoded(await r.bannerlord_tournament(req));who='alice'
            b['tournament_empty']=decoded(await r.bannerlord_tournament(req))
            await action('join','hero.join_tournament',{'price':0},True)
            b['join_buffs']=decoded(await r.bannerlord_my_buffs(req))
            b['tournament_pending_join']=decoded(await r.bannerlord_tournament(req))
            await action('join_cooldown','hero.join_tournament',{'price':0},False)
            _cooldowns.clear();await action('join_pending','hero.join_tournament',{'price':0},False);await finish()
            await adapter._on_tournament_joined(CHANNEL_ID,env('tournament.joined',{'username':'bobby','entry_fee':0}))
            b['tournament_queue']=decoded(await r.bannerlord_tournament(req))
            await adapter._on_tournament_joined(CHANNEL_ID,env('tournament.joined',{'username':'alice','entry_fee':0}))
            b['tournament_joined']=decoded(await r.bannerlord_tournament(req))
            await action('join_already','hero.join_tournament',{'price':0},False)
            await adapter._on_tournament_left(CHANNEL_ID,env('tournament.left',{'username':'alice'}))
            b['tournament_left_mod_event']=decoded(await r.bannerlord_tournament(req))
            await action('join_spoof_price','hero.join_tournament',{'price':98765,'hero_gold_cost':54321},True);await finish()
            who='carol';await action('join_no_hero','hero.join_tournament',{'price':0},False);who='alice'
            await action('predict_idle','tournament.predict',{'target':'bobby'},False)
            await adapter._on_tournament_started(CHANNEL_ID,env('tournament.started',{'participants':['alice','bobby','carol']}))
            b['tournament_running']=decoded(await r.bannerlord_tournament(req))
            await action('join_running','hero.join_tournament',{'price':0},False)
            await action('predict_blank','tournament.predict',{'target':''},False)
            await action('predict_not_participant','tournament.predict',{'target':'missing'},False)
            await action('predict','tournament.predict',{'target':'bobby'},True)
            b['predict_buffs']=decoded(await r.bannerlord_my_buffs(req))
            b['tournament_predicted']=decoded(await r.bannerlord_tournament(req))
            await action('predict_cooldown','tournament.predict',{'target':'carol'},False);_cooldowns.clear()
            await action('predict_duplicate_round','tournament.predict',{'target':'carol'},False)
            who='carol';await action('predict_no_hero','tournament.predict',{'target':' ALICE ','price':999,'amount':999},True);who='alice';await finish()
            await adapter._on_tournament_round_ended(CHANNEL_ID,env('tournament.round_ended',{'round_index':0,'survivors':['alice','bobby']}))
            b['tournament_next_round']=decoded(await r.bannerlord_tournament(req))
            await action('predict_next_round','tournament.predict',{'target':'carol'},True);await finish()
            # Authoritative modern queue snapshot allows inspection of ordered entries and capacity display.
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'forge-save')",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'forge-session',1)",(CHANNEL_ID,))
            await store_snapshot(db,CHANNEL_ID,{'save_id':'forge-save','equipment_session_id':'forge-session','queue_seq':1,'entries':[{'username':'fixture_'+str(i),'entry_fee':0} for i in range(17)]})
            await sql("UPDATE bannerlord_tournament_state SET status='idle',last_winner='bobby' WHERE channel_id=?",(CHANNEL_ID,))
            b['tournament_queue17']=decoded(await r.bannerlord_tournament(req))
            await action('join_queue17','hero.join_tournament',{'price':0},True);await finish()
            # Forge mirror and inventory are independent real mod contracts.
            await action('reforge_unsynced','hero.reforge_quality',{'slot':'head'},False)
            await sql("UPDATE viewers SET points=1000000 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            slots=['weapon0','weapon1','weapon2','weapon3','head','body','leg','gloves','cape','horse','horseharness']
            qualities=[None,'fine','masterwork','legendary','poor','inferior','common',None,None,None,None]
            inventory=[]
            for slot,quality in zip(slots,qualities):
                stats={'hp':450,'body':10} if slot=='weapon1' else {}
                await adapter._on_equipment_changed(CHANNEL_ID,env('hero.equipment_changed',{'username':'alice','slot':slot,'item_id':'fixture_'+slot,'item_name':'Fixture '+slot,'quality':quality,'tier':3,'item_value':1000,'weight':1.25,'stats':stats}))
                # ReforgeQuality.Rank in the mod maps both lower-quality labels to 0.
                rank={None:0,'common':0,'poor':0,'inferior':0,'fine':1,'masterwork':2,'legendary':3}[quality]
                inventory.append({'source':'equipped','slot':slot,'owned_id':'equipped|'+slot,'item_id':'fixture_'+slot,'name':'Fixture '+slot,'quality':quality,'tier':3,'item_value':1000,'weight':1.25,'stats':stats,'modifier_id':quality,'quality_rank':rank,'reforge_options':[] if slot=='horse' else [{'rank':i,'modifier_id':'fixture_rank'+str(i)} for i in [1,2,3]]})
            seq=0
            async def snapshot(items=inventory,state={}):
                nonlocal seq;seq+=1
                await store_inventory(db,CHANNEL_ID,env('hero.inventory_snapshot',{'username':'alice','save_id':'forge-save','hero_id':'test_hero_alice','equipment_session_id':'forge-session','inventory_seq':seq,'items':items,'inventory_state':{'party_available':True,'party_id':'fixture-party','in_mission':False,**state}},seq))
            await snapshot()
            b['hero_forge']=decoded(await r.bannerlord_my_hero(req));b['equipment_forge']=decoded(await r.bannerlord_equipment_shop(req))
            await adapter._on_equipment_changed(CHANNEL_ID,env('hero.equipment_changed',{'username':'alice','slot':'head','item_id':'fixture_head','item_name':'Fixture head','quality':'fine','tier':3,'item_value':1000,'weight':1.25,'stats':{}}))
            await snapshot([{**x,'quality':'fine','quality_rank':1,'modifier_id':'fixture_rank1'} if x['slot']=='head' else x for x in inventory])
            b['hero_forge_upgraded']=decoded(await r.bannerlord_my_hero(req))
            await sql("UPDATE bannerlord_heroes SET is_alive=0 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            b['hero_forge_dead']=decoded(await r.bannerlord_my_hero(req))
            await sql("UPDATE bannerlord_heroes SET is_alive=1 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            await snapshot()
            await action('reforge_horse','hero.reforge_quality',{'slot':'horse'},False)
            await action('reforge_bad_slot','hero.reforge_quality',{'slot':'missing'},False)
            await action('reforge_best','hero.reforge_quality',{'slot':'weapon3'},False)
            await action('reforge','hero.reforge_quality',{'slot':'head'},True)
            b['reforge_buffs']=decoded(await r.bannerlord_my_buffs(req))
            await action('reforge_pending_right','hero.reforge_quality',{'slot':'head'},False);await finish()
            await action('reforge_harness','hero.reforge_quality',{'slot':'horseharness'},True);await finish()
            await action('reforge_upper_slot','hero.reforge_quality',{'slot':'WEAPON0','price':1},True);await finish()
            await snapshot(state={'in_mission':True});b['equipment_mission']=decoded(await r.bannerlord_equipment_shop(req))
            await action('reforge_in_mission','hero.reforge_quality',{'slot':'body'},True);await finish()
            await snapshot()
            await sql("UPDATE viewers SET points=1 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            await action('reforge_poor','hero.reforge_quality',{'slot':'gloves'},False)
            await action('smith_retired','hero.smith_item',{},False)
            await action('trophy_retired','hero.equip_trophy',{},False)
            await action('leave_absent','hero.leave_tournament',{},False)
            who='carol';b['hero_absent']=decoded(await r.bannerlord_my_hero(req));await action('reforge_no_hero','hero.reforge_quality',{'slot':'head'},False);who='alice'
            await sql("UPDATE viewers SET points=1000000 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            await sql("UPDATE bannerlord_heroes SET is_prisoner=1 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            b['hero_prisoner']=decoded(await r.bannerlord_my_hero(req))
            await action('reforge_prisoner','hero.reforge_quality',{'slot':'cape'})
            # Every displayed actionable slot is admitted through the real cashier.
            await sql("UPDATE bannerlord_heroes SET is_prisoner=0 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            for slot in ['weapon0','weapon1','weapon2','head','body','leg','gloves','cape','horse']:
                await finish()
                await sql('DELETE FROM bannerlord_reforge_rights WHERE channel_id=?',(CHANNEL_ID,))
                await snapshot()
                await action('reforge_slot_'+slot,'hero.reforge_quality',{'slot':slot},slot!='horse')
            paths=['Расширение/frontend/extension.html','Расширение/frontend/mobile.html','Расширение/frontend/viewer-bannerlord.js','Расширение/frontend/viewer-actions.js','Расширение/backend/routes/bannerlord.py','Расширение/backend/modules/bannerlord/reforge.py','Расширение/backend/modules/bannerlord/_adapter.py','BannerlordLink/src/Actions/ReforgeQualityHandler.cs','BannerlordLink/src/Actions/JoinTournamentHandler.cs']
            provenance={'repository':str(REPO),'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),'database':'isolated temporary SQLite + current main.run_migrations()','handlers':'real public route functions, real BannerlordAdapter events and equipment/queue snapshot handlers','auth':'require_jwt_user test stub; real JWT verification not exercised','game':False,'network':False,'source_sha256':{p:hashlib.sha256((REPO/p).read_bytes()).hexdigest() for p in paths}}
            (OUT/'forge-tournament-responses.json').write_text(json.dumps({'provenance':provenance,'responses':b},ensure_ascii=False,indent=2)+'\n')
            print('FORGE_TOURNAMENT_PROBE_OK',len(b),'real handler bodies')
        finally:await db._pool.close()
asyncio.run(main())
