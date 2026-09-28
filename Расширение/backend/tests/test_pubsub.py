"""
test_pubsub.py — security smoke-test для PubSub send-side (Phase C).

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_pubsub.py

Покрывает:
1. PII deny-list — scrub raises на token/email/etc, проходит safe payload
2. Envelope schema — {v:1, type, seq, ts, data}, monotonic seq per type
3. Envelope size limit — > 5 KB raises
4. JWT signing — claims correct (role, channel_id, pubsub_perms.send)
5. JWT roundtrip — encoded → decoded с тем же секретом, claims match
6. Queue backpressure — coalesce oldest при > _QUEUE_BACKPRESSURE
"""
from __future__ import annotations

import os
import sys
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

# Required env для config.py + pubsub.py
os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault(
    "TWITCH_EXTENSION_SECRET",
    "dGVzdC1zZWNyZXQtMzItYnl0ZXMtZm9yLXVuaXQtdGVzdA",  # base64url of 32-byte
)
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-12345")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")

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


def assert_raises(callable_, exc_type: type, label: str):
    try:
        callable_()
        msg = f"  ❌ {label}: expected {exc_type.__name__}, got no exception"
        _failures.append(msg)
        print(msg)
    except exc_type:
        _successes.append(label)
        print(f"  ✅ {label}")
    except Exception as e:
        msg = f"  ❌ {label}: expected {exc_type.__name__}, got {type(e).__name__}: {e}"
        _failures.append(msg)
        print(msg)


# ─── Test 1: PII deny-list ────────────────────────────────────────────────────


def test_scrub_payload():
    print("\n[1] PII deny-list scrub")
    import pubsub

    # Safe payload — passes
    try:
        pubsub._scrub_payload({"username": "alice", "points": 100, "option": "a"})
        _successes.append("safe payload passes")
        print("  ✅ safe payload passes")
    except Exception as e:
        _failures.append(f"  ❌ safe payload rejected: {e}")

    # Top-level denied
    assert_raises(
        lambda: pubsub._scrub_payload({"token": "leak"}),
        ValueError, "top-level 'token' raises"
    )
    assert_raises(
        lambda: pubsub._scrub_payload({"email": "alice@example.com"}),
        ValueError, "top-level 'email' raises"
    )
    # Case-insensitive
    assert_raises(
        lambda: pubsub._scrub_payload({"AUTHORIZATION": "Bearer xxx"}),
        ValueError, "case-insensitive 'AUTHORIZATION' raises"
    )
    # Nested
    assert_raises(
        lambda: pubsub._scrub_payload({"user": {"helix_token": "xxx"}}),
        ValueError, "nested 'helix_token' raises"
    )
    # In list
    assert_raises(
        lambda: pubsub._scrub_payload({"users": [{"name": "a", "password": "x"}]}),
        ValueError, "nested list-of-dict 'password' raises"
    )


# ─── Test 2: Envelope schema + monotonic seq ──────────────────────────────────


def test_envelope_schema():
    print("\n[2] Envelope schema + monotonic seq")
    import json
    import pubsub

    # Reset seq counter for isolation
    pubsub._seq_counter.clear()

    env_str = pubsub._make_envelope("vote_tick", 12345, {"total_pool": 500})
    env = json.loads(env_str)

    assert_eq(env["v"], 1, "envelope v=1")
    assert_eq(env["type"], "vote_tick", "envelope type")
    assert_eq(env["seq"], 1, "first seq=1")
    assert_eq(env["data"], {"total_pool": 500}, "data passthrough")
    assert_true(isinstance(env["ts"], int) and env["ts"] > 0, "ts is unix-ms int")

    # Monotonic per (channel, type)
    env2 = json.loads(pubsub._make_envelope("vote_tick", 12345, {"total_pool": 600}))
    assert_eq(env2["seq"], 2, "monotonic seq increment")

    # Different type — separate counter
    env3 = json.loads(pubsub._make_envelope("match_state", 12345, {"room_id": "r1"}))
    assert_eq(env3["seq"], 1, "different type → separate seq counter")

    # Different channel — separate counter
    env4 = json.loads(pubsub._make_envelope("vote_tick", 99999, {"total_pool": 1}))
    assert_eq(env4["seq"], 1, "different channel → separate seq counter")


# ─── Test 3: Payload size limit ───────────────────────────────────────────────


def test_payload_size_limit():
    print("\n[3] Payload 5KB limit")
    import pubsub

    # Сoтворим huge payload — массив строк >5KB
    huge = {"items": ["x" * 100 for _ in range(60)]}  # ~6000+ bytes
    assert_raises(
        lambda: pubsub._make_envelope("test", 12345, huge),
        ValueError, "huge payload >5KB raises"
    )

    # Small payload — passes
    try:
        pubsub._make_envelope("test", 12345, {"k": "v"})
        _successes.append("small payload passes size check")
        print("  ✅ small payload passes size check")
    except Exception as e:
        _failures.append(f"  ❌ small payload rejected: {e}")


# ─── Test 4: JWT signing — claims correct ──────────────────────────────────────


def test_jwt_signing():
    print("\n[4] JWT signing — claims correct")
    import base64 as _b64
    import time
    import jwt as _jwt
    import pubsub

    channel_id = 98319857
    topics = ["broadcast", "whisper-U123"]
    token = pubsub._make_send_jwt(channel_id, topics)

    # Decode без verify чтобы прочитать payload
    decoded = _jwt.decode(token, options={"verify_signature": False})

    assert_eq(decoded["channel_id"], str(channel_id), "claims.channel_id matches")
    assert_eq(decoded["role"], "external", "claims.role = 'external'")
    assert_eq(decoded["pubsub_perms"]["send"], topics, "claims.pubsub_perms.send")
    assert_true(decoded["exp"] > int(time.time()), "claims.exp in future")
    assert_true(decoded["exp"] <= int(time.time()) + 130, "claims.exp <= 120s+10 (TTL)")


def test_jwt_roundtrip_verify():
    print("\n[5] JWT roundtrip verify — same secret accepts, wrong rejects")
    import jwt as _jwt
    import pubsub

    token = pubsub._make_send_jwt(98319857, ["broadcast"])

    # Verify с тем же secret — должно пройти
    secret_b64 = os.environ["TWITCH_EXTENSION_SECRET"]
    secret = pubsub._decode_extension_secret(secret_b64)
    try:
        verified = _jwt.decode(token, secret, algorithms=["HS256"])
        assert_eq(verified["channel_id"], "98319857", "roundtrip with correct secret")
    except Exception as e:
        _failures.append(f"  ❌ roundtrip failed unexpectedly: {e}")

    # С другим secret — должно fail
    assert_raises(
        lambda: _jwt.decode(token, b"wrong-secret-32-bytes-aaaaaaaa", algorithms=["HS256"]),
        _jwt.InvalidSignatureError,
        "wrong secret rejected by verifier"
    )


# ─── Test 6: Queue backpressure coalesce ─────────────────────────────────────


def test_queue_backpressure():
    print("\n[6] Queue backpressure — drops oldest")
    import asyncio
    import pubsub

    # Sync coro runner для use in this sync test fn
    loop = asyncio.new_event_loop()
    try:
        # Clean queue state isolation
        pubsub._send_queues.clear()

        # Push _QUEUE_BACKPRESSURE+3 sigvalues. Должны coalesce.
        ch = 77777
        topic = "broadcast"
        for i in range(pubsub._QUEUE_BACKPRESSURE + 3):
            pubsub._enqueue(ch, topic, f"msg-{i}")

        q = pubsub._send_queues[(ch, topic)]
        # Очередь должна содержать ровно _QUEUE_BACKPRESSURE messages
        assert_eq(q.qsize(), pubsub._QUEUE_BACKPRESSURE,
                   f"qsize capped at {pubsub._QUEUE_BACKPRESSURE}")

        # Oldest msg-0/msg-1/msg-2 должны быть дропнуты, осталось msg-3+
        first = q.get_nowait()
        assert_true(
            int(first.split("-")[1]) >= 3,
            f"first remaining msg index >= 3 (got {first})"
        )
    finally:
        loop.close()


# ─── Test 7: Public broadcast/whisper API ─────────────────────────────────────


def test_public_api():
    print("\n[7] Public broadcast() / whisper() API")
    import pubsub

    pubsub._send_queues.clear()

    # broadcast → enqueued
    ok = pubsub.broadcast(12345, "vote_started", {"event_id": 1, "options": []})
    assert_true(ok, "broadcast returns True")
    assert_true(
        (12345, "broadcast") in pubsub._send_queues,
        "broadcast topic 'broadcast' queue created"
    )

    # whisper → topic format whisper-<opaque>
    ok = pubsub.whisper(12345, "U12345", "balance_changed", {"points": 100})
    assert_true(ok, "whisper returns True for valid opaque_id")
    assert_true(
        (12345, "whisper-U12345") in pubsub._send_queues,
        "whisper topic format correct"
    )

    # whisper с пустым opaque_id → no-op
    ok = pubsub.whisper(12345, "", "balance_changed", {"points": 100})
    assert_eq(ok, False, "whisper with empty opaque_id returns False")

    # broadcast с PII → raises
    assert_raises(
        lambda: pubsub.broadcast(12345, "bad", {"token": "leak"}),
        ValueError, "broadcast scrubs PII before enqueue"
    )


# ─── Run ──────────────────────────────────────────────────────────────────────


def main():
    test_scrub_payload()
    test_envelope_schema()
    test_payload_size_limit()
    test_jwt_signing()
    test_jwt_roundtrip_verify()
    test_queue_backpressure()
    test_public_api()

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
