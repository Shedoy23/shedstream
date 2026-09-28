# -*- coding: utf-8 -*-
"""M98 — ключ для распознавания повторного клика в очереди команд RimWorld.

ЗАЧЕМ. Зритель жмёт «купить» дважды (лаг, нетерпение, случайный дабл-клик) —
уходит два одинаковых запроса, списывается дважды, а получает он одно. У
Bannerlord это закрыто клиентским `client_action_id` (M46): фронт генерирует
идентификатор попытки, бэк по нему узнаёт повтор. У RimWorld такого нет, и
попросить фронт мы сейчас не можем — он заморожен на CDN до вердикта Twitch.

РЕШЕНИЕ БЕЗ ФРОНТА. Два клика по одной кнопке дают побайтово одинаковую команду,
отличается только служебное поле `id`. Значит ключ выводится из самого
содержимого: отпечаток команды без `id`. Разные покупки дают разные отпечатки
сами собой — знать про каждый тип команды ничего не нужно.

Колонка + индекс (channel_id, dedup_key, created_at): проверка «был ли такой же
за последние N секунд» идёт ВНУТРИ той же транзакции, что списание, поэтому
двух одновременных запросов не рассинхронизировать.

Идемпотентно через `migrations_applied`.
"""


async def _is_applied(conn, name: str) -> bool:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,))
    return await cur.fetchone() is not None


async def _table_exists(conn, table: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return await cur.fetchone() is not None


async def _has_column(conn, table: str, column: str) -> bool:
    cur = await conn.execute("PRAGMA table_info(%s)" % table)
    return any(r[1] == column for r in await cur.fetchall())


async def apply(conn) -> None:
    name = "M98.rimworld_dedup_key"
    if await _is_applied(conn, name):
        return

    # Таблица создаётся лениво при первой команде. Если её ещё нет — колонка
    # уже заложена в актуальном DDL (`_ensure_pending_commands_table`),
    # мигрировать нечего.
    if await _table_exists(conn, "rimworld_pending_commands"):
        if not await _has_column(conn, "rimworld_pending_commands", "dedup_key"):
            await conn.execute(
                "ALTER TABLE rimworld_pending_commands ADD COLUMN dedup_key TEXT")
            print("✅ M98: dedup_key добавлен в rimworld_pending_commands")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rw_cmds_dedup "
            "ON rimworld_pending_commands(channel_id, dedup_key, created_at)")

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M98: защита от двойного клика готова")
