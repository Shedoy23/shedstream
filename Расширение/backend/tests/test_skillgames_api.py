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


if __name__ == '__main__': unittest.main(verbosity=2)
