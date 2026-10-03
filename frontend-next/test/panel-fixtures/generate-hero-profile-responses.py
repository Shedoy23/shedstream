"""Real profile actions and snapshots; synthetic game family supplied to its adapter."""
import asyncio,atexit,copy,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();sys.dont_write_bytecode=True
temporary_config=tempfile.TemporaryDirectory(prefix='profile-fixture-config-');atexit.register(temporary_config.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(temporary_config.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID
async def main():
    with tempfile.TemporaryDirectory(prefix='profile-fixture-db-') as temporary:
        db=await _build_db(str(Path(temporary)/'fixture.db'))
        try:
            from routes import bannerlord as route
            from modules.bannerlord._adapter import _cooldowns,BannerlordAdapter
            from modules._base import ModuleEnvelope
            from modules._loader import load_manifest
            import module_liveness
            adapter=BannerlordAdapter(load_manifest(ROOT/'Расширение/backend/modules/bannerlord/manifest.yaml'))
            request=_make_anon_request();route.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            async def sql(q,args=()):
                async with db._connect() as c:await c.execute(q,args);await c.commit()
            out={'config':await route.bannerlord_config()}
            async def action(key,kind,data={}):
                _cooldowns.clear();await sql("UPDATE module_actions SET status='acked'")
                result=await route._bannerlord_buy_action_locked(request,'alice',CHANNEL_ID,kind,copy.deepcopy(data))
                if not isinstance(result,dict):result=json.loads(result.body)
                out[key]={'request':{'action_type':kind,'data':data},'response':result};return result
            clan={'name':'Клан фикстуры','is_leader':True,'members_count':4,'parties_count':1,'tier':3}
            family={'spouse':{'hero_id':'spouse-fixture','name':'Супруга фикстуры','is_alive':True,'age':29,'is_female':True,'is_pregnant':False},'children':[{'hero_id':'child-fixture','name':'Ребёнок фикстуры','age':7,'is_alive':True,'is_female':False}],'father':{'name':'Отец фикстуры','age':59,'is_alive':False,'is_female':False},'mother':{'name':'Мать фикстуры','age':54,'is_alive':True,'is_female':True},'sibling_count':2}
            async def state(key,fi,cl=clan,gold=500000):
                await adapter._on_player_state_update(CHANNEL_ID,ModuleEnvelope(id=key,kind='event',type='player.state_update',ts=0,data={'username':'alice','gold':gold,'clan_info':cl,'kingdom_info':None,'is_female':False,'family_info':fi}))
                out[key]=await route.bannerlord_my_hero(request)
            await state('hero_single',{**family,'spouse':None})
            assert (await action('marry','hero.marry'))['success']
            await state('hero_married',family)
            assert (await action('baby','hero.make_baby'))['success']
            assert (await action('divorce','hero.divorce'))['success']
            for gender in ['male','female']:assert (await action('gender_'+gender,'hero.set_gender',{'gender':gender}))['success']
            await state('hero_poor',family,gold=0)
            assert not (await action('gender_refused','hero.set_gender',{'gender':'female'}))['success']
            assert not (await action('baby_refused','hero.make_baby'))['success']
            await state('hero_clanless',{**family,'spouse':None},cl=None)
            assert not (await action('marry_refused','hero.marry'))['success']
            await state('hero_many_children',{**family,'children':[{**family['children'][0],'hero_id':'child-'+str(i)} for i in range(5)]})
            assert (await action('baby_queued_limit','hero.make_baby'))['success']
            Path(__file__).with_name('hero-profile-responses.json').write_text(json.dumps({'provenance':{'base':'052bf70','database':'owned temporary SQLite','live_game':False,'synthetic':'family metadata ingested by actual adapter'},'responses':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('PROFILE_FIXTURES_OK',len(out))
        finally:await db._pool.close()
asyncio.run(main())
