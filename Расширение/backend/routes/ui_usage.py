"""Small best-effort UI counter endpoint; no game/financial writes or payloads."""
import json
import re
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from auth import verify_twitch_jwt
from dependencies import get_db, require_jwt_channel
from ui_usage import CLIENT, MODULES, validate_batch

router = APIRouter()
_MAX_BODY = 8192
_RATE_BUCKETS = OrderedDict()
_RATE_MAX_IDENTITIES = 10000


def _allow(channel_id, viewer_id, now):
    key = channel_id, viewer_id
    window, used = _RATE_BUCKETS.get(key, (now, 0))
    if now - window >= 60:
        window, used = now, 0
    if used >= 6:
        return False
    if key not in _RATE_BUCKETS and len(_RATE_BUCKETS) >= _RATE_MAX_IDENTITIES:
        # Do not evict fresh quota entries: churn must not reset a viewer's limit.
        oldest, (started, _) = next(iter(_RATE_BUCKETS.items()))
        if now - started < 60:
            return False
        del _RATE_BUCKETS[oldest]
    _RATE_BUCKETS[key] = window, used + 1
    _RATE_BUCKETS.move_to_end(key)
    return True


@router.post('/api/viewer/ui-usage')
async def record_ui_usage(request: Request):
    channel_id = require_jwt_channel(request)
    if channel_id is None:
        return JSONResponse({'status': 'unauthenticated'}, status_code=401)
    claims = verify_twitch_jwt(request)
    viewer_id = claims.get('user_id', '')
    # Exclude unlinked/anonymous sessions; never store a raw login or manufacture
    # a persistent browser tracking identifier just to inflate coverage.
    if not isinstance(viewer_id, str) or not re.fullmatch(r'[0-9]{1,24}', viewer_id):
        return JSONResponse({'status': 'linked_identity_required'}, status_code=403)
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > _MAX_BODY:
            return JSONResponse({'status': 'body_too_large'}, status_code=413)
    try:
        body = validate_batch(json.loads(chunks))
    except (ValueError, TypeError, KeyError):
        return JSONResponse({'status': 'invalid_batch'}, status_code=400)
    now = int(time.time())
    if not _allow(channel_id, viewer_id, now):
        return JSONResponse({'status': 'rate_limited'}, status_code=429, headers={'Retry-After': '60'})
    today = datetime.fromtimestamp(now, timezone.utc).date()
    db = get_db()
    try:
        async with db._connect() as conn:
            # Dedup check and aggregate increments share one write transaction.
            await conn.execute('BEGIN IMMEDIATE')
            await conn.execute('DELETE FROM ui_usage_batches WHERE channel_id=? AND created_at<?', (channel_id, now - 86400))
            await conn.execute('DELETE FROM ui_feature_usage WHERE channel_id=? AND day<?', (channel_id, (today - timedelta(days=89)).isoformat()))
            inserted = await conn.execute('INSERT OR IGNORE INTO ui_usage_batches(channel_id, viewer_id, batch_id, created_at) VALUES(?,?,?,?)', (channel_id, viewer_id, body['batch_id'], now))
            if inserted.rowcount == 0:
                await conn.commit()
                return JSONResponse({'status': 'ok', 'duplicate': True})
            row = await (await conn.execute('SELECT active_module FROM channels WHERE channel_id=?', (channel_id,))).fetchone()
            active_module = row[0] if row and row[0] in MODULES else 'unknown'
            await conn.executemany('''INSERT INTO ui_feature_usage
                (channel_id, day, viewer_id, client, surface, module_id, active_module, kind, feature_key, count)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(channel_id, day, viewer_id, client, surface, module_id, active_module, kind, feature_key)
                DO UPDATE SET count=count+excluded.count''',
                [(channel_id, today.isoformat(), viewer_id, CLIENT, body['surface'], event['feature'].split(':', 1)[0], active_module, event['kind'], event['feature'], event['count']) for event in body['events']])
            await conn.commit()
    except Exception:
        # Telemetry failure must never affect an action; the client only retries
        # this independent batch. No body/JWT/identity is printed to logs.
        return JSONResponse({'status': 'unavailable'}, status_code=503)
    return JSONResponse({'status': 'ok', 'duplicate': False})
