"""M132: недавние возвраты в /my-hero читают только последние 30 секунд.

25.09.2026 на прод-базе этот запрос перебирал все ~27 тыс. платных действий
канала и сортировал их — 153 мс на каждый опрос /my-hero, около трети ядра на
стриме. Проверяем план запроса (индекс по времени) и что результат прежний.
"""
import asyncio
import json
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, CHANNEL_ID


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'refunds.db'))
        try:
            from routes.bannerlord import RECENT_REFUNDS_SQL
            async with db._connect() as conn:
                rows = [(CHANNEL_ID, 'bannerlord', f'old{i}', 'player.spawn', json.dumps({'initiated_by': 'alice'}),
                         'failed', 'REFUNDED:50 reason=x', '2026-01-01 00:00:00') for i in range(3000)]
                await conn.executemany(
                    "INSERT INTO module_actions(channel_id,module_id,action_id,type,data,status,error_msg,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)", rows)
                await conn.execute(
                    "INSERT INTO module_actions(channel_id,module_id,action_id,type,data,status,error_msg,created_at) "
                    "VALUES(?,?,?,?,?,?,?,datetime('now'))",
                    (CHANNEL_ID, 'bannerlord', 'fresh', 'player.spawn', json.dumps({'initiated_by': 'alice'}),
                     'failed', 'REFUNDED:50 reason=offline'))
                await conn.commit()
                plan = ' '.join(str(r[-1]) for r in await (await conn.execute(
                    "EXPLAIN QUERY PLAN " + RECENT_REFUNDS_SQL, (CHANNEL_ID,))).fetchall())
                found = [r[0] for r in await (await conn.execute(RECENT_REFUNDS_SQL, (CHANNEL_ID,))).fetchall()]
            assert 'idx_module_actions_recent' in plan, plan
            assert found == ['fresh'], found
            print('PASS recent refunds: time index used, only the last 30 s returned')
        finally:
            await db._pool.close()


if __name__ == '__main__':
    asyncio.run(main())
