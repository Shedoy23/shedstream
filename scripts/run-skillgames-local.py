"""Run real skillgame routes against a disposable database on loopback only.

This is an integration harness, not the production app, Twitch auth, or a fixture
transport. It uses the production engine, routes, service, migration and HS256
JWT verifier. Only users/season base tables and Twitch Helper are synthesized.
No bot, payouts, external calls, real credentials or existing DB are used.

Build frontend-next first, then:
  python scripts/run-skillgames-local.py --allow-local-demo --port 4180
Open two tabs: /extension.html?player=alice and /mobile.html?player=bobby.
Closing this process discards its temporary SQLite database.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'Расширение' / 'backend'
DIST = ROOT / 'frontend-next' / 'dist'


def create_local_app():
    # Deliberately replace rather than inherit production credentials. This
    # function is only reached behind the explicit standalone CLI opt-in.
    secret = secrets.token_bytes(32)
    os.environ.update(TWITCH_EXTENSION_SECRET=base64.b64encode(secret).decode(),
                      MODULE_TOKEN_SECRET=secrets.token_hex(32),
                      SESSION_SECRET=secrets.token_hex(32), DEV_MODE='false',
                      RIMLINK_ENV='local', TWITCH_OAUTH_TOKEN='oauth:local-unused',
                      TWITCH_CLIENT_ID='local-unused', TWITCH_CLIENT_SECRET='local-unused',
                      TWITCH_BOT_ID='local-unused', TWITCH_BROADCASTER_ID='11',
                      ADMIN_PASSWORD=secrets.token_hex(32))
    sys.path.insert(0, str(BACKEND))
    import aiosqlite
    import jwt
    import dependencies
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles
    from migrations import m135_skillgames
    from routes import skillgames
    from skillgames.service import SkillgameService

    @asynccontextmanager
    async def lifespan(app):
        with tempfile.TemporaryDirectory(prefix='shedlink-local-skillgames-') as directory:
            path = Path(directory) / 'disposable.db'
            class LocalDB:
                @asynccontextmanager
                async def _connect(self):
                    async with aiosqlite.connect(path, timeout=10) as connection:
                        try:
                            yield connection
                            await connection.commit()
                        except Exception:
                            await connection.rollback()
                            raise
            db = LocalDB()
            async with db._connect() as connection:
                await connection.executescript('''
                  PRAGMA journal_mode=WAL;
                  CREATE TABLE duel_stats(channel_id INTEGER,username TEXT,game_type TEXT,
                    elo INTEGER DEFAULT 1100,win_streak INTEGER DEFAULT 0,season_id INTEGER,
                    updated_at TEXT,PRIMARY KEY(channel_id,username,game_type));
                  CREATE TABLE duel_seasons(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER,game_type TEXT,started_at TEXT,ends_at TEXT,finished INTEGER DEFAULT 0);
                  CREATE TABLE viewers(channel_id INTEGER,username TEXT,points INTEGER DEFAULT 0,
                    PRIMARY KEY(channel_id,username));
                  CREATE TABLE channels(channel_id INTEGER PRIMARY KEY,active_module TEXT);
                  INSERT INTO channels VALUES(11,'bannerlord'),(22,'rimworld');
                  INSERT INTO viewers VALUES(11,'alice',0),(11,'bobby',0),(22,'alice',0),(22,'bobby',0);
                ''')
                await m135_skillgames.apply(connection)
            dependencies.set_db(db)
            dependencies.mark_channel_registered(11, 'local_channel', approved=True)
            dependencies.mark_channel_registered(22, 'other_local_channel', approved=True)
            service = SkillgameService(db)
            skillgames.get_service = lambda: service
            app.state.local_service = service
            try:
                yield
            finally:
                await service.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def loopback_only(request: Request, call_next):
        # Protect synthetic identities from a different website and DNS rebinding.
        if not request.client or request.client.host not in ('127.0.0.1', '::1'):
            return JSONResponse({'error':'Local harness only'}, status_code=403)
        host = request.headers.get('host','').split(':')[0]
        if host not in ('127.0.0.1', 'localhost'):
            return JSONResponse({'error':'Local host required'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin not in (str(request.base_url).rstrip('/'),
                                      str(request.base_url).replace('127.0.0.1','localhost').rstrip('/')):
            return JSONResponse({'error':'Cross-origin local demo forbidden'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    app.include_router(skillgames.router)

    @app.get('/local-identity')
    async def local_identity(player: str = 'alice', channel: int = 11):
        if player not in ('alice','bobby') or channel not in (11,22):
            raise HTTPException(400,'Unknown disposable identity')
        user_id = '101' if player == 'alice' else '102'
        token = jwt.encode({'sub':player,'user_id':user_id,'channel_id':str(channel),
                            'role':'viewer','exp':int(time.time())+3600},secret,algorithm='HS256')
        return {'token':token,'userId':user_id,'channelId':str(channel)}

    @app.get('/local-twitch-helper.js')
    async def local_helper():
        return Response('''"use strict";
window.Twitch = {ext: {environment: "local-integration", onAuthorized(callback) {
  const params = new URLSearchParams(location.search);
  const query = new URLSearchParams({player:params.get("player") || "alice",channel:params.get("channel") || "11"});
  fetch("/local-identity?"+query, {cache:"no-store"}).then(r => {
    if (!r.ok) throw new Error("Unknown local test identity"); return r.json();
  }).then(callback);
}}};
''', media_type='application/javascript')

    @app.get('/')
    async def home():
        return HTMLResponse('''<!doctype html><html lang="ru"><meta charset="utf-8">
<title>ShedLink: local HTTP integration</title><h1>Локальная проверка двух игр</h1>
<p>Настоящие API и серверные правила; временная база и вымышленные пользователи.
Никакого подключения к Twitch, production или реальных наград.</p>
<p><a href="/extension.html?player=alice">Alice: настольная панель</a></p>
<p><a href="/mobile.html?player=bobby">Bobby: мобильная панель</a></p>
<p>Для морского боя откройте обе панели и нажмите поиск соперника.</p></html>''')

    @app.get('/{entrypoint}.html')
    async def entrypoint(entrypoint: str):
        if entrypoint not in ('extension','mobile','index','tournament'):
            raise HTTPException(404)
        path = DIST / (entrypoint+'.html')
        if not path.is_file():
            raise HTTPException(503,'Build frontend-next first: npm --prefix frontend-next run build')
        content = path.read_text(encoding='utf-8')
        content = content.replace('https://extension-files.twitch.tv/helper/v1/twitch-ext.min.js',
                                  '/local-twitch-helper.js')
        return HTMLResponse(content)

    app.mount('/assets', StaticFiles(directory=DIST / 'assets',check_dir=False), name='assets')
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-local-demo',action='store_true',
                        help='Explicitly allow disposable synthetic identities on loopback')
    parser.add_argument('--port',type=int,default=4180)
    args = parser.parse_args()
    if not args.allow_local_demo:
        parser.error('--allow-local-demo is required; never run this as production')
    if not 1024 <= args.port <= 65535:
        parser.error('--port must be between 1024 and 65535')
    if not (DIST / 'extension.html').is_file():
        parser.error('Build frontend-next first: npm --prefix frontend-next run build')
    import uvicorn
    uvicorn.run(create_local_app(),host='127.0.0.1',port=args.port,proxy_headers=False)


if __name__ == '__main__': main()
