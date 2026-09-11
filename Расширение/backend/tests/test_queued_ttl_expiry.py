"""
test_queued_ttl_expiry.py — REGRESSION на T-01 / S-11.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_queued_ttl_expiry.py

## Что за дыра

Зритель покупает действие, когда мод офлайн. Деньги списываются, строка ложится
в очередь — и висит там ВЕЧНО: ни эффекта, ни возврата. TTL-сторож существовал,
но обслуживал только `shedcolony`; Bannerlord был исключён намеренно.

Проверено на проде 27.07: `player.spawn` за 100💎, куплен за полторы минуты до
конца стрима, `status='queued'` сутки спустя, id в логе мода отсутствует.

## Чего требуем

1. Просроченное платное действие получает возврат РОВНО списанного.
2. Строка становится **терминальной**. Это не косметика: курсор опроса мода
   (`ActionPoller._cursor`) сбрасывается в 0 при перезапуске игры, и старую
   `queued`-строку он увидит снова. Без терминального статуса зритель получил бы
   и деньги назад, И эффект.
3. Просроченное БЕСПЛАТНОЕ действие тоже становится терминальным — иначе сторож
   будет натыкаться на него каждый проход бесконечно.
4. Свежее действие сторож НЕ трогает (порог по времени работает).

## Тест видели красным (правило CLAUDE.md 2b)

До фикса (когда `_on_action_failed` статус не менял):
    ❌ [1] строка стала терминальной (мод её больше не увидит): expected True, got False
    ❌ [3] бесплатное просроченное тоже терминально: expected True, got False
"""
from __future__ import annotations

import asyncio
import json
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
PRICE = 100
TTL_SEC = 1800          # тот же порог, что у сторожа в main.py

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


async def _points(db, username="alice"):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, username))
        row = await cur.fetchone()
    return (row[0] if row else 0)


async def _status(db, action_id):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT status FROM module_actions WHERE channel_id=? AND action_id=?",
            (CHANNEL_ID, action_id))
        row = await cur.fetchone()
    return (row[0] if row else None)


async def _add_action(db, action_id, price, age_minutes):
    """Кладём действие в очередь с искусственным возрастом."""
    data = {"initiated_by": "alice", "target": "alice", "price": price}
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status, created_at) "
            "VALUES (?, 'bannerlord', ?, 'player.spawn', ?, 'queued', "
            "        datetime('now', ?))",
            (CHANNEL_ID, action_id, json.dumps(data, ensure_ascii=False),
             f"-{age_minutes} minutes"))
        await conn.commit()


async def _sweep_once(db):
    """Один проход сторожа — НАСТОЯЩИЙ, из main.py.

    До 2026-09-11 здесь лежала копия его SQL, и она разошлась с продом: в копии
    не было RimWorld, который сторож с 11.09 обслуживает. Копия проверяет
    саму себя, а не сторож.
    """
    import main
    from modules._loader import discover_modules
    discover_modules()
    return await main._expire_stale_queued(TTL_SEC)


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
            "VALUES (?, 'alice_chan', 'Alice Channel', 'free')", (CHANNEL_ID,))
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, 'alice', 10000)",
            (CHANNEL_ID,))
        await conn.commit()
    return test_db


async def test_paid_expired_refunded_and_terminal(db):
    print("\n[1] Просроченное ПЛАТНОЕ: возврат + терминальный статус")
    aid = "ttl-paid"
    await _add_action(db, aid, PRICE, age_minutes=45)
    before = await _points(db)

    await _sweep_once(db)

    assert_eq(await _points(db) - before, PRICE, "[1] вернулось ровно списанное")
    st = await _status(db, aid)
    assert_eq(st in ("failed", "acked", "expired"), True,
              f"[1] строка стала терминальной (мод её больше не увидит), статус={st}")
    assert_eq(st == "queued", False, "[1] строка НЕ осталась в очереди")


async def test_fresh_action_untouched(db):
    print("\n[2] Свежее действие сторож не трогает")
    aid = "ttl-fresh"
    await _add_action(db, aid, PRICE, age_minutes=1)
    before = await _points(db)

    await _sweep_once(db)

    assert_eq(await _points(db) - before, 0, "[2] денег не вернул")
    assert_eq(await _status(db, aid), "queued", "[2] осталось в очереди")


async def test_free_expired_also_terminal(db):
    print("\n[3] Просроченное БЕСПЛАТНОЕ тоже становится терминальным")
    aid = "ttl-free"
    await _add_action(db, aid, 0, age_minutes=45)

    await _sweep_once(db)

    st = await _status(db, aid)
    assert_eq(st != "queued", True,
              f"[3] бесплатное просроченное тоже терминально, статус={st}")

    # Второй проход не должен снова его подхватывать — иначе сторож
    # обрабатывает одну и ту же строку вечно.
    swept = await _sweep_once(db)
    assert_eq(swept, 0, "[3] второй проход сторожа уже ничего не находит")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_ttl_")
    os.close(fd)
    os.unlink(db_path)

    db = await _build_db(db_path)
    try:
        await test_paid_expired_refunded_and_terminal(db)
        await test_fresh_action_untouched(db)
        await test_free_expired_also_terminal(db)
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
    print("REGRESSION T-01/S-11: истечение зависших действий (без двойного эффекта)")
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
    print("ALL GREEN ✅ — зависшие возвращаются и повторно не исполняются.")
    sys.exit(0)


if __name__ == "__main__":
    main()
