"""Real game route replies, disposable SQLite, all outward messaging disabled."""
import asyncio,atexit,copy,json,os,socket,sys,tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();sys.dont_write_bytecode=True
cfg=tempfile.TemporaryDirectory(prefix='community-game-config-');atexit.register(cfg.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(cfg.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_tugofwar import _build_db,CHANNEL_ID
class Request:
    def __init__(self,data=None):self.data=data or {}
    async def json(self):return self.data
class OfflineBot:
    async def send_message(self,*args,**kwargs):pass
    async def check_and_unlock_achievements(self,*args,**kwargs):pass
async def main():
    with tempfile.TemporaryDirectory(prefix='community-games-') as tmp:
        db=await _build_db(str(Path(tmp)/'fixture.db'))
        try:
            from routes import match,rps,tictactoe as ttt,tugofwar as tug,duel
            import pubsub
            import dependencies
            dependencies.require_jwt_channel=lambda _:CHANNEL_ID
            dependencies.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            pubsub.broadcast=lambda *a,**kw:None
            for route in (match,rps,ttt,tug,duel):
                route.require_jwt_user=lambda _:('alice',CHANNEL_ID)
                route.require_jwt_channel=lambda _:CHANNEL_ID
                route.get_bot=lambda:OfflineBot()
            out={'duels':await duel.list_duels(Request()),'rps_leaderboard':await duel.duel_leaderboard(Request()),'ttt_leaderboard':await ttt.tictactoe_leaderboard(Request()),'tug_status_idle':await tug.http_status(Request())}
            async def sql(q,args=()):
                async with db._connect() as conn:await conn.execute(q,args);await conn.commit()
            for game in ('rps','tictactoe','tug'):
                req=Request({'game_type':game})
                out[game+'_idle']=await match.match_queue_status(req,game)
                out[game+'_join']=await match.match_queue_enqueue(req)
                out[game+'_queued']=await match.match_queue_status(req,game)
                out[game+'_duplicate']=await match.match_queue_enqueue(req)
                out[game+'_cancel']=await match.match_queue_cancel(req)
                rid='fixture-'+game
                # Same empty room state produced by matchmaking, not client-authored rules.
                await sql("INSERT INTO match_rooms(room_id,channel_id,game_type,player_a,player_b,player_a_elo,player_b_elo,state,status) VALUES(?,?,?,'alice','bob',1000,1073,'{}','active')",(rid,CHANNEL_ID,game))
                out[game+'_matched']=await match.match_queue_status(req,game)
                if game=='tug':
                    out['tug_active']=await tug.http_status(req)
                    out['tug_pull']=await tug.http_pull(Request({'taps':3}))
                    out['tug_after']=await tug.http_status(req)
                    await sql("UPDATE match_rooms SET status='finished',outcome='win_a',winner='alice' WHERE room_id=?",(rid,))
                    out['tug_finished']=await tug.http_status(req)
                else:
                    poll=rps.rps_poll if game=='rps' else ttt.tictactoe_poll
                    move=rps.rps_move if game=='rps' else ttt.tictactoe_move
                    out[game+'_active']=await poll(req,rid)
                    # Poll's lazy initial state is not persisted; persist its exact observed state.
                    state=copy.deepcopy(out[game+'_active']['room']['state'])
                    if game=='tictactoe':state['boards'][-1]['next_turn']='a'
                    await sql('UPDATE match_rooms SET state=? WHERE room_id=?',(json.dumps(state),rid))
                    out[game+'_active']=await poll(req,rid)
                    body={'room_id':rid,**({'move':'rock'} if game=='rps' else {'cell':5})}
                    out[game+'_move']=await move(Request(body))
                    assert out[game+'_move']['success'],out[game+'_move']
                    out[game+'_after']=await poll(req,rid)
                    out[game+'_refused']=await move(Request(body))
                    state=copy.deepcopy(out[game+'_after']['room']['state']);state['phase']='finished';state['wins']={'a':2,'b':0}
                    await sql("UPDATE match_rooms SET state=?,status='finished',winner='alice',outcome='win_a' WHERE room_id=?",(json.dumps(state),rid))
                    out[game+'_finished']=await poll(req,rid)
            Path(__file__).with_name('community-game-responses.json').write_text(json.dumps({'provenance':{'base':'c11b1f2','database':'owned temporary SQLite','network':'no outgoing messaging, fixture-only','synthetic':'matchmaker-like rooms and finished-state seed; actual route serialization'},'responses':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('COMMUNITY_GAME_FIXTURES_OK',len(out))
        finally:await db._pool.close()
asyncio.run(main())
