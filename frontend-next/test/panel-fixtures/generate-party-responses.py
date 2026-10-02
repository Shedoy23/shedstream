"""Read-only repository probe. Only isolated temporary SQLite/config are mutated.
Seed values are representative, not claims about any live game. Route bodies are real.
"""
import asyncio, atexit, copy, json, os, sys, tempfile
from pathlib import Path
REPO=Path(sys.argv[1]).resolve(); OUT=Path(__file__).parent
config=tempfile.TemporaryDirectory(prefix='party-army-config-'); atexit.register(config.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(config.name)/'unused-prices.json')
sys.dont_write_bytecode=True
sys.path[:0]=[str(REPO/'Расширение/backend/tests'), str(REPO/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID
from starlette.requests import Request

def decoded(x): return x if isinstance(x,dict) else json.loads(x.body)
async def main():
    bodies={}; expected_success=[]
    with tempfile.TemporaryDirectory(prefix='party-army-db-') as td:
        db=await _build_db(str(Path(td)/'fixture.db'))
        try:
            from routes import bannerlord as r, bannerlord_party_orders as po, bannerlord_vassals as va
            from modules.bannerlord._adapter import _cooldowns
            import module_liveness
            request=_make_anon_request()
            for route in [r,po,va]: route.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            async def sql(q,args=()):
                async with db._connect() as conn:
                    await conn.execute(q,args); await conn.commit()
            async def rows(q,args=()):
                async with db._connect() as conn: return [list(row) for row in await (await conn.execute(q,args)).fetchall()]
            async def finish():
                await sql("UPDATE module_actions SET status='done'"); _cooldowns.clear()
            async def action(label,kind,data={},success=None):
                payload={**data,'client_action_id':'party-probe-'+label}
                async def receive(): return {'type':'http.request','body':json.dumps({'action_type':kind,'data':payload}).encode(),'more_body':False}
                areq=Request({'type':'http','method':'POST','path':'/api/bannerlord/action','headers':[],'query_string':b''},receive)
                result=decoded(await r.bannerlord_buy_action(areq))
                bodies[label]={'request':{'action_type':kind,'data':payload},'response':result}
                if result.get('success'):
                    queued=await rows('SELECT type,data FROM module_actions WHERE channel_id=? ORDER BY rowid DESC LIMIT 1',(CHANNEL_ID,))
                    bodies[label]['queued']= [{'type':t,'data':json.loads(d)} for t,d in queued]
                if success is not None:
                    assert bool(result.get('success'))==success,(label,result)
                return result
            own=[{'id':'fixture_own_town','name':'Own Town','type':'town','days':3},{'id':'fixture_own_village','name':'Own Village','type':'village','days':1},{'id':'fixture_own_castle','name':'Own Castle','type':'castle','days':2}]
            enemies=[{'id':'fixture_enemy_castle','name':'Enemy Castle','type':'castle','days':4},{'id':'fixture_enemy_town','name':'Enemy Town','type':'town','days':2},{'id':'fixture_enemy_village','name':'Enemy Village','type':'village','days':1}]
            clan={'name':'[BLink] Fixture Clan','is_leader':True,'leader_name':'Alice Hero','members_count':3,'tier':3,'renown':1300,'fiefs_count':2,'parties_count':0,'vassal_heirs':[{'hero_id':'fixture_heir','name':'Fixture Heir'}]}
            kingdom={'id':'vlandia','name':'Vlandia','is_clan_leader':True,'is_ruler':False,'own_settlements':own,'enemy_settlements':enemies}
            party={'size':25,'task':'GoToSettlement','target':'Own Town','in_army':0,'has_army':0,'army_party_count':0,'cohesion':0}
            await sql("UPDATE bannerlord_heroes SET clan_name=?,kingdom_name='Vlandia',clan_info_json=?,kingdom_info_json=?,party_info_json=NULL WHERE channel_id=? AND username='alice'",(clan['name'],json.dumps(clan),json.dumps(kingdom),CHANNEL_ID))
            bodies['config']=decoded(await r.bannerlord_config())
            bodies['hero_no_party']=decoded(await r.bannerlord_my_hero(request))
            bodies['orders_none']=decoded(await po.my_party_order(request))
            bodies['vassals_none']=decoded(await va.my_vassals(request))
            await action('create_party','hero.create_party',success=True); await finish()
            await sql("UPDATE bannerlord_heroes SET party_info_json=?,clan_info_json=? WHERE channel_id=? AND username='alice'",(json.dumps(party),json.dumps({**clan,'parties_count':1}),CHANNEL_ID))
            bodies['hero_party']=decoded(await r.bannerlord_my_hero(request))
            await action('army_create','hero.army_create',success=True); await finish()
            for key,p in [('army_leader',{**party,'in_army':1,'has_army':1,'army_party_count':3,'cohesion':70}),('army_member',{**party,'in_army':1,'has_army':0})]:
                await sql("UPDATE bannerlord_heroes SET party_info_json=? WHERE channel_id=? AND username='alice'",(json.dumps(p),CHANNEL_ID))
                bodies['hero_'+key]=decoded(await r.bannerlord_my_hero(request))
            await action('army_already_in','hero.army_create',success=False)
            await action('army_disband','hero.army_disband',success=True); await finish()
            await sql("UPDATE bannerlord_heroes SET party_info_json=? WHERE channel_id=? AND username='alice'",(json.dumps(party),CHANNEL_ID))
            for kind in ['siege','defend','raid','garrison','patrol','recruit']:
                data={'order_type':kind,'target_settlement_id':'' if kind=='recruit' else ('fixture_enemy_village' if kind=='raid' else 'fixture_enemy_town' if kind=='siege' else 'fixture_own_town'),'target_settlement_name':'' if kind=='recruit' else 'Fixture Target (город, ~2 дн)'}
                await action('order_'+kind,'hero.party_order_set',data,True)
                bodies['orders_'+kind]=decoded(await po.my_party_order(request))
                if kind=='siege':
                    bodies['buffs_order']=decoded(await r.bannerlord_my_buffs(request))
                    await action('order_cooldown','hero.party_order_set',data,False)
                await finish()
            await action('order_release','hero.party_order_release',success=True); await finish()
            bodies['orders_released']=decoded(await po.my_party_order(request))
            await action('order_release_absent','hero.party_order_release',success=False)
            await action('order_missing_target','hero.party_order_set',{'order_type':'siege'},False)
            await action('order_for_expiry','hero.party_order_set',{'order_type':'patrol','target_settlement_id':'fixture_own_town'},True); await finish()
            await sql("UPDATE bannerlord_party_orders SET expires_at=datetime('now','-1 second') WHERE status='active'")
            bodies['orders_expired']=decoded(await po.my_party_order(request))
            assert bodies['orders_expired']=={'success':True,'active':None}
            await sql("UPDATE bannerlord_heroes SET gold=0 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            bodies['hero_empty_retinue_poor']=decoded(await r.bannerlord_my_hero(request))
            await action('recruit_insufficient','hero.recruit_troops',{'is_elite':False},False)
            await action('party_insufficient','hero.create_party',{},False)
            await sql("UPDATE bannerlord_heroes SET gold=500000 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            bodies['hero_empty_retinue_rich']=decoded(await r.bannerlord_my_hero(request))
            for label,kind,data in [('recruit_basic','hero.recruit_troops',{'is_elite':False}),('recruit_elite','hero.recruit_troops',{'is_elite':True}),('train_empty','hero.train_troops',{})]:
                await action(label,kind,data,True)
                bodies['buffs_'+label]=decoded(await r.bannerlord_my_buffs(request))
                await finish()
            members=[(0,'fixture_basic_1','Basic One',1,0),(1,'fixture_basic_5','Basic Max',5,0),(2,'fixture_elite_5','Elite Five',5,1),(3,'fixture_elite_6','Elite Max',6,1),(4,'fixture_basic_3','Basic Three',3,0)]
            for slot,tid,name,tier,elite in members:
                await sql("INSERT INTO bannerlord_retinue(channel_id,username,slot_index,troop_id,troop_name,tier,is_elite) VALUES(?,'alice',?,?,?,?,?)",(CHANNEL_ID,slot,tid,name,tier,elite))
            bodies['hero_retinue_full']=decoded(await r.bannerlord_my_hero(request))
            await action('upgrade_basic','hero.recruit_troops',{'is_elite':False},True); await finish()
            await action('upgrade_elite','hero.recruit_troops',{'is_elite':True},True); await finish()
            await action('train_full','hero.train_troops',{},True)
            await action('train_cooldown','hero.train_troops',{},False); await finish()
            await sql("UPDATE bannerlord_heroes SET gold=0 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            bodies['hero_retinue_poor']=decoded(await r.bannerlord_my_hero(request))
            await sql("UPDATE bannerlord_heroes SET gold=500000 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_clan_upgrades_catalog(channel_id,upgrade_id,name,tier,gold_cost,effects_json,deprecated) VALUES(?,'fixture_retinue_bonus','Fixture Bonus',1,1,'{\"retinue_size_bonus\":2}',0)",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_clan_upgrades_owned(channel_id,username,upgrade_id,gold_paid) VALUES(?,'alice','fixture_retinue_bonus',1)",(CHANNEL_ID,))
            bodies['hero_retinue_cap7']=decoded(await r.bannerlord_my_hero(request))
            await sql("INSERT INTO bannerlord_heirs(channel_id,parent_username,heir_hero_id,heir_name,alive,activated) VALUES(?,'alice','fixture_heir','Fixture Heir',1,0)",(CHANNEL_ID,))
            bodies['heirs_available']=decoded(await va.eligible_heirs(request))
            await action('vassal_create','hero.create_vassal_clan',{'heir_hero_id':'fixture_heir','vassal_name':'New Vassal'},True); await finish()
            bodies['vassals_pending_hidden']=decoded(await va.my_vassals(request))
            bodies['heirs_pending_reserved']=decoded(await va.eligible_heirs(request))
            await sql("UPDATE bannerlord_vassals SET vassal_clan_id='fixture_real_vassal' WHERE channel_id=? AND parent_username='alice'",(CHANNEL_ID,))
            bodies['vassals_real']=decoded(await va.my_vassals(request))
            vid=bodies['vassals_real']['vassals'][0]['id']
            await action('vassal_rename','hero.rename_vassal',{'vassal_id':vid,'new_name':'Renamed Vassal'},True); await finish()
            bodies['vassals_renamed']=decoded(await va.my_vassals(request))
            await sql("UPDATE bannerlord_heroes SET clan_name=NULL,clan_info_json=NULL,kingdom_name=NULL,kingdom_info_json=NULL,party_info_json=NULL WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            bodies['hero_clanless']=decoded(await r.bannerlord_my_hero(request))
            await action('army_no_kingdom','hero.army_create',{},False)
            await action('party_no_clan','hero.create_party',{},False)
            await sql("UPDATE bannerlord_heroes SET gold=2000000 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            await action('clan_create','hero.create_clan',{'clan_name':'Fixture New Clan'},True); await finish()
            await action('clan_join','hero.join_clan',{'clan_name':'Fixture Existing Clan'},True); await finish()
            await sql("UPDATE bannerlord_heroes SET clan_name='Native Clan',clan_info_json=? WHERE channel_id=? AND username='alice'",(json.dumps({**clan,'name':'Native Clan','is_leader':False}),CHANNEL_ID))
            bodies['hero_clan_member']=decoded(await r.bannerlord_my_hero(request))
            await sql("UPDATE bannerlord_heroes SET kingdom_name='Vlandia',kingdom_info_json=? WHERE channel_id=? AND username='alice'",(json.dumps({**kingdom,'is_clan_leader':False}),CHANNEL_ID))
            await action('army_not_clan_leader','hero.army_create',{},False)
            await action('clan_leave','hero.leave_clan',{},True); await finish()
            (OUT/'party-responses.json').write_text(json.dumps({'provenance':{'repository':str(REPO),'database':'isolated full-migrations temporary SQLite','live_game':False,'handlers':['routes.bannerlord','routes.bannerlord_party_orders','routes.bannerlord_vassals'],'state_sources':['tests/test_bannerlord_buy_action.py','BannerlordLink/src/Util/HeroStateSync.cs'],'representative_ids':'fixture_* IDs are seeded local identities, no external game resolution performed'},'responses':bodies},ensure_ascii=False,indent=2)+'\n')
            print('PARTY_PROBE_OK',len(bodies),'real handler bodies')
        finally: await db._pool.close()
asyncio.run(main())
