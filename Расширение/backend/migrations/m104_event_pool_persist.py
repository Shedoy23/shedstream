# -*- coding: utf-8 -*-
"""M104 — копилка ивента переезжает из оперативной памяти в базу.

ЗАЧЕМ. Зритель скидывает крустики в копилку («рулекцион»): списание идёт в
базу, а сама копилка живёт полем `EventManager.event_pool` в памяти процесса.
Любой рестарт бэкенда — деплой, перезапуск supervisor'ом, падение — обнуляет
её. Крустики при этом уже списаны: ни возврата, ни записи о взносе, ни следа.

Копилка стартует ивент при 100 000💎 и копится днями. Деплой в середине
накопления стирает всё, что успели собрать. То есть при регулярных деплоях
порог может не достигаться в принципе — зрители платят в дырявое ведро.

Таблицы:
  event_pool              — сколько накоплено на канале (одна строка на канал)
  event_pool_contributors — кто сколько внёс в ТЕКУЩИЙ круг (для топа
                            вкладчиков; обнуляется при старте ивента)

Обе привязаны к каналу: прежний код списывал крустики через
`remove_points(username, amount)` без канала, то есть всегда с канала по
умолчанию. На одном канале незаметно, на втором — чужие деньги.

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
    name = "M104.event_pool_persist"
    if await _is_applied(conn, name):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS event_pool (
            channel_id INTEGER PRIMARY KEY,
            pool       INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS event_pool_contributors (
            channel_id INTEGER NOT NULL,
            username   TEXT    NOT NULL,
            amount     INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username)
        )
    """)

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M104: копилка ивента переживает рестарт (event_pool)")
