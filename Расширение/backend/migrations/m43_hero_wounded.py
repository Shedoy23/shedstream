"""
Migration M43 — `bannerlord_heroes.is_wounded` column.

Sprint 5.32 — Bannerlord state machine богаче чем бинарное alive/dead:
  - Hero.IsAlive=true, IsWounded=true → KO'd в бою, оживёт через несколько дней
  - Hero.IsAlive=true, IsWounded=false → активный
  - Hero.IsPrisoner=true → в плену
  - Hero.IsAlive=false → permanent death (триггерит "Создать нового")

Раньше viewer'у показывали только 💚 жив / 💀 мёртв badge. Если hero KO'd
в битве, badge оставался 💚 — viewer думал что баг. Теперь добавляем 🟡
ранен state и показываем правильно.

Idempotent: ALTER TABLE ... ADD COLUMN на existing rows проставит DEFAULT 0
(не wounded). Через `if "is_wounded" not in cols` чтобы не было ошибки
при повторном apply.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M43.hero_wounded"):
        return

    # Check existing schema before ALTER.
    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    cols = {row[1] for row in await cur.fetchall()}
    if "is_wounded" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes "
            "ADD COLUMN is_wounded INTEGER NOT NULL DEFAULT 0"
        )
        print("M43: bannerlord_heroes.is_wounded column added")
    else:
        print("M43: is_wounded column already exists, skipped ALTER")

    await conn.commit()
    await _mark_applied(conn, "M43.hero_wounded")


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
