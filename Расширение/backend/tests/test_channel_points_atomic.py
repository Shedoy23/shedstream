"""
test_channel_points_atomic.py — REGRESSION-тест на дыру S-06
(внешний аудит 2026-07-27, подтверждена по коду).

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_channel_points_atomic.py

## Что за дыра

`eventsub._on_channel_points` писал строку дедупликации в `channel_points_log`
и КОММИТИЛ её, а крустики начислял отдельным вызовом `add_points()` — то есть
вторым соединением и вторым коммитом.

Если в окне между ними процесс падал (или `add_points` бросал исключение),
получалось худшее из возможного:
  • Channel Points у зрителя Twitch уже списал;
  • строка дедупликации закоммичена;
  • крустики НЕ начислены;
  • повторная доставка вебхука от Twitch видит дедуп и молча выходит.
Начисление терялось НАВСЕГДА, без следа и без возможности повтора.

Это прямое нарушение правила проекта «списание/источник и эффект — в одной
транзакции» (CLAUDE.md), тот же класс, что ловили 7 раз в аудите 2026-07-02.

## Как чинится

Вставка дедуп-строки и начисление идут одним `BEGIN IMMEDIATE` с одним
коммитом: `INSERT OR IGNORE` (дедуп держит UNIQUE-индекс) + `add_points_tx`
на том же соединении. Сбой откатывает ОБА действия → повтор вебхука от Twitch
отработает штатно и зритель получит своё.

## Тест видели красным (правило CLAUDE.md 2b)

До фикса:
    ❌ после сбоя дедуп-строка НЕ осталась: expected 0, got 1
    ❌ повтор вебхука начислил крустики: expected 500, got 0
После фикса — зелёное.
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
REWARD_TITLE = "Тестовая награда"
DIAMONDS = 500
REDEMPTION_ID = "redemption-abc-123"

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


async def _get_points(db, username: str):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, username))
        row = await cur.fetchone()
    return (row[0] if row else 0)


async def _count_log(db, redemption_id: str):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM channel_points_log WHERE twitch_redemption_id=?",
            (redemption_id,))
        row = await cur.fetchone()
    return row[0]


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
            "VALUES (?, 'alice_chan', 'Alice Channel', 'free')",
            (CHANNEL_ID,))
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, 'alice', 0)",
            (CHANNEL_ID,))
        await conn.commit()

    return test_db


def _make_event():
    return {
        "user_login": "alice",
        "id": REDEMPTION_ID,
        "reward": {"title": REWARD_TITLE},
    }


async def test_crash_between_dedup_and_credit(db):
    """Сбой в окне «дедуп записан / крустики ещё нет» не должен съедать награду."""
    print("\n[1] S-06: сбой между дедупом и начислением")

    import eventsub
    from config import CHANNEL_POINTS_CONFIG
    from database import Database

    # Регистрируем награду в конфиге (иначе handler выйдет как на unknown title).
    CHANNEL_POINTS_CONFIG.setdefault("rewards", {})[REWARD_TITLE] = {
        "diamonds": DIAMONDS,
        "channel_points_cost": 1000,
    }

    handler = eventsub._on_channel_points

    # Имитируем падение ровно на начислении — так же выглядит死 процесса или
    # ошибка SQLite в этот момент.
    original_tx = Database.add_points_tx
    original_plain = Database.add_points

    async def _boom(*args, **kwargs):
        raise RuntimeError("имитация сбоя ровно на начислении")

    Database.add_points_tx = _boom
    Database.add_points = _boom
    try:
        try:
            await handler(_make_event(), CHANNEL_ID)
        except RuntimeError:
            pass    # падение ожидаемо — проверяем, что осталось в БД
    finally:
        Database.add_points_tx = original_tx
        Database.add_points = original_plain

    left_over = await _count_log(db, REDEMPTION_ID)
    assert_eq(left_over, 0,
              "после сбоя дедуп-строка НЕ осталась (повтор возможен)")

    # Twitch повторяет вебхук — зритель обязан получить своё.
    await handler(_make_event(), CHANNEL_ID)
    points = await _get_points(db, "alice")
    assert_eq(points, DIAMONDS, "повтор вебхука начислил крустики")


async def test_dedup_still_blocks_double_credit(db):
    """Штатная дедупликация не сломана: тот же redemption_id не платит дважды."""
    print("\n[2] Дедупликация продолжает работать")
    import eventsub
    handler = eventsub._on_channel_points

    before = await _get_points(db, "alice")
    await handler(_make_event(), CHANNEL_ID)      # тот же REDEMPTION_ID
    after = await _get_points(db, "alice")

    assert_eq(after - before, 0, "повторный тот же redemption_id не начислил снова")
    assert_eq(await _count_log(db, REDEMPTION_ID), 1, "в журнале ровно одна строка")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_cp_atomic_")
    os.close(fd)
    os.unlink(db_path)

    db = await _build_db(db_path)
    try:
        await test_crash_between_dedup_and_credit(db)
        await test_dedup_still_blocks_double_credit(db)
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass


def main():
    print("=" * 70)
    print("REGRESSION S-06: Channel Points — дедуп и начисление одной транзакцией")
    print("=" * 70)
    try:
        asyncio.run(_run())
    except Exception:
        print("\n💥 Test harness CRASHED (не assertion — инфраструктура):")
        traceback.print_exc()
        sys.exit(2)

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("\nFAILURES:")
        for f in _failures:
            print(f)
        sys.exit(1)
    print("ALL GREEN ✅ — начисление за Channel Points атомарно.")
    sys.exit(0)


if __name__ == "__main__":
    main()
