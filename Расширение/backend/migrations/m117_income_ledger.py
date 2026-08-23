# -*- coding: utf-8 -*-
"""m117 — учёт того, ОТКУДА зритель берёт крустики.

ЗАЧЕМ. 2026-08-23 мы дважды подбирали числа баланса на глаз, и оба раза
владелец поправлял: сначала потолок бонуса за чат оказался втрое ниже реального
разговора, потом выяснилось, что квесты платят за сидение вчетверо больше, чем
за общение. Спорить о числах бессмысленно, пока их никто не считает.

ЧТО СЧИТАЕМ. Одна строка на (канал, зритель, день, источник) с накоплением:

    watch_full  — минута просмотра при свежем взаимодействии
    watch_half  — то же, но зритель ничего не делал (вкладка открыта)
    chat        — бонус за сообщение
    quest       — награда за выполненный квест

Этого достаточно, чтобы на пост-стрим-триаже увидеть: сколько дал разговор,
сколько сидение, кто из зрителей на что живёт — и подобрать числа по факту.

Почему отдельная таблица, а не сумма по существующим. Начисления живут в
разных местах и в разных формах: часть в `viewers.points` (только итог),
часть в `chat_stats.bonus_points`, квесты нигде. Восстановить источник задним
числом невозможно — а именно источник и нужен для решения.
"""


async def apply(conn):
    name = "M117.income_ledger"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS points_income (
            channel_id  INTEGER NOT NULL,
            username    TEXT    NOT NULL,
            day         TEXT    NOT NULL,   -- YYYY-MM-DD по времени сервера (UTC)
            source      TEXT    NOT NULL,   -- watch_full | watch_half | chat | quest
            points      INTEGER NOT NULL DEFAULT 0,
            events      INTEGER NOT NULL DEFAULT 0,   -- сколько раз начисляли
            PRIMARY KEY (channel_id, username, day, source)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_points_income_day "
        "ON points_income(channel_id, day)"
    )
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
    print("✅ M117: учёт источников дохода зрителя")
