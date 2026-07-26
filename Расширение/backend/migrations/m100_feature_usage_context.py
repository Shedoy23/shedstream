# -*- coding: utf-8 -*-
"""M100 — записывать, какая игра была в эфире, рядом со счётчиком фич.

ЗАЧЕМ. Метрика `feature_usage` хранит только (канал, фича, день, счётчик).
Из-за этого она СМЕШИВАЕТ два совершенно разных факта: «фичей не захотели
пользоваться» и «фичей не могли пользоваться, потому что стример играл в другую
игру». Различить их потом нельзя.

2026-07-26 это привело к неверному выводу: у RimWorld ноль использований, и я
предложил модуль похоронить. Владелец поправил — ноль был гарантирован
устройством, он просто не стримил RimWorld в окне замера, а стример не может
играть в две игры одновременно. Метрика физически не могла показать другое.

С колонкой `active_module` вопрос становится осмысленным: «сколько раз фичу
использовали в дни, когда ЕЁ игра была в эфире». Только тогда ноль что-то значит.

Старые строки остаются с NULL — честно: для них контекст не сохранялся, и
задним числом его не восстановить.

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
    name = "M100.feature_usage_context"
    if await _is_applied(conn, name):
        return

    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='feature_usage'")
    if await cur.fetchone():
        if not await _has_column(conn, "feature_usage", "active_module"):
            await conn.execute(
                "ALTER TABLE feature_usage ADD COLUMN active_module TEXT")
            print("✅ M100: active_module добавлен в feature_usage "
                  "(старые строки остаются с NULL — контекст не сохранялся)")

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M100: метрика теперь помнит, какая игра была в эфире")
