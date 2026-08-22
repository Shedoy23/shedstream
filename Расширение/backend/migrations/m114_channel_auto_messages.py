# -*- coding: utf-8 -*-
"""m114 — автосообщения бота становятся per-channel.

ЗАЧЕМ. Список `AUTO_MESSAGES` в config.py — один на всю платформу, а бот
рассылает его в чат КАЖДОГО канала из реестра. Внутри списка жили личные
ссылки владельца: DonationAlerts, Boosty и его Telegram. С одним стримером это
незаметно. Со вторым бот начал бы рекламировать чужие донаты в его чате —
худший возможный первый день: стример вправе счесть это мошенничеством, а бота
забанить. Найдено 2026-08-22 по прямому наблюдению владельца («сообщения
навязаны на мой канал»).

ЧТО ДЕЛАЕМ. Общий список в config.py остаётся, но становится НЕЙТРАЛЬНЫМ —
только про механики самого расширения, без ссылок и без названий наград
конкретного канала. Всё личное переезжает в эту таблицу и привязывается к
своему channel_id.

Идемпотентно: таблица создаётся при отсутствии, сид владельца вставляется
через INSERT OR IGNORE по (channel_id, position).
"""

# Личные сообщения владельца (channel_id 98319857) — ровно те, что до сих пор
# лежали в общем списке. Переносим как есть, чтобы поведение его канала не
# изменилось ни на символ.
_OWNER_CHANNEL_ID = 98319857
_OWNER_MESSAGES = [
    (0, '/announcepurple Поддержи стримера, будет крайне благодарен тебе 💜 '
        'https://www.donationalerts.com/r/shedoy23 https://boosty.to/shedoy23'),
    (1, '/announcepurple Наш канал в ТГ и чат, ждём тебя 💜 '
        't.me/ttvshedoy23 https://t.me/+x6Di_VyeFMxhZWE6'),
    (2, '💎 Чтобы участвовать в интеграции, купи в наградах канала '
        'ПОЛУЧИТЬ ДОСТУП К...'),
]


async def apply(conn):
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
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_channel_auto_messages_ch
            ON channel_auto_messages(channel_id, enabled)
    """)

    # Сид ТОЛЬКО для канала владельца. Новый стример получает пустой набор и
    # видит лишь нейтральные сообщения — это и есть цель миграции.
    for position, text in _OWNER_MESSAGES:
        await conn.execute(
            "INSERT OR IGNORE INTO channel_auto_messages "
            "(channel_id, position, text) VALUES (?,?,?)",
            (_OWNER_CHANNEL_ID, position, text),
        )
