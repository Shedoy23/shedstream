# -*- coding: utf-8 -*-
"""Migration M109 — `module_last_seen`: когда игровой мод последний раз выходил
на связь, в БАЗЕ, а не в памяти процесса.

ЗАЧЕМ (2026-08-05/06). Отметка «мод жив» жила в обычном словаре внутри
процесса. Пока по ней рисовался только бейдж на дашборде стримера, это было
терпимо. Теперь по ней решается, предлагать ли зрителю платные действия, —
и цена ошибки другая: любой деплой бэкенда обнулял бы словарь, и расширение
у ВСЕХ зрителей на полминуты объявляло бы игру выключенной посреди стрима.

Повод завести именно сейчас: 05.08 стрим шёл под другой игрой, `active_module`
канала остался прежним, и пять зрителей забрали ежедневный бонус в пустоту —
отметка «забрал» записалась, награда не выдана, потому что мода не было.
"""


async def apply(conn):
    name = "M109.module_last_seen"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,)
    )
    if await cur.fetchone():
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS module_last_seen (
            channel_id   INTEGER NOT NULL,
            module_id    TEXT    NOT NULL,
            last_seen_ts REAL    NOT NULL,
            PRIMARY KEY (channel_id, module_id)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_module_last_seen_ch "
        "ON module_last_seen(channel_id, last_seen_ts)"
    )
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
    print("✅ M109: module_last_seen table created")
