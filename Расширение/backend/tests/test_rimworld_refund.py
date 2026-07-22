"""
test_rimworld_refund.py — рефанд очков за провалившиеся RimWorld-команды.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_rimworld_refund.py

Фикс 2026-07-19: раньше ack-command был print()-заглушкой — success=false от
мода ничего не делал, зритель молча терял очки. Теперь очередь
rimworld_pending_commands хранит строки до ack (status queued→delivered),
цена/канал едут в cmd_json, на fail/stale — идемпотентный возврат.

Сценарии:
  1. fail-ack → возврат цены, строка удалена
  2. повторный fail-ack → БЕЗ двойного возврата (идемпотентность)
  3. success-ack → возврата нет, строка удалена
  4. stale delivered (мод умер после выдачи) → авто-рефанд при следующем поллинге
  5. legacy-команда без price → no-op без падения
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
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
START_POINTS = 10_000

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


def _make_json_request(payload: dict):
    """Starlette Request с JSON-телом (для прямого вызова ack_command)."""
    from starlette.requests import Request
    body = json.dumps(payload).encode()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/rimworld/ack-command",
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
    }
    received = {"done": False}

    async def receive():
        if received["done"]:
            return {"type": "http.disconnect"}
        received["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


async def _get_points(db, username: str):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, username))
        row = await cur.fetchone()
    return (row[0] if row else None)


async def _row_count(db, cmd_id: str):
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM rimworld_pending_commands WHERE cmd_id=?",
            (cmd_id,))
        return (await cur.fetchone())[0]


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
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, 'alice', ?)",
            (CHANNEL_ID, START_POINTS))
        await conn.commit()
    return test_db


async def _run():
    db_path = tempfile.mktemp(suffix="_rw_refund_test.db")
    db = await _build_db(db_path)

    import rimworld as rw

    async def serve_to_mod():
        """Симуляция GET /commands (внутренности, без auth)."""
        async with rw.get_commands_lock():
            return await rw._get_commands_inner()

    async def enqueue(cmd):
        async with rw.get_commands_lock():
            rw.get_pending().append(cmd)
        await rw._db_enqueue_command(cmd)

    try:
        # ── [1] fail-ack → возврат ──
        print("\n[1] mod refuse (success=false) → цена возвращается, строка удалена")
        cmd = {"type": "heal_pawn", "id": "t1", "username": "alice",
               "price": 500, "channel_id": CHANNEL_ID}
        await enqueue(cmd)
        served = await serve_to_mod()
        assert_eq(len([c for c in served if c["id"] == "t1"]), 1, "команда выдана моду")
        before = await _get_points(db, "alice")
        await rw.ack_command(_make_json_request(
            {"command_id": "t1", "success": False, "message": "no_effect"}))
        after = await _get_points(db, "alice")
        assert_eq(after - before, 500, "возврат ровно 500")
        assert_eq(await _row_count(db, "t1"), 0, "строка очереди удалена")

        # ── [2] повторный fail-ack → идемпотентно ──
        print("\n[2] повторный fail-ack того же cmd_id → двойного возврата НЕТ")
        await rw.ack_command(_make_json_request(
            {"command_id": "t1", "success": False, "message": "no_effect"}))
        after2 = await _get_points(db, "alice")
        assert_eq(after2, after, "баланс не изменился на повторе")

        # ── [3] success-ack → без возврата ──
        print("\n[3] success=true → возврата нет, строка удалена")
        cmd = {"type": "heal_pawn", "id": "t3", "username": "alice",
               "price": 500, "channel_id": CHANNEL_ID}
        await enqueue(cmd)
        await serve_to_mod()
        before = await _get_points(db, "alice")
        await rw.ack_command(_make_json_request({"command_id": "t3", "success": True}))
        assert_eq(await _get_points(db, "alice"), before, "баланс не тронут на успехе")
        assert_eq(await _row_count(db, "t3"), 0, "строка удалена на успехе")

        # ── [4] stale delivered → авто-рефанд ──
        print("\n[4] delivered без ack дольше таймаута → авто-рефанд при поллинге")
        cmd = {"type": "event_raid", "id": "t4", "username": "alice",
               "price": 2000, "channel_id": CHANNEL_ID}
        await enqueue(cmd)
        await serve_to_mod()  # → delivered, ack не приходит
        # Состариваем delivered_at за порог.
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(
                "UPDATE rimworld_pending_commands SET delivered_at=? WHERE cmd_id='t4'",
                (time.time() - rw._DELIVERED_STALE_SEC - 5,))
            await conn.commit()
        before = await _get_points(db, "alice")
        await serve_to_mod()  # следующий поллинг триггерит sweep
        after = await _get_points(db, "alice")
        assert_eq(after - before, 2000, "stale-команда отрефанжена на 2000")
        assert_eq(await _row_count(db, "t4"), 0, "stale-строка удалена")

        # ── [5] legacy-команда без price → no-op ──
        print("\n[5] legacy cmd без price/channel_id → fail-ack не падает и не платит")
        cmd = {"type": "heal_pawn", "id": "t5", "username": "alice"}
        await enqueue(cmd)
        await serve_to_mod()
        before = await _get_points(db, "alice")
        await rw.ack_command(_make_json_request({"command_id": "t5", "success": False}))
        assert_eq(await _get_points(db, "alice"), before, "без price возврата нет (0)")
        assert_eq(await _row_count(db, "t5"), 0, "legacy-строка удалена")

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
    print("REFUND: rimworld_pending_commands — возврат очков за провал/потерю")
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
    print("ALL GREEN ✅")
    sys.exit(0)


if __name__ == "__main__":
    main()
