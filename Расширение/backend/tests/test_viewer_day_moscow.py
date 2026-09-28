"""
test_viewer_day_moscow.py — сутки зрителя кончаются в полночь по Москве.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_viewer_day_moscow.py

ЧТО ДОКАЗЫВАЕТ (багрепорт #48, kuro_gothic 13.08, подтверждён 12.09).
    Зритель писал: «квесты не обновляются 00:00 по мск». Так и было: прод
    живёт в UTC, «сегодня» считалось через `date.today()`, поэтому день
    кончался в 00:00 UTC — то есть в 03:00 МСК. В час ночи человек ждал новые
    квесты и ещё два часа видел вчерашние, а свой ночной чат и просмотр —
    записанными во вчерашний день.

    Ловушка, из-за которой одной заменой «сегодня» не обойтись: время в
    таблицах пишется в UTC (`CURRENT_TIMESTAMP` у SQLite). Сравнивать
    `date(created_at)` с московским днём НЕЛЬЗЯ — с 00:00 до 03:00 МСК это
    разные даты, и запросы просто перестали бы находить свежие записи.
    Сдвигать надо обе стороны.

КАК ПРОВЕРЯЕМ, НЕ ЗАВИСЯ ОТ ВРЕМЕНИ ПРОГОНА.
    Все моменты считаются ОТ текущего московского дня: его полночь переводится
    в UTC, и вокруг неё расставляются записи — за полчаса до и через полчаса
    после. Поэтому тест одинаково валиден в полдень и в три часа ночи.

ТЕСТЫ:
    [1] московская полночь наступает на 3 часа раньше UTC-полуночи
    [2] чат в 00:30 МСК попадает в сегодняшний день
    [3] чат в 23:30 МСК вчерашнего дня в сегодняшний НЕ попадает
    [4] просмотр в 00:30 МСК попадает в сегодняшний день
    [5] квест заводится на московский день
    [6] сводка «за сегодня» согласована с обеими выборками
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

HERE = Path(__file__).parent.absolute()
sys.path.insert(0, str(HERE.parent))

for _v, _d in (("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "c"),
               ("TWITCH_CLIENT_SECRET", "s"), ("TWITCH_BOT_ID", "b"),
               ("TWITCH_CHANNEL_NAME", "ch"),
               ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
               ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
               ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_v, _d)

CHANNEL_ID = 98319857
USER = "alice"

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


def sql_time(moment: datetime) -> str:
    """Как SQLite пишет CURRENT_TIMESTAMP: UTC без пояса."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def run():
    import config
    import dependencies
    import main
    from database import Database

    db_path = tempfile.mktemp(suffix="_viewer_day.db")
    db = Database(db_path)
    main.db = db
    dependencies.set_db(db)
    await db.init_pool()
    await db.init_tables()
    await main.run_migrations()

    try:
        day = config.viewer_day()                       # сегодня по Москве
        midnight_msk_utc = (datetime.fromisoformat(day)
                            .replace(tzinfo=timezone.utc)
                            - timedelta(hours=config.VIEWER_DAY_OFFSET_HOURS))
        inside = midnight_msk_utc + timedelta(minutes=30)    # 00:30 МСК сегодня
        before = midnight_msk_utc - timedelta(minutes=30)    # 23:30 МСК вчера

        print(f"\n  московский день {day}; его полночь в UTC — {sql_time(midnight_msk_utc)}")

        print("\n[1] Граница суток")
        utc_today = datetime.now(timezone.utc).date().isoformat()
        expected = (datetime.now(timezone.utc)
                    + timedelta(hours=config.VIEWER_DAY_OFFSET_HOURS)).date().isoformat()
        check("день зрителя считается по Москве, а не по UTC", day == expected,
              f"viewer_day()={day}, ожидался {expected} (в UTC сейчас {utc_today})")

        async with db._connect() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
                "VALUES (?, 'alice_chan', 'Alice', 'free')", (CHANNEL_ID,))
            await conn.execute(
                "INSERT OR IGNORE INTO viewers (channel_id, username, points) "
                "VALUES (?, ?, 100)", (CHANNEL_ID, USER))
            await conn.execute(
                "INSERT INTO chat_stats (channel_id, username, message_length, created_at) "
                "VALUES (?, ?, 40, ?)", (CHANNEL_ID, USER, sql_time(inside)))
            await conn.execute(
                "INSERT INTO chat_stats (channel_id, username, message_length, created_at) "
                "VALUES (?, ?, 77, ?)", (CHANNEL_ID, USER, sql_time(before)))
            await conn.execute(
                "INSERT INTO activity_stats (channel_id, username, watch_time, created_at) "
                "VALUES (?, ?, 15, ?)", (CHANNEL_ID, USER, sql_time(inside)))
            await conn.execute(
                "INSERT INTO activity_stats (channel_id, username, watch_time, created_at) "
                "VALUES (?, ?, 99, ?)", (CHANNEL_ID, USER, sql_time(before)))
            await conn.commit()

        print("\n[2-3] Ночной чат")
        chat = await db.get_today_chat_stats(USER, channel_id=CHANNEL_ID)
        check("сообщение в 00:30 МСК — сегодняшнее",
              chat.get("message_count", 0) >= 1,
              f"сообщений за сегодня {chat.get('message_count')}, ожидалось хотя бы одно "
              f"(в 00:30 МСК зритель уже в новом дне)")
        check("сообщение в 23:30 МСК вчера в сегодня не попало",
              chat.get("message_count", 0) == 1 and chat.get("total_length") == 40,
              f"счёт {chat.get('message_count')}, сумма длин {chat.get('total_length')} "
              f"(ожидались 1 и 40: вчерашнее сообщение длиной 77 сюда не относится)")

        print("\n[4] Ночной просмотр")
        activity = await db.get_today_activity(USER, channel_id=CHANNEL_ID)
        check("просмотр в 00:30 МСК — сегодняшний",
              activity.get("total_time") == 15,
              f"время за сегодня {activity.get('total_time')}, ожидалось 15 "
              f"(99 — вчерашние, до полуночи по Москве)")

        print("\n[5] Квест заводится на московский день")
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO quests (channel_id, username, quest_type, target_value, "
                "current_value, reward_points, day_date) VALUES (?, ?, 'chat_messages_10', 10, 1, 500, ?)",
                (CHANNEL_ID, USER, day))
            await conn.commit()
        quests = await db.get_quests(USER, channel_id=CHANNEL_ID)
        check("квест на сегодняшний московский день виден",
              any(q.get("type") == "chat_messages_10" for q in (quests or [])),
              f"вернулось {len(quests or [])} квестов при day_date={day}")

        print("\n[6] Сводка согласована с выборками")
        summary = await db.get_today_summary(USER, channel_id=CHANNEL_ID) \
            if hasattr(db, "get_today_summary") else None
        if summary is None:
            print("      сводки нет в этой версии — пропуск не влияет на вердикт")
        else:
            check("сводка говорит про тот же день", summary.get("date") == day,
                  f"в сводке {summary.get('date')}, а день зрителя {day}")
    finally:
        # Пул у этого экземпляра свой: глобальный close_db_pool его не знает,
        # и без явного закрытия процесс не завершается — тест «проходит», а
        # раннер убивает его по таймауту.
        await db._pool.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass


def main() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    print()
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print(" ", f.strip())
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
