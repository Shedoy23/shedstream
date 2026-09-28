# -*- coding: utf-8 -*-
"""M102 — модерация озвучки: скрытие сообщения и блок-лист зрителей.

ЗАЧЕМ. Озвучка — пользовательский контент, и Twitch требует к нему набор
возможностей модерации (удаление, блокировка автора, история). У нас не было
ничего: сообщение проходило оплату и СРАЗУ уходило на оверлей со статусом
'pending'. Единственным барьером была цена в 5000💎.

Версия 0.0.1 ревью прошла — скорее всего потому, что у ревьюера не было такой
суммы, чтобы дойти до функции. Следующую подачу смотрят заново, а в правилах
Twitch про UGC прямо сказано: «Missing these features significantly delays
approval».

ЧТО ДЕЛАЕМ.

1. `tts_messages.moderated_by` — кто скрыл сообщение (логин стримера/модератора)
   и `moderated_at`. **Почему колонка, а не новый статус:** у таблицы жёсткий
   `CHECK (status IN ('pending','played'))`, и добавить 'rejected' в SQLite
   можно только пересоздав таблицу целиком. Пересоздавать боевую таблицу с
   историей ради одного значения — риск больше пользы. Скрытое сообщение
   остаётся в истории со своим статусом, но оверлей его не берёт.

2. `tts_blocked_users` — блок-лист на канал. Заблокированный зритель не может
   отправить озвучку, и деньги с него не списываются (отказ до оплаты).

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Синхронизации с банами канала Twitch и AutoMod-
фильтрации: для них нужен scope `moderation:read`, которого у наших токенов
нет. Добавление скоупа потребует повторной авторизации от КАЖДОГО стримера —
это отдельное решение владельца, а не побочный эффект миграции.

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
    name = "M102.tts_moderation"
    if await _is_applied(conn, name):
        return

    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tts_messages'")
    if await cur.fetchone():
        if not await _has_column(conn, "tts_messages", "moderated_by"):
            await conn.execute(
                "ALTER TABLE tts_messages ADD COLUMN moderated_by TEXT")
        if not await _has_column(conn, "tts_messages", "moderated_at"):
            await conn.execute(
                "ALTER TABLE tts_messages ADD COLUMN moderated_at TIMESTAMP")
        print("✅ M102: tts_messages получил поля модерации")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS tts_blocked_users (
            channel_id  INTEGER NOT NULL,
            username    TEXT    NOT NULL,
            blocked_by  TEXT,
            reason      TEXT,
            blocked_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username)
        )
    """)

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M102: модерация озвучки — блок-лист и скрытие сообщений")
