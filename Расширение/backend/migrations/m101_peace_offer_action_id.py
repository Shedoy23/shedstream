# -*- coding: utf-8 -*-
"""M101 — связать заявку на мир с действием, которое её породило.

ЗАЧЕМ. `bannerlord_peace_offers` пишется со статусом 'pending' и не имеет
никакой связи с действием в очереди. Закрыть такую заявку по итогу действия
физически нечем — нет ключа, по которому её найти.

Последствие серьёзнее, чем мусор в таблице. Уникальный индекс
`idx_peace_pending_unique` частичный, `WHERE status = 'pending'`: пока заявка
висит в этом статусе, тот же зритель-король НЕ МОЖЕТ предложить мир той же
фракции ещё раз — вставка падает на UNIQUE, а зритель видит «Peace offer уже
отправлен». То есть один неудачный запрос закрывает направление навсегда.

На проде 2026-07-28 в таком состоянии висит заявка id=1.

Колонка `action_id` даёт эту связь: отказ действия (в том числе истечение по
TTL) переводит заявку в терминальный статус, и направление снова открыто.

Старые строки остаются с NULL — для них action_id не сохранялся, и задним
числом его не восстановить. Их разберёт сторож по возрасту.

Идемпотентно через `migrations_applied`.
"""


async def _is_applied(conn, name: str) -> bool:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,))
    return await cur.fetchone() is not None


async def _has_column(conn, table: str, column: str) -> bool:
    cur = await conn.execute("PRAGMA table_info(%s)" % table)
    return any(r[1] == column for r in await cur.fetchall())


async def apply(conn) -> None:
    name = "M101.peace_offer_action_id"
    if await _is_applied(conn, name):
        return

    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='bannerlord_peace_offers'")
    if await cur.fetchone():
        if not await _has_column(conn, "bannerlord_peace_offers", "action_id"):
            await conn.execute(
                "ALTER TABLE bannerlord_peace_offers ADD COLUMN action_id TEXT")
            print("✅ M101: action_id добавлен в bannerlord_peace_offers "
                  "(старые строки с NULL — их разберёт сторож по возрасту)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_peace_action "
            "ON bannerlord_peace_offers(channel_id, action_id)")

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M101: заявка на мир теперь закрывается по итогу своего действия")
