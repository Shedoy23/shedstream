"""Real RimWorld handlers on an owned temporary DB; no production/game traffic."""
import asyncio,atexit,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();sys.dont_write_bytecode=True
config=tempfile.TemporaryDirectory(prefix='rw-port-config-');atexit.register(config.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(config.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_tugofwar import _build_db,CHANNEL_ID
class Request:
    def __init__(self,data=None):self.data=data if data is not None else {}
    async def json(self):return self.data
class OfflineBot:
    async def touch_viewer(self,*args,**kwargs):pass
    async def send_message(self,*args,**kwargs):pass
    async def check_and_unlock_achievements(self,*args,**kwargs):pass
async def main():
    with tempfile.TemporaryDirectory(prefix='rw-port-') as tmp:
        db=await _build_db(str(Path(tmp)/'fixture.db'))
        try:
            import rimworld as rw,dependencies,pubsub,main
            main.bot=OfflineBot()
            dependencies.set_request_channel_id(CHANNEL_ID)
            dependencies.get_bot=lambda:OfflineBot();pubsub.broadcast=lambda *a,**kw:None
            rw.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            rw.require_jwt_channel=lambda _:CHANNEL_ID
            async def live(*args):return None
            rw._require_stream_live=live
            async def sql(q,args=()):
                async with db._connect() as conn:await conn.execute(q,args);await conn.commit()
            await sql("UPDATE channels SET active_module='rimworld',approved=1 WHERE channel_id=?",(CHANNEL_ID,))
            await sql("UPDATE viewers SET points=1000000 WHERE username='alice'")
            out={'config':await rw.rimworld_config(),'empty_pawn':await rw.get_my_pawn('alice',Request())}
            catalog=[
                {'category':'weapon','def_name':'PortSword','label':'Меч поселенца','desc':'Меч из каталога игры','price':713,'tooltip':'Описание меча'},
                {'category':'implant','def_name':'PortArm','label':'Парная рука','price':811,'is_paired':True},
                {'category':'implant','def_name':'PortHeart','label':'Сердце','price':419},
                {'category':'neurotrainer','def_name':'PortTrainer','label':'Урок строительства','price':317},
                {'category':'trait','def_name':'PortTrait:1','label':'Упорный','price':rw.BASE_TRAIT_PRICE,'base_price':rw.BASE_TRAIT_PRICE,'trait_def':'PortTrait','degree':1},
                {'category':'gene','def_name':'PortGene','label':'Зоркость','price':rw.BASE_GENE_PRICE,'base_price':rw.BASE_GENE_PRICE},
                {'category':'xenotype','def_name':'PortXeno','label':'Путник','price':1211,'source_mod':'Fixture Colony','has_archite':False,'genes':[{'def_name':'PortGene','label':'Зоркость'}]},
            ]
            assert (await rw.receive_shop_catalog(Request(catalog),CHANNEL_ID))['status']=='ok'
            assert (await rw.sync_event_catalog(Request([{'id':'mod-event','name':'Гости из долины','cost':613,'cmd':'visitor','params':{},'category':'Гости'}]),CHANNEL_ID))['success']
            pawn={'username':'alice','pawn_name':'Алиса','is_alive':True,'health':0.73,'world_id':'world-A','world_name':'Долина',
                  'equipment':[{'slot':'weapon','def_name':'PortSword','label':'Меч поселенца','hp':61,'max_hp':100,'quality':'excellent','description':'Старый меч','weapon_traits':['Точный']}],
                  'skills':[{'def_name':'Construction','level':9,'passion':1,'xp':137},{'def_name':'Shooting','level':4,'passion':0},{'def_name':'Artistic','level':2,'passion':0,'is_disabled':True}],
                  'traits':[{'def_name':'OldTrait','degree':-1,'label':'Задумчивый','desc':'Из наблюдаемого состояния'}],
                  'genes':[{'def_name':'OldGene','label':'Старый ген','is_active':False,'xenogene':True,'gene_class':'mod-gene'}],
                  'hediffs':[{'part':'торс','label':'Ушиб','severity':0.21,'age_ticks':123}],
                  'implants':[{'def_name':'PortArm','label':'Парная рука','part_def':'Arm','part_label':'левая рука','is_paired':True,'is_left':True}]}
            assert (await rw.sync_pawns_bulk(Request([pawn]),CHANNEL_ID))['status']=='ok'
            out.update(pawn=await rw.get_my_pawn('alice',Request()),colonists=await rw.get_colonists_all(Request()),status=await rw.rimworld_status(Request()),catalog=await rw.get_catalog(Request(),username='alice'),events=await rw.get_events(Request()),skills=await rw.get_pawn_skills('alice',Request()),cooldown=await rw.get_heal_cooldown('alice',Request()))
            for category in ('neurotrainer','xenotype'):
                out[category]=await rw.get_catalog(Request(),category=category,username='alice')
            actions=[('create',rw.create_pawn,{'pawn_name':'alice'}),('heal',rw.heal_pawn,{}),('heal_refused',rw.heal_pawn,{}),('resurrect',rw.resurrect_pawn,{}),
                     ('item',rw.buy_item,{'item_def':'PortSword'}),('implant',rw.buy_implant_alias,{'item_def':'PortHeart'}),('paired_implant',rw.buy_implant_alias,{'item_def':'PortArm','part_hint':'right'}),
                     ('neuro',rw.train_skill_alias,{'item_def':'PortTrainer'}),('xeno',rw.buy_item,{'item_def':'PortXeno','def_name':'PortXeno'}),
                     ('trait',rw.buy_trait,{'trait_def':'PortTrait','degree':1,'expected_price':rw.BASE_TRAIT_PRICE}),('gene',rw.buy_gene,{'def_name':'PortGene','expected_price':rw.BASE_GENE_PRICE}),
                     ('remove_trait',rw.remove_trait,{'trait_def':'OldTrait','degree':-1}),('remove_gene',rw.remove_gene,{'def_name':'OldGene','label':'Старый ген'}),
                     ('passion',rw.buy_passion,{'skill_def':'Shooting','passion':1}),('reset',rw.reset_passion,{'skill_def':'Construction'}),('event',rw.trigger_event,{'event_id':'mod-event'})]
            for name,handler,body in actions:
                out[name]=await handler(Request({'username':'alice',**body}))
                assert bool(out[name].get('success'))==(name!='heal_refused'),(name,out[name])
                if name=='gene':out['catalog_after']=await rw.get_catalog(Request(),username='alice')
            out['catalog_final']=await rw.get_catalog(Request(),username='alice')
            out['cooldown_after']=await rw.get_heal_cooldown('alice',Request())
            await rw.sync_pawns_bulk(Request([{'username':'alice','is_alive':False}]),CHANNEL_ID)
            out['dead_pawn']=await rw.get_my_pawn('alice',Request())
            Path(__file__).with_name('rimworld-responses.json').write_text(json.dumps({'provenance':{'base':'e6abb9b','database':'owned temporary SQLite','outward_messaging':'disabled','catalog':'fictional game fixture ingested through actual mod routes; all prices returned by server'},'responses':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('RIMWORLD_FIXTURES_OK',len(out))
        finally:await db._pool.close()
asyncio.run(main())
