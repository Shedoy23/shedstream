# -*- coding: utf-8 -*-
"""m116 — отличать смотрящего зрителя от открытой вкладки.

ЗАЧЕМ. Крустики за просмотр начислялись по одному признаку: панель прислала
heartbeat за последние 15 минут. То есть полную ставку получал и тот, кто
смотрит, и тот, кто открыл вкладку и ушёл. Измерено на эфире 2026-08-20:
пассивно за 9 часов — около 13 500💎, а самый активный в чате (108 сообщений)
получил за них ~900💎. Чат был 7% от пассива.

ЧТО ДОБАВЛЯЕМ.

1. `viewers.last_interaction_at` — когда зритель последний раз ДЕЙСТВОВАЛ:
   кликнул/двигал мышью в панели либо написал в чат. Полная ставка теперь
   требует свежего взаимодействия; без него — половина, но НЕ ноль.

   Почему не ноль: на мобильном мышью не двигают, и честный мобильный лёркер
   не должен быть наказан. Ровно из-за этого перекоса в июне заводили флаг
   `PRESENCE_WATCHTIME_ENABLED`.

2. `chat_stats.bonus_points` — сколько крустиков реально выдано за сообщение.
   Нужно для дневного потолка бонуса: без него потолок пришлось бы держать
   в памяти процесса, а он теряется при каждом рестарте — и ограничение
   обходилось бы само собой (кулдауны Bannerlord уже живут этой болезнью,
   см. DEFERRED). Заодно даёт данные, чтобы настраивать баланс по факту, а
   не на глаз.

Обе колонки добавляются только если их нет. Существующие строки получают NULL /
0, что означает «взаимодействия не видели» — то есть после выката все временно
на половинной ставке, пока не кликнут или не напишут. Это правильное поведение,
а не потеря: первый же клик возвращает полную.
"""

DEFAULT_BONUS = 0


async def _columns(conn, table: str) -> set:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in await cur.fetchall()}


async def apply(conn):
    name = "M116.engagement_watchtime"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )

    viewer_cols = await _columns(conn, "viewers")
    if viewer_cols and "last_interaction_at" not in viewer_cols:
        await conn.execute(
            "ALTER TABLE viewers ADD COLUMN last_interaction_at TIMESTAMP"
        )

    chat_cols = await _columns(conn, "chat_stats")
    if chat_cols and "bonus_points" not in chat_cols:
        await conn.execute(
            "ALTER TABLE chat_stats ADD COLUMN bonus_points INTEGER NOT NULL "
            f"DEFAULT {DEFAULT_BONUS}"
        )
        # Дневной потолок считает СУММУ за сегодня; без индекса это был бы
        # полный скан таблицы на каждое сообщение в чате.
        #
        # `channel_id` в chat_stats добавляет более ранняя миграция, и на
        # свежей установке её может ещё не быть — тогда индекс просто
        # пропускаем, вместо того чтобы уронить весь старт бэкенда.
        if "channel_id" in chat_cols:
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_stats_bonus_day "
                "ON chat_stats(channel_id, username, created_at)"
            )

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
    print("✅ M116: учёт взаимодействия и бонус-потолок чата")
