# -*- coding: utf-8 -*-
"""Пустая база + все миграции = рабочая схема.

Миграций уже сотня, и растут они только в одну сторону. Обновление
существующей базы мы проверяем постоянно — просто запуская прод. А установку
С НУЛЯ не проверяет никто: она нужна ровно тогда, когда что-то случилось и
поднимать надо срочно, то есть в худший возможный момент.

Ломается такое обычно тихо: миграция N рассчитывает на таблицу, которую в
свежей базе создаёт код, а не миграция; или на данные, которых на чистой
установке нет. На живой базе всё работает годами, на новой — падает.

Проверка предложена внешним ревьюером 2026-07-26; на тот момент цепочка была
исправна (106 таблиц, идентично проду). Тест нужен, чтобы поломку заметили в
день появления, а не в день аварии.

Запуск:  python tests/test_fresh_install.py
"""
import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

for _k, _v in (("TWITCH_OAUTH_TOKEN", "x"), ("TWITCH_CLIENT_ID", "x"),
               ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
               ("TWITCH_BROADCASTER_ID", "98319857"),
               ("TWITCH_CHANNEL_NAME", "localtest"),
               ("MODULE_TOKEN_SECRET", "local-secret"),
               ("ADMIN_PASSWORD", "local")):
    os.environ.setdefault(_k, _v)

# main.py создаёт объект базы на ИМПОРТЕ, читая DB_PATH. Значит путь к свежей
# базе надо задать раньше импорта, иначе миграции поедут по чужому файлу.
FRESH_DIR = tempfile.mkdtemp(prefix="fresh_")
FRESH_DB = os.path.join(FRESH_DIR, "viewers.db")
os.environ["DB_PATH"] = FRESH_DB

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print("  OK   %s" % msg)
    else:
        failed += 1
        print("  FAIL %s" % msg)


async def main():
    import aiosqlite
    import database as database_mod
    import main as main_mod

    path = FRESH_DB
    db = database_mod.Database(path)

    # Ровно та последовательность, что выполняет боевой старт: сначала
    # init_tables, затем run_migrations (он сам открывает соединение по пути,
    # который main.py взял из DB_PATH на импорте).
    await db.init_tables()
    failures = []
    try:
        await main_mod.run_migrations()
    except Exception as e:
        failures.append("%s: %s" % (type(e).__name__, e))

    check(not failures,
          "все миграции применились на ПУСТОЙ базе%s"
          % ("" if not failures else " — упало: " + failures[0]))

    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in await cur.fetchall()}
        cur = await conn.execute("SELECT COUNT(*) FROM migrations_applied")
        applied = (await cur.fetchone())[0]

    check(len(tables) > 90,
          "схема развернулась полностью (таблиц: %d)" % len(tables))
    check(applied > 100,
          "отметок о применённых миграциях: %d" % applied)

    # Таблицы, без которых расширение не работает вообще.
    critical = ["viewers", "channels", "bannerlord_heroes", "module_actions",
                "purchase_counters", "feature_usage", "migrations_applied"]
    missing = [t for t in critical if t not in tables]
    check(not missing,
          "ключевые таблицы на месте%s"
          % ("" if not missing else " — НЕТ: " + ", ".join(missing)))

    # Колонки, добавленные поздними миграциями: если свежая база их не получила,
    # значит миграция сработала только на существующей.
    async with aiosqlite.connect(path) as conn:
        async def cols(t):
            cur = await conn.execute("PRAGMA table_info(%s)" % t)
            return {r[1] for r in await cur.fetchall()}
        late = [
            ("channels", "approved", "M99 — ворота для стримеров"),
            ("feature_usage", "active_module", "M100 — контекст метрики"),
            ("viewers", "channel_id", "M1 — мультиарендность"),
        ]
        for table, col, why in late:
            if table in tables:
                check(col in await cols(table),
                      "%s.%s есть на свежей установке (%s)" % (table, col, why))

    if getattr(db, "_pool", None):
        await db._pool.close()

    print("=" * 70)
    print("PASSED: %d   FAILED: %d" % (passed, failed))
    print("ALL GREEN — с нуля поднимается." if not failed
          else "КРАСНО — новую установку сейчас не поднять.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
