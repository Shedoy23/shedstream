# -*- coding: utf-8 -*-
"""M107 — предварительное одобрение озвучки (гейт) + переключатель канала.

ЗАЧЕМ. M102 дал модерацию РЕАКТИВНУЮ: скрыть сообщение и заблокировать автора
постфактум. Для правил Twitch этого мало. Дословно, Extensions Guidelines §7.2:

    «Extensions must provide broadcasters with the ability to review, and
     reject or approve any image or other audio-visual user content that has
     been submitted through an Extension on their channel.»

Озвучка на оверлее — ровно audio-visual user content. А «reject» после того,
как звук уже прозвучал в эфире, — это не reject: оверлей опрашивает очередь
раз в 3 секунды, и стример физически не успевает. Требование закрывается
только предварительным одобрением.

ЧТО ДЕЛАЕМ.

1. `tts_messages.approved_at` — когда стример одобрил сообщение.
   **Почему колонка, а не новый статус:** причина та же, что в M102 — у таблицы
   жёсткий `CHECK (status IN ('pending','played'))`, и добавить значение в
   SQLite можно только пересоздав таблицу. Пересобирать боевую таблицу с
   аудио-BLOB'ами ради одного значения — риск больше пользы.

2. `channel_tts_settings.require_approval` — переключатель на канал.
   **DEFAULT 1 (гейт включён) — это не вкусовщина, а условие прохождения ревью.**
   Ревьюер смотрит расширение в состоянии по умолчанию; если модерация выключена
   из коробки, он увидит ровно то, что §7.2 запрещает. Стример вправе отключить
   гейт у себя (расширение возможность ПРЕДОСТАВЛЯЕТ — правило соблюдено), но
   отключает он сам и осознанно.

   Существующим каналам тоже ставится 1: на момент миграции гейта не было, и
   тихо оставить их без модерации — значит оставить их в состоянии, которое
   правилам не соответствует.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. AutoMod-фильтрации текста: Submission Best Practices
формулируют её через «must», но нужен scope `moderation:read` и повторная
авторизация от КАЖДОГО стримера. Это отдельное решение владельца (DEFERRED),
а не побочный эффект миграции. Остаточный риск на ревью — есть, записан.

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
    name = "M107.tts_approval_gate"
    if await _is_applied(conn, name):
        return

    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tts_messages'")
    if await cur.fetchone():
        if not await _has_column(conn, "tts_messages", "approved_at"):
            await conn.execute(
                "ALTER TABLE tts_messages ADD COLUMN approved_at TIMESTAMP")
        print("✅ M107: tts_messages получил отметку об одобрении")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_tts_settings (
            channel_id       INTEGER PRIMARY KEY,
            require_approval INTEGER NOT NULL DEFAULT 1,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Существующие каналы — тоже под гейт. Явной строкой, а не «умолчанием при
    # чтении»: настройка, которой нет в базе, невидима стримеру в дашборде.
    await conn.execute(
        "INSERT OR IGNORE INTO channel_tts_settings (channel_id, require_approval) "
        "SELECT channel_id, 1 FROM channels")

    cur = await conn.execute("SELECT COUNT(*) FROM channel_tts_settings")
    n = (await cur.fetchone())[0]

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M107: гейт одобрения озвучки включён для %d канал(ов)" % n)
