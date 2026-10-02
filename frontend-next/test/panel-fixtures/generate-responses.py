"""Isolated response provenance probe; does not modify repository or production.
Run with /tmp/preact-backend-venv/bin/python, repository root as first argument.
Representative state is seeded using existing backend test infrastructure;
every saved endpoint body is emitted by a real route handler.
"""
import asyncio, copy, json, sys, tempfile, time
from pathlib import Path
REPO=Path(sys.argv[1]).resolve()
OUT=Path(__file__).parent
sys.path[:0]=[str(REPO/'Расширение/backend/tests'),str(REPO/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID

def decoded(value):
    return value if isinstance(value,dict) else json.loads(value.body)

async def main():
    bodies={}
    with tempfile.TemporaryDirectory(prefix='panel-route-provenance-') as tmp:
        db=await _build_db(str(Path(tmp)/'test.db'))
        try:
            from routes import bannerlord as r
            from routes import viewer, duel, ui_usage
            from modules.bannerlord.equipment_shop import store_catalog,store_inventory
            from modules._base import ModuleEnvelope
            from modules.bannerlord._adapter import _cooldowns
            import module_liveness
            request=_make_anon_request()
            r.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            viewer.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            duel.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            async def sql(query,args=()):
                async with db._connect() as conn:
                    await conn.execute(query,args);await conn.commit()
            async def finish():
                await sql("UPDATE module_actions SET status='done'")
                _cooldowns.clear()
            async def action(label,kind,data):
                submitted={**data,'client_action_id':'fixture-'+label}
                response=await r._bannerlord_buy_action_locked(request,'alice',CHANNEL_ID,kind,copy.deepcopy(submitted))
                bodies[label]={'request':{'action_type':kind,'data':submitted},'response':decoded(response)}
                return response
            skills=['OneHanded','TwoHanded','Polearm','Bow','Crossbow','Throwing','Riding','Athletics','Crafting','Scouting','Tactics','Roguery','Charm','Leadership','Trade','Steward','Medicine','Engineering']
            for i,key in enumerate(skills):
                await sql('INSERT INTO bannerlord_skills(channel_id,username,skill_key,level,xp,focus) VALUES(?,?,?,?,?,?)',(CHANNEL_ID,'alice',key,30+i*10,1234+i,i%5))
            for i,key in enumerate(['vigor','control','endurance','cunning','social','intelligence']):
                await sql('INSERT INTO bannerlord_attributes(channel_id,username,attribute,value) VALUES(?,?,?,?)',(CHANNEL_ID,'alice',key,2+i))
            await sql("UPDATE bannerlord_heroes SET level=35,culture='vlandia',location='Pravend' WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_hero_class(channel_id,username,class_key,class_level) VALUES(?,'alice','tank',1)",(CHANNEL_ID,))
            await sql("UPDATE channels SET active_module='bannerlord' WHERE channel_id=?", (CHANNEL_ID,))
            bodies['stats']=decoded(await viewer.viewer_stats('alice',request))
            bodies['level']=decoded(await viewer.get_user_level('alice',request))
            bodies['duels']=decoded(await duel.list_duels(request))
            bodies['usage_unauthorized']=decoded(await ui_usage.record_ui_usage(request))
            from starlette.requests import Request
            usage_bytes=json.dumps({'batch_id':'11111111-1111-4111-8111-111111111111','surface':'desktop','events':[{'kind':'panel_view','feature':'core:panel','count':1}]}).encode()
            async def receive_usage():
                return {'type':'http.request','body':usage_bytes,'more_body':False}
            saved_channel, saved_claims=ui_usage.require_jwt_channel,ui_usage.verify_twitch_jwt
            try:
                ui_usage.require_jwt_channel=lambda _:CHANNEL_ID
                ui_usage.verify_twitch_jwt=lambda _:{'user_id':'123'}
                bodies['usage_ok']=decoded(await ui_usage.record_ui_usage(Request(dict(request.scope),receive_usage)))
                assert bodies['usage_ok']=={'status':'ok','duplicate':False},bodies['usage_ok']
            finally:
                ui_usage.require_jwt_channel,ui_usage.verify_twitch_jwt=saved_channel,saved_claims
            # Actual role refusal schema, used as a future server-refusal edge
            # in development UI tests; today's development actions are not gated.
            bodies['role_refusal']=r._resolve_perks(request,'world.trigger_event',0,'alice',CHANNEL_ID,{})

            for name,fn in [('config',r.bannerlord_config),('hero',lambda:r.bannerlord_my_hero(request)),('classes',lambda:r.bannerlord_classes(request)),('build_no_session',lambda:r.bannerlord_build(request)),('buffs',lambda:r.bannerlord_my_buffs(request)),('daily',lambda:r.bannerlord_daily_status(request)),('tournament',lambda:r.bannerlord_tournament(request))]:
                bodies[name]=decoded(await fn())
            r.require_jwt_user=lambda _:('carol',CHANNEL_ID)
            bodies['hero_absent']=decoded(await r.bannerlord_my_hero(request))
            r.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await action('focus_success','hero.add_focus',{'skill_key':'OneHanded','amount':1})
            bodies['focus_buffs']=decoded(await r.bannerlord_my_buffs(request))
            await action('focus_cooldown','hero.add_focus',{'skill_key':'TwoHanded','amount':1})
            await finish()
            await action('attribute_success','hero.add_attribute',{'attribute_key':'Vigor','amount':1});await finish()
            await action('class_success','hero.set_class',{'class_key':'archer','price':0});await finish()
            await sql("UPDATE bannerlord_heroes SET gold=0 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            await action('attribute_insufficient','hero.add_attribute',{'attribute_key':'Vigor','amount':1})
            await action('focus_insufficient','hero.add_focus',{'skill_key':'OneHanded','amount':1})
            await sql("UPDATE bannerlord_heroes SET gold=500000 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)",(CHANNEL_ID,))
            # Exact engine-defined choice IDs and field names; representative values.
            build={'version':1,'specialization':'guardian','selected_weapon_type':'one_handed','selected_power':'rage',
                   'starter_kit':None,'starter_claimed':False,'weapon_power_cooldown_until':0,'is_prisoner':False,
                   'is_mounted':False,'can_manage':True,'in_battle':False,
                   'specializations':[{'id':k,'label':l,'description':d} for k,l,d in [
                       ('guardian','Защитник','+15% здоровья в полевых боях.'),('assault','Натиск','+10% урона оружием в ближнем бою.'),
                       ('marksman','Стрелок','+10% урона стрелами, болтами и метательным оружием.'),('mobility','Подвижность','+10% скорости передвижения пешком.')]],
                   'starter_kits':[{'id':k,'label':l,'items':[],'available':True,'reason':None} for k,l in [
                       ('infantry','Одноручное оружие и щит'),('two_handed','Двуручное оружие'),('archer','Лук и стрелы')]],
                   'power_options':[{'weapon_type':'one_handed','power_key':'rage','label':'Натиск','description':'Усиливает удары одноручным оружием на 45 секунд.','skill':'OneHanded','skill_level':80,'rank':2,'value':1.25,'available':True,'reason':None},
                       {'weapon_type':'two_handed','power_key':'cleave','label':'Рассечение','description':'Удары двуручным оружием задевают соседних врагов на 45 секунд.','skill':'TwoHanded','skill_level':40,'rank':1,'value':.2,'available':False,'reason':'required_weapon_not_equipped'}]}
            seq=0
            owned=[{'owned_id':'equipped|weapon0','item_id':'sword','name':'Sword','tier':4,'slot':'weapon0','slots':['weapon0','weapon1'],'modifier_id':'','source':'equipped','trade_in_gold':700,'category':'one_handed','stats':{'swing_dmg':30}},
                   {'owned_id':'party|sword|fine','item_id':'sword','name':'Fine Sword','tier':4,'slot':None,'slots':['weapon0','weapon1'],'modifier_id':'fine','source':'party','count':2,'category':'one_handed','stats':{'swing_dmg':35}},
                   {'owned_id':'legacy-owned-1','item_id':'sword','name':'Stored Sword','tier':4,'slot':None,'slots':['weapon0','weapon1'],'modifier_id':'','source':'legacy','category':'one_handed','stats':{'swing_dmg':30}}]
            inv_state={'party_available':True,'party_id':'alice-party','party_name':'Alice Party','in_mission':False}
            def env(data,kind='hero.inventory_snapshot'):
                return ModuleEnvelope(id='probe',kind='event',type=kind,ts=int(time.time()),data={'equipment_session_id':'session-a','save_id':'save-a',**data})
            async def snapshot(current_build=build,current_state=inv_state,items=owned):
                nonlocal seq;seq+=1
                await store_inventory(db,CHANNEL_ID,env({'username':'alice','hero_id':'test_hero_alice','inventory_seq':seq,'items':items,'build':current_build,'inventory_state':current_state}))
            await snapshot()
            bodies['build_ready']=decoded(await r.bannerlord_build(request))
            bodies['hero_new_equipment']=decoded(await r.bannerlord_my_hero(request))
            await action('specialization_success','hero.set_specialization',{'specialization':'assault'})
            bodies['build_pending']=decoded(await r.bannerlord_build(request));await finish()
            await action('starter_success','hero.claim_starter',{'starter_kit':'infantry'});await finish()
            await snapshot({**build,'starter_claimed':True,'starter_kit':'infantry','starter_kits':[]})
            bodies['build_claimed']=decoded(await r.bannerlord_build(request))
            await snapshot({**build,'in_battle':True,'can_manage':False})
            bodies['build_battle']=decoded(await r.bannerlord_build(request))
            await snapshot({});bodies['build_syncing']=decoded(await r.bannerlord_build(request))
            await snapshot(None);bodies['build_legacy']=decoded(await r.bannerlord_build(request))
            await snapshot()
            # Catalog normalization and output use real store_catalog/route, as in backend equipment test.
            catalog=[{'item_id':'sword','name':'Sword','tier':4,'required_level':1,'price_gold':1000,'category':'one_handed','slots':['weapon0','weapon1'],'stats':{'swing_dmg':30},'weight':1.2},
                     {'item_id':'tier5','name':'Tier Five Sword','tier':5,'required_level':1,'price_gold':1500,'category':'one_handed','slots':['weapon0','weapon1'],'stats':{'swing_dmg':40},'weight':1.7}]
            await store_catalog(db,CHANNEL_ID,env({'entries':catalog},'module.catalog_update'))
            bodies['equipment_inventory']=decoded(await r.bannerlord_equipment_shop(request))
            for name,kind,data in [('equipment_buy','hero.buy_equipment',{'item_id':'sword'}),('equipment_equip','hero.equip_owned',{'owned_id':'party|sword|fine','slot':'weapon1'}),('equipment_unequip','hero.unequip_owned',{'slot':'weapon0'}),('equipment_discard','hero.discard_owned',{'owned_id':'party|sword|fine'})]:
                await action(name,kind,data);await finish()
            await snapshot(build,{'party_available':False,'party_reason':'no_party_inventory','buy_equip_available':True,'in_mission':False})
            bodies['equipment_direct']=decoded(await r.bannerlord_equipment_shop(request))
            item=bodies['equipment_direct']['items'][0];option=item['purchase_options'][0]
            await action('equipment_direct_buy','hero.buy_equipment',{'item_id':item['item_id'],'equip_now':True,'slot':option['slot'],'replace_owned_id':option['replace_owned_id'],'replace_item_id':option['replace_item_id'],'replace_modifier_id':option['replace_modifier_id'],'expected_price_gold':item['price_gold'],'expected_trade_in_gold':option['trade_in_gold']});await finish()
            await snapshot(build,{'party_available':False,'party_reason':'no_party_inventory','stash_available':True,'stash_count':1,'stash_capacity':10,'in_mission':False})
            bodies['equipment_stash']=decoded(await r.bannerlord_equipment_shop(request))
            await sql("UPDATE bannerlord_heroes SET is_alive=0 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            bodies['hero_dead']=decoded(await r.bannerlord_my_hero(request))
            bodies['equipment_dead']=decoded(await r.bannerlord_equipment_shop(request))
            (OUT/'real-responses.json').write_text(json.dumps({'provenance':{'repository':str(REPO),'handlers':['routes.bannerlord','routes.viewer.viewer_stats','routes.viewer.get_user_level','routes.duel.list_duels','routes.ui_usage.record_ui_usage'],'database':'isolated full-migrations temporary SQLite','live_game':False,'representative_state_sources':['tests/test_bannerlord_buy_action.py','tests/test_bannerlord_build.py','tests/test_bannerlord_equipment_shop.py','BannerlordLink/src/Util/HeroBuildRuntime.cs']},'responses':bodies},ensure_ascii=False,indent=2)+'\n')
            print('PROBE_OK',len(bodies),'bodies; real attributes:',bodies['hero']['attributes'],'classes:',len(bodies['classes']['classes']))
            failures=[key for key,value in bodies.items() if key.endswith('_success') and not value['response'].get('success')]
            assert not failures, failures
            print('All requested success fixtures verified')
        finally:
            await db._pool.close()
asyncio.run(main())
