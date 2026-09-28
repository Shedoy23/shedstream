"""
Migration M89: attendance first_seen_at — серверное время как гейт стрик-награды (2026-07-02).

Security-фикс (аудит 2026-07-02): POST /api/viewer/attendance берёт `minutes` из
запроса зрителя, а награда (1000×streak) выдавалась при minutes>=15 → crafted-запрос
с minutes=15 забирал стрик БЕЗ реального просмотра. Фикс: record_attendance теперь
гейтит claim по СЕРВЕРНОМУ времени — награда доступна только когда с первого пинга
(first_seen_at) прошло >= 15 реальных минут (нельзя ускорить клиентским `minutes`).

Схема: stream_attendance += first_seen_at TIMESTAMP (nullable — SQLite ALTER не даёт
non-const DEFAULT; выставляется явно на INSERT и backfill'ится COALESCE'ом на следующем
пинге в record_attendance). Legacy-строки до M89 остаются NULL → grandfathered.

Идемпотентно: migrations_applied['M89.attendance_first_seen'] + PRAGMA-гард.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M89.attendance_first_seen"):
        return

    if not await _has_column(conn, "stream_attendance", "first_seen_at"):
        await conn.execute(
            "ALTER TABLE stream_attendance ADD COLUMN first_seen_at TIMESTAMP"
        )

    await conn.commit()
    await _mark_applied(conn, "M89.attendance_first_seen")
    print("✅ M89: stream_attendance.first_seen_at (server-time gate для стрик-награды)")


async def _has_column(conn, table: str, column: str) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in await cur.fetchall())


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
