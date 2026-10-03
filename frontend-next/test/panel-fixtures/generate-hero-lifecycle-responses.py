"""Real Bannerlord handlers, owned disposable DB, synthetic game catalogs only."""
import asyncio, atexit, copy, json, os, sys, tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve()
OUT=Path(__file__).parent
sys.dont_write_bytecode=True
temporary_config=tempfile.TemporaryDirectory(prefix='hero-fixture-config-')
atexit.register(temporary_config.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(temporary_config.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID

async def main():
    with tempfile.TemporaryDirectory(prefix='hero-fixture-db-') as temporary:
        db=await _build_db(str(Path(temporary)/'fixture.db'))
        try:
            from routes import bannerlord as route
            from modules.bannerlord.content_catalogs import store_catalog
            from modules.bannerlord._adapter import _cooldowns
            import module_liveness
            request=_make_anon_request()
            route.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            async def sql(query,args=()):
                async with db._connect() as conn:
                    await conn.execute(query,args);await conn.commit()
            async def buy(label,kind,data):
                _cooldowns.clear()
                await sql("UPDATE module_actions SET status='acked'")
                result=await route._bannerlord_buy_action_locked(request,'alice',CHANNEL_ID,kind,copy.deepcopy(data))
                result=result if isinstance(result,dict) else json.loads(result.body)
                responses[label]={'request':{'action_type':kind,'data':data},'response':result}
                return result
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            responses={'config':await route.bannerlord_config(),'hero_alive':await route.bannerlord_my_hero(request)}
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')",(CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)",(CHANNEL_ID,))
            await store_catalog(db,CHANNEL_ID,dict(catalog='cultures',catalog_seq=1,save_id='save-a',equipment_session_id='session-a',entries=[dict(id='Mod.Culture-X',name='Культура из игры',description='Описание из игрового каталога',available=True)]))
            context=dict(save_id='save-a',equipment_session_id='session-a')
            await sql("DELETE FROM bannerlord_heroes WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            responses['hero_absent']=await route.bannerlord_my_hero(request)
            assert (await buy('create_culture','hero.create',dict(price=0,culture='Mod.Culture-X',content_context=context)))['success']
            assert (await buy('create_random','hero.create',dict(price=0,content_context=context)))['success']
            assert not (await buy('create_stale','hero.create',dict(price=0,culture='Mod.Culture-X',content_context={**context,'equipment_session_id':'old-session'})))['success']
            await sql("INSERT INTO bannerlord_heroes(channel_id,username,hero_id,display_name,is_alive,is_prisoner,gold) VALUES(?,'alice','dead_hero','Alice Hero',0,0,500000)",(CHANNEL_ID,))
            responses['hero_dead']=await route.bannerlord_my_hero(request)
            assert (await buy('respawn','hero.create',dict(price=0)))['success']
            await sql("UPDATE bannerlord_heroes SET is_alive=1 WHERE username='alice'")
            for gender in ['male','female']:
                assert (await buy('gender_'+gender,'hero.set_gender',dict(gender=gender)))['success']
            responses['daily_ready']=await route.bannerlord_daily_status(request)
            for reward in ['gold','xp']:
                await sql("DELETE FROM bannerlord_daily_claims WHERE username='alice'")
                request._json={'reward_type':reward}
                responses['daily_'+reward]=await route.bannerlord_daily_claim(request)
                assert responses['daily_'+reward]['success']
                responses['daily_claimed_'+reward]=await route.bannerlord_daily_status(request)
            responses['daily_refused']=await route.bannerlord_daily_claim(request)
            (OUT/'hero-lifecycle-responses.json').write_text(json.dumps({'provenance':{'base':'e966dcd','database':'owned temporary SQLite, full merged migrations','handlers':['bannerlord_my_hero','bannerlord_config','_bannerlord_buy_action_locked','bannerlord_daily_status','bannerlord_daily_claim'],'live_game':False},'responses':responses},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('HERO_FIXTURES_OK',len(responses),'real responses; no production requests')
        finally:
            await db._pool.close()
asyncio.run(main())
