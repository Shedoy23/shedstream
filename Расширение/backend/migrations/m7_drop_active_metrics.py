"""
Migration m7_drop_active_metrics: убираем неиспользуемые колонки
`active_clicks` и `active_moves` из `activity_stats`.

Историческая причина: в первых версиях фронт обещал слать счётчики
кликов/движений мыши для антибот-защиты. Реально никогда не реализовано —
INSERT всегда писал нули, никто никогда не читал > 0.

Старый quest `active_viewer` использовал `total_clicks >= 50` как часть
условия — после миграции это условие убирается из bot_core, остаётся
проверка времени и числа сообщений.

Требует SQLite ≥ 3.35 (March 2021). На проде 3.45.

Идемпотентно через `migrations_applied['M7.drop_active_metrics']`.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M7.drop_active_metrics"):
        return

    # Проверяем что колонки существуют (после M1 они должны быть).
    # PRAGMA table_info — sqlite-specific.
    cur = await conn.execute("PRAGMA table_info(activity_stats)")
    columns = {row[1] for row in await cur.fetchall()}

    if "active_clicks" in columns:
        try:
            await conn.execute("ALTER TABLE activity_stats DROP COLUMN active_clicks")
            print("✅ M7: dropped activity_stats.active_clicks")
        except Exception as e:
            print(f"⚠️  M7: drop active_clicks failed: {e}")
    else:
        print("⏭  M7: activity_stats.active_clicks already absent")

    if "active_moves" in columns:
        try:
            await conn.execute("ALTER TABLE activity_stats DROP COLUMN active_moves")
            print("✅ M7: dropped activity_stats.active_moves")
        except Exception as e:
            print(f"⚠️  M7: drop active_moves failed: {e}")
    else:
        print("⏭  M7: activity_stats.active_moves already absent")

    await conn.commit()
    await _mark_applied(conn, "M7.drop_active_metrics")


async def _ensure_migrations_table(conn) -> None:
    """Defensive duplicate (создаётся в M1/M4/M5/M6)."""
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
