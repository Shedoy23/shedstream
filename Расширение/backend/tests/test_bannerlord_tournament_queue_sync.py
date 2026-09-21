"""Game-owned tournament queue: restoration, ordering and session fences."""
import asyncio
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, CHANNEL_ID

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'queue.db'))
        try:
            from modules.bannerlord._adapter import BannerlordAdapter
            from modules._base import ModuleEnvelope
            adapter = BannerlordAdapter(None)
            async def sql(q, args=()):
                async with db._connect() as conn:
                    rows = await (await conn.execute(q, args)).fetchall()
                    await conn.commit()
                    return rows
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')", (CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)", (CHANNEL_ID,))
            async def snapshot(seq, users, **extra):
                data = dict(save_id='save-a', equipment_session_id='session-a', queue_seq=seq,
                            entries=[dict(username=u,entry_fee=0) for u in users])
                data.update(extra)
                await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(id='queue',kind='event',type='tournament.queue_snapshot',ts=seq,data=data))
            async def queue():
                return [r[0] for r in await sql('SELECT username FROM bannerlord_tournament_queue WHERE channel_id=? ORDER BY joined_at, rowid', (CHANNEL_ID,))]
            restored = [f'viewer{i}' for i in range(13)]
            await snapshot(1, restored)
            assert await queue() == restored, 'Saved queue must restore all 13 viewers in order'
            await snapshot(2, ['waiting'])
            await snapshot(1, restored)
            await snapshot(3, [], save_id='other-save')
            await snapshot(4, [], equipment_session_id='old-session')
            assert await queue() == ['waiting'], 'Old sequence/save/session must not overwrite current queue'
            await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(id='start',kind='event',type='tournament.started',ts=5,data={'participants':restored}))
            assert await queue() == ['waiting'], 'Start must preserve viewers waiting for the next tournament'
            await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(id='late',kind='event',type='tournament.joined',ts=6,data={'username':'ghost'}))
            assert await queue() == ['waiting'], 'Late legacy joins must not resurrect snapshot-owned entries'
            try:
                await snapshot(5, ['same','same'])
            except ValueError:
                pass
            else:
                raise AssertionError('Duplicate snapshot must be rejected atomically')
            assert await queue() == ['waiting']
            await sql("INSERT INTO bannerlord_tournament_queue(channel_id,username,entry_fee) VALUES(?,'other-channel',0)", (CHANNEL_ID+1,))
            await snapshot(6, [])
            assert await queue() == [], 'Empty authoritative queue must clear mirror'
            assert await sql('SELECT username FROM bannerlord_tournament_queue WHERE channel_id=?',(CHANNEL_ID+1,)) == [('other-channel',)]
            await sql("UPDATE bannerlord_equipment_sessions SET session_id='session-b' WHERE channel_id=?",(CHANNEL_ID,))
            await snapshot(1, ['new-session'], equipment_session_id='session-b')
            assert await queue() == ['new-session'], 'Sequence restarts when campaign session changes'
            print('PASS tournament queue: restore 13, order, sequence/save/session fences, leftovers, late joins, invalid payload, empty, tenant isolation, new session')
        finally:
            await db._pool.close()

if __name__ == '__main__':
    asyncio.run(main())
