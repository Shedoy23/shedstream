"""Two original skins remain available as common; existing ownership is untouched."""
async def apply(conn):
    await conn.execute('CREATE TABLE IF NOT EXISTS migrations_applied (name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    name = 'M133.pet_legacy_common'
    if await (await conn.execute('SELECT 1 FROM migrations_applied WHERE name=?', (name,))).fetchone():
        return
    # Developer-owned global cosmetic catalogue, not viewer or channel balances.
    await conn.execute(
        "UPDATE pet_catalog SET rarity='common' WHERE item_id IN (?,?)",
        ('skin_kimono', 'skin_underwear'),
    )
    await conn.execute('INSERT INTO migrations_applied(name) VALUES(?)', (name,))
    await conn.commit()
