"""
test_duel_season_rollover.py — REGRESSION: незакрытый сезон не остаётся навсегда.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_duel_season_rollover.py

## Что за дыра

Ротация сезона дуэлей смотрела ТОЛЬКО на самый свежий незакрытый сезон
(`ORDER BY id DESC LIMIT 1`). Если рядом висел незакрытый старый — он не
попадал в обработку никогда: ни призов, ни закрытия, ни следующего взгляда.

На проде 29.07 так висели три сезона rps (истекли 24.05 и 21.06) и один
tictactoe (21.06). Формально «сезон идёт» — по факту он не кончится.

Отдельная неприятность: выплатить призы за такие сезоны уже нельзя. Ротация
сбрасывает `duel_stats` целиком по (каналу, игре) — строк со старым season_id
в базе не остаётся. Поэтому просроченные, кроме последнего, закрываются без
призов: платить физически не по чему.

## Чего требуем

1. Все просроченные сезоны закрываются, а не только последний.
2. Призы платятся за ПОСЛЕДНИЙ просроченный (его результаты ещё живы).
3. Старые закрываются молча, без выплат.
4. Незакрытым остаётся ровно один сезон — новый.
5. Идущий сезон не закрывается досрочно.

## Красный до фикса

    ❌ [1] все просроченные закрыты: expected 0, got 2
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
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
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CHANNEL_ID = 98319857
GAME = "rps"
WINNER = "champion"

_failures: list = []
_successes: list = []


def assert_eq(actual, expected, label: str):
    if actual == expected:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected {expected!r}, got {actual!r}"
        _failures.append(msg)
        print(msg)


async def _build_db(db_path: str):
    import main
    import dependencies
    from database import Database

    test_db = Database(db_path)
    main.db = test_db
    dependencies.set_db(test_db)
    await test_db.init_pool()
    await test_db.init_tables()
    await main.run_migrations()

    async with test_db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
            "VALUES (?, 'chan', 'Chan', 'free')", (CHANNEL_ID,))
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 0)",
            (CHANNEL_ID, WINNER))
        await conn.execute(
            "DELETE FROM duel_seasons WHERE channel_id=?", (CHANNEL_ID,))
        await conn.commit()
    return test_db


async def _add_season(db, days_ago_start: int, days_ago_end: int) -> int:
    now = datetime.now(timezone.utc)
    async with db._connect() as conn:
        cur = await conn.execute(
            "INSERT INTO duel_seasons (channel_id, game_type, started_at, ends_at, finished) "
            "VALUES (?, ?, ?, ?, 0)",
            (CHANNEL_ID, GAME,
             (now - timedelta(days=days_ago_start)).isoformat(),
             (now - timedelta(days=days_ago_end)).isoformat()))
        sid = cur.lastrowid
        await conn.commit()
    return sid


async def _unfinished(db):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT id FROM duel_seasons WHERE channel_id=? AND game_type=? AND finished=0 "
            "ORDER BY id", (CHANNEL_ID, GAME))
        return [r[0] for r in await cur.fetchall()]


async def _points(db) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, WINNER))
        row = await cur.fetchone()
        return row[0] if row else -1


async def main_async():
    tmp = tempfile.mkdtemp(prefix="duel_season_")
    db = await _build_db(os.path.join(tmp, "test.db"))
    try:
        from routes.duel import check_season_end, PRIZES, PRIZE_ELO_GATE

        print("\n[1-4] Три просроченных сезона: закрыть все, заплатить за последний")
        old1 = await _add_season(db, 70, 63)   # истёк давно
        old2 = await _add_season(db, 50, 43)   # истёк давно
        last = await _add_season(db, 14, 1)    # истёк вчера

        # Результаты живы ТОЛЬКО у последнего — так и бывает после сброса.
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO duel_stats (channel_id, username, game_type, elo, "
                " win_streak, season_id) VALUES (?, ?, ?, ?, 0, ?)",
                (CHANNEL_ID, WINNER, GAME, PRIZE_ELO_GATE + 50, last))
            await conn.commit()

        await check_season_end(CHANNEL_ID, GAME)

        left = await _unfinished(db)
        assert_eq(len([s for s in left if s in (old1, old2, last)]), 0,
                  "[1] все просроченные закрыты")
        assert_eq(len(left), 1, "[4] незакрытым остался ровно один — новый")
        assert_eq(await _points(db), PRIZES[1],
                  "[2] приз выплачен за последний просроченный")

        # M105: выплата обязана оставить след — иначе через месяц вопрос
        # «кому и сколько заплатили» неразрешим (на этом уже обожглись).
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT username, rank, amount, season_id FROM duel_season_payouts "
                "WHERE channel_id=?", (CHANNEL_ID,))
            paid = await cur.fetchall()
        assert_eq(len(paid), 1, "[6] выплата записана в журнал")
        if paid:
            assert_eq(paid[0][0], WINNER, "[6b] в журнале верный получатель")
            assert_eq(paid[0][2], PRIZES[1], "[6c] в журнале верная сумма")
            assert_eq(paid[0][3], last, "[6d] в журнале верный сезон")

        print("\n[5] Идущий сезон не закрывается досрочно")
        running = left[0]
        await check_season_end(CHANNEL_ID, GAME)
        still = await _unfinished(db)
        assert_eq(still, [running], "[5] идущий сезон остался открытым")
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass

    print("\n" + "=" * 62)
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}, пройдено: {len(_successes)}")
        for f in _failures:
            print(f)
        return 1
    print(f"ВСЁ ЗЕЛЁНОЕ: {len(_successes)} проверок")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async()))
    except Exception:
        traceback.print_exc()
        sys.exit(2)
