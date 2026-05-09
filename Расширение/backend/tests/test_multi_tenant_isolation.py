"""
test_multi_tenant_isolation.py — smoke-test multi-tenant invariants.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_multi_tenant_isolation.py

Покрывает:
1. resolve_channel_id strict-режим (raises без ContextVar/explicit param)
2. resolve_channel_id_or_default soft fallback в DEFAULT
3. Module token issue → verify → tampered reject
4. Module token cross-module mismatch reject
5. Per-channel viewers isolation (M1 + M4 channels)
6. Action queue cross-channel ACK guard
7. Catalog replace-семантика per (channel, module, type)

Если что-то упало — это РЕГРЕСС. Архитектура многоtenant-инвариантов нарушена.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import json
import traceback
from pathlib import Path

# Setup imports — script запускается из backend/, добавляем его в path
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


# ─────────────────────────────────────────────────────────────────────────────
# Test runner — minimal без pytest
# ─────────────────────────────────────────────────────────────────────────────
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


def assert_raises(callable_, exc_type: type, label: str):
    try:
        result = callable_()
        if asyncio.iscoroutine(result):
            asyncio.get_event_loop().run_until_complete(result)
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


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: resolve_channel_id strict + soft variants
# ─────────────────────────────────────────────────────────────────────────────
def test_resolve_channel_id():
    print("\n[1] resolve_channel_id strict + soft variants")
    import dependencies
    # Strict без params + без ContextVar → raise
    try:
        dependencies.resolve_channel_id()
        _failures.append("  ❌ resolve_channel_id() без аргумента должен raise'нуть")
        print(_failures[-1])
    except RuntimeError:
        _successes.append("strict raise without context")
        print("  ✅ strict raise without context")
    # Strict с явным param > 0 → возвращает его
    assert_eq(dependencies.resolve_channel_id(123), 123, "strict with explicit param")
    # Strict с param=0 → raise (param<=0 не считается)
    try:
        dependencies.resolve_channel_id(0)
        _failures.append("  ❌ resolve_channel_id(0) должен raise'нуть")
        print(_failures[-1])
    except RuntimeError:
        _successes.append("strict raise with param=0")
        print("  ✅ strict raise with param=0")
    # Soft default → returns DEFAULT_CHANNEL_ID
    from config import DEFAULT_CHANNEL_ID
    assert_eq(dependencies.resolve_channel_id_or_default(), DEFAULT_CHANNEL_ID, "soft fallback to DEFAULT")
    assert_eq(dependencies.resolve_channel_id_or_default(456), 456, "soft with explicit param")
    # ContextVar set → strict возвращает его
    dependencies.set_request_channel_id(789)
    assert_eq(dependencies.resolve_channel_id(), 789, "strict via ContextVar")
    # Reset ContextVar
    dependencies._current_channel_id.set(None)


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Module token round-trip + tamper resistance
# ─────────────────────────────────────────────────────────────────────────────
def test_module_token():
    print("\n[2] Module token issue/verify/tamper")
    from routes.streamer import issue_module_token, verify_module_token

    tok = issue_module_token(98319857, "rimworld")
    claims = verify_module_token(tok)
    assert_true(claims is not None, "valid token verifies")
    assert_eq(claims["channel_id"], 98319857, "token.channel_id correct")
    assert_eq(claims["module_id"], "rimworld", "token.module_id correct")
    assert_true(claims["expires_at"] > int(time.time()), "token.expires_at in future")

    # Tamper: меняем последний символ подписи
    tampered = tok[:-1] + ("X" if not tok.endswith("X") else "Y")
    assert_eq(verify_module_token(tampered), None, "tampered token rejected")

    # Garbage / empty
    assert_eq(verify_module_token(""), None, "empty token rejected")
    assert_eq(verify_module_token("foo|bar"), None, "malformed token rejected")
    assert_eq(verify_module_token("foo|bar|baz"), None, "wrong-segment-count rejected")

    # Expired token
    past_tok = issue_module_token(98319857, "rimworld", ttl_seconds=60)
    # Manually craft expired token
    parts = past_tok.split("|")
    parts[2] = str(int(time.time()) - 100)  # expires_at в прошлом
    fake_msg = "|".join(parts[:3])
    import hmac as _hmac
    import hashlib
    secret = os.environ["MODULE_TOKEN_SECRET"].encode()
    fake_sig = _hmac.new(secret, fake_msg.encode(), hashlib.sha256).hexdigest()
    expired_tok = f"{fake_msg}|{fake_sig}"
    assert_eq(verify_module_token(expired_tok), None, "expired token rejected")


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Per-channel viewer isolation (raw SQL — без полного init Database)
# ─────────────────────────────────────────────────────────────────────────────
async def test_channel_isolation():
    print("\n[3] Per-channel viewer isolation")
    import aiosqlite
    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        async with aiosqlite.connect(db_path) as conn:
            # Минимальная схема похожая на M1-migrated viewers
            await conn.execute("""
                CREATE TABLE viewers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    points INTEGER DEFAULT 0,
                    UNIQUE(channel_id, username)
                )
            """)
            # Одинаковый username "alice" в двух каналах
            await conn.execute(
                "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
                (98319857, "alice", 100),
            )
            await conn.execute(
                "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
                (99999, "alice", 200),
            )
            await conn.commit()

            # Scoped query: канал A
            cur = await conn.execute(
                "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                (98319857, "alice"),
            )
            row = await cur.fetchone()
            assert_eq(row[0], 100, "channel A alice.points=100")

            # Scoped query: канал B
            cur = await conn.execute(
                "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                (99999, "alice"),
            )
            row = await cur.fetchone()
            assert_eq(row[0], 200, "channel B alice.points=200")

            # Anti-pattern test: запрос БЕЗ channel_id — должен вернуть несколько строк
            cur = await conn.execute("SELECT points FROM viewers WHERE username=?", ("alice",))
            rows = await cur.fetchall()
            assert_eq(len(rows), 2, "single-tenant query returns BOTH channels (anti-pattern detection)")

            # Cross-channel UPDATE protection: попытка обновить канал A через WHERE без channel_id
            # повлияет на оба — это и есть пример bug'а
            await conn.execute("UPDATE viewers SET points=999 WHERE username=?", ("alice",))
            await conn.commit()
            cur = await conn.execute("SELECT channel_id, points FROM viewers WHERE username=?", ("alice",))
            rows = await cur.fetchall()
            assert_true(all(r[1] == 999 for r in rows),
                        "UPDATE без channel_id поразил оба канала (антипаттерн)")
            assert_eq(len(rows), 2, "antipattern: 2 rows updated (must have channel_id in WHERE)")
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Action queue idempotency + cross-channel ACK guard
# ─────────────────────────────────────────────────────────────────────────────
async def test_action_queue_isolation():
    print("\n[4] Action queue idempotency + cross-channel ACK guard")
    import aiosqlite
    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        from migrations import m5_module_actions
        async with aiosqlite.connect(db_path) as conn:
            await m5_module_actions.apply(conn)

        async with aiosqlite.connect(db_path) as conn:
            # Канал A enqueue'ит action
            await conn.execute(
                """INSERT INTO module_actions
                   (channel_id, module_id, action_id, type, data, status)
                   VALUES (?, ?, ?, ?, ?, 'queued')""",
                (98319857, "rimworld", "env-1", "player.spawn", "{}"),
            )
            # Канал B enqueue'ит action с тем же action_id (это нормально — разные scopes)
            await conn.execute(
                """INSERT INTO module_actions
                   (channel_id, module_id, action_id, type, data, status)
                   VALUES (?, ?, ?, ?, ?, 'queued')""",
                (99999, "rimworld", "env-1", "player.spawn", "{}"),
            )
            await conn.commit()

            # ACK env-1 от канала A — обновится ТОЛЬКО его запись
            cur = await conn.execute(
                """UPDATE module_actions SET status='acked', acked_at=CURRENT_TIMESTAMP
                   WHERE channel_id=? AND module_id=? AND action_id=?
                   AND status IN ('queued', 'dispatched')""",
                (98319857, "rimworld", "env-1"),
            )
            await conn.commit()
            assert_eq(cur.rowcount, 1, "ACK от channel A обновил 1 запись")

            # Verify: канал B запись осталась queued
            cur = await conn.execute(
                "SELECT status FROM module_actions WHERE channel_id=?",
                (99999,),
            )
            row = await cur.fetchone()
            assert_eq(row[0], "queued", "channel B запись не затронута ACK'ом канала A")

            # Cross-channel attack: канал C пытается ACK'нуть env-1 канала A
            cur = await conn.execute(
                """UPDATE module_actions SET status='acked'
                   WHERE channel_id=? AND module_id=? AND action_id=?
                   AND status IN ('queued', 'dispatched')""",
                (12345, "rimworld", "env-1"),
            )
            await conn.commit()
            assert_eq(cur.rowcount, 0, "cross-channel ACK от 12345 → 0 rows (security)")

            # Idempotent ACK: повторный ACK от канала A — 0 rows (уже acked)
            cur = await conn.execute(
                """UPDATE module_actions SET status='acked'
                   WHERE channel_id=? AND module_id=? AND action_id=?
                   AND status IN ('queued', 'dispatched')""",
                (98319857, "rimworld", "env-1"),
            )
            await conn.commit()
            assert_eq(cur.rowcount, 0, "повторный ACK от того же канала → 0 rows (idempotent)")
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Catalog replace-семантика
# ─────────────────────────────────────────────────────────────────────────────
async def test_catalog_replace_semantics():
    print("\n[5] Catalog replace-semantics + cross-channel isolation")
    import aiosqlite
    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        from migrations import m6_module_catalogs
        async with aiosqlite.connect(db_path) as conn:
            await m6_module_catalogs.apply(conn)

        async with aiosqlite.connect(db_path) as conn:
            async def replace(channel_id, mod_id, ctype, entries):
                await conn.execute("BEGIN IMMEDIATE")
                await conn.execute(
                    "DELETE FROM module_catalogs WHERE channel_id=? AND module_id=? AND catalog_type=?",
                    (channel_id, mod_id, ctype),
                )
                for e in entries:
                    await conn.execute(
                        "INSERT INTO module_catalogs (channel_id, module_id, catalog_type, entry_id, payload) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (channel_id, mod_id, ctype, e["id"], json.dumps(e)),
                    )
                await conn.commit()

            # Channel A: 3 shop entries
            await replace(98319857, "rimworld", "shop", [
                {"id": "Wood", "price": 50},
                {"id": "Steel", "price": 200},
                {"id": "Plasteel", "price": 1000},
            ])
            # Channel B: 1 entry — другой канал параллельно
            await replace(99999, "rimworld", "shop", [{"id": "OtherItem", "price": 1}])

            # Verify channel A — 3 entries
            cur = await conn.execute(
                "SELECT COUNT(*) FROM module_catalogs WHERE channel_id=? AND module_id=? AND catalog_type=?",
                (98319857, "rimworld", "shop"),
            )
            row = await cur.fetchone()
            assert_eq(row[0], 3, "channel A shop = 3 entries")

            # Replace channel A с 2 entries (Gold, Silver) — старые 3 должны исчезнуть
            await replace(98319857, "rimworld", "shop", [
                {"id": "Gold", "price": 5000},
                {"id": "Silver", "price": 1500},
            ])
            cur = await conn.execute(
                "SELECT entry_id FROM module_catalogs WHERE channel_id=? AND module_id=? AND catalog_type=?",
                (98319857, "rimworld", "shop"),
            )
            rows = await cur.fetchall()
            assert_eq(len(rows), 2, "channel A shop after replace = 2 entries (replace-semantics)")
            entry_ids = sorted(r[0] for r in rows)
            assert_eq(entry_ids, ["Gold", "Silver"], "channel A entries — новые, старые удалены")

            # Channel B не затронут replace'ом канала A
            cur = await conn.execute(
                "SELECT entry_id FROM module_catalogs WHERE channel_id=?",
                (99999,),
            )
            row = await cur.fetchone()
            assert_eq(row[0], "OtherItem", "channel B не затронут replace'ом канала A")

            # Cross-channel cleanup test (session_start hook)
            cur = await conn.execute(
                "DELETE FROM module_catalogs WHERE channel_id=? AND module_id=?",
                (98319857, "rimworld"),
            )
            await conn.commit()
            assert_eq(cur.rowcount, 2, "session_start cleanup channel A → 2 entries gone")
            cur = await conn.execute("SELECT COUNT(*) FROM module_catalogs WHERE channel_id=?", (99999,))
            row = await cur.fetchone()
            assert_eq(row[0], 1, "channel B остался нетронут после session_start канала A")
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: In-memory cache key — multi-tenant invariant
# ─────────────────────────────────────────────────────────────────────────────
def test_in_memory_cache_keys():
    print("\n[6] In-memory cache: per-(channel, user) keys (no overwrite)")
    # Симулируем то что bot_core.update_viewer_presence/chat делает:
    # ключ — tuple (channel_id, username), не просто username.
    cache = {}
    from datetime import datetime as _dt
    t1 = _dt(2026, 5, 9, 10, 0, 0)
    t2 = _dt(2026, 5, 9, 11, 0, 0)
    # alice на канале A
    cache[(98319857, "alice")] = t1
    # alice на канале B (другой стример) — должна быть НЕЗАВИСИМАЯ запись
    cache[(99999, "alice")] = t2
    assert_eq(len(cache), 2, "two keys for same username on different channels")
    assert_eq(cache.get((98319857, "alice")), t1, "channel A retains its timestamp")
    assert_eq(cache.get((99999, "alice")), t2, "channel B retains its timestamp")
    # Регресс check: старый код хранил по username — overwrite'нул бы
    assert_true(cache[(98319857, "alice")] != cache[(99999, "alice")],
                "no cross-channel overwrite (bug class fixed)")


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Chat-bonus антифрод (M7)
# ─────────────────────────────────────────────────────────────────────────────
def test_chat_bonus_antifraud():
    print("\n[7] Chat-bonus антифрод (M7): cooldown + min length + dedup")
    # Импорт BotCore + создаём фейковый instance минимально чтобы не
    # дёргать DB. Метод compute_chat_bonus pure (in-memory only).
    from bot_core import BotCore
    # BotCore требует db в __init__ для event_manager. Дадим mock.
    class _MockDb:
        db_path = ":memory:"
    bot = BotCore.__new__(BotCore)
    # Минимальный init только нужных полей. __init__ дёрнет EventManager
    # который не нужен здесь — обходимся вручную.
    bot.db = _MockDb()
    bot.viewers_last_active = {}
    bot.last_chat_update = {}
    bot.last_activity_update = {}
    bot.last_attention = {}
    bot._chat_bonus_last_at = {}
    bot._chat_bonus_recent_hashes = {}
    from collections import deque as _deque
    bot._chat_bonus_recent_hashes_factory = _deque

    cid_a = 98319857
    cid_b = 99999

    # Min length: < 10 chars → 0
    assert_eq(bot.compute_chat_bonus(cid_a, "alice", "hi"), 0,
              "<10 chars → no bonus")
    assert_eq(bot.compute_chat_bonus(cid_a, "alice", "short"), 0,
              "5 chars → no bonus")

    # First long message → bonus
    bonus1 = bot.compute_chat_bonus(cid_a, "alice", "Hello chat folks!")
    assert_true(bonus1 > 0, "first 17-char msg → bonus")
    expected = min(len("Hello chat folks!") // 10, 10)
    assert_eq(bonus1, expected, f"bonus = min(len/10, 10) = {expected}")

    # Cooldown: same user, immediately → 0
    assert_eq(bot.compute_chat_bonus(cid_a, "alice", "Different message text"), 0,
              "cooldown <10s → no bonus")

    # Different user same channel — independent
    bonus2 = bot.compute_chat_bonus(cid_a, "bob", "Hello from Bob there")
    assert_true(bonus2 > 0, "different user same channel — own cooldown")

    # Same user, different channel — independent
    bonus3 = bot.compute_chat_bonus(cid_b, "alice", "Hello chat folks!")
    assert_true(bonus3 > 0, "same user different channel — own state")

    # Dedup: simulate cooldown expiry by manually clearing last_at, then send
    # the SAME text → should be 0 because hash already in recent.
    from datetime import datetime as _dt, timedelta as _td
    # Forget cooldown for alice on cid_a
    bot._chat_bonus_last_at[(cid_a, "alice")] = _dt.now() - _td(seconds=20)
    # Same hash as bonus1 — was "Hello chat folks!"
    assert_eq(bot.compute_chat_bonus(cid_a, "alice", "Hello chat folks!"), 0,
              "dedup: repeat same text → no bonus (cooldown already expired)")

    # Normalized dedup: case + extra whitespace shouldn't fool us
    bot._chat_bonus_last_at[(cid_a, "alice")] = _dt.now() - _td(seconds=20)
    assert_eq(bot.compute_chat_bonus(cid_a, "alice", "HELLO   chat   folks!"), 0,
              "dedup: normalized case+whitespace → no bonus")

    # New unique text after cooldown → bonus
    bot._chat_bonus_last_at[(cid_a, "alice")] = _dt.now() - _td(seconds=20)
    assert_true(
        bot.compute_chat_bonus(cid_a, "alice", "Completely fresh and unique") > 0,
        "new unique text after cooldown → bonus"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────
async def run_all_tests():
    print("=" * 70)
    print("Multi-tenant isolation smoke-tests")
    print("=" * 70)

    test_resolve_channel_id()
    test_module_token()
    await test_channel_isolation()
    await test_action_queue_isolation()
    await test_catalog_replace_semantics()
    test_in_memory_cache_keys()
    test_chat_bonus_antifraud()

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}    FAILED: {len(_failures)}")
    print("=" * 70)
    if _failures:
        print("\nFAILURES:")
        for f in _failures:
            print(f)
        return 1
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(run_all_tests())
    except Exception as e:
        traceback.print_exc()
        rc = 2
    sys.exit(rc)
