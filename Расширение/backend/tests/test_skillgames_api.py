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
        from fastapi import FastAPI
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'skillgames.db')
        class DB:
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
                CREATE TABLE match_rooms(room_id TEXT PRIMARY KEY,channel_id INTEGER,game_type TEXT,state TEXT);
                INSERT INTO viewers VALUES(11,'alice',1234),(11,'bobby',987),(22,'alice',4321);
            ''')
            await m135_skillgames.apply(conn)
            await m135_skillgames.apply(conn)
        self.service = SkillgameService(self.db)
        self.patchers = [patch.object(skillgames, 'get_service', return_value=self.service),
                         patch.object(dependencies, 'is_channel_registered', return_value=True),
                         patch.object(dependencies, 'is_channel_approved', return_value=True),
                         patch.object(dependencies, '_check_request_rate_limit')]
        for p in self.patchers: p.start()
        self.secret = base64.b64decode(auth.TWITCH_EXTENSION_SECRET)
        app = FastAPI()
        app.include_router(skillgames.router)
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


if __name__ == '__main__': unittest.main(verbosity=2)
