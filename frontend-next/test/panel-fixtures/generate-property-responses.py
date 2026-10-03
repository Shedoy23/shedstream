"""Actual property handlers against an owned disposable SQLite database."""
import asyncio, atexit, copy, json, os, sys, tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve()
sys.dont_write_bytecode=True
config_dir=tempfile.TemporaryDirectory(prefix='property-config-')
atexit.register(config_dir.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(config_dir.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID

async def main():
    with tempfile.TemporaryDirectory(prefix='property-fixtures-') as temporary:
        db=await _build_db(str(Path(temporary)/'fixture.db'))
        try:
            from routes import bannerlord as route, bannerlord_workshops as ws, bannerlord_caravans as cv, bannerlord_fiefs as ff, bannerlord_settlements as towns
            from modules.bannerlord._adapter import _cooldowns
            import module_liveness
            request=_make_anon_request()
            for module in [route,ws,cv,ff,towns]: module.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            async def sql(query,args=()):
                async with db._connect() as conn:
                    await conn.execute(query,args);await conn.commit()
            out={'config':await route.bannerlord_config(),'hero':await route.bannerlord_my_hero(request)}
            async def buy(key,kind,data):
                _cooldowns.clear()
                await sql("UPDATE module_actions SET status='acked'")
                result=await route._bannerlord_buy_action_locked(request,'alice',CHANNEL_ID,kind,copy.deepcopy(data))
                if not isinstance(result,dict): result=json.loads(result.body)
                out[key]={'request':{'action_type':kind,'data':data},'response':result}
                return result
            out['workshops_empty']=await ws.my_workshops(request)
            out['caravans_empty']=await cv.my_caravans(request)
            assert (await buy('workshop_buy','hero.buy_workshop',dict(settlement_id='town_fixture',settlement_name='Город фикстуры',workshop_type='brewery',workshop_type_name='Пивоварня')))['success']
            await sql("UPDATE bannerlord_workshops SET total_profit=12345,initial_capital=9876")
            out['workshops']=await ws.my_workshops(request)
            out['workshop_id']=out['workshops']['workshops'][0]['id']
            assert (await buy('workshop_sell','hero.sell_workshop',dict(workshop_id=out['workshop_id'])))['success']
            assert not (await buy('workshop_refused','hero.sell_workshop',dict(workshop_id=out['workshop_id'])))['success']
            assert (await buy('workshop_modded','hero.buy_workshop',dict(settlement_id='town_fixture',settlement_name='Город фикстуры',workshop_type='Mod.Workshop-X',workshop_type_name='Мастерская из игры')))['success']
            assert (await buy('caravan_buy','hero.buy_caravan',dict(home_settlement_id='town_fixture',home_settlement_name='Город фикстуры')))['success']
            await sql("UPDATE bannerlord_caravans SET total_collected_dinars=6789")
            out['caravans']=await cv.my_caravans(request)
            out['caravan_id']=out['caravans']['caravans'][0]['id']
            assert (await buy('caravan_sell','hero.sell_caravan',dict(caravan_id=out['caravan_id'])))['success']
            assert not (await buy('caravan_refused','hero.sell_caravan',dict(caravan_id=out['caravan_id'])))['success']
            await sql("INSERT INTO bannerlord_fiefs(channel_id,owner_username,fief_id,fief_name,fief_type,total_collected_dinars) VALUES(?,'alice','town_fixture','Город фикстуры','town',65432)",(CHANNEL_ID,))
            out['fiefs']=await ff.my_fiefs(request)
            await sql("INSERT INTO bannerlord_inheritance_log(channel_id,parent_username,heir_hero_id,asset_type,asset_ref,asset_name,total_value,inherited_at) VALUES(?,'alice','heir-fixture','workshop','1','Унаследованная мастерская',54321,'2026-10-02 12:00:00')",(CHANNEL_ID,))
            out['inheritance']=await route.bannerlord_inheritance_log(request,limit=15)
            # Only the mod-fed cache is synthetic; serialization/filtering is the real route.
            from modules import _loader
            class Adapter:
                def get_settlements(self,channel):
                    assert channel==CHANNEL_ID
                    return {'updated_at':'2026-10-02T12:00:00Z','settlements':[dict(id='town_fixture',name='Город фикстуры',type='town'),dict(id='castle_fixture',name='Замок фикстуры',type='castle')]}
            original=_loader.get_module
            try:
                _loader.get_module=lambda _:Adapter()
                out['settlements']=await towns.settlements_catalog(request)
            finally: _loader.get_module=original
            Path(__file__).with_name('property-responses.json').write_text(json.dumps({'provenance':{'base':'a056e77','database':'owned temporary SQLite, merged migrations','live_game':False,'synthetic':'mod settlement cache and ownership seeds'},'responses':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('PROPERTY_FIXTURES_OK',len(out),'real responses; no production requests')
        finally: await db._pool.close()
asyncio.run(main())
