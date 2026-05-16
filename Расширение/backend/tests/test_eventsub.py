"""
test_eventsub.py — security smoke-test для EventSub flow (Phase A).

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_eventsub.py

Покрывает:
1. HMAC signature verify — valid / tampered body / wrong secret / missing fields
2. Replay window — fresh / >10min old / malformed timestamp
3. Dedupe table — first INSERT_OR_IGNORE → новое, повтор → дубль, разные msg_id → оба новые
4. End-to-end dispatch — valid request → handler called, signature mismatch → 403,
   duplicate msg_id → 200 без второго handler call, unregistered channel → 200 ignored,
   unknown event type → 200 ignored, handler exception → не 5xx
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json
import os
import sys
import tempfile
import time as _time
from datetime import datetime, timezone
from pathlib import Path

# Windows console (cp1251) не умеет emoji — переключаем stdout/stderr на UTF-8
# до первого print. На Linux/macOS no-op.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

# Required env vars для config.py
os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
# ADMIN_PASSWORD должен быть задан — иначе dependencies.py при импорте
# печатает warning с emoji, что ломает Windows cp1251 console.
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")

# ─── Test infrastructure ─────────────────────────────────────────────────────

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


def assert_true(cond: bool, label: str):
    if cond:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected truthy"
        _failures.append(msg)
        print(msg)


def assert_false(cond: bool, label: str):
    assert_true(not cond, label)


# ─── Stub Request (duck-types starlette.requests.Request) ────────────────────


class StubRequest:
    """Минимальный stub для _process_eventsub_request — только body() и headers."""

    def __init__(self, body: bytes, headers: dict):
        self._body = body
        self.headers = headers

    async def body(self) -> bytes:
        return self._body


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_signature(secret: bytes, msg_id: str, msg_ts: str, body: bytes) -> str:
    return "sha256=" + _hmac.new(
        secret, (msg_id + msg_ts).encode() + body, hashlib.sha256
    ).hexdigest()


def _make_eventsub_payload(
    event_type: str, broadcaster_id: int, event_extras: dict | None = None
) -> bytes:
    event = {"broadcaster_user_id": str(broadcaster_id)}
    if event_extras:
        event.update(event_extras)
    return json.dumps({
        "subscription": {"type": event_type, "version": "1"},
        "event": event,
    }).encode()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: HMAC signature verify
# ─────────────────────────────────────────────────────────────────────────────


def test_signature_verify():
    print("\n[1] HMAC signature verify")
    from eventsub import _verify_signature

    secret = b"super-secret-32-bytes-abcdefghij"
    msg_id = "msg-uuid-abc"
    msg_ts = _now_iso()
    body = b'{"event":{}}'
    sig = _make_signature(secret, msg_id, msg_ts, body)

    # Valid
    assert_true(
        _verify_signature(body, msg_id, msg_ts, sig, secret),
        "valid signature accepted",
    )
    # Tampered body — signature рассчитывалась над оригиналом
    assert_false(
        _verify_signature(b'{"event":{"evil":true}}', msg_id, msg_ts, sig, secret),
        "tampered body rejected",
    )
    # Wrong secret
    assert_false(
        _verify_signature(body, msg_id, msg_ts, sig, b"wrong-secret"),
        "wrong secret rejected",
    )
    # Tampered signature
    bad_sig = sig[:-2] + "00"
    assert_false(
        _verify_signature(body, msg_id, msg_ts, bad_sig, secret),
        "tampered signature rejected",
    )
    # Empty fields
    assert_false(_verify_signature(body, "", msg_ts, sig, secret), "empty msg_id rejected")
    assert_false(_verify_signature(body, msg_id, "", sig, secret), "empty timestamp rejected")
    assert_false(_verify_signature(body, msg_id, msg_ts, "", secret), "empty signature rejected")
    assert_false(_verify_signature(body, msg_id, msg_ts, sig, b""), "empty secret rejected")


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Replay window
# ─────────────────────────────────────────────────────────────────────────────


def test_replay_window():
    print("\n[2] Replay window")
    from eventsub import _check_replay_window

    # Fresh
    assert_eq(_check_replay_window(_now_iso()), None, "fresh timestamp accepted")

    # Too old (12 min)
    old = datetime.now(timezone.utc).timestamp() - 720
    old_iso = datetime.fromtimestamp(old, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    err = _check_replay_window(old_iso)
    assert_true(err is not None and "out of window" in err, "12-min-old timestamp rejected")

    # Future (clock skew > 10 мин) тоже отсекаем (abs())
    fut = datetime.now(timezone.utc).timestamp() + 720
    fut_iso = datetime.fromtimestamp(fut, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    err2 = _check_replay_window(fut_iso)
    assert_true(err2 is not None and "out of window" in err2, "12-min-future timestamp rejected")

    # Malformed
    err3 = _check_replay_window("not-a-timestamp")
    assert_true(err3 is not None and "bad timestamp" in err3, "malformed timestamp rejected")

    # Empty
    err4 = _check_replay_window("")
    assert_true(err4 is not None, "empty timestamp rejected")


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Dedupe table behavior (без полного Database, raw aiosqlite)
# ─────────────────────────────────────────────────────────────────────────────


async def test_dedupe_table():
    print("\n[3] eventsub_seen dedupe table")
    import aiosqlite

    db_path = tempfile.mktemp(suffix="_test_eventsub.db")
    try:
        async with aiosqlite.connect(db_path) as conn:
            from migrations import m17_eventsub_dedupe
            await m17_eventsub_dedupe.apply(conn)

            async def try_insert(msg_id: str, ch: int, etype: str) -> int:
                cursor = await conn.execute(
                    "INSERT OR IGNORE INTO eventsub_seen "
                    "(message_id, channel_id, event_type, seen_at) "
                    "VALUES (?, ?, ?, ?)",
                    (msg_id, ch, etype, _time.time()),
                )
                await conn.commit()
                return cursor.rowcount

            # First insert → 1 row affected (новая)
            assert_eq(await try_insert("msg-1", 100, "stream.online"), 1,
                      "first message_id INSERT → 1 row")
            # Same message_id → 0 (duplicate)
            assert_eq(await try_insert("msg-1", 100, "stream.online"), 0,
                      "duplicate message_id INSERT_OR_IGNORE → 0 rows")
            # Different message_id same channel/type → 1 (новая)
            assert_eq(await try_insert("msg-2", 100, "stream.online"), 1,
                      "different message_id → 1 row")
            # Same message_id even different channel → 0 (PK is message_id alone)
            assert_eq(await try_insert("msg-1", 999, "stream.offline"), 0,
                      "global PK: same msg_id any channel → duplicate")

            # TTL delete (cutoff = future, всё попадает в expired)
            cur = await conn.execute(
                "DELETE FROM eventsub_seen WHERE seen_at < ?", (_time.time() + 1,)
            )
            await conn.commit()
            assert_true(cur.rowcount >= 2, "TTL cleanup removes expired rows")
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: End-to-end dispatch flow
# ─────────────────────────────────────────────────────────────────────────────


async def test_dispatch_flow():
    print("\n[4] End-to-end dispatch (signature → channel-gate → dedupe → handler)")
    import aiosqlite

    import dependencies
    import eventsub as es

    db_path = tempfile.mktemp(suffix="_test_dispatch.db")
    try:
        # Setup: реальный Database через aiosqlite-pool. Минимальные таблицы.
        # Используем настоящий Database класс — get_db() в eventsub вызывает
        # db._connect() через DBPool.
        from database import Database
        db = Database(db_path=db_path)
        await db.init_pool()
        try:
            async with db._connect() as conn:
                from migrations import m17_eventsub_dedupe
                await m17_eventsub_dedupe.apply(conn)
            dependencies.set_db(db)

            # Регистрируем один канал в cache (другой НЕ регистрируем для теста gate)
            dependencies._registered_channels_cache.clear()
            dependencies._channels_cache_initialized = True
            REGISTERED_CH = 12345
            UNREGISTERED_CH = 99999
            dependencies._registered_channels_cache.add(REGISTERED_CH)

            # Подмена handler'ов на mock со счётчиком
            calls = []

            async def mock_handler(event, channel_id):
                calls.append((event, channel_id))

            saved_handlers = dict(es._handlers)
            es._handlers["test.event"] = mock_handler
            es._handlers["test.crash"] = _make_crashing_handler()

            secret = b"phase-a-test-secret-32-bytes-abc"

            # Подмена eventsub_secret в config
            from config import CHANNEL_POINTS_CONFIG
            saved_secret = CHANNEL_POINTS_CONFIG.get("eventsub_secret", "")
            CHANNEL_POINTS_CONFIG["eventsub_secret"] = secret.decode()

            async def post_event(
                msg_id: str, event_type: str, broadcaster_id: int,
                *, bad_signature: bool = False, old_timestamp: bool = False,
            ):
                msg_ts = _now_iso() if not old_timestamp else (
                    datetime.fromtimestamp(
                        _time.time() - 800, tz=timezone.utc
                    ).isoformat().replace("+00:00", "Z")
                )
                body = _make_eventsub_payload(event_type, broadcaster_id)
                sig = _make_signature(secret, msg_id, msg_ts, body)
                if bad_signature:
                    sig = sig[:-2] + "00"
                req = StubRequest(body, {
                    "Twitch-Eventsub-Message-Id": msg_id,
                    "Twitch-Eventsub-Message-Timestamp": msg_ts,
                    "Twitch-Eventsub-Message-Signature": sig,
                    "Twitch-Eventsub-Message-Type": "notification",
                })
                return await es._process_eventsub_request(req)

            # 4.1 Valid request → handler called once, response 200
            resp = await post_event("msg-100", "test.event", REGISTERED_CH)
            assert_eq(resp.status_code, 200, "valid event → 200")
            assert_eq(len(calls), 1, "valid event → handler called 1×")
            assert_eq(calls[0][1], REGISTERED_CH, "handler got correct channel_id")

            # 4.2 Same msg_id again → dedupe, handler НЕ вызван второй раз
            resp = await post_event("msg-100", "test.event", REGISTERED_CH)
            assert_eq(resp.status_code, 200, "duplicate msg_id → 200")
            assert_eq(len(calls), 1, "duplicate msg_id → handler NOT re-called")

            # 4.3 Tampered signature → 403, handler НЕ вызван
            resp = await post_event(
                "msg-101", "test.event", REGISTERED_CH, bad_signature=True
            )
            assert_eq(resp.status_code, 403, "bad signature → 403")
            assert_eq(len(calls), 1, "bad signature → handler not called")

            # 4.4 Old timestamp → 403, handler НЕ вызван
            resp = await post_event(
                "msg-102", "test.event", REGISTERED_CH, old_timestamp=True
            )
            assert_eq(resp.status_code, 403, "old timestamp → 403")
            assert_eq(len(calls), 1, "old timestamp → handler not called")

            # 4.5 Unregistered channel → 200 ignored, handler НЕ вызван
            resp = await post_event("msg-103", "test.event", UNREGISTERED_CH)
            assert_eq(resp.status_code, 200, "unregistered channel → 200 (not 4xx)")
            assert_eq(len(calls), 1, "unregistered channel → handler not called")

            # 4.6 Unknown event type → 200 ignored
            resp = await post_event("msg-104", "completely.unknown.type", REGISTERED_CH)
            assert_eq(resp.status_code, 200, "unknown event type → 200")
            assert_eq(len(calls), 1, "unknown type → no handler call")

            # 4.7 Handler exception → НЕ 5xx (иначе Twitch retry бесконечный)
            resp = await post_event("msg-105", "test.crash", REGISTERED_CH)
            assert_eq(resp.status_code, 200, "handler crash → 200 (no 5xx)")

            # 4.8 Webhook callback verification → 200 + challenge text
            msg_id = "msg-verify"
            msg_ts = _now_iso()
            challenge_body = json.dumps({
                "challenge": "test-challenge-string",
                "subscription": {"type": "test.event"},
            }).encode()
            sig = _make_signature(secret, msg_id, msg_ts, challenge_body)
            req = StubRequest(challenge_body, {
                "Twitch-Eventsub-Message-Id": msg_id,
                "Twitch-Eventsub-Message-Timestamp": msg_ts,
                "Twitch-Eventsub-Message-Signature": sig,
                "Twitch-Eventsub-Message-Type": "webhook_callback_verification",
            })
            resp = await es._process_eventsub_request(req)
            assert_eq(resp.status_code, 200, "challenge → 200")
            assert_eq(resp.body, b"test-challenge-string", "challenge response = challenge text")

            # Restore _handlers
            es._handlers.clear()
            es._handlers.update(saved_handlers)
            CHANNEL_POINTS_CONFIG["eventsub_secret"] = saved_secret
            dependencies._registered_channels_cache.clear()
            dependencies._channels_cache_initialized = False
        finally:
            await db._pool.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _make_crashing_handler():
    async def crash_handler(event, channel_id):
        raise RuntimeError("intentional test crash — should be caught")
    return crash_handler


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────


async def _run_async():
    await test_dedupe_table()
    await test_dispatch_flow()


def main():
    test_signature_verify()
    test_replay_window()
    asyncio.run(_run_async())

    total = len(_successes) + len(_failures)
    print(f"\n{'='*60}")
    print(f"Результат: {len(_successes)}/{total} тестов прошли")
    if _failures:
        print(f"\nПровалы ({len(_failures)}):")
        for f in _failures:
            print(f)
        sys.exit(1)
    else:
        print("✅ Все тесты прошли")
        sys.exit(0)


if __name__ == "__main__":
    main()
