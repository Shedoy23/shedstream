# -*- coding: utf-8 -*-
"""M104 — убрать три таблицы, к которым никто не обращается.

ЗАЧЕМ. Прогон `scripts/audit_dead_code.py` 2026-07-29 нашёл таблицы, которые
создаются миграциями, но не встречаются ни в одном запросе вне их самих. На
проде из них существуют три, и все ПУСТЫЕ (проверено запросом, 0 строк):

  twitch_ids                  — след старой схемы сопоставления Twitch-ID
  rimworld_catalog            — предшественник нынешнего каталога RimWorld
  rimworld_purchase_counters  — предшественник счётчиков прогрессивной цены

Решение владельца: «мёртвый нахер не нужен, опять кто-то из-за него
запутается». Причина ровно эта — пустая таблица с правдоподобным именем
выглядит как рабочая и уводит следующего читателя не туда.

ЗАЩИТА. Таблица удаляется ТОЛЬКО если она пуста. Если в ней вдруг окажутся
строки (значит кто-то её всё-таки пишет, и наш анализ был неверен) — миграция
её НЕ трогает и печатает предупреждение. Терять данные ради чистоты нельзя.

Идемпотентно через `migrations_applied`.
"""

_DEAD_TABLES = (
    "twitch_ids",
    "rimworld_catalog",
    "rimworld_purchase_counters",
)


async def _is_applied(conn, name: str) -> bool:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,))
    return await cur.fetchone() is not None


async def apply(conn) -> None:
    name = "M104.drop_dead_tables"
    if await _is_applied(conn, name):
        return

    dropped, kept = [], []
    for table in _DEAD_TABLES:
        cur = await conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not await cur.fetchone():
            continue
        cur = await conn.execute(f"SELECT COUNT(*) FROM {table}")  # tenant-ok: служебная проверка пустоты
        rows = (await cur.fetchone())[0]
        if rows:
            kept.append((table, rows))
            continue
        await conn.execute(f"DROP TABLE {table}")
        dropped.append(table)

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()

    if dropped:
        print(f"✅ M104: удалены пустые таблицы без читателей: {', '.join(dropped)}")
    if kept:
        for table, rows in kept:
            print(f"⚠️ M104: таблица {table} НЕ удалена — в ней {rows} строк, "
                  f"значит её кто-то пишет. Разобраться, прежде чем удалять.")
    if not dropped and not kept:
        print("✅ M104: мёртвых таблиц не найдено (уже чисто)")
