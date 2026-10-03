"""Vassals and ransom: real handlers against an owned disposable database."""
import asyncio,atexit,copy,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();sys.dont_write_bytecode=True
cfg=tempfile.TemporaryDirectory(prefix='vassal-config-');atexit.register(cfg.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(cfg.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID
async def main():
    with tempfile.TemporaryDirectory(prefix='vassal-fixture-') as temporary:
        db=await _build_db(str(Path(temporary)/'fixture.db'))
        try:
            from routes import bannerlord as route,bannerlord_vassals as vassals,bannerlord_diplomacy as diplo
            from modules.bannerlord._adapter import _cooldowns
            import module_liveness
            request=_make_anon_request()
            for module in [route,vassals,diplo]:module.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            async def sql(q,args=()):
                async with db._connect() as conn:await conn.execute(q,args);await conn.commit()
            await sql("UPDATE bannerlord_heroes SET clan_name='Клан фикстуры',gold=900000 WHERE username='alice'")
            await sql("INSERT INTO bannerlord_heirs(channel_id,parent_username,heir_hero_id,heir_name,alive,activated,came_of_age_at) VALUES(?,'alice','heir-eligible','Взрослый наследник',1,0,'2026-10-02 12:00:00')",(CHANNEL_ID,))
            async with db._connect() as conn:
                await vassals.reconcile_vassal_snapshot(conn,CHANNEL_ID,'alice',[dict(clan_id='vassal-1',leader_hero_id='vassal-leader-1',name='Северный дом',banner_code='fixture')]);await conn.commit()
            await sql("INSERT INTO bannerlord_heroes(channel_id,username,hero_id,display_name,is_alive,captured,captor_party,gear_tier) VALUES(?,'bob','hero-bob','Герой Боба',1,1,'Партия разбойников',3)",(CHANNEL_ID,))
            out={'config':await route.bannerlord_config(),'vassals':await vassals.my_vassals(request),'eligible':await vassals.eligible_heirs(request),'ransom':await diplo.ransom_pool_status(request)}
            async def buy(key,kind,data):
                _cooldowns.clear();await sql("UPDATE module_actions SET status='acked'")
                result=await route._bannerlord_buy_action_locked(request,'alice',CHANNEL_ID,kind,copy.deepcopy(data))
                if not isinstance(result,dict):result=json.loads(result.body)
                out[key]={'request':{'action_type':kind,'data':data},'response':result};return result
            vassal_id=out['vassals']['vassals'][0]['id']
            assert (await buy('rename','hero.rename_vassal',dict(vassal_id=vassal_id,new_name='Южный дом')))['success']
            assert not (await buy('rename_refused','hero.rename_vassal',dict(vassal_id=vassal_id+999,new_name='Южный дом')))['success']
            assert (await buy('create','hero.create_vassal_clan',dict(heir_hero_id='heir-eligible',vassal_name='Дом наследника')))['success']
            assert not (await buy('create_refused','hero.create_vassal_clan',dict(heir_hero_id='heir-eligible',vassal_name='Второй дом')))['success']
            assert (await buy('ransom_pay','hero.pay_ransom',dict(captured_hero='bob')))['success']
            out['ransom_after']=await diplo.ransom_pool_status(request)
            await sql("UPDATE bannerlord_heroes SET captured=0 WHERE username='bob'")
            assert not (await buy('ransom_refused','hero.pay_ransom',dict(captured_hero='bob')))['success']
            out['ransom_empty']=await diplo.ransom_pool_status(request)
            Path(__file__).with_name('vassal-ransom-responses.json').write_text(json.dumps({'provenance':{'base':'aa45a59','database':'owned temporary SQLite','live_game':False,'synthetic':'owned heir/vassal/capture observations'},'responses':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('VASSAL_RANSOM_FIXTURES_OK',len(out))
        finally:await db._pool.close()
asyncio.run(main())
