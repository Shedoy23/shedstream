"""Social family route replies and proof of ignored selected proposer; offline DB only."""
import asyncio,atexit,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();sys.dont_write_bytecode=True
cfg=tempfile.TemporaryDirectory(prefix='social-family-config-');atexit.register(cfg.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(cfg.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_tugofwar import _build_db,CHANNEL_ID
class Request:
    def __init__(self,data=None):self.data=data or {}
    async def json(self):return self.data
class OfflineBot:
    async def touch_viewer(self,*args,**kwargs):pass
    async def send_message(self,*args,**kwargs):pass
async def main():
    with tempfile.TemporaryDirectory(prefix='social-family-') as tmp:
        db=await _build_db(str(Path(tmp)/'fixture.db'))
        try:
            from routes import marriage,misc
            import dependencies,pubsub
            dependencies.get_bot=lambda:OfflineBot();pubsub.broadcast=lambda *a,**kw:None
            marriage.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            async def live():return None
            marriage.require_stream_live=live
            async def sql(q,args=()):
                async with db._connect() as conn:await conn.execute(q,args);await conn.commit()
            await sql("UPDATE viewers SET points=1000000 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
            out={'config':await misc.core_config(),'single':await marriage.marriage_status('alice',Request())}
            out['propose']=await marriage.marriage_propose(Request({'username':'alice','target':'bob'}))
            await sql("INSERT INTO marriage_proposals(channel_id,from_user,to_user,created_at) VALUES(?,'bob','alice','2026-10-01 12:00:00')",(CHANNEL_ID,))
            await sql("INSERT INTO marriage_proposals(channel_id,from_user,to_user,created_at) VALUES(?,'carol','alice','2026-10-02 12:00:00')",(CHANNEL_ID,))
            out['proposals']=await marriage.get_proposals('alice',Request())
            chosen={'username':'alice','from_user':'bob'}
            out['accept_wrong_target']={'request':chosen,'response':await marriage.marriage_accept(Request(chosen)),'status':await marriage.marriage_status('alice',Request())}
            assert out['accept_wrong_target']['status']['partner']=='carol','Regression proof changed: re-evaluate accept blocker'
            out['married']=await marriage.marriage_status('alice',Request())
            out['divorce']=await marriage.divorce(Request({'username':'alice'}))
            assert out['divorce']['success']
            out['divorce_refused']=await marriage.divorce(Request({'username':'alice'}))
            await sql("INSERT INTO marriage_proposals(channel_id,from_user,to_user) VALUES(?,'bob','alice')",(CHANNEL_ID,))
            out['reject']=await marriage.marriage_reject(Request({'from_user':'bob'}))
            out['empty_proposals']=await marriage.get_proposals('alice',Request())
            Path(__file__).with_name('social-family-responses.json').write_text(json.dumps({'provenance':{'base':'d5a6fef','database':'owned temporary SQLite','outward_messaging':'disabled','proof':'request.from_user bob produces partner carol; server source unchanged'},'responses':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('SOCIAL_FAMILY_FIXTURES_OK',len(out),'ACCEPT_TARGET_MISMATCH bob -> carol')
        finally:await db._pool.close()
asyncio.run(main())
