# -*- coding: utf-8 -*-
"""m120 — «Перетягивание каната»: раунды и участники.

ЗАЧЕМ. Решение владельца 2026-09-01: канат заменяет кубики. Кубики морозим —
в них случайность неустранима (это буквально бросок), и именно они стоят
первыми в претензии Twitch по правилу 3.5. Канат даёт то же место в продукте
(массовое развлечение с низким порогом), но без единого броска.

ЧТО ЗДЕСЬ ВАЖНО ДЛЯ КОМПЛАЕНСА (разбор — `docs/specs/SPEC_TUG_OF_WAR_COMPLIANCE_JIM_2026-08-26.md`):

* **Награда не зависит от исхода.** Поэтому в `tug_participants` есть `credited`
  (выдан ли фиксированный кредит за участие) и НЕТ поля «выигрыш». Победившая
  сторона получает только статус — строку в `tug_rounds.result`.
* **Размер команды заморожен.** `team_a_size` / `team_b_size` пишутся один раз,
  на закрытии приёма. Иначе поздний участник задним числом менял бы ценность
  чужих тапов — непрозрачная переоценка, прямо запрещённая в ревью.
* **Сторона фиксируется.** `side` в участнике пишется при входе и не меняется:
  перебегать в выигрывающую команду нельзя.
* **Ни одного случайного числа.** Ничья остаётся ничьёй — не разыгрывается
  монеткой. Это проверяется тестом грепом по модулю, а не обещанием.

ЦЕЛЫЕ ЧИСЛА. Позиция каната и вклад хранятся целыми (`effective` — вклад после
затухания, `pos` — смещение каната). Плавающая точка тут не нужна и вредна:
формула опубликована зрителю, и она обязана воспроизводиться в уме и на бумаге.
"""


async def apply(conn):
    name = "M120.tug_of_war"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS tug_rounds (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id   INTEGER NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'join',   -- join / pull / finished
            side_a       TEXT    NOT NULL,
            side_b       TEXT    NOT NULL,
            join_until   REAL    NOT NULL,
            pull_until   REAL    NOT NULL,
            team_a_size  INTEGER NOT NULL DEFAULT 0,        -- заморожено на закрытии приёма
            team_b_size  INTEGER NOT NULL DEFAULT 0,
            eff_a        INTEGER NOT NULL DEFAULT 0,        -- суммарный вклад после затухания
            eff_b        INTEGER NOT NULL DEFAULT 0,
            pos          INTEGER NOT NULL DEFAULT 0,        -- позиция каната, ±ROPE_LIMIT
            result       TEXT,                              -- a / b / draw
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at  TIMESTAMP
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tug_rounds_channel "
        "ON tug_rounds(channel_id, status, id)")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS tug_participants (
            channel_id   INTEGER NOT NULL,
            round_id     INTEGER NOT NULL,
            username     TEXT    NOT NULL,
            side         TEXT    NOT NULL,                  -- a / b, не меняется
            taps         INTEGER NOT NULL DEFAULT 0,
            effective    INTEGER NOT NULL DEFAULT 0,
            last_pull_at REAL    NOT NULL DEFAULT 0,
            credited     INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (channel_id, round_id, username)
        )
    """)
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
    print("✅ M120: перетягивание каната (tug_rounds + tug_participants)")
