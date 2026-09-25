"""Кэш каталога магазина снаряжения (25.09.2026, оптимизация после лагов).

Кэш обязан: (1) видеть перезапись каталога даже при том же числе вещей —
мод переписывает его раз в 5 минут; (2) видеть удаление; (3) не делить
вещи между каналами; (4) отдавать копии — роут дописывает в вещь поля
конкретного зрителя, и они не должны утечь в следующий ответ.
"""
import asyncio
import json
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, CHANNEL_ID

OTHER = CHANNEL_ID + 1


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'cache.db'))
        try:
            from modules.bannerlord.equipment_shop import catalog

            async def write(channel_id, entries):
                async with db._connect() as conn:
                    await conn.execute("DELETE FROM module_catalogs WHERE channel_id=? AND module_id='bannerlord' AND catalog_type='equipment'", (channel_id,))
                    for e in entries:
                        await conn.execute(
                            "INSERT OR REPLACE INTO module_catalogs(channel_id,module_id,catalog_type,entry_id,payload) VALUES(?,'bannerlord','equipment',?,?)",
                            (channel_id, e['item_id'], json.dumps(e)))
                    await conn.commit()

            async def read(channel_id):
                async with db._connect() as conn:
                    return await catalog(conn, channel_id)

            await write(CHANNEL_ID, [dict(item_id='axe', price_gold=300)])
            await write(OTHER, [dict(item_id='bow', price_gold=900)])
            first = await read(CHANNEL_ID)
            assert [x['item_id'] for x in first] == ['axe'], first
            first[0]['can_buy'] = True
            again = await read(CHANNEL_ID)
            assert 'can_buy' not in again[0], 'viewer fields must not leak into the next response'
            assert [x['item_id'] for x in await read(OTHER)] == ['bow'], 'channels must not share a catalog'

            # Та же длина каталога, другое содержимое — самый вероятный случай
            # на проде (мод переписывает тот же набор с новыми ценами).
            await write(CHANNEL_ID, [dict(item_id='axe', price_gold=450)])
            assert (await read(CHANNEL_ID))[0]['price_gold'] == 450, 'rewrite with same count must refresh the cache'

            await write(CHANNEL_ID, [])
            assert await read(CHANNEL_ID) == [], 'deleted catalog must not be served from cache'
            print('PASS equipment catalog cache: refresh on rewrite and delete, per channel, copies per response')
        finally:
            await db._pool.close()


if __name__ == '__main__':
    asyncio.run(main())
