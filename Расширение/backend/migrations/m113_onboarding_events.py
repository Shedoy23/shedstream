# -*- coding: utf-8 -*-
"""M113 — воронка онбординга: приём событий установки и первой активации.

ЗАЧЕМ. ROADMAP §R4 требует двадцать типов событий, чтобы наблюдать за первыми
стримерами: где человек застрял, сколько занял путь, чем кончилось. Ни одного
из них сегодня не пишется — есть только `feature_usage`, счётчик фич ВНУТРИ
расширения, то есть уже после успешной установки. Всё, что до неё, невидимо.

Прибор должен существовать до опыта, иначе альфа начнётся со сбора прибора в
тот момент, когда надо смотреть на живых людей.

ЧТО ЗДЕСЬ НЕ ХРАНИТСЯ. Ни логинов, ни путей на диске, ни токенов. Установка
опознаётся анонимным `installation_id`, который Manager генерит у себя и который
ни с чем не связан, пока человек не вошёл через Twitch; после входа появляется
`channel_id`. Это позволяет считать воронку и не собирать личное.
"""


async def apply(conn) -> None:
    name = "M113.onboarding_events"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onboarding_events (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            event               TEXT NOT NULL,
            installation_id     TEXT,
            channel_id          INTEGER,
            integration_id      TEXT,
            integration_version TEXT,
            manager_version     TEXT,
            elapsed_ms          INTEGER,
            result              TEXT,
            source_step         TEXT,
            client_event_id     TEXT,
            created_at          REAL NOT NULL
        )
    """)
    # Воронка считается по установке во времени: «где остановился каждый».
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_onboarding_install "
        "ON onboarding_events(installation_id, created_at)"
    )
    # Разрезы по каналу и по игре — для «сколько дошло до готовности в Bannerlord».
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_onboarding_channel "
        "ON onboarding_events(channel_id, event, created_at)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_onboarding_event "
        "ON onboarding_events(event, created_at)"
    )
    # Идемпотентность по ключу, который придумывает Manager, а НЕ по паре
    # «установка + шаг». Разница важна: повтор из-за сетевого сбоя должен
    # схлопнуться, а вторая честная попытка установки после неудачи — остаться
    # отдельным событием, иначе воронка спрячет именно то, ради чего её завели.
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_onboarding_dedup "
        "ON onboarding_events(installation_id, client_event_id) "
        "WHERE installation_id IS NOT NULL AND client_event_id IS NOT NULL"
    )
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
    print("✅ M113: onboarding funnel events table created")
