"""Reproducible combat provenance: real outer handlers on an isolated full-migrations DB.
Run directly with repository root argument, or via generate-responses.py.
No game, production database, or home configuration is accessed.
"""
import asyncio, atexit, copy, json, os, re, sys, tempfile, time
from pathlib import Path
REPO=Path(sys.argv[1]).resolve()
OUT=Path(__file__).parent
_fixture_config=tempfile.TemporaryDirectory(prefix='combat-fixture-config-')
atexit.register(_fixture_config.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(_fixture_config.name)/'unused-prices.json')
sys.dont_write_bytecode=True
sys.path[:0]=[str(REPO/'Расширение/backend/tests'),str(REPO/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID
from starlette.requests import Request

def decoded(x):return x if isinstance(x,dict) else json.loads(x.body)
async def main():
    bodies={}
    with tempfile.TemporaryDirectory(prefix='battle-contract-readonly-') as tmp:
        db=await _build_db(str(Path(tmp)/'test.db'))
        try:
            from routes import bannerlord as r
            from modules.bannerlord import _adapter as m
            from modules.bannerlord.equipment_shop import store_inventory
            from modules._base import ModuleEnvelope
            import module_liveness
            r.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            req=_make_anon_request()
            async def sql(q,args=()):
                async with db._connect() as conn:
                    cur=await conn.execute(q,args);rows=await cur.fetchall();await conn.commit();return rows
            async def finish(clear=True):
                await sql("UPDATE module_actions SET status='done'")
                if clear:m._cooldowns.clear()
            async def action(label,kind,data):
                submitted={'action_type':kind,'data':{**data,'client_action_id':'battle-probe-'+label}}
                async def receive():return {'type':'http.request','body':json.dumps(submitted).encode(),'more_body':False}
                areq=Request({'type':'http','method':'POST','path':'/api/bannerlord/action','headers':[],'query_string':b''},receive)
                result=decoded(await r.bannerlord_buy_action(areq))
                item={'request':submitted,'response':result}
                if result.get('success'):
                    rows=await sql('SELECT data FROM module_actions WHERE action_id=?',(result['action_id'],))
                    item['queued_payload']=json.loads(rows[0][0])
                bodies[label]=item
                return result
            bodies['config']=decoded(await r.bannerlord_config())
            bodies['hero']=decoded(await r.bannerlord_my_hero(req))
            bodies['build_no_session']=decoded(await r.bannerlord_build(req))
            bodies['buffs_empty']=decoded(await r.bannerlord_my_buffs(req))
            await sql("INSERT INTO bannerlord_hero_class(channel_id,username,class_key,class_level) VALUES(?,'alice','tank',1)",(CHANNEL_ID,))
            bodies['classes_by_key']={}
            first=decoded(await r.bannerlord_classes(req))
            for c in first['classes']:
                await sql("UPDATE bannerlord_hero_class SET class_key=? WHERE channel_id=? AND username='alice'",(c['class_key'],CHANNEL_ID))
                bodies['classes_by_key'][c['class_key']]=decoded(await r.bannerlord_classes(req))
            adapter=m.BannerlordAdapter(db)
            person={'username':'Alice','hp':87,'hp_max':115,'alive':True,'state':'active','order_status':'formation','is_player_side':True,'kills':0,'retinue_kills':0,'gold_earned':0,'payout_version':2,'payout_id':'representative-test-battle','payout_settled':False,'payout_status':'pending','payout_estimate_min':100,'payout_estimate_max':120,'payout_participation':0,'payout_personal':0,'payout_retinue':0,'payout_personal_points':0,'payout_retinue_points':0,'xp_earned':0}
            def battle(**extra):
                adapter._on_battle_stats(CHANNEL_ID,ModuleEnvelope(id='probe-battle',kind='event',type='battle.stats_snapshot',ts=int(time.time()),data={'participants':[copy.deepcopy(person)],**extra}))
            bodies['battle_idle']=decoded(await r.bannerlord_battle_status(req))
            for label,extra in [('field',{}),('siege',{'is_siege':True}),('not_spawned',{'participants':[dict(person,username='Bob')]}),('dead',{'participants':[dict(person,alive=False,hp=0,state='unconscious')]}),('routed',{'participants':[dict(person,state='routed',order_status='blocked')]}),('killed',{'participants':[dict(person,alive=False,hp=0,state='killed')]}),('legacy_payout',{'participants':[dict(person,payout_version=1,gold_earned=50,xp_earned=17,kills=2)]}),('final_paid',{'final':True,'participants':[dict(person,payout_status='paid',payout_settled=True,gold_earned=154800,payout_participation=60000,payout_personal=60000,payout_retinue=34800)]}),('final_failed',{'final':True,'participants':[dict(person,payout_status='failed',payout_settled=True)]}),('final_unavailable',{'final':True,'participants':[dict(person,payout_status='unavailable')]})]:
                battle(**extra);bodies['battle_'+label]=decoded(await r.bannerlord_battle_status(req))
            m._battle_stats[CHANNEL_ID]['updated_at']=time.time()-121
            bodies['battle_expired']=decoded(await r.bannerlord_battle_status(req))
            battle(is_siege=True)
            for kind in ['hero.detach_hold','hero.detach_charge','hero.attach','hero.detach_walls','hero.detach_gate','hero.detach','hero.detach_skirmish','hero.detach_raid']:
                await action(kind,kind,{'price':bodies['config']['action_prices'][kind]});await finish()
            for stance in ['defensive','balanced','aggressive']:
                await action('stance_'+stance,'hero.set_combat_stance',{'stance':stance});await finish()
            for side in ['player','enemy']:
                await action('spawn_'+side,'player.spawn',{'price':bodies['config']['spawn_prices'][side],'side':side})
                bodies['buffs_spawn_'+side]=decoded(await r.bannerlord_my_buffs(req))
                await action('spawn_'+side+'_cooldown','player.spawn',{'price':bodies['config']['spawn_prices'][side],'side':side});await finish()
            powers={p['power_key']:p for c in bodies['classes_by_key'].values() for p in c['current_powers']}
            for key,p in powers.items():
                await action('legacy_power_'+key,'power.activate',{'price':p['price'],'power_key':key});await finish()
            await action('order_cooldown_start','hero.detach_hold',{'price':30})
            bodies['buffs_order']=decoded(await r.bannerlord_my_buffs(req))
            await action('order_cooldown_refuse','hero.detach_hold',{'price':30});await finish()
            await adapter._on_buff_activated(CHANNEL_ID,ModuleEnvelope(id='probe-buff',kind='event',type='buff.activated',ts=int(time.time()),data={'username':'alice','power_key':'rage','duration_s':45}))
            bodies['buffs_active']=decoded(await r.bannerlord_my_buffs(req));m._active_buffs.clear()
            # Parse exact vocabulary/effect definitions from engine source rather than maintain invented IDs.
            policy=(REPO/'BannerlordLink/src/Util/HeroBuildPolicy.cs').read_text()
            defs=re.findall(r'new WeaponPowerDefinition\("([^"]+)", "([^"]+)", "([^"]+)", "([^"]+)", "([^"]+)", ([^)]+)\)',policy)
            assert len(defs)==7
            options=[{'weapon_type':w,'power_key':p,'label':label,'description':desc,'skill':skill,'skill_level':80,'rank':2,'value':float(values.split(',')[1]),'available':True,'reason':None} for w,p,label,desc,skill,values in defs]
            build={'version':1,'specialization':'guardian','selected_weapon_type':'one_handed','selected_power':'rage','starter_kit':'infantry','starter_claimed':True,'weapon_power_cooldown_until':0,'is_prisoner':False,'is_mounted':True,'can_manage':True,'in_battle':False,'power_options':options,'starter_kits':[],'specializations':[]}
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)",(CHANNEL_ID,))
            seq=0
            async def snapshot(b):
                nonlocal seq;seq+=1
                await store_inventory(db,CHANNEL_ID,ModuleEnvelope(id='probe-inventory',kind='event',type='hero.inventory_snapshot',ts=int(time.time()),data={'username':'alice','hero_id':'test_hero_alice','save_id':'save-a','equipment_session_id':'session-a','inventory_seq':seq,'items':[],'build':copy.deepcopy(b),'inventory_state':{'party_available':True,'party_id':'alice-party','in_mission':b.get('in_battle',False) if isinstance(b,dict) else False}}))
            await snapshot(build);bodies['build_choices']=decoded(await r.bannerlord_build(req))
            for p in options:
                await action('select_'+p['weapon_type'],'hero.select_weapon_power',{'weapon_type':p['weapon_type']});await finish()
            for p in options:
                combat={**build,'selected_weapon_type':p['weapon_type'],'selected_power':p['power_key'],'in_battle':True,'can_manage':False}
                await snapshot(combat);bodies['build_combat_'+p['weapon_type']]=decoded(await r.bannerlord_build(req))
                await action('build_power_'+p['weapon_type'],'power.activate',{'power_key':p['power_key']})
                bodies['build_pending_'+p['weapon_type']]=decoded(await r.bannerlord_build(req))
                bodies['buffs_build_'+p['weapon_type']]=decoded(await r.bannerlord_my_buffs(req));await finish()
            await snapshot({**build,'in_battle':True,'can_manage':False})
            await action('build_heal','power.activate',{'power_key':'heal_burst'});await finish()
            await snapshot({**build,'in_battle':True,'can_manage':False,'weapon_power_cooldown_until':int(time.time())+90})
            bodies['build_saved_cooldown']=decoded(await r.bannerlord_build(req))
            await action('build_saved_cooldown_refuse','power.activate',{'power_key':'rage'})
            await snapshot(build);await action('build_not_battle_refuse','power.activate',{'power_key':'rage'})
            await snapshot({**build,'in_battle':True,'can_manage':False});await action('build_wrong_power_refuse','power.activate',{'power_key':'cleave'})
            await snapshot({**build,'in_battle':True,'can_manage':False,'power_options':[dict(p,available=False,reason='required_weapon_not_equipped') for p in options]})
            bodies['build_unavailable']=decoded(await r.bannerlord_build(req));await action('build_weapon_refuse','power.activate',{'power_key':'rage'})
            await snapshot({**build,'is_prisoner':True,'can_manage':False});bodies['build_prisoner']=decoded(await r.bannerlord_build(req))
            await snapshot({});bodies['build_syncing']=decoded(await r.bannerlord_build(req))
            await snapshot(None);bodies['build_legacy_session']=decoded(await r.bannerlord_build(req))
            await action('build_not_ready_refuse','power.activate',{'power_key':'rage'})
            await sql("UPDATE viewers SET points=0 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,));await action('order_poor_refuse','hero.detach_charge',{'price':30})
            await snapshot(build)
            await module_liveness.clear(db,CHANNEL_ID,'bannerlord')
            bodies['build_offline']=decoded(await r.bannerlord_build(req))
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            for label,reason in [('legacy_power_rage','hero_not_spawned'),('stance_aggressive','unspecified')]:
                await adapter._on_action_failed(CHANNEL_ID,ModuleEnvelope(id='probe-refund-'+label,kind='event',type='action.failed',ts=int(time.time()),data={'action_id':bodies[label]['response']['action_id'],'reason':reason}))
                bodies['hero_refund_'+label]=decoded(await r.bannerlord_my_hero(req))
            assert bodies['hero_refund_legacy_power_rage']['recent_refunds'][0]['refunded'] is True
            assert len(bodies['hero_refund_stance_aggressive']['recent_refunds']) == 2
            assert sum(bool(v.get('response',{}).get('success')) for v in bodies.values() if isinstance(v,dict)) == 38
            # No final snapshot tasks with kills were scheduled; this probe never contacts a mod/game.
            path=OUT/'combat-responses.json'
            path.write_text(json.dumps({'provenance':{'kind':'direct real route handlers on isolated full-migration DB; not HTTP or live game','weapon_options_source':'BannerlordLink/src/Util/HeroBuildPolicy.cs parsed definitions','battle_participant_source':'BannerlordLink/src/Behaviors/KillRewardBehavior.cs PushStatsSnapshot, representative values','all_weapon_options_available':'branch coverage snapshot, not a claimed real loadout'},'responses':bodies},ensure_ascii=False,indent=2)+'\n')
            print('BATTLE_PROBE_OK',len(bodies),'bodies',len(bodies['classes_by_key']),'classes',len(powers),'legacy powers',len(options),'weapon choices')
            print('LEGACY_POWERS',json.dumps({k:[p['power_key'] for p in v['current_powers']] for k,v in bodies['classes_by_key'].items()},ensure_ascii=False))
            print('SUCCESS_ACTIONS',sum(bool(v.get('response',{}).get('success')) for v in bodies.values() if isinstance(v,dict)))
            print('EXPECTED_REFUSALS',json.dumps({k:v['response'] for k,v in bodies.items() if isinstance(v,dict) and 'response' in v and not v['response'].get('success')},ensure_ascii=False))
        finally:await db._pool.close()
asyncio.run(main())
