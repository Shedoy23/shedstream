# -*- coding: utf-8 -*-
"""m115 — у каждого автосообщения свой таймер, и все они видны стримеру.

ЗАЧЕМ. m114 развела личные сообщения по каналам, но оставила половину работы:
нейтральные сообщения продолжали жить в config.py, а личные — в таблице.
Стример, открыв дашборд, увидел бы только часть своих сообщений и не понял бы,
откуда берутся остальные. Плюс интервал был один на всех (раз в 3 минуты по
кругу) — нельзя было сказать «про донат раз в час, а про квесты раз в 15 минут».

ЧТО ДЕЛАЕМ.
  1. Таблица получает `interval_min` (свой таймер у каждой строки) и
     `last_sent_at` (когда это сообщение уходило в чат последний раз).
  2. Нейтральные сообщения из `AUTO_MESSAGES` переносятся В ТАБЛИЦУ каждому
     существующему каналу. После этого таблица — единственный источник правды,
     а список в config.py остаётся ШАБЛОНОМ для новых каналов.

Идемпотентно: колонки добавляются только если их нет, сид идёт INSERT OR IGNORE
по (channel_id, position), а каналы, где сид уже был, узнаются по наличию строк
с текстом из шаблона.
"""

DEFAULT_INTERVAL_MIN = 20


async def _columns(conn, table: str) -> set:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in await cur.fetchall()}


async def apply(conn):
    name = "M115.auto_message_timers"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    # m114 могла не примениться на свежей базе — не полагаемся на порядок.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_auto_messages (
            channel_id  INTEGER NOT NULL,
            position    INTEGER NOT NULL,
            text        TEXT    NOT NULL,
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, position)
        )
    """)

    cols = await _columns(conn, "channel_auto_messages")
    if "interval_min" not in cols:
        await conn.execute(
            "ALTER TABLE channel_auto_messages ADD COLUMN interval_min "
            f"INTEGER NOT NULL DEFAULT {DEFAULT_INTERVAL_MIN}"
        )
    if "last_sent_at" not in cols:
        await conn.execute(
            "ALTER TABLE channel_auto_messages ADD COLUMN last_sent_at REAL"
        )

    # Переносим нейтральный шаблон в таблицу каждому каналу, который его ещё
    # не получил. Импорт локальный: config тянет .env, а миграции гоняются и в
    # тестах, где его может не быть.
    from config import AUTO_MESSAGES

    # На свежей установке `channels` может ещё не существовать — порядок
    # миграций там иной, а сеять всё равно некому. Молча пропускаем: новый
    # канал получит шаблон при первом открытии дашборда
    # (`seed_channel_auto_messages`).
    cur = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='channels'"
    )
    if not await cur.fetchone():
        channel_ids = []
    else:
        cur = await conn.execute("SELECT channel_id FROM channels")
        channel_ids = [int(r[0]) for r in await cur.fetchall()]

    for channel_id in channel_ids:
        cur = await conn.execute(
            "SELECT COALESCE(MAX(position), -1), COUNT(*) "
            "FROM channel_auto_messages WHERE channel_id = ?",
            (channel_id,),
        )
        max_pos, _ = await cur.fetchone()
        pos = int(max_pos) + 1
        for text in AUTO_MESSAGES:
            cur = await conn.execute(
                "SELECT 1 FROM channel_auto_messages "
                "WHERE channel_id = ? AND text = ? LIMIT 1",
                (channel_id, text),
            )
            if await cur.fetchone():
                continue        # уже переносили
            await conn.execute(
                "INSERT OR IGNORE INTO channel_auto_messages "
                "(channel_id, position, text, interval_min) VALUES (?,?,?,?)",
                (channel_id, pos, text, DEFAULT_INTERVAL_MIN),
            )
            pos += 1

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
    print("✅ M115: у автосообщений появились свои таймеры")
