"""Isolated read-only source probe: temporary full-schema SQLite, real handlers.
Representative seed data mirrors HeroStateSync DTO, never claims live-game state.
"""
import asyncio, atexit, copy, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
REPO=Path(sys.argv[1]).resolve(); OUT=Path(__file__).parent
cfg=tempfile.TemporaryDirectory(prefix='kingdom-diplomacy-config-'); atexit.register(cfg.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(cfg.name)/'unused-prices.json')
sys.dont_write_bytecode=True
sys.path[:0]=[str(REPO/'Расширение/backend/tests'),str(REPO/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID

def decoded(x): return x if isinstance(x,dict) else json.loads(x.body)
async def main():
    bodies={}
    with tempfile.TemporaryDirectory(prefix='kingdom-diplomacy-db-') as td:
        db=await _build_db(str(Path(td)/'fixture.db'))
        try:
            from routes import bannerlord as r,bannerlord_diplomacy as dip
            from modules.bannerlord._adapter import _cooldowns, BannerlordAdapter
            from modules._base import ModuleEnvelope
            from modules._loader import load_manifest
            adapter=BannerlordAdapter(load_manifest(REPO/"Расширение/backend/modules/bannerlord/manifest.yaml"))
            import module_liveness
            req=_make_anon_request()
            for m in [r,dip]: m.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            async def sql(q,args=()):
                async with db._connect() as c: await c.execute(q,args); await c.commit()
            async def rows(q,args=()):
                async with db._connect() as c: return [list(x) for x in await (await c.execute(q,args)).fetchall()]
            async def finish():
                await sql("UPDATE module_actions SET status='done'"); _cooldowns.clear()
            async def action(label,kind,data={},ok=None):
                payload={**data,'client_action_id':'kingdom-probe-'+label}
                response=decoded(await r._bannerlord_buy_action_locked(req,'alice',CHANNEL_ID,kind,copy.deepcopy(payload)))
                bodies[label]={'request':{'action_type':kind,'data':payload},'response':response}
                if response.get('success'):
                    bodies[label]['queued']=[{'type':t,'data':json.loads(d)} for t,d in await rows('SELECT type,data FROM module_actions WHERE channel_id=? ORDER BY rowid DESC LIMIT 1',(CHANNEL_ID,))]
                if ok is not None: assert bool(response.get('success'))==ok,(label,response)
                return response
            clan={'name':'[BLink] Fixture Clan','is_leader':True,'leader_name':'Alice Hero','members_count':3,'tier':3,'renown':1300,'fiefs_count':2,'parties_count':1}
            kingdom={'id':'fixture_kingdom','name':'Fixture Kingdom','ruler_name':'Alice Hero','is_ruler':True,'is_clan_leader':True,'clans_count':3,'fiefs_count':5,'at_war_count':1,'at_war_names':['Fixture Enemy'],'own_settlements':[],'enemy_settlements':[],'all_kingdoms':[{'id':'fixture_neutral','name':'Fixture Neutral','at_war':False},{'id':'fixture_enemy','name':'Fixture Enemy','at_war':True}],'rebellion_supporters':[],'rebellion_supporters_required':2,'rebellion_relation_required':50,'culture':'vlandia'}
            async def state(label,ki,cl=clan,gold=10000000):
                await adapter._on_player_state_update(CHANNEL_ID, ModuleEnvelope(id='fixture-state-'+label,kind='event',type='player.state_update',ts=0,data={'username':'alice','gold':gold,'clan_info':cl,'kingdom_info':ki}))
                bodies['hero_'+label]=decoded(await r.bannerlord_my_hero(req)); bodies['kingdom_'+label]=decoded(await dip.my_kingdom_state(req))
            bodies['config']=decoded(await r.bannerlord_config())
            dip.require_jwt_user=lambda _:None
            bodies['kingdom_unauthorized']=decoded(await dip.my_kingdom_state(req))
            dip.require_jwt_user=lambda _:('carol',CHANNEL_ID)
            bodies['kingdom_absent']=decoded(await dip.my_kingdom_state(req))
            dip.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await state('independent',None)
            await action('create','hero.create_kingdom',{'kingdom_name':'Fixture New Kingdom'},True); await finish()
            await action('create_blank','hero.create_kingdom',{'kingdom_name':''},True); await finish()
            await action('create_bad_name','hero.create_kingdom',{'kingdom_name':'<bad>'},False)
            await action('join','hero.join_kingdom',{'kingdom_name':'Fixture Existing'},True); await finish()
            await state('poor',None,gold=0)
            await action('create_poor','hero.create_kingdom',{'kingdom_name':''},False)
            await action('join_poor','hero.join_kingdom',{'kingdom_name':'Fixture'},False)
            await state('ruler',kingdom)
            await action('leave','hero.leave_kingdom',{},True); await finish()
            await action('recruit','hero.recruit_vassal_clan',{},True)
            bodies['buffs_recruit']=decoded(await r.bannerlord_my_buffs(req)); await finish()
            await action('policy_enact','hero.enact_policy',{'policy_id':'policy_royal_guard','policy_name':'Королевская гвардия'},True)
            bodies['kingdom_pending']=decoded(await dip.my_kingdom_state(req))
            bodies['buffs_policy']=decoded(await r.bannerlord_my_buffs(req))
            await action('policy_cooldown','hero.enact_policy',{'policy_id':'policy_trial_by_jury','policy_name':'Суд присяжных'},False)
            await finish()
            await action('policy_duplicate','hero.enact_policy',{'policy_id':'policy_royal_guard','policy_name':'Королевская гвардия'},False)
            await sql("UPDATE bannerlord_policy_requests SET status='enacted' WHERE channel_id=?",(CHANNEL_ID,))
            bodies['kingdom_enacted']=decoded(await dip.my_kingdom_state(req))
            await action('policy_remove','hero.enact_policy',{'policy_id':'policy_royal_guard','policy_name':'Королевская гвардия'},True); await finish()
            await sql("UPDATE bannerlord_policy_requests SET status='removed' WHERE channel_id=? AND status='pending'",(CHANNEL_ID,))
            bodies['kingdom_removed']=decoded(await dip.my_kingdom_state(req))
            assert not bodies['kingdom_removed']['policies_enacted']
            await action('direct_peace','hero.make_peace',{'target_kingdom_id':'fixture_enemy','target_kingdom_name':'Fixture Enemy','offered_tribute':-200},True)
            bodies['kingdom_peace_pending']=decoded(await dip.my_kingdom_state(req)); await finish()
            await action('direct_peace_clamp','hero.make_peace',{'target_kingdom_id':'fixture_enemy','target_kingdom_name':'Fixture Enemy','offered_tribute':20000},True); await finish()
            await action('direct_peace_self','hero.make_peace',{'target_kingdom_id':'fixture_kingdom','target_kingdom_name':'Fixture Kingdom','offered_tribute':0},False)
            for pct in [0,10,25,50]:
                await action('tax_'+str(pct),'kingdom.set_tax_rate',{'tax_rate_pct':pct},True); await finish()
                bodies['kingdom_tax_'+str(pct)]=decoded(await dip.my_kingdom_state(req))
            await action('war','kingdom.propose_war',{'target_kingdom_id':'fixture_neutral','target_kingdom_name':'Fixture Neutral'},True)
            bodies['buffs_war']=decoded(await r.bannerlord_my_buffs(req))
            await action('war_cooldown','kingdom.propose_war',{'target_kingdom_id':'fixture_neutral','target_kingdom_name':'Fixture Neutral'},False); await finish()
            await action('peace_vote','kingdom.propose_peace',{'target_kingdom_id':'fixture_enemy','target_kingdom_name':'Fixture Enemy'},True); await finish()
            await state('vassal',{**kingdom,'is_ruler':False,'ruler_name':'Other Ruler','rebellion_supporters':[{'id':'fixture_supporter','name':'Supporter Clan','fiefs_count':1}]})
            await action('rebellion_low_supporters','hero.create_kingdom',{'kingdom_name':'Rebellion'},True); await finish()
            await action('recruit_not_ruler','hero.recruit_vassal_clan',{},False)
            await action('tax_not_ruler','kingdom.set_tax_rate',{'tax_rate_pct':25},False)
            await action('peace_not_ruler','hero.make_peace',{'target_kingdom_id':'fixture_enemy'},False)
            await state('vassal_supported',{**kingdom,'is_ruler':False,'ruler_name':'Other Ruler','rebellion_supporters':[{'id':'fixture_supporter','name':'Supporter Clan','fiefs_count':1},{'id':'fixture_supporter_2','name':'Another Clan','fiefs_count':2}]})
            await state('member',{**kingdom,'is_ruler':False,'is_clan_leader':False},{**clan,'is_leader':False})
            await action('policy_not_leader','hero.enact_policy',{'policy_id':'policy_trial_by_jury','policy_name':'Суд присяжных'},False)
            await action('war_not_leader_backend','kingdom.propose_war',{'target_kingdom_id':'fixture_neutral','target_kingdom_name':'Fixture Neutral'},True); await finish()
            await state('no_kingdom',None)
            await action('war_no_kingdom_backend','kingdom.propose_war',{'target_kingdom_id':'fixture_neutral','target_kingdom_name':'Fixture Neutral'},True); await finish()
            await state('other',{**kingdom,'id':'fixture_other_kingdom','name':'Other Kingdom','ruler_name':'Other Ruler','is_ruler':False})
            paths=['Расширение/frontend/viewer-bannerlord.js','Расширение/frontend/viewer-actions.js','Расширение/backend/routes/bannerlord.py','Расширение/backend/routes/bannerlord_diplomacy.py','BannerlordLink/src/Util/HeroStateSync.cs']
            provenance={'repository':str(REPO),'database':'isolated temporary full-schema SQLite','seed':'representative HeroStateSync-shaped data applied through real BannerlordAdapter._on_player_state_update, fixture_* IDs local only','handlers':['routes.bannerlord','routes.bannerlord_diplomacy','BannerlordAdapter._on_player_state_update'],'auth':'require_jwt_user locally returns test alice/channel; production JWT verification not exercised','game':False,'source_sha256':{p:hashlib.sha256((REPO/p).read_bytes()).hexdigest() for p in paths},'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()}
            (OUT/'kingdom-responses.json').write_text(json.dumps({'provenance':provenance,'responses':bodies},ensure_ascii=False,indent=2)+'\n')
            print('KINGDOM_DIPLOMACY_PROBE_OK',len(bodies),'real handler bodies')
        finally: await db._pool.close()
asyncio.run(main())
