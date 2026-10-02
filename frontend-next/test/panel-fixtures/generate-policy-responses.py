"""Real main.app ASGI response provenance; no live network or production data.
Usage: isolated_venv_python this_script.py ISOLATED_ARCHIVE OUTPUT_JSON SOURCE_COMMIT
"""
from __future__ import annotations
import asyncio, base64, hashlib, json, os, sys, tempfile, time
from pathlib import Path

ROOT, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
os.chdir(ROOT)
sys.dont_write_bytecode = True

def no_network(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise AssertionError('Network is prohibited in panel policy ASGI probe')
sys.addaudithook(no_network)
SECRET = b'local-panel-policy-proof-only-key-32b'
for name, value in {
    'TWITCH_OAUTH_TOKEN': 'oauth:test', 'TWITCH_CLIENT_ID': 'test-client',
    'TWITCH_CLIENT_SECRET': 'test-secret', 'TWITCH_BOT_ID': 'test-bot',
    'TWITCH_CHANNEL_NAME': 'test-channel', 'TWITCH_BROADCASTER_ID': '98319857',
    'TWITCH_EXTENSION_SECRET': base64.b64encode(SECRET).decode(),
    'MODULE_TOKEN_SECRET': 'test-module-secret-32bytes-1234567890',
    'ADMIN_PASSWORD': 'test_admin_password_for_tests_only',
    'DEV_MODE': 'false', 'RIMLINK_ENV': 'test',
    'PYTHON_DOTENV_DISABLED': '1',
}.items(): os.environ[name] = value
sys.path[:0] = [str(ROOT/'Расширение/backend/tests'), str(ROOT/'Расширение/backend')]

async def run():
    with tempfile.TemporaryDirectory(prefix='panel-policy-db-') as tmp:
        os.environ['RIMWORLD_PRICES_PATH'] = str(Path(tmp)/'unused-prices.json')
        import jwt, httpx
        from test_bannerlord_buy_action import _build_db, CHANNEL_ID
        db = await _build_db(str(Path(tmp)/'policy.db'))
        import main, dependencies as dep
        from routes import bannerlord
        try:
            async with db._connect() as conn:
                await conn.execute('UPDATE channels SET approved=1 WHERE channel_id=?', (CHANNEL_ID,))
                await conn.execute("INSERT INTO channels(channel_id,login,display_name,tier,approved) VALUES(22,'pending_chan','Pending','free',0)")
                await conn.commit()
            await dep.init_registered_channels_cache(db)
            assert bannerlord.require_jwt_user is dep.require_jwt_user
            assert dep.verify_twitch_jwt.__module__ == 'auth'
            assert main.app.router.on_startup  # Deliberately NOT run: no bots/loops.
            dep._channel_rate_buckets.clear()
            tier = dep._channel_tier_cache.get(CHANNEL_ID, dep.RATE_LIMIT_DEFAULT_TIER)
            for _ in range(dep.RATE_LIMITS_BY_TIER[tier]):
                assert dep.check_channel_rate_limit(CHANNEL_ID)

            def token(channel, expired=False):
                return jwt.encode({'sub': 'alice', 'user_id':'123', 'channel_id':str(channel),
                    'role':'viewer', 'exp':int(time.time()) + (-3600 if expired else 3600)}, SECRET, algorithm='HS256')
            async def db_state():
                async with db._connect() as conn:
                    queries = {
                        'viewers': 'SELECT channel_id,username,points FROM viewers ORDER BY channel_id,username',
                        'heroes': 'SELECT channel_id,username,gold FROM bannerlord_heroes ORDER BY channel_id,username',
                        'actions': 'SELECT COUNT(*) FROM module_actions',
                    }
                    return {key:[list(row) for row in await (await conn.execute(sql)).fetchall()] for key,sql in queries.items()}

            result = {'source_head':sys.argv[3],
                'app':'unchanged main.app (actual routers and middleware), httpx.ASGITransport, lifespan not run',
                'network':'socket.connect and socket.getaddrinfo prohibited by sys audit hook',
                'exception_handlers': {str(k): v.__module__+'.'+v.__name__ for k,v in main.app.exception_handlers.items()},
                'source_sha256': {str(p):hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in [Path('frontend-next/src/panel/transport.ts'),Path('frontend-next/src/skillgames/http.ts'),Path('Расширение/backend/dependencies.py'),Path('Расширение/backend/routes/bannerlord.py'),Path('Расширение/backend/main.py')]},
                'cases':{}}
            for name, channel, signed_token in [
                ('unregistered', 33, token(33)), ('pending',22,token(22)),
                ('rate_limited',CHANNEL_ID,token(CHANNEL_ID)),
                ('expired',CHANNEL_ID,token(CHANNEL_ID,True)), ('missing',CHANNEL_ID,None),
            ]:
                trace, receive_calls = [], []
                def profiler(frame, event, arg):
                    if event != 'call': return
                    if frame.f_code.co_name == 'get_db' and frame.f_code.co_filename.endswith('/dependencies.py'):
                        raise AssertionError('Guard: expected pre-action refusal escaped auth boundary')
                    filename = frame.f_code.co_filename
                    fn = frame.f_code.co_name
                    if filename.endswith(('/routes/bannerlord.py', '/dependencies.py', '/auth.py')) and fn in {
                        'bannerlord_buy_action','require_jwt_user','verify_twitch_jwt','resolve_jwt_login',
                        'is_channel_registered','is_channel_approved','_raise_channel_not_registered',
                        '_raise_channel_pending','_check_request_rate_limit','check_channel_rate_limit',
                        '_raise_channel_rate_limited','get_db','_require_live_mod','_get_user_lock',
                        '_bannerlord_buy_action_locked',
                    }: trace.append({'function':fn,'line':frame.f_code.co_firstlineno,'file':str(Path(filename).relative_to(ROOT))})
                async def app(scope, receive, send):
                    async def observed_receive():
                        receive_calls.append('http body receive')
                        return await receive()
                    await main.app(scope, observed_receive, send)
                before = await db_state()
                sys.setprofile(profiler)
                try:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://asgi.test') as client:
                        response = await client.post('/api/bannerlord/action',
                            headers={'X-Twitch-JWT':signed_token} if signed_token else {},
                            json={'action_type':'hero.army_create','data':{'client_action_id':'local-policy-'+name}})
                finally: sys.setprofile(None)
                after = await db_state()
                assert before == after, (name, before, after)
                assert receive_calls == [], (name, receive_calls)
                assert not any(r['function'] in {'get_db','_require_live_mod','_get_user_lock','_bannerlord_buy_action_locked'} for r in trace), trace
                result['cases'][name] = {'request':{'method':'POST','path':'/api/bannerlord/action','jwt': 'missing' if not signed_token else 'synthetic HS256, expired' if name=='expired' else 'synthetic HS256, valid',
                    'identity':{'channelId':str(channel),'userId':'123'},'body':{'action_type':'hero.army_create','data':{'client_action_id':'local-policy-'+name}}},
                    'response':{'status':response.status_code,'headers':dict(response.headers),'body':response.json(),'raw_body':response.text},
                    'trace':trace,'request_body_receive_calls':len(receive_calls),'db_before':before,'db_after':after}
                print(name, response.status_code, response.text, 'body_reads=0; financial/action state unchanged')
            assert result['cases']['unregistered']['response']['status']==403
            assert result['cases']['pending']['response']['status']==403
            assert result['cases']['rate_limited']['response']['status']==429
            for name in ('expired','missing'):
                assert result['cases'][name]['response']['body']==bannerlord._AUTH_FAIL
            OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        finally:
            await db._pool.close()

asyncio.run(run())
