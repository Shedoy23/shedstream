"""
Migration M59 — Kingdom tax (Backlog #1, BLT-RC22 C.5 KingdomTaxBehavior).

Король (viewer-ruler королевства) задаёт налоговую ставку 0-100%. Раз в день
мод собирает rate% дневной прибыли вассальных кланов в казну короля.

Storage: ставка — это PROJECTION для отображения (см. ARCH_DATA_OWNERSHIP.md).
Authority живёт в моде (KingdomTaxBehavior.SyncData). Backend хранит последнее
заданное значение на строке короля, чтобы Kingdom-панель показывала текущую
ставку. Расхождение (если случится) косметическое — мод перезапишет эффектом.

Один столбец на bannerlord_heroes:
  kingdom_tax_pct INTEGER DEFAULT 0  — 0..100, последняя заданная королём ставка.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M59.kingdom_tax"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    existing_cols = {row[1] for row in await cur.fetchall()}
    if "kingdom_tax_pct" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN kingdom_tax_pct INTEGER DEFAULT 0"
        )
    print("M59: bannerlord_heroes.kingdom_tax_pct added")

    await conn.commit()
    await _mark_applied(conn, "M59.kingdom_tax")


async def _ensure_migrations_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS migrations_applied (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _is_applied(conn, name: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,)
    )
    return await cur.fetchone() is not None


async def _mark_applied(conn, name: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
