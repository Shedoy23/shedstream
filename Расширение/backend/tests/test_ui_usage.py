"""UI intent counters: standalone, real signed JWTs and isolated SQLite only."""
import asyncio
import base64
import json
import importlib.util
import subprocess
import sqlite3
import sys
import tempfile
import time
import re
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_frozen_client_0_0_5  # isolated environment defaults
assert test_frozen_client_0_0_5.TWITCH_UID
import aiosqlite
import jwt
from fastapi import HTTPException
from starlette.requests import Request
import auth
import dependencies as deps


async def main():
    try:
        from routes import ui_usage as route
        from migrations import m134_ui_usage as migration
    except ImportError as exc:
        raise AssertionError('Missing authenticated section/action UI counters') from exc
    class DB:
        @asynccontextmanager
        async def _connect(self):
            async with aiosqlite.connect(self.path) as conn:
                yield conn
    with tempfile.TemporaryDirectory() as tmp:
        db = DB()
        db.path = str(Path(tmp) / 'ui.db')
        async with db._connect() as conn:
            await conn.execute('CREATE TABLE channels(channel_id INTEGER PRIMARY KEY, active_module TEXT)')
            await conn.executemany('INSERT INTO channels VALUES (?,?)', [(11, 'bannerlord'), (22, 'rimworld')])
            await conn.execute('CREATE TABLE feature_usage(channel_id INTEGER, feature_key TEXT, day TEXT, count INTEGER)')
            await conn.execute("INSERT INTO feature_usage VALUES(11, 'bannerlord:hero.set_class', '2026-01-01', 7)")
            await conn.commit()
            await migration.apply(conn)
            await migration.apply(conn)
        secret = base64.b64decode(auth.TWITCH_EXTENSION_SECRET)
        def request(payload, uid='101', cid=11, token=None, raw=None):
            claims = {'exp': int(time.time()) + 120, 'user_id': uid, 'channel_id': str(cid), 'opaque_user_id': 'UopaqueViewerIdentity', 'role': 'viewer'}
            encoded = token if token is not None else jwt.encode(claims, secret, algorithm='HS256')
            body = raw if raw is not None else json.dumps(payload).encode()
            async def receive():
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return Request({'type': 'http', 'method': 'POST', 'path': '/api/viewer/ui-usage', 'headers': [(b'x-twitch-jwt', encoded.encode())], 'query_string': b'channel_id=22&username=spoof'}, receive)
        seq = 0
        def batch(*events):
            nonlocal seq
            seq += 1
            return {'batch_id': f'00000000-0000-4000-8000-{seq:012d}', 'surface': 'desktop', 'events': list(events or [dict(kind='section_open', feature='bannerlord:details.hero-progression', count=1)])}
        async def post(payload, **kwargs):
            try:
                result = await route.record_ui_usage(request(payload, **kwargs))
                return result.status_code, json.loads(result.body)
            except HTTPException as exc:
                return exc.status_code, exc.detail
        def rows(sql, values=()):
            with sqlite3.connect(db.path) as conn:
                return conn.execute(sql, values).fetchall()
        deps._channel_rate_buckets.clear()
        with patch.object(route, 'get_db', return_value=db), patch.object(deps, 'is_channel_registered', return_value=True), patch.object(deps, 'is_channel_approved', return_value=True):
            payload = batch(dict(kind='panel_view', feature='bannerlord:panel', count=1), dict(kind='section_open', feature='bannerlord:details.hero-progression', count=2), dict(kind='action_attempt', feature='bannerlord:hero.set_class', count=1))
            assert (await post(payload))[0] == 200
            assert (await post(payload))[1]['duplicate'] is True, 'Network retry must not inflate intent counts'
            assert sum(r[0] for r in rows('SELECT count FROM ui_feature_usage WHERE channel_id=11')) == 4
            assert (await post(payload, uid='102'))[0] == 200, 'Batch dedupe must include signed viewer'
            assert (await post(payload, cid=22))[0] == 200, 'Batch dedupe must include signed channel'
            assert rows('SELECT DISTINCT viewer_id FROM ui_feature_usage WHERE channel_id=11') == [('101',), ('102',)]
            assert rows('SELECT DISTINCT active_module FROM ui_feature_usage WHERE channel_id=22') == [('rimworld',)]
            with patch.object(deps, 'is_channel_registered', return_value=False):
                assert (await post(batch(), uid='201'))[0] == 403
            with patch.object(deps, 'is_channel_approved', return_value=False):
                assert (await post(batch(), uid='201'))[0] == 403
            race = batch()
            first, second = await asyncio.gather(post(race, uid='202'), post(race, uid='202'))
            assert first[0] == second[0] == 200
            assert sorted([first[1]['duplicate'], second[1]['duplicate']]) == [False, True]
            assert rows('SELECT SUM(count) FROM ui_feature_usage WHERE channel_id=11 AND viewer_id=?', ('202',)) == [(1,)]
            class FailingDB:
                @asynccontextmanager
                async def _connect(self):
                    async with db._connect() as conn:
                        async def failed_write(*args, **kwargs):
                            raise RuntimeError('storage unavailable')
                        with patch.object(conn, 'executemany', side_effect=failed_write):
                            yield conn
            retry = batch()
            with patch.object(route, 'get_db', return_value=FailingDB()):
                assert (await post(retry, uid='203'))[0] == 503
            assert not rows('SELECT batch_id FROM ui_usage_batches WHERE channel_id=11 AND viewer_id=?', ('203',)), 'Failed transaction must not consume retry ID'
            assert (await post(retry, uid='203'))[0] == 200
            assert rows('SELECT SUM(count) FROM ui_feature_usage WHERE channel_id=11 AND viewer_id=?', ('203',)) == [(1,)]
            assert (await post(batch(), token='bad'))[0] == 401
            assert (await post(batch(), uid=''))[0] == 403, 'No raw login/anonymous identity fallback'
            assert (await post(batch(), token=jwt.encode({'exp': 1, 'channel_id':'11','user_id':'101'}, secret, algorithm='HS256')))[0] == 401
            for payload in [dict(batch(), channel_id=22), dict(batch(), username='private'), batch(dict(kind='action_attempt', feature='bannerlord:private name', count=1)), batch(dict(kind='section_open', feature='bannerlord:details.hero-progression', count=True)), batch(dict(kind='section_open', feature='bannerlord:details.hero-progression', count=21)), batch(dict(kind='section_open', feature='bannerlord:details.hero-progression', count=1, data='secret')), batch(*[dict(kind='section_open',feature='bannerlord:details.hero-progression',count=1)]*21), dict(batch(), surface='secret')]:
                code, detail = await post(payload, uid='103')
                assert code in (400, 413), (code, detail)
            assert (await post({}, raw=b'x'*20000, uid='104'))[0] == 413
            assert not any(isinstance(key, int) for key in deps._channel_rate_buckets), 'Telemetry must not spend shared action quota'
            for _ in range(10):
                code, _ = await post(batch(), uid='105')
                if code == 429:
                    break
            assert code == 429, 'Telemetry has a bounded per-viewer rate'
            assert (await post(batch(), uid='106'))[0] == 200, 'Rate limiting one viewer must not block another'
            with patch.dict(deps._channel_rate_buckets, {}, clear=True), patch.object(deps, '_CHANNEL_POLL_BUCKETS_MAX', 0):
                assert (await post(batch(), uid='990'))[0] == 429, 'Telemetry cache overflow must fail closed instead of consuming action quota'
                assert not deps._channel_rate_buckets, 'Telemetry overload cannot create a shared action bucket'
            # Commit old rows, then ingestion must prune only its own channel.
            with sqlite3.connect(db.path) as conn:
                conn.execute("UPDATE ui_feature_usage SET day='2000-01-01' WHERE channel_id=22")
                conn.execute("UPDATE ui_usage_batches SET created_at=0 WHERE channel_id=22")
            await post(batch(), cid=22, uid='107')
            assert not rows("SELECT count FROM ui_feature_usage WHERE channel_id=22 AND day='2000-01-01'")
            assert not rows('SELECT batch_id FROM ui_usage_batches WHERE channel_id=22 AND created_at=0')
            assert rows('SELECT count FROM feature_usage WHERE channel_id=11') == [(7,)], 'Existing accepted-action metric must remain unchanged'
            assert rows("SELECT COUNT(*) FROM migrations_applied WHERE name='M134.ui_usage'") == [(1,)]
            from ui_usage import ACTIONS, SECTIONS
            root = Path(__file__).resolve().parents[3]
            frontend = (root / 'Расширение/frontend/viewer-usage.js').read_text(encoding='utf-8')
            for name, allowed in [('actions', ACTIONS), ('sections', SECTIONS)]:
                match = re.search(r'var ' + name + r' = new Set\((\[.*?\])\);', frontend)
                assert match and set(json.loads(match.group(1))) == allowed, f'{name} allowlist drift'
            report_path = root / 'scripts/ui-usage-report.py'
            spec = importlib.util.spec_from_file_location('ui_report', report_path)
            reporter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(reporter)
            with sqlite3.connect(db.path) as conn:
                conn.execute("""INSERT INTO ui_feature_usage
                    SELECT channel_id,date(day,'-1 day'),viewer_id,client,surface,module_id,active_module,kind,feature_key,count
                    FROM ui_feature_usage WHERE channel_id=11 AND viewer_id='101' AND kind='action_attempt'""")
                conn.commit()
                data = reporter.report(conn, 11)
                feature = next(f for f in data['ui_features'] if f['kind'] == 'action_attempt')
                assert feature['unique_viewers'] == 2
                assert feature['panel_cohort_viewers'] == 2
                assert feature['panel_cohort_percent'] == 100.0
                assert reporter.report(conn, 22)['ui_features'][0]['eligible_count'] == 0, 'Inactive game use is not an eligible denominator'
                before = list(conn.iterdump())
            run = subprocess.run([sys.executable, str(report_path), '--db', db.path, '--channel', '11'], capture_output=True, text=True)
            assert run.returncode == 0, run.stderr
            assert 'viewer_id' not in run.stdout and 'private' not in run.stdout
            with sqlite3.connect(db.path) as conn:
                assert list(conn.iterdump()) == before, 'Report command is read-only'
            print('PASS: report cohort intersection, cross-channel isolation, eligibility, unique viewers and read-only CLI')
            print('PASS: JWT, tenant/viewer isolation, allowlist/bounds, retry dedupe, rate, retention, existing metrics unchanged')

if __name__ == '__main__':
    asyncio.run(main())
