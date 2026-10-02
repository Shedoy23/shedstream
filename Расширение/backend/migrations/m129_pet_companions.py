"""Six fixed-price rare companion skins, approved by owner 2026-09-26."""
from pet_collection import seed_collection


async def apply(conn):
    await conn.execute('CREATE TABLE IF NOT EXISTS migrations_applied (name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    name = 'M129.pet_companions'
    if await (await conn.execute('SELECT 1 FROM migrations_applied WHERE name=?', (name,))).fetchone():
        return
    await seed_collection(conn)
    await conn.execute('INSERT INTO migrations_applied(name) VALUES(?)', (name,))
    await conn.commit()

