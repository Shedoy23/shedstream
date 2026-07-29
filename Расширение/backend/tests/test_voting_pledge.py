"""
test_voting_pledge.py — REGRESSION: обещанный взнос за своё предложение
нельзя не заплатить.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_voting_pledge.py

## Что за дыра

Зритель предлагает свой вариант в голосование и обещает взнос (пледж).
Крустики списываются НЕ в момент предложения, а когда стример его одобрит.

Между этими двумя моментами зритель может потратить крустики на что угодно.
Раньше списание в этот момент было «best-effort»: не хватило — молча не
списали, а вариант ВСЁ РАВНО попадал в бюллетень с пулом 0. То есть цена
предложения обходилась полностью и без всякого взлома: пообещал, потратил,
дождался одобрения.

## Чего требуем

1. Хватает крустиков → вариант добавлен, списано ровно столько, сколько обещано.
2. Не хватает → одобрение НЕ проходит, вариант в бюллетень не попадает.
3. Заявка остаётся в статусе 'pending' — стример может одобрить позже, когда
   зритель накопит. Отказ не должен сжигать заявку.
4. Баланс зрителя при отказе не тронут.

## Красный до фикса

    ❌ [2] без денег одобрение не проходит: expected False, got True
    ❌ [3] вариант не попал в бюллетень: expected 1, got 2
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
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
RICH = "rich_viewer"
BROKE = "broke_viewer"
PLEDGE = 100

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
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 1000)",
            (CHANNEL_ID, RICH))
        # Начинает богатым: заявку с пледжем нельзя подать без денег —
        # баланс проверяется уже при подаче. Дыра открывается ПОЗЖЕ, когда
        # деньги потрачены до одобрения. Ниже мы это и воспроизводим.
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 1000)",
            (CHANNEL_ID, BROKE))
        await conn.commit()
    return test_db


async def _points(db, user: str) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, user))
        row = await cur.fetchone()
        return row[0] if row else -1


async def _option_count(db, event_id: int) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM voting_options WHERE event_id=?", (event_id,))
        return (await cur.fetchone())[0]


async def _proposal_status(db, pid: int) -> str:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT status FROM voting_proposals WHERE id=?", (pid,))
        row = await cur.fetchone()
        return row[0] if row else "?"


async def main_async():
    tmp = tempfile.mkdtemp(prefix="voting_pledge_")
    db = await _build_db(os.path.join(tmp, "test.db"))
    try:
        # «Открытый» раунд — единственный, куда зритель может предлагать
        # своё (allow_proposals=1). Раунд по шаблону предложений не принимает.
        ev = await db.start_open_voting_event(
            channel_id=CHANNEL_ID, options=["Базовый вариант"])
        assert ev.get("started"), ev
        event_id = ev["event_id"]
        base_options = await _option_count(db, event_id)

        print("\n[1] Хватает крустиков — вариант добавлен, списано ровно обещанное")
        p1 = await db.create_voting_proposal(
            channel_id=CHANNEL_ID, username=RICH,
            label="Вариант богатого", pledge=PLEDGE)
        assert p1.get("created"), p1
        pid1 = p1["proposal_id"]
        res1 = await db.approve_voting_proposal(pid1, channel_id=CHANNEL_ID)
        assert_eq(bool(res1.get("approved")), True, "[1] одобрение прошло")
        assert_eq(await _points(db, RICH), 1000 - PLEDGE,
                  "[1b] списано ровно обещанное")
        assert_eq(await _option_count(db, event_id), base_options + 1,
                  "[1c] вариант в бюллетене")

        print("\n[2-4] Крустиков не хватает — одобрение не проходит")
        before_opts = await _option_count(db, event_id)
        before_pts = await _points(db, BROKE)
        p2 = await db.create_voting_proposal(
            channel_id=CHANNEL_ID, username=BROKE,
            label="Вариант без денег", pledge=PLEDGE)
        assert p2.get("created"), p2
        pid2 = p2["proposal_id"]

        # Зритель тратит обещанное на что-то другое, пока стример думает.
        # Оставляем на 1 крустик меньше пледжа — граница, а не «ноль».
        async with db._connect() as conn:
            await conn.execute(
                "UPDATE viewers SET points=? WHERE channel_id=? AND username=?",
                (PLEDGE - 1, CHANNEL_ID, BROKE))
            await conn.commit()
        before_pts = await _points(db, BROKE)

        res2 = await db.approve_voting_proposal(pid2, channel_id=CHANNEL_ID)

        assert_eq(bool(res2.get("approved")), False,
                  "[2] без денег одобрение не проходит")
        assert_eq(res2.get("reason"), "pledge_unpaid",
                  "[2b] причина названа явно")
        assert_eq(await _option_count(db, event_id), before_opts,
                  "[3] вариант не попал в бюллетень")
        assert_eq(await _proposal_status(db, pid2), "pending",
                  "[3b] заявка жива — можно одобрить позже")
        assert_eq(await _points(db, BROKE), before_pts,
                  "[4] баланс не тронут")
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
