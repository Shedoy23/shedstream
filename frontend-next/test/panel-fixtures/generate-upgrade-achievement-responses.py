"""Lazy clan upgrades and achievements serialized by the real API handlers."""
import asyncio,atexit,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();sys.dont_write_bytecode=True
cfg=tempfile.TemporaryDirectory(prefix='upgrade-config-');atexit.register(cfg.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(cfg.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID
async def main():
    with tempfile.TemporaryDirectory(prefix='upgrade-fixture-') as tmp:
        db=await _build_db(str(Path(tmp)/'fixture.db'))
        try:
            from routes import bannerlord as route,bannerlord_achievements as achievements
            import module_liveness
            request=_make_anon_request()
            for module in [route,achievements]:module.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            async def sql(q,args=()):
                async with db._connect() as conn:await conn.execute(q,args);await conn.commit()
            await sql('DELETE FROM bannerlord_clan_upgrades_catalog')
            for uid,name,tier,price,req,effects in [('fixture-a','Дружина',1,12345,None,{'retinue_size_bonus':7}),('fixture-b','Караванные пути',1,23456,None,{'party_speed_bonus':0.7}),('fixture-owned','Знамя клана',1,35000,None,{'renown_daily':3}),('fixture-locked','Большая дружина',2,45678,'fixture-a',{'retinue_size_bonus':11})]:
                await sql('INSERT INTO bannerlord_clan_upgrades_catalog(channel_id,upgrade_id,name,description,tier,required_upgrade_id,gold_cost,effects_json) VALUES(?,?,?,?,?,?,?,?)',(CHANNEL_ID,uid,name,'Игровое описание '+name,tier,req,price,json.dumps(effects)))
            await sql("INSERT INTO bannerlord_clan_upgrades_owned(channel_id,username,upgrade_id,gold_paid) VALUES(?,'alice','fixture-owned',35000)",(CHANNEL_ID,))
            await achievements.increment_stat(CHANNEL_ID,'alice','kills',37)
            out={'catalog':await route.bannerlord_clan_upgrades_list(request),'achievements':await achievements.viewer_achievements(request)}
            async def buy(key,ids):
                req=_make_anon_request();req._json={'upgrade_ids':ids}
                response=await route.bannerlord_clan_upgrades_buy(req)
                out[key]={'request':req._json,'response':response};return response
            assert not (await buy('locked',['fixture-locked']))['success']
            assert not (await buy('too_many',['fixture-'+str(i) for i in range(11)]))['success']
            assert (await buy('buy',['fixture-a','fixture-b']))['success']
            out['pending']=await route.bannerlord_clan_upgrades_list(request)
            assert not (await buy('duplicate',['fixture-a','fixture-b']))['success']
            Path(__file__).with_name('upgrade-achievement-responses.json').write_text(json.dumps({'provenance':{'base':'a1a4a3f','database':'owned temporary SQLite','live_game':False,'synthetic':'game-like clan catalog; achievements from actual server catalog and increment_stat'},'responses':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('UPGRADE_ACHIEVEMENT_FIXTURES_OK',len(out))
        finally:await db._pool.close()
asyncio.run(main())
