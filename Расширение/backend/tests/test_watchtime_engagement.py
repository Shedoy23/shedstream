"""
test_watchtime_engagement.py — полную ставку даёт просмотр, а не открытая вкладка.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_watchtime_engagement.py

ЗАЧЕМ. До 2026-08-23 крустики за просмотр начислялись по одному признаку —
панель прислала heartbeat. Значит полную ставку получал и тот, кто смотрит, и
тот, кто открыл вкладку и ушёл на кухню. Замер на эфире 20.08: пассивно за
9 часов набегало ~13 500💎, а самый разговорчивый в чате (108 сообщений)
получил за них ~900💎 — то есть 7%.

Тест держит две границы, которые легко потерять при следующей правке баланса:

1. **Взаимодействие решает ставку.** Клик/движение в панели или сообщение в
   чат → полная; без них → половина.
2. **Половина, а НЕ ноль.** На мобильном мышью не двигают, и честный лёркер не
   должен быть наказан за устройство. Ровно из-за этого перекоса в июне
   заводили `PRESENCE_WATCHTIME_ENABLED`; если кто-то однажды «оптимизирует»
   ветку до нуля, здесь станет красно.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")
# M1 backfill'ит существующие строки этим channel_id — без переменной миграция
# намеренно падает, чтобы не размазать чужие данные по случайному каналу.
os.environ.setdefault("TWITCH_BROADCASTER_ID", "4242")

_failures: list = []
CH = 4242


def check(cond: bool, label: str):
    if cond:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}")
        _failures.append(label)


async def _points(db, username: str) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CH, username))
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def run() -> int:
    import dependencies
    from bot_core import BotCore
    from config import POINTS_PER_MINUTE
    from database import Database
    from migrations import m1_multitenant, m116_engagement_watchtime

    db_path = tempfile.mktemp(suffix="_engage.db")
    db = Database(db_path=db_path)
    await db.init_pool()
    await db.init_tables()
    async with db._connect() as conn:
        # m1 делает схему многоканальной (channel_id в viewers/chat_stats);
        # без неё тест проверял бы не ту таблицу, что живёт на проде.
        await m1_multitenant.apply(conn)
        await m116_engagement_watchtime.apply(conn)
        await conn.commit()
    dependencies.set_db(db)
    bot = BotCore(db)

    # Трое присутствуют одинаково свежо. Разница только во взаимодействии.
    async with db._connect() as conn:
        for name, interact in (
            ("clicker", "datetime('now', '-60 seconds')"),   # кликал минуту назад
            ("lurker", "NULL"),                              # вкладка открыта, и всё
            ("stale", "datetime('now', '-3600 seconds')"),   # действовал час назад
        ):
            await conn.execute(
                f"INSERT INTO viewers (channel_id, username, points, last_seen, "
                f"last_interaction_at) VALUES (?, ?, 0, datetime('now'), {interact})",
                (CH, name))
        await conn.commit()

    print("\n[1] Начисление за минуту просмотра")
    await bot._reward_points(CH)
    clicker, lurker, stale = (
        await _points(db, "clicker"),
        await _points(db, "lurker"),
        await _points(db, "stale"),
    )
    check(clicker == POINTS_PER_MINUTE,
          f"взаимодействовал — полная ставка ({clicker} из {POINTS_PER_MINUTE})")
    check(lurker == POINTS_PER_MINUTE // 2,
          f"вкладка открыта, действий нет — половина ({lurker})")
    check(stale == POINTS_PER_MINUTE // 2,
          f"действовал давно — тоже половина ({stale})")

    print("\n[2] Половина, а не ноль")
    # Отдельной проверкой, потому что это ПРОДУКТОВОЕ решение, а не деталь:
    # мобильные зрители мышью не двигают.
    check(lurker > 0, "лёркер всё равно что-то получает — мобильных не наказываем")

    print("\n[3] Сообщение в чат приравнено к взаимодействию")
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE viewers SET last_interaction_at = datetime('now') "
            "WHERE channel_id=? AND username=?", (CH, "lurker"))
        await conn.commit()
    before = await _points(db, "lurker")
    await bot._reward_points(CH)
    gained = await _points(db, "lurker") - before
    check(gained == POINTS_PER_MINUTE,
          f"после отметки взаимодействия — полная ставка ({gained})")

    print("\n[4] Модель принимает то, что фронт и так шлёт")
    from models import ActivityRequest
    req = ActivityRequest(username="x", watch_time=30, active_clicks=4, mouse_moves=9)
    check(req.active_clicks == 4 and req.mouse_moves == 9,
          "active_clicks и mouse_moves больше не выбрасываются молча")

    print("\n[5] Болтун обгоняет молчуна")
    from config import (CHAT_BONUS_BASE, CHAT_BONUS_PER_CHARS, CHAT_BONUS_MAX,
                        CHAT_BONUS_DAILY_CAP)
    avg_len = 29          # средняя длина сообщения на эфире 20.08
    per_msg = min(CHAT_BONUS_BASE + avg_len // CHAT_BONUS_PER_CHARS, CHAT_BONUS_MAX)

    # Прямое требование владельца: «болтуны нужны, болтуны мне важны», и «за
    # стрим человек и 500 сообщений выдать может». Значит разговор обязан
    # ОБГОНЯТЬ пассивный просмотр, а не догонять его — иначе экономика говорит
    # зрителю «сиди молча», что противоположно цели продукта.
    heavy_chatter = 500 * per_msg
    full_stream_passive = POINTS_PER_MINUTE * 60 * 10
    check(heavy_chatter > full_stream_passive,
          f"500 сообщений выгоднее полного эфира молчком "
          f"({heavy_chatter}💎 > {full_stream_passive}💎)")

    # Короткая живая реплика тоже обязана что-то стоить: разговор состоит и из
    # «ага». При делителе без базы она давала 3💎, то есть практически ноль.
    short = min(CHAT_BONUS_BASE + 10 // CHAT_BONUS_PER_CHARS, CHAT_BONUS_MAX)
    check(short >= 15, f"короткая реплика (10 симв.) стоит ощутимо ({short}💎)")

    # Потолок существует ТОЛЬКО против флуда и не должен резать собеседника.
    check(CHAT_BONUS_DAILY_CAP > heavy_chatter,
          f"потолок не режет болтуна ({CHAT_BONUS_DAILY_CAP}💎 > {heavy_chatter}💎)")
    flood_hour = 360 * short          # кулдаун 10с, минимальные сообщения
    check(CHAT_BONUS_DAILY_CAP < flood_hour * 5,
          f"но флуд упирается в него за разумное время "
          f"({CHAT_BONUS_DAILY_CAP}💎 против {flood_hour}💎/час)")

    await db._pool.close()
    try:
        os.unlink(db_path)
    except OSError:
        pass

    print("\n" + "=" * 58)
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print("  -", f)
        return 1
    print("Все проверки прошли")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
