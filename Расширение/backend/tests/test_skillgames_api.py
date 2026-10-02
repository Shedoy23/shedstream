"""Standalone real-ASGI regressions for isolated server-authoritative skill games.
Run: python tests/test_skillgames_api.py. No Twitch, production DB or bot calls.
"""
import asyncio
import base64
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault('TWITCH_OAUTH_TOKEN', 'oauth:test')
os.environ.setdefault('TWITCH_CLIENT_ID', 'test_client')
os.environ.setdefault('TWITCH_CLIENT_SECRET', 'test_secret')
os.environ.setdefault('TWITCH_BOT_ID', 'test_bot')
os.environ.setdefault('TWITCH_EXTENSION_SECRET', base64.b64encode(b'test-skillgames-secret-32-bytes!!!').decode())
os.environ.setdefault('MODULE_TOKEN_SECRET', 'test-module-secret-32bytes-1234567890')
os.environ.setdefault('ADMIN_PASSWORD', 'test_admin_password_for_tests_only')
os.environ.setdefault('TWITCH_BROADCASTER_ID', '98319857')
os.environ.setdefault('RIMWORLD_PRICES_PATH', str(Path(tempfile.gettempdir()) / 'skillgames-test-prices.json'))


class SkillgamesHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            from routes import skillgames
            from migrations import m135_skillgames
            from skillgames.service import SkillgameService
        except ImportError as exc:
            self.fail('New skillgame API is missing: cannot safely persist hidden boards, scoped sessions and exactly-once results: ' + str(exc))
        import aiosqlite
        import auth
        import dependencies
        import httpx
        from routes import match
        from database import Database
        from fastapi import FastAPI
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'skillgames.db')
        class DB:
            get_room = Database.get_room

            @asynccontextmanager
            async def _connect(inner):
                async with aiosqlite.connect(self.path, timeout=10) as conn:
                    yield conn
        self.db = DB()
        async with self.db._connect() as conn:
            await conn.executescript('''
                CREATE TABLE duel_stats(channel_id INTEGER, username TEXT, game_type TEXT, elo INTEGER DEFAULT 1100, win_streak INTEGER DEFAULT 0, season_id INTEGER DEFAULT 1, updated_at TEXT, PRIMARY KEY(channel_id,username,game_type));
                CREATE TABLE duel_seasons(id INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER,game_type TEXT,started_at TEXT,ends_at TEXT,finished INTEGER DEFAULT 0);
                CREATE TABLE viewers(channel_id INTEGER,username TEXT,points INTEGER DEFAULT 0,PRIMARY KEY(channel_id,username));
                CREATE TABLE match_rooms(room_id TEXT PRIMARY KEY,channel_id INTEGER,game_type TEXT,player_a TEXT,player_b TEXT,player_a_elo INTEGER,player_b_elo INTEGER,state TEXT,status TEXT,winner TEXT,outcome TEXT,created_at TEXT,finished_at TEXT);
                INSERT INTO viewers VALUES(11,'alice',1234),(11,'bobby',987),(22,'alice',4321);
            ''')
            await m135_skillgames.apply(conn)
            await m135_skillgames.apply(conn)
        self.service = SkillgameService(self.db)
        self.patchers = [patch.object(skillgames, 'get_service', return_value=self.service),
                         patch.object(match, 'get_db', return_value=self.db),
                         patch.object(dependencies, 'is_channel_registered', return_value=True),
                         patch.object(dependencies, 'is_channel_approved', return_value=True),
                         patch.object(dependencies, '_check_request_rate_limit')]
        for p in self.patchers: p.start()
        self.secret = base64.b64decode(auth.TWITCH_EXTENSION_SECRET)
        app = FastAPI()
        app.include_router(skillgames.router)
        app.include_router(match.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    async def asyncTearDown(self):
        if hasattr(self, 'client'): await self.client.aclose()
        if hasattr(self, 'service'): await self.service.close()
        for p in getattr(self, 'patchers', []): p.stop()
        if hasattr(self, 'tmp'): self.tmp.cleanup()

    def headers(self, user='alice', channel=11):
        import jwt
        claims = {'sub':user,'exp':int(time.time())+3600,'user_id':user+'id','role':'viewer'}
        if channel is not None: claims['channel_id'] = str(channel)
        return {'X-Twitch-JWT':jwt.encode(claims,self.secret,algorithm='HS256')}

    async def call(self, method, path, body=None, user='alice', channel=11, code=200):
        response = await self.client.request(method,'/api/skillgames'+path,json=body,headers=self.headers(user,channel))
        self.assertEqual(response.status_code,code,response.text)
        return response.json()

    def rows(self, sql, args=()):
        with sqlite3.connect(self.path) as conn: return conn.execute(sql,args).fetchall()

    async def start(self,user='alice',channel=11,mode='ranked'):
        body = dict(game_type='minesweeper',mode=mode,difficulty='beginner',request_id=str(uuid.uuid4()))
        result = await self.call('POST','/start',body,user,channel)
        return result['session']

    async def action(self, session, action, user='alice', channel=11, code=200, **values):
        body = dict(session_id=session['id'],version=session['version'],request_id=str(uuid.uuid4()),action=action,**values)
        result = await self.call('POST','/action',body,user,channel,code)
        return result.get('session',result)

    async def test_auth_bounds_and_server_config(self):
        result = await self.call('GET','/config')
        self.assertEqual({x['game_type'] for x in result['catalog']},{'battleship','minesweeper'})
        self.assertTrue(all(not x['rewards']['enabled'] for x in result['catalog']))
        self.assertTrue(all(x['rating']['initial']==1000 for x in result['catalog']))
        await self.call('GET','/state',channel=None,code=401)
        bad = dict(game_type='minesweeper',mode='ranked',difficulty='beginner',request_id='good-id-123',username='bobby')
        await self.call('POST','/start',bad,code=422)
        session = await self.start()
        await self.action(session,'open',cell=True,code=422)
        await self.action(session,'open',cell=36,code=422)
        await self.action(session,'open',cell=-1,code=422)
        await self.call('POST','/start',dict(bad,username='alice',channel_id=22),code=422)

    async def test_resume_secrecy_channels_and_practice(self):
        session = await self.start()
        self.assertEqual(session['status'],'awaiting_first_move')
        self.assertIsNone(session['started_at'])
        self.assertIsNone(session['expires_at'])
        self.assertEqual((await self.start())['id'],session['id'])
        self.assertEqual((await self.call('GET','/state'))['active_session']['id'],session['id'])
        await self.call('GET','/state?session_id='+session['id'],user='bobby',code=404)
        await self.action(session,'open',channel=22,cell=0,code=404)
        other = await self.start(channel=22)
        self.assertNotEqual(session['id'],other['id'])
        opened = await self.action(session,'open',cell=0)
        public = json.dumps(opened)
        for secret in ('"mines"','"seed"','"certification"'): self.assertNotIn(secret,public)
        self.assertEqual(opened['version'],session['version']+1)
        self.assertIsNotNone(opened['started_at'])
        self.assertFalse(self.rows('SELECT * FROM match_rooms'))
        practice = await self.start(user='bobby',mode='practice')
        practice = await self.action(practice,'open',user='bobby',cell=0)
        if practice['status']=='active': await self.action(practice,'quit',user='bobby')
        self.assertFalse(self.rows("SELECT * FROM duel_stats WHERE username='bobby'"))
        self.assertEqual(self.rows('SELECT points FROM viewers WHERE channel_id=11 AND username=?',('alice',)),[(1234,)])

    async def test_retry_race_and_exactly_once_loss(self):
        session = await self.start()
        session = await self.action(session,'open',cell=0)
        if session['status']=='finished': self.skipTest('Generated first click solved puzzle')
        body = dict(session_id=session['id'],version=session['version'],request_id='same-forfeit-id',action='quit')
        a,b = await asyncio.gather(self.call('POST','/action',body),self.call('POST','/action',body))
        self.assertEqual(a,b)
        self.assertEqual(a['session']['result']['outcome'],'loss')
        self.assertEqual(self.rows('SELECT COUNT(*) FROM skillgame_results WHERE channel_id=11'),[(1,)])
        self.assertEqual(self.rows("SELECT elo FROM duel_stats WHERE channel_id=11 AND username='alice' AND game_type='minesweeper'"),[(984,)])
        await self.call('POST','/action',dict(body,action='restart'),code=409)
        await self.action(session,'flag',cell=35,code=409)

    async def test_battleship_queue_race_and_private_projection(self):
        a,b = await asyncio.gather(self.call('POST','/queue',{'request_id':'queue-alice'}),self.call('POST','/queue',{'request_id':'queue-bobby'},user='bobby'))
        alice = (await self.call('GET','/state'))['active_session']
        bob = (await self.call('GET','/state',user='bobby'))['active_session']
        self.assertEqual(alice['id'],bob['id'])
        self.assertEqual(alice['game_type'],'battleship')
        await self.start(channel=22)
        await self.call('POST','/start',dict(game_type='minesweeper',mode='ranked',difficulty='beginner',request_id='blocked-start'),code=409)
        alice = await self.action(alice,'autoplace')
        bob = (await self.call('GET','/state',user='bobby'))['active_session']
        bob = await self.action(bob,'autoplace',user='bobby')
        self.assertNotIn('fleets',json.dumps(bob))
        self.assertNotIn('mines',json.dumps(bob))
        self.assertFalse(self.rows('SELECT * FROM match_rooms'))


    async def test_signed_authentication_and_body_limits(self):
        import jwt
        bad = jwt.encode({'sub':'alice','channel_id':'11','exp':int(time.time())+60},b'wrong-secret-key-32-bytes-long!!!',algorithm='HS256')
        response = await self.client.get('/api/skillgames/state',headers={'X-Twitch-JWT':bad})
        self.assertEqual(response.status_code,401)
        response = await self.client.get('/api/skillgames/state')
        self.assertEqual(response.status_code,401)
        response = await self.client.post('/api/skillgames/start',content=b'x'*4097,headers=self.headers())
        self.assertEqual(response.status_code,413)
        response = await self.client.post('/api/skillgames/start',content=b'{broken',headers=self.headers())
        self.assertEqual(response.status_code,422)
        await self.call('POST','/start',dict(game_type='minesweeper',mode='ranked',difficulty='impossible',request_id='no-such-tier'),code=422)
        await self.call('POST','/queue',dict(request_id='no-money-ever',amount=100),code=422)

    async def test_one_active_session_concurrency_and_queue_cancel(self):
        body = dict(game_type='minesweeper',mode='ranked',difficulty='beginner',request_id='concurrent-start')
        a,b = await asyncio.gather(self.call('POST','/start',body),self.call('POST','/start',body))
        self.assertEqual(a,b)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM skillgame_sessions WHERE channel_id=11'),[(1,)])
        await self.call('POST','/start',dict(body,request_id='cannot-practice',mode='practice'),code=409)
        await self.call('POST','/queue',dict(request_id='cannot-queue-now'),code=409)
        cancelled = await self.action(a['session'],'quit')
        self.assertEqual(cancelled['status'],'void')
        self.assertFalse(self.rows('SELECT * FROM duel_stats'))
        await self.call('POST','/queue',dict(request_id='real-queue-join'))
        await self.call('POST','/queue/cancel',dict(request_id='real-queue-cancel'))
        self.assertEqual((await self.call('GET','/state'))['queue']['status'],'idle')
        self.assertFalse(self.rows('SELECT * FROM skillgame_queue WHERE channel_id=11'))

    async def test_generation_is_async_reserved_and_failure_is_void(self):
        import threading
        from skillgames import minesweeper
        original = minesweeper.initialize
        entered, release = threading.Event(), threading.Event()
        calls = []
        def slow(*args,**kwargs):
            calls.append(args)
            entered.set()
            release.wait(2)
            return original(*args,**kwargs)
        session = await self.start()
        body = dict(session_id=session['id'],version=0,request_id='first-cell-reserve',action='open',cell=0)
        with patch.object(minesweeper,'initialize',side_effect=slow):
            task = asyncio.create_task(self.call('POST','/action',body))
            for _ in range(100):
                if entered.is_set(): break
                await asyncio.sleep(.01)
            self.assertTrue(entered.is_set())
            current = await asyncio.wait_for(self.call('GET','/state'),timeout=.5)
            self.assertEqual(current['active_session']['status'],'generating')
            await self.call('POST','/action',dict(body,request_id='second-firstcell'),code=409)
            release.set()
            completed = await task
        self.assertEqual(len(calls),1)
        self.assertEqual(completed['session']['version'],1)
        await self.action(completed['session'],'quit')
        session = await self.start()
        with patch.object(minesweeper,'initialize',side_effect=minesweeper.GenerationError('bounded failure')):
            failure = await self.action(session,'open',cell=0,code=503)
        self.assertEqual(failure['status'],'void')
        self.assertEqual(failure['result']['reason'],'generation_failed')
        self.assertEqual(self.rows("SELECT elo FROM duel_stats WHERE channel_id=11 AND username='alice'"),[(984,)])

    async def test_attempt_expiry_restart_and_service_restart(self):
        from skillgames.service import SkillgameService
        from routes import skillgames as route
        session = await self.action(await self.start(),'open',cell=0)
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE skillgame_sessions SET expires_at=? WHERE channel_id=? AND id=?',(time.time()-1,11,session['id']))
        expired = (await self.call('GET','/state'))['active_session']
        self.assertEqual(expired['result']['reason'],'attempt_expired')
        self.assertEqual(expired['result']['rating']['delta'],-16)
        self.assertEqual((await self.call('GET','/state'))['active_session'],expired)
        session = await self.action(await self.start(),'open',cell=0)
        oldrating = self.rows("SELECT elo FROM duel_stats WHERE channel_id=11 AND username='alice'")
        other_worker = SkillgameService(self.db)
        try:
            with patch.object(route,'get_service',return_value=other_worker):
                live = (await self.call('GET','/state'))['active_session']
                self.assertEqual(live['status'],'active','A second live worker must not void another worker sessions')
                await self.service.close()
                resumed = (await self.call('GET','/state'))['active_session']
                self.assertEqual(resumed['status'],'void')
                self.assertEqual(resumed['result']['reason'],'service_unavailable')
                self.assertEqual(self.rows("SELECT elo FROM duel_stats WHERE channel_id=11 AND username='alice'"),oldrating)
        finally:
            await other_worker.close()

    async def test_snapshot_season_rollover_and_no_legacy_prizes(self):
        from skillgames import config
        from routes import duel
        session = await self.start()
        with patch.object(config,'ATTEMPT_SECONDS',1),patch.object(config,'ELO_K',64):
            opened = await self.action(session,'open',cell=0)
            self.assertEqual(opened['rules']['rating']['k'],32)
            self.assertAlmostEqual(opened['expires_at']-opened['started_at'],600)
            result = await self.action(opened,'restart')
        self.assertEqual(result['result']['rating']['delta'],-16)
        session = await self.action(await self.start(),'open',cell=0)
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE duel_seasons SET ends_at='2000-01-01T00:00:00+00:00' WHERE channel_id=11 AND game_type='minesweeper'")
        with patch.object(duel,'get_db',return_value=self.db):
            await duel.check_season_end(11,'minesweeper')
        state = (await self.call('GET','/state'))['active_session']
        self.assertEqual(state['status'],'void')
        self.assertEqual(state['result']['reason'],'season_changed')
        self.assertEqual(self.rows("SELECT elo FROM duel_stats WHERE channel_id=11 AND username='alice'"),[(1000,)])
        self.assertEqual(self.rows('SELECT points FROM viewers WHERE channel_id=11 AND username=?',('alice',)),[(1234,)])
        self.assertEqual(self.rows('SELECT reason FROM skillgame_season_closures WHERE channel_id=11'),[('rewards_not_calibrated',)])
        self.assertFalse(self.rows('SELECT * FROM duel_stats WHERE channel_id=22'))

    async def test_finalization_failure_rolls_back_rating_and_voids_attempt(self):
        from routes import duel
        session = await self.action(await self.start(),'open',cell=0)
        with patch.object(duel,'_update_stats',side_effect=RuntimeError('simulated write interruption')):
            response = await self.action(session,'quit',code=503)
        self.assertEqual(response['reason'],'service_unavailable')
        current = (await self.call('GET','/state'))['active_session']
        self.assertEqual(current['status'],'void')
        self.assertFalse(self.rows('SELECT * FROM duel_stats'))
        self.assertEqual(self.rows('SELECT outcome,reason FROM skillgame_results WHERE channel_id=11'),[('void','service_unavailable')])

    async def test_real_battleship_finish_and_duplicate_final_shot(self):
        await self.call('POST','/queue',dict(request_id='battle-alice-join'))
        await self.call('POST','/queue',dict(request_id='battle-bobby-join'),user='bobby')
        for user in ('alice','bobby'):
            session = (await self.call('GET','/state',user=user))['active_session']
            session = await self.action(session,'autoplace',user=user)
            await self.action(session,'ready',user=user)
        raw = json.loads(self.rows('SELECT secret_state FROM skillgame_sessions WHERE channel_id=11')[0][0])
        targets = {'alice':sorted(c for ship in raw['fleets']['bobby'] for c in ship),
                   'bobby':sorted(set(range(36))-{c for ship in raw['fleets']['alice'] for c in ship})}
        final_body = None
        for _ in range(20):
            alice = (await self.call('GET','/state'))['active_session']
            if alice['status']=='finished': break
            user = 'alice' if alice['state']['your_turn'] else 'bobby'
            current = alice if user=='alice' else (await self.call('GET','/state',user=user))['active_session']
            body = dict(session_id=current['id'],version=current['version'],request_id=str(uuid.uuid4()),action='fire',cell=targets[user].pop(0))
            shot = await self.call('POST','/action',body,user=user)
            if shot['session']['status']=='finished':
                final_body, final_response = body,shot
                break
        self.assertIsNotNone(final_body)
        self.assertEqual(final_response['session']['result']['winner'],'alice')
        self.assertEqual(final_response,await self.call('POST','/action',final_body))
        self.assertEqual(self.rows("SELECT username,elo FROM duel_stats WHERE channel_id=11 AND game_type='battleship' ORDER BY username"),[('alice',1016),('bobby',984)])
        self.assertEqual(self.rows('SELECT COUNT(*) FROM skillgame_results WHERE channel_id=11'),[(1,)])
        bob = (await self.call('GET','/state',user='bobby'))['active_session']
        self.assertEqual(bob['result']['outcome'],'loss')
        self.assertNotIn('fleets',json.dumps(bob))
        self.assertEqual(self.rows('SELECT points FROM viewers WHERE channel_id=11 ORDER BY username'),[(1234,),(987,)])

    async def test_prestart_setup_and_turn_timeout_policies(self):
        await self.call('POST','/queue',dict(request_id='timeout-alice-join'))
        await self.call('POST','/queue',dict(request_id='timeout-bobby-join'),user='bobby')
        session = (await self.call('GET','/state'))['active_session']
        session = await self.action(session,'autoplace')
        session = await self.action(session,'ready')
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE skillgame_sessions SET expires_at=? WHERE channel_id=11 AND id=?',(time.time()-1,session['id']))
        result = (await self.call('GET','/state'))['active_session']
        self.assertEqual(result['result']['winner'],'alice')
        self.assertEqual(result['result']['reason'],'setup_expired')
        self.assertEqual(result['result']['rating']['delta'],16)
        await self.call('POST','/queue',dict(request_id='turn-alice-join'))
        await self.call('POST','/queue',dict(request_id='turn-bobby-join'),user='bobby')
        for user in ('alice','bobby'):
            session = (await self.call('GET','/state',user=user))['active_session']
            session = await self.action(session,'autoplace',user=user)
            await self.action(session,'ready',user=user)
        session = (await self.call('GET','/state'))['active_session']
        loser = 'alice' if session['state']['your_turn'] else 'bobby'
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE skillgame_sessions SET expires_at=? WHERE channel_id=11 AND id=?',(time.time()-1,session['id']))
        result = (await self.call('GET','/state'))['active_session']
        self.assertEqual(result['result']['reason'],'turn_expired')
        self.assertNotEqual(result['result']['winner'],loser)


    async def test_expiry_waits_for_positive_uptime_evidence(self):
        session = await self.action(await self.start(),'open',cell=0)
        now = time.time()
        # Original process disappeared just before expiry. Its lease is still
        # within grace, but no heartbeat proves the server reached the deadline.
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE skillgame_sessions SET expires_at=? WHERE channel_id=11 AND id=?',(now-.1,session['id']))
            conn.execute('UPDATE skillgame_runtimes SET last_seen=? WHERE runtime_id=?',(now-1,self.service.runtime_id))
        observed = (await self.call('GET','/state'))['active_session']
        self.assertEqual(observed['status'],'active','A fresh-looking old lease is not evidence that service survived the deadline')
        self.assertFalse(self.rows('SELECT * FROM duel_stats'))
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE skillgame_runtimes SET last_seen=? WHERE runtime_id=?',(now-20,self.service.runtime_id))
        observed = (await self.call('GET','/state'))['active_session']
        self.assertEqual(observed['status'],'void')
        self.assertEqual(observed['result']['reason'],'service_unavailable')
        self.assertFalse(self.rows('SELECT * FROM duel_stats'))


    async def test_generic_room_endpoint_cannot_see_private_boards(self):
        session = await self.action(await self.start(),'open',cell=0)
        response = await self.client.get('/api/match/room/'+session['id']+'/state',headers=self.headers())
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['success'])
        self.assertNotIn('mines',response.text)
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO match_rooms(room_id,channel_id,game_type,player_a,player_b,player_a_elo,player_b_elo,state,status) VALUES (?,?,?,?,?,?,?,?,?)",('old-rps-room',11,'rps','alice','bobby',1000,1000,'{}','active'))
        response = await self.client.get('/api/match/room/old-rps-room/state',headers=self.headers())
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['room']['game_type'],'rps')
        other = await self.client.get('/api/match/room/old-rps-room/state',headers=self.headers(channel=22))
        self.assertFalse(other.json()['success'])

    async def test_real_mines_win_difficulty_and_old_rating_isolation(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO duel_stats(channel_id,username,game_type,elo,win_streak,season_id) VALUES (11,'alice','rps',1555,7,99)")
        start = dict(game_type='minesweeper',mode='ranked',difficulty='advanced',request_id='advanced-rated-start')
        session = (await self.call('POST','/start',start))['session']
        session = await self.action(session,'open',cell=0)
        secret = json.loads(self.rows('SELECT secret_state FROM skillgame_sessions WHERE channel_id=11 AND id=?',(session['id'],))[0][0])
        for cell in range(36):
            if session['status']=='finished': break
            if cell not in secret['mines'] and str(cell) not in session['state']['opened']:
                session = await self.action(session,'open',cell=cell)
        self.assertEqual(session['status'],'finished')
        self.assertEqual(session['result']['outcome'],'win')
        self.assertEqual(session['result']['rating'],{'before':1000,'after':1024,'delta':24})
        self.assertEqual(self.rows("SELECT elo,win_streak FROM duel_stats WHERE channel_id=11 AND username='alice' AND game_type='rps'"),[(1555,7)])
        self.assertFalse(self.rows("SELECT * FROM duel_stats WHERE game_type='battleship' OR channel_id=22"))
        for secret_key in ('mines','certification','generation','seed'):
            self.assertNotIn('"'+secret_key+'"',json.dumps(session))
        self.assertEqual(self.rows('SELECT points FROM viewers WHERE channel_id=11 AND username=?',('alice',)),[(1234,)])


    async def test_stale_generation_reservations_cannot_block_channel(self):
        alice, bob = await self.start(), await self.start(user='bobby')
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO skillgame_runtimes VALUES('dead-owner',0)")
            conn.execute("UPDATE skillgame_sessions SET status='generating',runtime_id='dead-owner',expires_at=? WHERE channel_id=11",(time.time()+600,))
        charlie = await self.start(user='charlie')
        opened = await self.action(charlie,'open',user='charlie',cell=0)
        self.assertEqual(opened['status'],'active')
        self.assertEqual(self.rows("SELECT COUNT(*) FROM skillgame_sessions WHERE channel_id=11 AND status='generating'"),[(0,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM skillgame_results WHERE channel_id=11 AND outcome='void'"),[(2,)])
        self.assertFalse(self.rows('SELECT * FROM duel_stats'))

    async def test_auth_policy_preserves_forbidden_and_retry_after(self):
        import dependencies
        with patch.object(dependencies,'is_channel_approved',return_value=False):
            result = await self.call('GET','/state',code=403)
        self.assertEqual(result['detail']['status'],'channel_pending_approval')
        with patch.object(dependencies,'is_channel_registered',return_value=False):
            result = await self.call('GET','/state',code=403)
        self.assertEqual(result['detail']['status'],'channel_not_registered')
        def limited(*args):
            dependencies._raise_channel_rate_limited(11,retry_after=17)
        with patch.object(dependencies,'_check_request_rate_limit',side_effect=limited):
            response = await self.client.get('/api/skillgames/state',headers=self.headers())
        self.assertEqual(response.status_code,429)
        self.assertEqual(response.headers.get('retry-after'),'17')

    async def test_receipts_have_bounded_retention_and_terminal_replay_safety(self):
        from skillgames import config
        with patch.object(config,'REQUEST_RETENTION_SECONDS',10,create=True),patch.object(config,'MAX_RECEIPTS_PER_USER',3,create=True):
            first = {'request_id':'first-bounded-cancel'}
            response = await self.call('POST','/queue/cancel',first)
            await self.call('POST','/queue/cancel',{'request_id':'second-bounded-cancel'})
            await self.call('POST','/queue/cancel',{'request_id':'third-bounded-cancel'})
            self.assertEqual(response,await self.call('POST','/queue/cancel',first))
            await self.call('POST','/queue/cancel',{'request_id':'fourth-bounded-cancel'},code=429)
            self.assertEqual(self.rows('SELECT COUNT(*) FROM skillgame_requests WHERE channel_id=11'),[(3,)])
            with sqlite3.connect(self.path) as conn:
                conn.execute('UPDATE skillgame_requests SET created_at=? WHERE channel_id=11',(time.time()-20,))
            await self.call('POST','/queue/cancel',{'request_id':'after-receipt-expiry'})
            self.assertEqual(self.rows('SELECT COUNT(*) FROM skillgame_requests WHERE channel_id=11'),[(1,)])
        session = await self.action(await self.start(),'open',cell=0)
        body = dict(session_id=session['id'],version=session['version'],request_id='expired-result-retry',action='quit')
        await self.call('POST','/action',body)
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE skillgame_requests SET created_at=0 WHERE channel_id=11')
        await self.call('POST','/action',body,code=409)
        self.assertEqual(self.rows("SELECT elo FROM duel_stats WHERE channel_id=11 AND username='alice'"),[(984,)])
        self.assertEqual(self.rows('SELECT COUNT(*) FROM skillgame_results WHERE channel_id=11'),[(1,)])


    async def test_disabled_game_prevents_new_entries_but_preserves_resume(self):
        from skillgames import config
        session = await self.start()
        disabled = {'minesweeper':{'enabled':False,'reason':'Техническая пауза'},'battleship':{'enabled':False,'reason':'Техническая пауза'}}
        with patch.object(config,'GAME_AVAILABILITY',disabled,create=True):
            catalog = (await self.call('GET','/config'))['catalog']
            self.assertTrue(all(not item['availability']['enabled'] for item in catalog))
            self.assertEqual((await self.start())['id'],session['id'])
            session = await self.action(session,'open',cell=0)
            await self.action(session,'quit')
            body = dict(game_type='minesweeper',mode='practice',difficulty='beginner',request_id='disabled-new-start')
            result = await self.call('POST','/start',body,code=409)
            self.assertEqual(result['reason'],'game_unavailable')
            self.assertEqual(result['message'],'Техническая пауза')
            await self.call('POST','/queue',{'request_id':'disabled-new-queue'},code=409)

    async def test_private_session_retention_preserves_result_audit(self):
        from skillgames import config
        session = await self.action(await self.start(),'open',cell=0)
        session = await self.action(session,'quit')
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE skillgame_sessions SET created_at=0 WHERE channel_id=11 AND id=?',(session['id'],))
        with patch.object(config,'SESSION_RETENTION_SECONDS',10,create=True):
            await self.call('POST','/queue/cancel',{'request_id':'trigger-history-cleanup'})
        self.assertFalse(self.rows('SELECT * FROM skillgame_sessions WHERE channel_id=11'))
        self.assertFalse(self.rows('SELECT * FROM skillgame_players WHERE channel_id=11'))
        self.assertEqual(self.rows('SELECT COUNT(*) FROM skillgame_results WHERE channel_id=11'),[(1,)])
        self.assertEqual(self.rows("SELECT elo FROM duel_stats WHERE channel_id=11 AND username='alice'"),[(984,)])


    async def test_declared_dependency_excludes_incompatible_pydantic_v1(self):
        import pydantic
        requirements = []
        for line in (BACKEND / 'requirements.txt').read_text().splitlines():
            line = line.split('#',1)[0].strip()
            if line:
                requirements.append(line)
        declared = [r for r in requirements if r.lower().startswith('pydantic==')]
        self.assertEqual(len(declared),1,'The API uses Pydantic v2-only validation, so v2 must be an explicit runtime dependency')
        self.assertTrue(pydantic.__version__.startswith('2.'),'The actual imported runtime must be v2')
        self.assertEqual(declared[0], 'pydantic=='+pydantic.__version__,'Runtime pin must match the validated installed version')
        from routes.skillgames import Action
        body = Action.model_validate_json(b'{"session_id":"abcdefgh","version":0,"request_id":"abcdefgh","action":"open","cell":0}')
        self.assertEqual(body.model_dump()['cell'],0)


if __name__ == '__main__': unittest.main(verbosity=2)
