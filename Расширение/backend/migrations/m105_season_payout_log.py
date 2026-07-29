# -*- coding: utf-8 -*-
"""M105 — журнал выплат за сезон мини-игр.

ЗАЧЕМ. Сезон дуэлей/костей/крестиков заканчивается, топ-3 получают
300K/200K/100K💎 — и в базе не остаётся НИ ОДНОЙ СТРОКИ об этом. Ни кто
получил, ни сколько, ни за какой сезон. Таблица результатов `duel_stats`
обнуляется той же ротацией, что и платит.

Следствие увидели 2026-07-29 на себе: я запросил `duel_stats`, увидел у всех
стартовые 1000 и уверенно написал в аудит, что порог приза никто никогда не
брал и призы не платились ни разу. Владелец возразил: людей, перешагнувших
порог, он помнит как минимум двоих. Проверить было НЕЧЕМ — следов нет, и
ошибочное утверждение опровергалось только памятью человека.

Деньги, уходящие зрителям, обязаны оставлять запись. Иначе любой вопрос
«платили ли, кому, сколько» через месяц неразрешим, а аудит превращается в
догадки по косвенным признакам.

Таблица заполняется в `routes/duel.py: check_season_end` той же транзакцией,
что и само начисление, — иначе запись и деньги смогут разойтись.

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
    name = "M105.season_payout_log"
    if await _is_applied(conn, name):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS duel_season_payouts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            season_id  INTEGER NOT NULL,
            game_type  TEXT    NOT NULL,
            username   TEXT    NOT NULL,
            rank       INTEGER NOT NULL,
            elo        INTEGER NOT NULL,
            amount     INTEGER NOT NULL,
            paid_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_season_payouts "
        "ON duel_season_payouts(channel_id, season_id)")

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M105: выплаты за сезон мини-игр теперь оставляют след")
