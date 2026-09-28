"""Six fantasy skins: rare, 500000 crustics, approved 2026-09-26."""
from pet_collection import FANTASY_COMPANIONS, seed_collection


async def apply(conn):
    await conn.execute('CREATE TABLE IF NOT EXISTS migrations_applied (name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    name = 'M130.pet_fantasy'
    if await (await conn.execute('SELECT 1 FROM migrations_applied WHERE name=?', (name,))).fetchone():
        return
    await seed_collection(conn, FANTASY_COMPANIONS)
    await conn.execute('INSERT INTO migrations_applied(name) VALUES(?)', (name,))
    await conn.commit()
