# -*- coding: utf-8 -*-
"""M103 — почтовый ящик зрителя: почему действие не сработало.

ЗАЧЕМ. Отказ мода возвращает крустики молча. Причина известна бэкенду
(`module_actions.error_msg` = `REFUNDED:<цена> reason=<код>`), но до панели
канала она не доходит никак: зритель видит, что деньги вернулись, и не знает —
он что-то сделал не так, игра была в бою, или сломались мы.

Наблюдаемое следствие уже фиксировалось: зритель повторяет платное действие
несколько раз подряд (баги #16/#17 — объявление войны 4×), потому что «ничего
не произошло» неотличимо от «не нажалось».

Таблица общая для платформы, не для одной игры: тем же каналом поедут истёкшие
покупки и прочие тихие возвраты.

`seen_at IS NULL` — непрочитанное. Панель забирает непрочитанное и подтверждает
показ отдельным запросом; поэтому потерянный ответ не съедает уведомление.

Идемпотентно через `migrations_applied`.
"""


async def _is_applied(conn, name: str) -> bool:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,))
    return await cur.fetchone() is not None


async def apply(conn) -> None:
    name = "M103.viewer_notices"
    if await _is_applied(conn, name):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS viewer_notices (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            username   TEXT    NOT NULL,
            kind       TEXT    NOT NULL,
            text       TEXT    NOT NULL,
            amount     INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            seen_at    TIMESTAMP
        )
    """)
    # Единственный горячий запрос — «непрочитанное этого зрителя на этом
    # канале». Сторож чистит по created_at.
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_notices_unseen "
        "ON viewer_notices(channel_id, username, seen_at)")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_notices_age "
        "ON viewer_notices(created_at)")

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M103: причина отказа теперь доезжает до зрителя (viewer_notices)")
