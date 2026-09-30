"""Fantasy catalogue migration and real purchase transactions for all six skins."""
import asyncio
import aiosqlite
from test_pet_collection_purchase import main as purchase_scenarios


async def main():
    from pet_collection import COMPANIONS, FANTASY_COMPANIONS, get_pet_price
    from migrations import m129_pet_companions, m130_pet_fantasy
    assert len(FANTASY_COMPANIONS) == 6
    assert set(COMPANIONS).isdisjoint(FANTASY_COMPANIONS)
    for variant in FANTASY_COMPANIONS:
        await purchase_scenarios(variant)
        assert get_pet_price('skin_' + variant, 'rare') == 500000
    async with aiosqlite.connect(':memory:') as conn:
        await conn.execute('CREATE TABLE pet_catalog(item_id TEXT PRIMARY KEY,name TEXT,slot TEXT,price_bits INTEGER,rarity TEXT,emoji TEXT,png_path TEXT,deprecated INTEGER)')
        await m129_pet_companions.apply(conn)
        before = await (await conn.execute('SELECT * FROM pet_catalog ORDER BY item_id')).fetchall()
        await m130_pet_fantasy.apply(conn)
        await m130_pet_fantasy.apply(conn)
        assert (await (await conn.execute('SELECT count(*) FROM pet_catalog')).fetchone())[0] == 12
        for row in before:
            assert await (await conn.execute('SELECT * FROM pet_catalog WHERE item_id=?', (row[0],))).fetchone() == row
        for variant in FANTASY_COMPANIONS:
            assert await (await conn.execute('SELECT rarity,png_path FROM pet_catalog WHERE item_id=?', ('skin_' + variant,))).fetchone() == ('rare', f'pet-assets/v2/{variant}/south.png')
    print('PASS: six fantasy purchases at 500000; idempotent migration preserves first collection')


if __name__ == '__main__':
    asyncio.run(main())
