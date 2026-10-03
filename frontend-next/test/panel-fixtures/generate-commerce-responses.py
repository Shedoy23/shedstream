"""Bannerlord commerce/legacy gear contracts, temporary DB and actual handlers."""
import asyncio,atexit,copy,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();sys.dont_write_bytecode=True
cfg=tempfile.TemporaryDirectory(prefix='commerce-config-');atexit.register(cfg.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(cfg.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID
async def main():
    with tempfile.TemporaryDirectory(prefix='commerce-fixture-') as tmp:
        db=await _build_db(str(Path(tmp)/'fixture.db'))
        try:
            from routes import bannerlord as route
            from modules.bannerlord._adapter import _cooldowns,update_last_seen
            import module_liveness
            req=_make_anon_request();route.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord');update_last_seen(CHANNEL_ID)
            async def sql(q,args=()):
                async with db._connect() as conn:await conn.execute(q,args);await conn.commit()
            await sql("INSERT OR REPLACE INTO bannerlord_hero_class(channel_id,username,class_key) VALUES(?,'alice','berserk')",(CHANNEL_ID,))
            await sql("UPDATE bannerlord_heroes SET gear_tier=2 WHERE username='alice'")
            await sql("UPDATE bannerlord_heroes SET culture='Культура фикстуры',location='Город фикстуры',tournament_wins=3 WHERE username='alice'")
            await sql("INSERT INTO bannerlord_equipment(channel_id,username,slot,item_id,item_name,tier,item_value,weight,stats_json,quality) VALUES(?,'alice','head','fixture-helmet','Шлем фикстуры',2,1234,2.5,?,'fine')",(CHANNEL_ID,json.dumps({'head':17,'body':3,'mod_stat':19})))
            out={'config':await route.bannerlord_config(),'hero':await route.bannerlord_my_hero(req),'classes':await route.bannerlord_classes(req),'status':await route.bannerlord_status(req)}
            for entry,payload in [('fixture-army',dict(name='Собрать армию',description='Предложение каталога игры',action_type='hero.army_create',price=out['config']['action_prices']['hero.army_create'])),('old-xp',dict(name='Устаревший опыт',action_type='hero.add_skill',price=1))]:
                await sql("INSERT INTO module_catalogs(channel_id,module_id,catalog_type,entry_id,payload) VALUES(?,'bannerlord','shop',?,?)",(CHANNEL_ID,entry,json.dumps(payload)))
            out['shop']=await route.bannerlord_shop(req)
            async def buy(key,kind,data):
                _cooldowns.clear();await sql("UPDATE module_actions SET status='acked'")
                result=await route._bannerlord_buy_action_locked(req,'alice',CHANNEL_ID,kind,copy.deepcopy(data))
                if not isinstance(result,dict):result=json.loads(result.body)
                out[key]={'request':{'action_type':kind,'data':data},'response':result};return result
            for i,preset in enumerate(out['config']['give_gold_presets']):assert (await buy('gold_'+str(i),'player.give_item',dict(price=preset['crusticov'],item_type='gold')))['success']
            assert (await buy('catalog_buy','hero.army_create',dict(price=out['config']['action_prices']['hero.army_create'])))['success']
            assert (await buy('upgrade','hero.upgrade_gear',{}))['success']
            assert (await buy('reequip','hero.reequip_gear',{}))['success']
            assert (await buy('discard','hero.discard_item',{'slot':'head'}))['success']
            await sql("UPDATE bannerlord_heroes SET gear_tier=6 WHERE username='alice'")
            out['hero_max_tier']=await route.bannerlord_my_hero(req)
            assert not (await buy('upgrade_refused','hero.upgrade_gear',{}))['success']
            Path(__file__).with_name('commerce-responses.json').write_text(json.dumps({'provenance':{'base':'b83f05a','database':'owned temporary SQLite','live_game':False,'synthetic':'game-like optional catalog, observed class/tier'},'responses':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('COMMERCE_FIXTURES_OK',len(out))
        finally:await db._pool.close()
asyncio.run(main())
