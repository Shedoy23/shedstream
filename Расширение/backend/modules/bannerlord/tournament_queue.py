"""The loaded campaign owns the queue; HTTP delivery order must not own it."""
from datetime import datetime, timedelta, timezone

# Legacy individual events must not overwrite an active snapshot stream.
LEGACY_QUEUE = """NOT EXISTS (
    SELECT 1 FROM bannerlord_tournament_queue_sync q
    JOIN bannerlord_equipment_sessions s ON s.channel_id=q.channel_id AND s.session_id=q.session_id
    WHERE q.channel_id=bannerlord_tournament_queue.channel_id
)"""

async def store_snapshot(db, channel_id, data):
    entries = data.get('entries')
    seq = data.get('queue_seq')
    session = data.get('equipment_session_id')
    save = data.get('save_id')
    if not isinstance(entries, list) or type(seq) is not int or seq < 1 or not session or not save:
        raise ValueError('Invalid tournament queue snapshot')
    rows, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('username'), str):
            raise ValueError('Invalid tournament queue entry')
        username = entry['username'].strip().lower()
        fee = entry.get('entry_fee', 0)
        if not username or username in seen or type(fee) is not int or fee < 0:
            raise ValueError('Invalid or duplicate tournament queue entry')
        seen.add(username)
        rows.append((username, fee))
    async with db._connect() as conn:
        try:
            await conn.execute('BEGIN IMMEDIATE')
            active = await (await conn.execute("""SELECT 1 FROM bannerlord_equipment_sessions s
                JOIN bannerlord_channel_state c ON c.channel_id=s.channel_id
                WHERE s.channel_id=? AND s.session_id=? AND c.current_save_id=?""",
                (channel_id, session, save))).fetchone()
            previous = await (await conn.execute('SELECT session_id,queue_seq FROM bannerlord_tournament_queue_sync WHERE channel_id=?', (channel_id,))).fetchone()
            if not active or (previous and previous[0] == session and previous[1] >= seq):
                await conn.rollback()
                return
            await conn.execute('DELETE FROM bannerlord_tournament_queue WHERE channel_id=?', (channel_id,))
            now = datetime.now(timezone.utc)
            await conn.executemany('INSERT INTO bannerlord_tournament_queue(channel_id,username,entry_fee,joined_at) VALUES(?,?,?,?)',
                [(channel_id, user, fee, (now + timedelta(microseconds=i)).isoformat()) for i,(user,fee) in enumerate(rows)])
            await conn.execute("""INSERT INTO bannerlord_tournament_queue_sync(channel_id,session_id,queue_seq) VALUES(?,?,?)
                ON CONFLICT(channel_id) DO UPDATE SET session_id=excluded.session_id,queue_seq=excluded.queue_seq""", (channel_id,session,seq))
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
