"""Багрепорт #72 (26.09.2026): найм свиты заблокирован до перезагрузки панели.

Замороженная панель перерисовывает блок свиты, только когда меняется JSON
списка `retinue` из /my-hero, а кнопки найма и «не хватает N💰» считает от
золота героя на момент отрисовки. Золото росло после боёв, список — нет.
Обход на бэке: у каждого бойца свиты ключ перерисовки из золота и предела.
Проверяем ровно то сравнение, которое делает панель (JSON списка).
"""
import asyncio
import json
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'retinue.db'))
        try:
            from routes import bannerlord as route
            route.require_jwt_user = lambda req: ('alice', CHANNEL_ID)

            async def sql(query, args=()):
                async with db._connect() as conn:
                    await conn.execute(query, args)
                    await conn.commit()

            async def retinue_json():
                data = await route.bannerlord_my_hero(_make_anon_request())
                assert data.get('success'), data
                # Панель: JSON.stringify(data.retinue) против прошлого снимка.
                return json.dumps(data['retinue'], ensure_ascii=False, sort_keys=False)

            await sql("UPDATE bannerlord_heroes SET gold=1000 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            for slot in range(6):
                await sql("INSERT INTO bannerlord_retinue(channel_id,username,slot_index,troop_id,troop_name,tier) "
                          "VALUES(?,?,?,?,?,?)", (CHANNEL_ID, 'alice', slot, 'vlandia_recruit', 'Рекрут', 1))

            before = await retinue_json()
            assert await retinue_json() == before, 'no change in gold — panel must not repaint the block'
            await sql("UPDATE bannerlord_heroes SET gold=90000 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            after = await retinue_json()
            assert after != before, 'gold changed — retinue JSON must change so the frozen panel re-enables hire'
            assert all(x['troop_id'] == 'vlandia_recruit' for x in json.loads(after)), 'members themselves unchanged'
            print('PASS retinue render key: gold change repaints the hire block, no change keeps it')
        finally:
            await db._pool.close()


if __name__ == '__main__':
    asyncio.run(main())
