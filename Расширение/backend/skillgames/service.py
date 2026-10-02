"""Private, transactional skill-game lifecycle. No points or PubSub writes.

A runtime heartbeat is a health lease, not viewer activity. Sessions retain the
runtime that admitted them. Other workers can serve them while its lease is
healthy; restarting another worker does not invalidate them. A dead/stalled
owner (including deployments) voids its sessions, never awards timeout losses.
Mines generation runs outside SQLite's writer lock behind bounded admission.
"""
import asyncio
import hashlib
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from . import battleship, config, minesweeper

logger = logging.getLogger('rimlink.skillgames')
ACTIVE = ('awaiting_first_move', 'generating', 'active')


class GameError(Exception):
    def __init__(self, reason, status=409, message=None):
        self.reason, self.status = reason, status
        self.message = message or config.message(reason)
        super().__init__(reason)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _fingerprint(operation, payload):
    return hashlib.sha256(_json([operation, payload]).encode()).hexdigest()


async def ensure_season(conn, channel_id, game_type):
    """Rotate only new games, preserving an explicit no-prize closure audit."""
    if game_type not in config.GAME_TYPES:
        raise ValueError('not a skill game')
    from routes.duel import _ensure_season
    now = time.time()
    rows = await (await conn.execute(
        'SELECT id,ends_at FROM duel_seasons WHERE channel_id=? AND game_type=? AND finished=0',
        (channel_id, game_type))).fetchall()
    expired, live = [], []
    for season_id, ends in rows:
        deadline = datetime.fromisoformat(ends)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        (expired if deadline.timestamp() <= now else live).append(season_id)
    for season_id in expired:
        await conn.execute('UPDATE duel_seasons SET finished=1 WHERE channel_id=? AND game_type=? AND id=?',
                           (channel_id, game_type, season_id))
        await conn.execute('INSERT OR IGNORE INTO skillgame_season_closures '
                           '(channel_id,game_type,season_id,reason,created_at) VALUES (?,?,?,?,?)',
                           (channel_id, game_type, season_id, 'rewards_not_calibrated', now))
    season_id = max(live) if live else await _ensure_season(conn, channel_id, game_type)
    if expired and not live:
        await conn.execute('UPDATE duel_stats SET elo=?,win_streak=0,season_id=? '
                           'WHERE channel_id=? AND game_type=?',
                           (config.ELO_START, season_id, channel_id, game_type))
    return season_id


class SkillgameService:
    def __init__(self, db):
        self.db = db
        self.runtime_id = uuid.uuid4().hex
        self._heartbeat_task = None
        self._start_lock = asyncio.Lock()
        self._last_wall = time.time()
        self._last_mono = time.monotonic()
        self._generating = 0
        self._retired = False
        self._generation_tasks = set()

    async def start(self):
        if self._heartbeat_task is not None:
            return
        async with self._start_lock:
            if self._heartbeat_task is None:
                await self._heartbeat()
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def close(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        async with self.db._connect() as conn:
            # tenant-ok: shared process-health registry contains no tenant/player data.
            await conn.execute('UPDATE skillgame_runtimes SET last_seen=0 WHERE runtime_id=?', (self.runtime_id,))
            await conn.commit()

    def retire_runtime(self):
        self._retired = True

    async def void_for_service_failure(self, cid, user, sid):
        async with self._tx() as conn:
            row = await self._load(conn,cid,sid,user)
            if row['status'] in ACTIVE:
                row['version'] += 1
                await self._finish(conn,row,reason='service_unavailable',void=True)

    async def _heartbeat(self):
        wall, mono = time.time(), time.monotonic()
        elapsed = mono - self._last_mono
        old_runtime = self.runtime_id
        if self._retired or elapsed > config.GRACE_SECONDS or abs((wall-self._last_wall)-elapsed) > config.GRACE_SECONDS:
            # Leave the old lease expired; a service stall is not player inactivity.
            self.runtime_id = uuid.uuid4().hex
        async with self.db._connect() as conn:
            if self.runtime_id != old_runtime:
                await conn.execute('UPDATE skillgame_runtimes SET last_seen=0 WHERE runtime_id=?', (old_runtime,))
            # tenant-ok: process-health lease shared by workers; contains no tenant data.
            await conn.execute('INSERT INTO skillgame_runtimes(runtime_id,last_seen) VALUES (?,?) '
                               'ON CONFLICT(runtime_id) DO UPDATE SET last_seen=excluded.last_seen',
                               (self.runtime_id, wall))
            await conn.commit()
        self._last_wall, self._last_mono = wall, mono
        self._retired = False

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(config.HEARTBEAT_SECONDS)
            try:
                await self._heartbeat()
                await self._sweep_owned_deadlines()
            except Exception:
                logger.exception('Skillgame health lease unavailable')
                # Do not refresh success time. Next successful heartbeat retires it.

    async def _sweep_owned_deadlines(self):
        # Only routing keys cross this system-level scan; every session read and
        # mutation below still requires its exact channel. A worker does not
        # penalize another worker's sessions and never depends on viewer polls.
        async with self.db._connect() as conn:
            rows = await (await conn.execute(  # tenant-ok: dispatch only; session access is scoped below.
                "SELECT channel_id,id FROM skillgame_sessions WHERE runtime_id=? "
                "AND status IN ('active','generating') AND expires_at<=? ORDER BY expires_at LIMIT 50",
                (self.runtime_id,time.time()))).fetchall()
        for cid,sid in rows:
            try:
                async with self._tx() as conn:
                    row = await self._load(conn,cid,sid)
                    await self._expire(conn,row)
            except Exception:
                logger.exception('Skillgame deadline processing failed')
                try:
                    await self.void_for_service_failure(cid,None,sid)
                except Exception:
                    self.retire_runtime()
                    break

    @asynccontextmanager
    async def _tx(self):
        await self.start()
        if self._retired:
            await self._heartbeat()
        async with self.db._connect() as conn:
            await conn.execute('BEGIN IMMEDIATE')
            try:
                yield conn
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise

    async def _load(self, conn, cid, sid, user=None):
        cur = await conn.execute('SELECT * FROM skillgame_sessions WHERE channel_id=? AND id=?', (cid, sid))
        raw = await cur.fetchone()
        if raw is None:
            raise GameError('not_found', 404)
        row = dict(zip([x[0] for x in cur.description], raw))
        players = await (await conn.execute('SELECT username FROM skillgame_players '
                                           'WHERE channel_id=? AND session_id=? ORDER BY rowid', (cid, sid))).fetchall()
        row['players'] = [x[0] for x in players]
        if user is not None and user not in row['players']:
            raise GameError('not_found', 404)
        row['secret_state'] = json.loads(row['secret_state']) if row['secret_state'] else None
        row['result'] = json.loads(row['result']) if row['result'] else None
        row['rules'] = json.loads(row['rules'])
        return row

    async def _save(self, conn, row):
        await conn.execute('UPDATE skillgame_sessions SET status=?,version=?,secret_state=?,started_at=?,expires_at=?,generation_token=?,result=? '
                           'WHERE channel_id=? AND id=?',
                           (row['status'], row['version'], _json(row['secret_state']) if row['secret_state'] else None,
                            row['started_at'], row['expires_at'], row.get('generation_token'),
                            _json(row['result']) if row['result'] else None, row['channel_id'], row['id']))

    async def _active(self, conn, cid, user, mode):
        record = await (await conn.execute('SELECT session_id FROM skillgame_players '
                                          'WHERE channel_id=? AND username=? AND (? IS NULL OR mode=?) AND active=1', (cid, user, mode, mode))).fetchone()
        if not record:
            return None
        row = await self._load(conn, cid, record[0], user)
        await self._expire(conn, row)
        return row if row['status'] in ACTIVE else None

    def _projection(self, row, user):
        state = row['secret_state']
        if row['game_type'] == 'battleship':
            public = battleship.public_projection(state, user)
        elif state:
            public = minesweeper.public_projection(state)
        else:
            public = dict(rows=minesweeper.ROWS, cols=minesweeper.COLS,
                          mine_count=minesweeper.TIERS[row['difficulty']]['mine_count'],
                          opened={}, flags=[], status=row['status'])
        result = row['result']
        if result:
            result = dict(result)
            ratings = result.pop('ratings', {})
            result['rating'] = ratings.get(user)
            if result['outcome'] != 'void':
                result['outcome'] = ('draw' if result['winner'] is None and row['game_type']=='battleship'
                                     else 'win' if result['winner']==user else 'loss')
            result['message'] = {'win':'Победа', 'loss':'Поражение', 'draw':'Ничья', 'void':'Попытка отменена'}[result['outcome']]
            result['reason_message'] = config.message(result['reason'])
        return {key: row[key] for key in ('id','game_type','mode','difficulty','status','version','created_at','started_at','expires_at')} | {
            'state': public, 'result': result, 'rules':row['rules']}

    async def _maintenance(self, conn, cid):
        # Bounded work, scoped by channel. No board or proof enters the durable
        # result audit. Old result/rating ledgers are deliberately never pruned.
        await conn.execute('DELETE FROM skillgame_requests WHERE channel_id=? AND rowid IN '
                           '(SELECT rowid FROM skillgame_requests WHERE channel_id=? AND created_at<? LIMIT 256)',
                           (cid,cid,time.time()-config.REQUEST_RETENTION_SECONDS))
        history = await (await conn.execute('SELECT id FROM skillgame_sessions '
            'WHERE channel_id=? AND created_at<? ORDER BY created_at LIMIT 8',
            (cid,time.time()-config.SESSION_RETENTION_SECONDS))).fetchall()
        for (sid,) in history:
            row = await self._load(conn,cid,sid)
            if row['status'] in ACTIVE:
                await self._expire(conn,row)
            if row['status'] not in ACTIVE:
                await conn.execute('DELETE FROM skillgame_players WHERE channel_id=? AND session_id=?',(cid,sid))
                await conn.execute('DELETE FROM skillgame_sessions WHERE channel_id=? AND id=?',(cid,sid))

    async def _clear_stale_generations(self, conn, cid):
        candidates = await (await conn.execute('SELECT id FROM skillgame_sessions '
            "WHERE channel_id=? AND status='generating' ORDER BY created_at LIMIT 16",(cid,))).fetchall()
        for (sid,) in candidates:
            row = await self._load(conn,cid,sid)
            await self._expire(conn,row)

    async def _receipt(self, conn, cid, user, request_id, fingerprint):
        await self._maintenance(conn,cid)
        record = await (await conn.execute('SELECT fingerprint,response,http_status FROM skillgame_requests '
                                          'WHERE channel_id=? AND username=? AND request_id=?', (cid,user,request_id))).fetchone()
        if record:
            if record[0] != fingerprint:
                raise GameError('request_id_reused')
            if record[1] is None:
                raise GameError('generation_in_progress', 409)
            return json.loads(record[1]), record[2]
        retained = await (await conn.execute('SELECT COUNT(*) FROM skillgame_requests '
            'WHERE channel_id=? AND username=? AND created_at>=?',
            (cid,user,time.time()-config.REQUEST_RETENTION_SECONDS))).fetchone()
        if retained[0]>=config.MAX_RECEIPTS_PER_USER:
            raise GameError('request_rate_limited',429)
        return None

    async def _record(self, conn, cid, user, request_id, fingerprint, response, code=200, sid=None):
        await conn.execute('INSERT INTO skillgame_requests '
                           '(channel_id,username,request_id,fingerprint,session_id,response,http_status,created_at) '
                           'VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(channel_id,username,request_id) '
                           'DO UPDATE SET response=excluded.response,http_status=excluded.http_status',
                           (cid,user,request_id,fingerprint,sid,_json(response) if response else None,code,time.time()))

    async def _finish(self, conn, row, *, winner=None, reason, void=False):
        if row['status'] not in ACTIVE:
            return
        cid, game = row['channel_id'], row['game_type']
        ratings, season_id = {}, row['season_id']
        if not void and row['mode']=='ranked':
            current_season = await ensure_season(conn,cid,game)
            if current_season != row['season_id']:
                void, winner, reason = True, None, 'season_changed'
        outcome = 'void' if void else ('win' if winner else ('draw' if game=='battleship' else 'loss'))
        # Only this ledger writer finalizes; it runs under the same lock as moves.
        exists = await (await conn.execute('SELECT 1 FROM skillgame_results WHERE channel_id=? AND session_id=?',
                                          (cid,row['id']))).fetchone()
        if exists:
            raise RuntimeError('result ledger already finalized active session')
        if not void and row['mode']=='ranked':
            from routes.duel import _get_stats, _update_stats
            season_id = await ensure_season(conn, cid, game)
            stats = {p: await _get_stats(conn,p,season_id,cid,game) for p in row['players']}
            for player, (before, streak) in stats.items():
                opponent = (next(d['puzzle_rating'] for d in row['rules']['difficulties'] if d['id']==row['difficulty']) if game=='minesweeper'
                            else stats[next(p for p in row['players'] if p != player)][0])
                score = (0.5 if game=='battleship' and winner is None else 1.0 if player==winner else 0.0)
                expected = 1/(1+10**((opponent-before)/400))
                after = round(before+row['rules']['rating']['k']*(score-expected))
                await _update_stats(conn, player, after, streak+1 if score==1 else 0, cid, game)
                ratings[player] = {'before':before,'after':after,'delta':after-before}
        row['status'] = 'void' if void else 'finished'
        row['generation_token'] = None
        row['expires_at'] = None
        row['result'] = {'outcome':outcome,'winner':winner,'reason':reason,'ratings':ratings,'points':0}
        await conn.execute('INSERT INTO skillgame_results '
                           '(channel_id,session_id,game_type,mode,season_id,outcome,reason,result,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                           (cid,row['id'],game,row['mode'],season_id,outcome,reason,_json(row['result']),time.time()))
        await conn.execute('UPDATE skillgame_players SET active=0 WHERE channel_id=? AND session_id=?', (cid,row['id']))
        await self._save(conn,row)

    async def _expire(self, conn, row):
        if row['status'] not in ACTIVE:
            return
        now = time.time()
        # tenant-ok: read the admitting runtime's system lease, no tenant data.
        lease = await (await conn.execute('SELECT last_seen FROM skillgame_runtimes WHERE runtime_id=?',
                                         (row['runtime_id'],))).fetchone()
        if not lease or now-lease[0] > config.GRACE_SECONDS or lease[0]-now > config.GRACE_SECONDS:
            row['version'] += 1
            await self._finish(conn,row,reason='service_unavailable',void=True)
        elif row['mode']=='ranked' and row['season_id'] != await ensure_season(conn,row['channel_id'],row['game_type']):
            row['version'] += 1
            await self._finish(conn,row,reason='season_changed',void=True)
        elif row['status']=='generating' and row['expires_at'] is not None and now>=row['expires_at']:
            row['version'] += 1
            await self._finish(conn,row,reason='generation_failed',void=True)
        elif row['status']=='awaiting_first_move' and now-row['created_at'] > row['rules']['timers']['first_move_wait_seconds']:
            row['version'] += 1
            await self._finish(conn,row,reason='first_move_not_started',void=True)
        elif row['expires_at'] is not None and now >= row['expires_at'] and lease[0] >= row['expires_at']:
            # A lease from just BEFORE the deadline cannot prove uptime through
            # it. Wait for a post-deadline heartbeat; if its owner died, the
            # lease expires and the earlier branch voids instead of penalizing.
            row['version'] += 1
            if row['game_type']=='minesweeper':
                await self._finish(conn,row,reason='attempt_expired')
            else:
                state = row['secret_state']
                if state['phase']=='placement':
                    ready = [p for p in row['players'] if state['ready'][p]]
                    await self._finish(conn,row,winner=ready[0] if len(ready)==1 else None,
                                       reason='setup_expired',void=len(ready)!=1)
                elif now >= state['started_at']+row['rules']['timers']['total_seconds']+row['rules']['timers']['grace_seconds']:
                    await self._finish(conn,row,reason='total_time_expired')
                else:
                    winner = next(p for p in row['players'] if p != state['turn'])
                    await self._finish(conn,row,winner=winner,reason='turn_expired')

    async def state(self, cid, user, sid=None):
        async with self._tx() as conn:
            if sid:
                row = await self._load(conn,cid,sid,user)
                await self._expire(conn,row)
            else:
                record = await (await conn.execute('SELECT p.session_id FROM skillgame_players p '
                    'JOIN skillgame_sessions s ON s.channel_id=p.channel_id AND s.id=p.session_id '
                    'WHERE p.channel_id=? AND p.username=? ORDER BY p.active DESC,s.created_at DESC LIMIT 1', (cid,user))).fetchone()
                row = await self._load(conn,cid,record[0],user) if record else None
                if row:
                    await self._expire(conn,row)
            await conn.execute('DELETE FROM skillgame_queue WHERE channel_id=? AND expires_at<=?', (cid,time.time()))
            queue = await self._queue_state(conn,cid,user)
            ratings = {}
            for game in config.GAME_TYPES:
                await ensure_season(conn,cid,game)
                stat = await (await conn.execute('SELECT elo FROM duel_stats WHERE channel_id=? AND username=? AND game_type=?',
                                               (cid,user,game))).fetchone()
                ratings[game] = stat[0] if stat else config.ELO_START
            return dict(success=True,catalog=config.catalog(),active_session=self._projection(row,user) if row else None,
                        queue=queue,ratings=ratings,server_time=time.time(),poll_interval_ms=config.POLL_INTERVAL_MS)

    async def _new(self, conn, cid, players, game, mode, difficulty=None):
        now, sid = time.time(), uuid.uuid4().hex
        season_id = await ensure_season(conn,cid,game) if mode=='ranked' else None
        secret = battleship.new_game(players, now=now) if game=='battleship' else None
        status = 'active' if secret else 'awaiting_first_move'
        expires = now+config.SETUP_SECONDS+config.GRACE_SECONDS if secret else None
        await conn.execute('INSERT INTO skillgame_sessions '
                           '(channel_id,id,game_type,mode,difficulty,status,secret_state,created_at,expires_at,runtime_id,rules,season_id) '
                           'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (cid,sid,game,mode,difficulty,status,_json(secret) if secret else None,now,expires,self.runtime_id,_json(next(rule for rule in config.catalog() if rule['game_type']==game)),season_id))
        await conn.executemany('INSERT INTO skillgame_players(channel_id,session_id,username,mode) VALUES (?,?,?,?)',
                              [(cid,sid,p,mode) for p in players])
        return await self._load(conn,cid,sid)

    async def start_game(self, cid, user, payload):
        fp = _fingerprint('start',payload)
        async with self._tx() as conn:
            replay = await self._receipt(conn,cid,user,payload['request_id'],fp)
            if replay: return replay
            row = await self._active(conn,cid,user,None)
            if row and (row['game_type'] != payload['game_type'] or row['mode'] != payload['mode']):
                raise GameError('active_session')
            if row is None:
                availability = config.GAME_AVAILABILITY[payload['game_type']]
                if not availability['enabled']:
                    raise GameError('game_unavailable',409,availability['reason'])
                queued = await self._queue_state(conn,cid,user)
                if payload['mode']=='ranked' and queued['status']=='queued':
                    raise GameError('already_queued')
                recent = await (await conn.execute('SELECT COUNT(*) FROM skillgame_players p JOIN skillgame_sessions s '
                    'ON s.channel_id=p.channel_id AND s.id=p.session_id WHERE p.channel_id=? AND p.username=? AND s.created_at>?',
                    (cid,user,time.time()-60))).fetchone()
                if recent[0] >= config.STARTS_PER_MINUTE:
                    raise GameError('start_rate_limited',429)
                row = await self._new(conn,cid,[user],payload['game_type'],payload['mode'],payload['difficulty'])
            result = dict(success=True,session=self._projection(row,user),server_time=time.time())
            await self._record(conn,cid,user,payload['request_id'],fp,result,sid=row['id'])
            return result,200

    async def _queue_state(self, conn, cid, user):
        row = await (await conn.execute('SELECT queued_at,expires_at FROM skillgame_queue '
                                       'WHERE channel_id=? AND username=? AND expires_at>?', (cid,user,time.time()))).fetchone()
        return {'status':'queued','queued_at':row[0],'expires_at':row[1]} if row else {'status':'idle'}

    async def queue(self, cid, user, payload, cancel=False):
        fp = _fingerprint('cancel' if cancel else 'queue',payload)
        async with self._tx() as conn:
            replay = await self._receipt(conn,cid,user,payload['request_id'],fp)
            if replay: return replay
            await conn.execute('DELETE FROM skillgame_queue WHERE channel_id=? AND expires_at<=?',(cid,time.time()))
            row = await self._active(conn,cid,user,None)
            if cancel:
                await conn.execute('DELETE FROM skillgame_queue WHERE channel_id=? AND username=?',(cid,user))
            elif row and (row['game_type']!='battleship' or row['mode']!='ranked'):
                raise GameError('active_ranked_session')
            elif row is None:
                availability = config.GAME_AVAILABILITY['battleship']
                if not availability['enabled']:
                    raise GameError('game_unavailable',409,availability['reason'])
                candidates = await (await conn.execute('SELECT username FROM skillgame_queue '
                    'WHERE channel_id=? AND username!=? ORDER BY queued_at LIMIT 20',(cid,user))).fetchall()
                opponent = None
                for (candidate,) in candidates:
                    if await self._active(conn,cid,candidate,None) is None:
                        opponent = candidate
                        break
                    await conn.execute('DELETE FROM skillgame_queue WHERE channel_id=? AND username=?',(cid,candidate))
                if opponent:
                    row = await self._new(conn,cid,[opponent,user],'battleship','ranked')
                    await conn.execute('DELETE FROM skillgame_queue WHERE channel_id=? AND username IN (?,?)',(cid,user,opponent))
                else:
                    now = time.time()
                    await conn.execute('INSERT OR IGNORE INTO skillgame_queue(channel_id,username,queued_at,expires_at) VALUES (?,?,?,?)',
                                       (cid,user,now,now+config.QUEUE_SECONDS))
            result = dict(success=True,active_session=self._projection(row,user) if row else None,
                          queue=await self._queue_state(conn,cid,user),server_time=time.time())
            await self._record(conn,cid,user,payload['request_id'],fp,result,sid=row['id'] if row else None)
            return result,200

    async def action(self, cid, user, payload):
        fp = _fingerprint('action',payload)
        generate, reserved = None, False
        try:
            async with self._tx() as conn:
                replay = await self._receipt(conn,cid,user,payload['request_id'],fp)
                if replay: return replay
                row = await self._load(conn,cid,payload['session_id'],user)
                await self._expire(conn,row)
                # Expiration must commit, even when the submitted move is now stale.
                expired_pending = row['status']=='active' and row['expires_at'] is not None and time.time()>=row['expires_at']
                if row['status'] not in ACTIVE or row['version'] != payload['version'] or expired_pending:
                    reason = 'expiry_verification_pending' if expired_pending else 'stale_version'
                    result = dict(success=False,reason=reason,message=config.message(reason),session=self._projection(row,user),server_time=time.time())
                    await self._record(conn,cid,user,payload['request_id'],fp,result,409,row['id'])
                    return result,409
                if row['status']=='generating': raise GameError('generation_in_progress')
                action = payload['action']
                if action in ('quit','restart'):
                    row['version'] += 1
                    state = row['secret_state']
                    unstarted = row['started_at'] is None and (row['game_type']=='minesweeper' or not any(state['ready'].values()))
                    winner = next((p for p in row['players'] if p!=user),None)
                    await self._finish(conn,row,winner=winner if not unstarted else None,reason=action,void=unstarted)
                elif row['game_type']=='minesweeper' and row['secret_state'] is None:
                    if action!='open' or payload.get('cell') is None: raise GameError('first_action_must_open',422)
                    if self._generating >= config.GENERATION_CONCURRENCY: raise GameError('generation_busy',503)
                    # Orphan reservations must not require their old viewer to return.
                    await self._clear_stale_generations(conn,cid)
                    # Global DB count bounds concurrent workers, not only this instance.
                    count = await (await conn.execute('SELECT COUNT(*) FROM skillgame_sessions WHERE channel_id=? AND status=?',
                                                     (cid,'generating'))).fetchone()
                    if count[0] >= config.GENERATION_CONCURRENCY:
                        # Commit bounded cleanup even if more stale/live rows remain.
                        # Failed admission does not consume the retry ID.
                        return dict(success=False,reason='generation_busy',message=config.message('generation_busy')),503
                    self._generating += 1
                    reserved = True
                    row['status'] = 'generating'
                    row['generation_token'] = uuid.uuid4().hex
                    row['expires_at'] = time.time()+config.GENERATION_SECONDS
                    await self._save(conn,row)
                    await self._record(conn,cid,user,payload['request_id'],fp,None,sid=row['id'])
                    generate = (row['id'],row['generation_token'],row['difficulty'],payload['cell'])
                else:
                    try:
                        if row['game_type']=='minesweeper':
                            state = minesweeper.apply_action(row['secret_state'],action,payload.get('cell'))
                        else:
                            state = battleship.apply_action(row['secret_state'],user,action,cell=payload.get('cell'),ships=payload.get('ships'),now=time.time())
                    except ValueError as exc:
                        raise GameError('invalid_action',422,str(exc)) from exc
                    row['secret_state'] = state
                    row['version'] += 1
                    if row['game_type']=='battleship' and state['phase']=='active':
                        row['started_at'] = state['started_at']
                        row['expires_at'] = min(state['started_at']+row['rules']['timers']['total_seconds'],state['turn_started_at']+row['rules']['timers']['turn_seconds'])+row['rules']['timers']['grace_seconds']
                    if state['status'] in ('won','lost','draw'):
                        winner = (user if state['status']=='won' else None) if row['game_type']=='minesweeper' else state['winner']
                        await self._finish(conn,row,winner=winner,reason='completed')
                    else:
                        await self._save(conn,row)
                if generate is None:
                    result = dict(success=True,session=self._projection(row,user),server_time=time.time())
                    await self._record(conn,cid,user,payload['request_id'],fp,result,sid=row['id'])
                    return result,200
            reserved = False  # Worker completion owns the admission slot now.
            return await self._generate(cid,user,payload,fp,generate)
        finally:
            if reserved: self._generating -= 1

    async def _generate(self, cid, user, payload, fp, reservation):
        sid, token, difficulty, first = reservation
        state, error = None, None
        try:
            task = asyncio.create_task(asyncio.to_thread(minesweeper.initialize,first,difficulty))
            self._generation_tasks.add(task)
            def release(done):
                self._generating -= 1
                self._generation_tasks.discard(done)
                if not done.cancelled():
                    done.exception()  # Consume exceptions after an HTTP timeout.
            task.add_done_callback(release)
            # Timeout/cancel must not free admission while CPU is still running.
            state = await asyncio.wait_for(asyncio.shield(task),timeout=config.GENERATION_SECONDS)
        except Exception as exc:
            logger.warning('Skillgame generation failed: %s',type(exc).__name__)
            error = 'generation_failed'
        async with self._tx() as conn:
            row = await self._load(conn,cid,sid,user)
            await self._expire(conn,row)
            if row['status']!='generating' or row['generation_token']!=token:
                result = dict(success=False,reason='service_unavailable',session=self._projection(row,user),server_time=time.time())
                await self._record(conn,cid,user,payload['request_id'],fp,result,503,sid)
                return result,503
            row['version'] += 1
            if error:
                await self._finish(conn,row,reason=error,void=True)
                result = dict(success=False,reason=error,message='Не удалось подготовить поле. Попытка отменена без потери рейтинга.',session=self._projection(row,user),server_time=time.time())
            else:
                row['secret_state'] = state
                row['status'] = 'active'
                row['generation_token'] = None
                row['started_at'] = time.time()
                row['expires_at'] = row['started_at']+row['rules']['timers']['attempt_seconds']
                if state['status'] in ('won','lost'):
                    await self._finish(conn,row,winner=user if state['status']=='won' else None,reason='completed')
                else:
                    await self._save(conn,row)
                result = dict(success=True,session=self._projection(row,user),server_time=time.time())
            code = 503 if error else 200
            await self._record(conn,cid,user,payload['request_id'],fp,result,code,sid)
            return result,code
