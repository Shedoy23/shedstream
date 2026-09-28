# -*- coding: utf-8 -*-
"""M99 — ворота для стримеров: поле «одобрен» в реестре каналов.

ЗАЧЕМ. Регистрация стримера сегодня полностью самообслуживаемая: зашёл на
`/streamer`, вошёл через Twitch — и канал в реестре, работает. Пока расширение
не опубликовано, это незаметно: чужие о нём не знают.

В день одобрения Twitch защита по имени «безвестность» исчезает разом. Любой
стример поставит расширение, зарегистрируется, пойдёт по пути установки мода,
который никто ни разу не проходил чужими руками, упрётся — и напишет владельцу.
Это не постепенный рост нагрузки, а обрыв: было ноль, стало сколько придёт,
в тот же вечер. Владелец работает соло, его время — главный дефицит проекта.

Правильный порядок — сначала ворота, потом автоматика, когда путь обкатан.
Сейчас у нас автоматика БЕЗ ворот, то есть худшая комбинация.

БЕЗОПАСНОСТЬ УМОЛЧАНИЙ (главное в этой миграции):
  * все УЖЕ существующие каналы получают approved = 1. Канал владельца не
    должен закрыться ни на секунду — цена такой ошибки это мёртвое расширение
    на живом стриме;
  * колонка объявлена DEFAULT 0, поэтому КАЖДЫЙ НОВЫЙ канал приходит
    «ожидающим». Умолчание выбрано так, что забывчивость безопасна: забудешь
    одобрить — человек подождёт; забудь мы наоборот — в систему молча зайдёт
    кто угодно.

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
    name = "M99.channel_approval"
    if await _is_applied(conn, name):
        return

    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='channels'")
    if not await cur.fetchone():
        # Свежая база: таблицу создаст m4_channels с уже актуальным DDL.
        await conn.execute(
            "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
        await conn.commit()
        return

    if not await _has_column(conn, "channels", "approved"):
        await conn.execute(
            "ALTER TABLE channels ADD COLUMN approved INTEGER NOT NULL DEFAULT 0")
        # Все, кто уже был, — одобрены. Иначе владелец закроет сам себя.
        cur = await conn.execute("UPDATE channels SET approved = 1")
        print("✅ M99: колонка approved добавлена, существующих каналов "
              "одобрено: %d" % cur.rowcount)

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M99: ворота для стримеров готовы (новые каналы — «ожидает»)")
