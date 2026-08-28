# -*- coding: utf-8 -*-
"""m118 — журнал ДВИЖЕНИЯ крустиков: каждое изменение баланса, включая возвраты.

ЗАЧЕМ. 28.08 на эфире платное действие `colonist.give_tools` (2500💎) упало с
`unknown_action`, код выполнил возврат — и доказать, что возврат реально
начислен, оказалось нечем. `points_income` (M117) пишет только ПРИХОД по
источникам, `channel_points_log` — обмен баллов Twitch на крустики. Списаний и
возвратов не было ни в одной таблице: подтверждение существовало только строкой
в логе, а лог ротируется. Арифметикой по балансу тоже не проверить — во время
эфира параллельно капает watchtime.

Для системы, где спорное списание — самый дорогой класс дефектов, это значит,
что любой спор «у меня списалось, а эффекта нет» неразрешим.

ПОЧЕМУ ТРИГГЕР, А НЕ ЗАПИСЬ В add_points/remove_points. Через эти функции
проходит 17 мест, а прямых `UPDATE viewers SET points = ...` мимо них — 22, в
шести файлах (аукционы Bannerlord, магазин ShedColony, рефанды в адаптерах).
Журнал на уровне функций пропустил бы большую часть денег и при этом ВЫГЛЯДЕЛ
бы полным — худший вид учёта. Триггер ловит любое изменение колонки, каким бы
кодом оно ни сделано, и попадает в ТУ ЖЕ транзакцию: строка журнала не может
разойтись с движением денег даже при падении посреди операции.

ЧТО ПИШЕМ. delta и баланс ДО/ПОСЛЕ. Пара «до/после» превращает журнал в
самопроверяемый: если у соседних строк одного зрителя `balance_after`
предыдущей не равен `balance_before` следующей — значит кто-то поменял баланс
в обход триггера (или таблицу правили руками). Это единственный способ узнать
о дыре в учёте, не доверяя учёту.

ЧЕГО ЗДЕСЬ НЕТ. Причины («за что»). Триггер её знать не может, а тащить её
через 39 мест — отдельная работа. Сегодня причина восстанавливается сопоставлением
по времени с `module_actions` (там тип действия, цена и статус). Записано в
`DEFERRED.md`.

РОСТ. Строка на каждое движение; при одном канале это сотни строк в час эфира.
Чистка не заводится намеренно: журнал денег, который сам себя подтирает, не
журнал. Понадобится — резать по дате отдельной задачей.
"""


async def apply(conn):
    name = "M118.points_ledger"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS points_ledger (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id     INTEGER NOT NULL,
            username       TEXT    NOT NULL,
            delta          INTEGER NOT NULL,   -- + приход, - списание
            balance_before INTEGER NOT NULL,
            balance_after  INTEGER NOT NULL,
            created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_points_ledger_who "
        "ON points_ledger(channel_id, username, id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_points_ledger_when "
        "ON points_ledger(created_at)"
    )

    # UPDATE OF points — чтобы триггер не срабатывал на каждое обновление
    # last_seen (а оно идёт раз в минуту на каждого зрителя).
    await conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_points_ledger_update
        AFTER UPDATE OF points ON viewers
        FOR EACH ROW WHEN NEW.points <> OLD.points
        BEGIN
            INSERT INTO points_ledger
                (channel_id, username, delta, balance_before, balance_after)
            VALUES (NEW.channel_id, NEW.username,
                    NEW.points - OLD.points, OLD.points, NEW.points);
        END
    """)
    # Новый зритель может появиться сразу с ненулевым балансом (add_points
    # делает INSERT ... ON CONFLICT DO UPDATE, и на первом разе это INSERT).
    await conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_points_ledger_insert
        AFTER INSERT ON viewers
        FOR EACH ROW WHEN NEW.points <> 0
        BEGIN
            INSERT INTO points_ledger
                (channel_id, username, delta, balance_before, balance_after)
            VALUES (NEW.channel_id, NEW.username, NEW.points, 0, NEW.points);
        END
    """)
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
    print("✅ M118: журнал движения крустиков (списания и возвраты тоже)")
