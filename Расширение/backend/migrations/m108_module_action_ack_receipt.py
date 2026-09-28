# -*- coding: utf-8 -*-
"""M108 — отдельный receipt ACK для terminal module actions.

`action.failed` может прийти раньше обычного ACK: обработчик игры сообщает
фактический отказ асинхронно, а poller подтверждает получение команды позже.
Terminal status и `REFUNDED:*` менять нельзя, но без отдельного receipt такой
ACK полностью терялся и строка выглядела как «connector не ответил».

Колонки nullable для старых строк. Миграция идемпотентна и безопасна как для
старой M5-схемы, так и для fresh install, где поля уже входят в SCHEMA.
"""


async def _has_column(conn, table: str, column: str) -> bool:
    cur = await conn.execute("PRAGMA table_info(%s)" % table)
    return any(row[1] == column for row in await cur.fetchall())


async def apply(conn) -> None:
    name = "M108.module_action_ack_receipt"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name=?", (name,))
    if await cur.fetchone():
        return

    columns = (
        ("ack_received_at", "TIMESTAMP"),
        ("ack_success", "INTEGER"),
        ("ack_error", "TEXT"),
    )
    for column, sql_type in columns:
        if not await _has_column(conn, "module_actions", column):
            await conn.execute(
                "ALTER TABLE module_actions ADD COLUMN %s %s" %
                (column, sql_type))

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M108: module_actions получил отдельный ACK receipt")
