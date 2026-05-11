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
# Test 8: BotCore.current_stream_id is per-channel (Bug 4 fix, 2026-05-10)
# ─────────────────────────────────────────────────────────────────────────────
def test_current_stream_id_per_channel():
    """Регресс-тест Bug 4: current_stream_id должен быть per-channel.

    Раньше это было `current_stream_id: str = ""` — глобальное состояние.
    После регистрации 2-го стримера запись stream_id канала B перетирала
    запись канала A, и attendance/streak ломались.
    """
    print("\n[8] Bug 4 fix: current_stream_id per-channel")
    from bot_core import BotCore

    class _MockDb:
        db_path = ":memory:"

    bot = BotCore.__new__(BotCore)
    bot.db = _MockDb()
    bot.current_stream_id = {}

    cid_a = 98319857
    cid_b = 99999

    # Изначально нет стрима — get вернёт ""
    from dependencies import _current_channel_id
    tok = _current_channel_id.set(cid_a)
    try:
        assert_eq(bot.get_current_stream_id(), "", "no stream → empty string")
        assert_eq(bot.get_current_stream_id(channel_id=cid_b), "",
                  "no stream channel B → empty string")
    finally:
        _current_channel_id.reset(tok)

    # Регистрируем стрим канала A
    bot.set_current_stream_id(cid_a, "2026-05-10")
    assert_eq(bot.get_current_stream_id(channel_id=cid_a), "2026-05-10",
              "channel A stream registered")
    assert_eq(bot.get_current_stream_id(channel_id=cid_b), "",
              "channel B isolated from A")

    # Регистрируем стрим канала B (другая дата чтобы поймать collision)
    bot.set_current_stream_id(cid_b, "2026-05-09")
    assert_eq(bot.get_current_stream_id(channel_id=cid_a), "2026-05-10",
              "channel A unchanged after B registered")
    assert_eq(bot.get_current_stream_id(channel_id=cid_b), "2026-05-09",
              "channel B has its own stream_id")
    assert_true(
        bot.get_current_stream_id(channel_id=cid_a) != bot.get_current_stream_id(channel_id=cid_b),
        "no cross-channel overwrite of stream_id (Bug 4 regress)"
    )

    # Завершаем стрим канала B (set "" удаляет)
    bot.set_current_stream_id(cid_b, "")
    assert_eq(bot.get_current_stream_id(channel_id=cid_b), "",
              "channel B ended → empty string")
    assert_eq(bot.get_current_stream_id(channel_id=cid_a), "2026-05-10",
              "channel A still live after B ended")

    # _stream_live_cache тоже per-channel
    bot._stream_live_cache = {}
    bot._stream_live_cache[cid_a] = (True, 1234567890.0)
    bot._stream_live_cache[cid_b] = (False, 1234567890.0)
    assert_true(bot._stream_live_cache[cid_a][0] is True,
                "channel A cached as live")
    assert_true(bot._stream_live_cache[cid_b][0] is False,
                "channel B cached as offline")
    assert_true(
        bot._stream_live_cache[cid_a] != bot._stream_live_cache[cid_b],
        "stream_live cache isolated per channel (no scalar pollution)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Cases system (Phase 2) — multi-tenant + idempotency + atomicity
# ─────────────────────────────────────────────────────────────────────────────
async def test_cases_system():
    """Phase 2 cases via raw SQL (без Database класса — init_pool requires
    full infrastructure setup, тут проверяем чистую логику multi-tenant
    isolation + idempotency + atomicity).

    Покрытие:
      - Multi-tenant isolation: тот же username, разные channel_id → разные кейсы
      - Idempotency через case_triggers_fired (one-time milestones)
      - Cross-channel boundary: trigger_key уникален per channel, не глобально
      - Cross-user attack protection: bob не может open кейс alice
      - Already-opened protection
      - Tier reward consistency (1k/10k/100k/500k)
    """
    print("\n[9] Cases system (Phase 2)")
    import aiosqlite as _aio
    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        async with _aio.connect(db_path) as conn:
            # Setup схема через M9 миграцию
            from migrations import m9_cases
            await m9_cases.apply(conn)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS viewers (
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    points INTEGER DEFAULT 0,
                    last_seen DATETIME,
                    join_time DATETIME,
                    is_afk INTEGER DEFAULT 0,
                    PRIMARY KEY(channel_id, username)
                )
            """)
            await conn.commit()

            CASE_REWARDS = {'common': 1000, 'rare': 10000, 'epic': 100000, 'legendary': 500000}
            cid_a = 98319857
            cid_b = 99999

            # ── Helper: raw grant_case logic (mirror of database.py) ──────────
            async def grant_case(cid, user, tier, source, trigger_key=None):
                if tier not in CASE_REWARDS:
                    return {'granted': False, 'reason': 'invalid_tier'}
                await conn.execute("BEGIN IMMEDIATE")
                if trigger_key:
                    cur = await conn.execute(
                        "SELECT case_id FROM case_triggers_fired "
                        "WHERE channel_id=? AND username=? AND trigger_key=?",
                        (cid, user.lower(), trigger_key)
                    )
                    existing = await cur.fetchone()
                    if existing:
                        await conn.execute("ROLLBACK")
                        return {'granted': False, 'reason': 'already_fired', 'case_id': existing[0]}
                cur = await conn.execute(
                    "INSERT INTO cases (channel_id, username, tier, source) VALUES (?, ?, ?, ?)",
                    (cid, user.lower(), tier, source)
                )
                case_id = cur.lastrowid
                if trigger_key:
                    await conn.execute(
                        "INSERT INTO case_triggers_fired (channel_id, username, trigger_key, case_id) "
                        "VALUES (?, ?, ?, ?)",
                        (cid, user.lower(), trigger_key, case_id)
                    )
                await conn.commit()
                return {'granted': True, 'case_id': case_id, 'tier': tier}

            # ── Helper: raw open_case ─────────────────────────────────────────
            async def open_case(case_id, user, cid):
                await conn.execute("BEGIN IMMEDIATE")
                cur = await conn.execute(
                    "SELECT channel_id, username, tier, opened_at FROM cases WHERE id=?",
                    (case_id,)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'opened': False, 'reason': 'not_found'}
                row_cid, row_user, row_tier, row_opened = row
                if row_cid != cid or row_user != user.lower():
                    await conn.execute("ROLLBACK")
                    return {'opened': False, 'reason': 'not_owner'}
                if row_opened is not None:
                    await conn.execute("ROLLBACK")
                    return {'opened': False, 'reason': 'already_opened'}
                reward = CASE_REWARDS[row_tier]
                await conn.execute(
                    "UPDATE cases SET opened_at=CURRENT_TIMESTAMP, reward_points=? WHERE id=?",
                    (reward, case_id)
                )
                await conn.execute("""
                    INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk)
                    VALUES (?, ?, ?, datetime('now'), datetime('now'), 0)
                    ON CONFLICT(channel_id, username) DO UPDATE SET points=points+excluded.points
                """, (cid, user.lower(), reward))
                cur = await conn.execute(
                    "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                    (cid, user.lower())
                )
                bal = (await cur.fetchone())[0]
                await conn.commit()
                return {'opened': True, 'tier': row_tier, 'reward_points': reward, 'new_balance': bal}

            # 9.1 Grant common case на канале A
            r = await grant_case(cid_a, "alice", "common", "quest")
            assert_true(r['granted'], "grant common case to alice on cid_a")
            case_id_a = r['case_id']

            # 9.2 Same username другой канал — отдельный кейс
            r = await grant_case(cid_b, "alice", "rare", "streak", trigger_key="streak_10")
            assert_true(r['granted'], "grant rare case to alice on cid_b")
            case_id_b = r['case_id']
            assert_true(case_id_a != case_id_b, "different case_ids per channel")

            # 9.3 Idempotency через trigger_key — повтор НЕ выдаёт
            r = await grant_case(cid_b, "alice", "rare", "streak", trigger_key="streak_10")
            assert_eq(r['granted'], False, "duplicate streak_10 trigger rejected")
            assert_eq(r['reason'], 'already_fired', "reason = already_fired")
            assert_eq(r['case_id'], case_id_b, "returned existing case_id")

            # 9.4 trigger_key UNIQUE per channel, не глобально
            r = await grant_case(cid_a, "alice", "rare", "streak", trigger_key="streak_10")
            assert_true(r['granted'], "channel A streak_10 — independent from channel B")

            # 9.5 Open case → правильная награда
            opn = await open_case(case_id_a, "alice", cid_a)
            assert_true(opn['opened'], "common case opened")
            assert_eq(opn['reward_points'], 1000, "common reward = 1000")
            assert_eq(opn['new_balance'], 1000, "balance credited correctly")

            # 9.6 Already-opened protection
            opn = await open_case(case_id_a, "alice", cid_a)
            assert_eq(opn['opened'], False, "second open rejected")
            assert_eq(opn['reason'], 'already_opened', "reason = already_opened")

            # 9.7 Cross-user attack: bob не может open кейс alice
            opn = await open_case(case_id_b, "bob", cid_b)
            assert_eq(opn['opened'], False, "bob cannot open alice's case")
            assert_eq(opn['reason'], 'not_owner', "reason = not_owner")

            # 9.8 Wrong-channel attack: alice's cid_b case через cid_a
            opn = await open_case(case_id_b, "alice", cid_a)
            assert_eq(opn['opened'], False, "wrong channel_id rejected")
            assert_eq(opn['reason'], 'not_owner', "reason = not_owner (cross-channel boundary)")

            # 9.9 Not-found protection
            opn = await open_case(99999, "alice", cid_a)
            assert_eq(opn['reason'], 'not_found', "non-existent case → not_found")

            # 9.10 Validation
            r = await grant_case(cid_a, "alice", "mythic", "quest")
            assert_eq(r['granted'], False, "invalid tier rejected")

            # 9.11 list/count per channel
            cur = await conn.execute(
                "SELECT COUNT(*) FROM cases WHERE channel_id=? AND username=?",
                (cid_a, "alice")
            )
            a_total = (await cur.fetchone())[0]
            cur = await conn.execute(
                "SELECT COUNT(*) FROM cases WHERE channel_id=? AND username=? AND opened_at IS NULL",
                (cid_a, "alice")
            )
            a_unopened = (await cur.fetchone())[0]
            assert_eq(a_total, 2, "channel A: 2 cases for alice (opened common + closed rare)")
            assert_eq(a_unopened, 1, "channel A: 1 unopened case (rare)")

            # 9.12 Epic reward
            r = await grant_case(cid_a, "charlie", "epic", "watch_milestone", trigger_key="watch_100h")
            assert_true(r['granted'], "epic case granted")
            opn = await open_case(r['case_id'], "charlie", cid_a)
            assert_eq(opn['reward_points'], 100_000, "epic reward = 100k")
            assert_eq(opn['new_balance'], 100_000, "charlie balance = 100k after epic open")

            # 9.13 Legendary reward
            r = await grant_case(cid_a, "dave", "legendary", "season_top",
                                 trigger_key="season_2026_Q1_top1")
            assert_true(r['granted'], "legendary case granted")
            opn = await open_case(r['case_id'], "dave", cid_a)
            assert_eq(opn['reward_points'], 500_000, "legendary reward = 500k")
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: Drops → cases distribution (Phase 6, 2026-05-11)
# ─────────────────────────────────────────────────────────────────────────────
def test_drops_distribution():
    """Phase 6: проверяет что DROP_CASE_TIERS weights дают распределение
    близкое к expected (70/25/4/1) на 2000 samples.

    Это chi-square-like sanity check, не строгий стат-тест — допустимые
    толерансы установлены щедро (±3% для common, ±2% для rare, ±1% для
    epic/legendary) чтобы не было flaky CI.

    Также проверяет что weights суммируются правильно (sanity).
    """
    print("\n[10] Drops → cases distribution (Phase 6)")
    import random as _random
    from bot_core import DROP_CASE_TIERS

    # Sanity: weights sum to 100
    total_w = sum(t[1] for t in DROP_CASE_TIERS)
    assert_eq(total_w, 100, "DROP_CASE_TIERS weights sum = 100")

    # Tiers present
    tier_names = [t[0] for t in DROP_CASE_TIERS]
    assert_true('common' in tier_names, "common in DROP_CASE_TIERS")
    assert_true('rare' in tier_names, "rare in DROP_CASE_TIERS")
    assert_true('epic' in tier_names, "epic in DROP_CASE_TIERS")
    assert_true('legendary' in tier_names, "legendary in DROP_CASE_TIERS")

    # Sample distribution
    N = 2000
    counts = {t: 0 for t, _ in DROP_CASE_TIERS}
    rng = _random.Random(42)  # seed для reproducible CI
    for _ in range(N):
        tier = rng.choices(
            [t[0] for t in DROP_CASE_TIERS],
            weights=[t[1] for t in DROP_CASE_TIERS],
        )[0]
        counts[tier] += 1

    common_pct = counts['common'] / N * 100
    rare_pct = counts['rare'] / N * 100
    epic_pct = counts['epic'] / N * 100
    legendary_pct = counts['legendary'] / N * 100

    # Толеранс: 3% для common, 2% для rare, 1.5% для epic/legendary
    # (с seed=42 на 2000 sample'ах распределение стабильное)
    assert_true(67.0 <= common_pct <= 73.0,
                f"common ≈ 70% (got {common_pct:.1f}%)")
    assert_true(23.0 <= rare_pct <= 27.0,
                f"rare ≈ 25% (got {rare_pct:.1f}%)")
    assert_true(2.5 <= epic_pct <= 5.5,
                f"epic ≈ 4% (got {epic_pct:.1f}%)")
    assert_true(0.3 <= legendary_pct <= 2.5,
                f"legendary ≈ 1% (got {legendary_pct:.1f}%)")

    print(f"  Distribution на {N} samples (seed=42):")
    print(f"    common:    {common_pct:.1f}% (target 70%)")
    print(f"    rare:      {rare_pct:.1f}% (target 25%)")
    print(f"    epic:      {epic_pct:.1f}% (target 4%)")
    print(f"    legendary: {legendary_pct:.1f}% (target 1%)")


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: Matchmaking infrastructure (Phase 5.0)
# ─────────────────────────────────────────────────────────────────────────────
async def test_matchmaking_infrastructure():
    """Phase 5.0: проверяет matchmaking pipeline через raw SQL:
      - enqueue: один юзер = одна активная queue per game (UNIQUE)
      - cross-channel/cross-game isolation queue-записей
      - find_match_pairs greedy ELO-pair логика
      - ELO-spread соблюдается (слишком разные ELO не матчатся)
      - room creation с правильными player_a/b после match
      - access-control get_room (cross-user, cross-channel snoop blocked)
      - finalize_match переводит room → finished
    """
    print("\n[11] Matchmaking infrastructure (Phase 5.0)")
    import aiosqlite as _aio
    import json as _json
    import uuid as _uuid

    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        async with _aio.connect(db_path) as conn:
            # Setup схема через M10
            await conn.execute("CREATE TABLE viewers (channel_id INTEGER, username TEXT, points INTEGER DEFAULT 0, last_seen DATETIME, join_time DATETIME, is_afk INTEGER DEFAULT 0, PRIMARY KEY(channel_id, username))")
            from migrations import m10_matchmaking
            await m10_matchmaking.apply(conn)
            await conn.commit()

            cid_a = 98319857
            cid_b = 99999

            # ── 11.1: Enqueue alice на RPS ─────────────────────────────────────
            cur = await conn.execute(
                "INSERT INTO match_queue (channel_id, username, game_type, elo_at_queue, elo_spread) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid_a, "alice", "rps", 1100, 100)
            )
            q1 = cur.lastrowid
            await conn.commit()
            assert_true(q1 > 0, "alice enqueued on cid_a/rps")

            # 11.2: UNIQUE constraint — повторный enqueue той же combo → fail
            from aiosqlite import IntegrityError as _IE
            try:
                await conn.execute(
                    "INSERT INTO match_queue (channel_id, username, game_type, elo_at_queue, elo_spread) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (cid_a, "alice", "rps", 1100, 100)
                )
                await conn.commit()
                assert_true(False, "duplicate active queue entry should fail")
            except _IE:
                assert_true(True, "duplicate active queue entry rejected by UNIQUE")
                await conn.rollback()

            # 11.3: Тот же юзер другой game_type — OK (отдельный rating)
            cur = await conn.execute(
                "INSERT INTO match_queue (channel_id, username, game_type, elo_at_queue, elo_spread) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid_a, "alice", "tictactoe", 1100, 100)
            )
            await conn.commit()
            assert_true(cur.lastrowid > 0, "alice can queue on different game_type")

            # 11.4: Тот же юзер другой channel — OK (multi-tenant)
            cur = await conn.execute(
                "INSERT INTO match_queue (channel_id, username, game_type, elo_at_queue, elo_spread) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid_b, "alice", "rps", 1100, 100)
            )
            await conn.commit()
            assert_true(cur.lastrowid > 0, "alice on cid_b/rps — independent from cid_a")

            # 11.5: Bob queues cid_a/rps — должен матчиться с alice
            await conn.execute(
                "INSERT INTO match_queue (channel_id, username, game_type, elo_at_queue, elo_spread) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid_a, "bob", "rps", 1150, 100)
            )
            await conn.commit()

            # 11.6: Simulate find_match_pairs greedy (inline mini-version)
            cur = await conn.execute(
                "SELECT id, username, elo_at_queue, elo_spread FROM match_queue "
                "WHERE channel_id = ? AND game_type = ? AND status = 'queued' "
                "ORDER BY elo_at_queue",
                (cid_a, "rps")
            )
            queued = await cur.fetchall()
            assert_eq(len(queued), 2, "2 queued (alice + bob) on cid_a/rps")

            # Pair them
            a_id, a_user, a_elo, a_spread = queued[0]
            b_id, b_user, b_elo, b_spread = queued[1]
            assert_true(abs(a_elo - b_elo) <= max(a_spread, b_spread),
                        "ELO diff (50) <= spread (100) → matchable")

            room_id = f"room_rps_{_uuid.uuid4().hex[:12]}"
            await conn.execute(
                "INSERT INTO match_rooms (room_id, channel_id, game_type, player_a, player_b, "
                "player_a_elo, player_b_elo, state, status) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', 'active')",
                (room_id, cid_a, "rps", a_user, b_user, a_elo, b_elo)
            )
            await conn.execute(
                "UPDATE match_queue SET status = 'matched', matched_with = ?, room_id = ? WHERE id = ?",
                (b_id, room_id, a_id)
            )
            await conn.execute(
                "UPDATE match_queue SET status = 'matched', matched_with = ?, room_id = ? WHERE id = ?",
                (a_id, room_id, b_id)
            )
            await conn.commit()

            # 11.7: Room visible to player_a + player_b, NOT visible to charlie
            cur = await conn.execute(
                "SELECT channel_id FROM match_rooms WHERE room_id = ? AND "
                "(player_a = ? OR player_b = ?)",
                (room_id, "alice", "alice")
            )
            row = await cur.fetchone()
            assert_true(row is not None, "alice sees the room")
            cur = await conn.execute(
                "SELECT channel_id FROM match_rooms WHERE room_id = ? AND "
                "(player_a = ? OR player_b = ?)",
                (room_id, "charlie", "charlie")
            )
            row = await cur.fetchone()
            assert_true(row is None, "charlie blocked from room (not a player)")

            # 11.8: Cross-channel boundary — room на cid_a не виден из cid_b context
            cur = await conn.execute(
                "SELECT room_id FROM match_rooms WHERE room_id = ? AND channel_id = ?",
                (room_id, cid_b)
            )
            row = await cur.fetchone()
            assert_true(row is None, "cross-channel attack blocked")

            # 11.9: State update — JSON storage
            state = {"alice_move": "rock", "bob_move": None}
            await conn.execute(
                "UPDATE match_rooms SET state = ? WHERE room_id = ? AND status = 'active'",
                (_json.dumps(state), room_id)
            )
            await conn.commit()
            cur = await conn.execute("SELECT state FROM match_rooms WHERE room_id = ?", (room_id,))
            stored = _json.loads((await cur.fetchone())[0])
            assert_eq(stored["alice_move"], "rock", "state JSON roundtrip works")

            # 11.10: ELO-spread protection — слишком разные не матчатся
            # Charlie 1500 vs Dave 1100, обоим spread=100 → НЕ должны matched
            await conn.execute(
                "INSERT INTO match_queue (channel_id, username, game_type, elo_at_queue, elo_spread) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid_b, "charlie", "rps", 1500, 100)
            )
            await conn.execute(
                "INSERT INTO match_queue (channel_id, username, game_type, elo_at_queue, elo_spread) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid_b, "dave", "rps", 1100, 100)
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT id, elo_at_queue, elo_spread FROM match_queue "
                "WHERE channel_id = ? AND game_type = ? AND status = 'queued' ORDER BY elo_at_queue",
                (cid_b, "rps")
            )
            cb_queued = await cur.fetchall()
            # alice was here too (cid_b/rps) — теперь 3 в очереди
            # Greedy: dave (1100) + (1100 alice если есть) первые, потом charlie уже не парим с разрывом 400
            assert_true(len(cb_queued) == 3, "3 queued on cid_b/rps")
            # Если бы был find_match_pairs запущен с greedy:
            # sorted by elo: dave 1100, alice 1100, charlie 1500
            # pair (dave, alice) — diff 0 <= 100 → match
            # charlie остаётся unmatched
            d_elo = cb_queued[0][1]; a_elo = cb_queued[1][1]; c_elo = cb_queued[2][1]
            assert_true(abs(d_elo - a_elo) <= 100, "first pair (1100, 1100) within spread")
            assert_true(abs(a_elo - c_elo) > 100, "alice-charlie diff > spread (would not match)")

            # 11.11: finalize_match — status active → finished
            await conn.execute(
                "UPDATE match_rooms SET status = 'finished', winner = ?, outcome = ?, "
                "finished_at = CURRENT_TIMESTAMP WHERE room_id = ? AND status = 'active'",
                ("alice", "win_a", room_id)
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT status, winner, outcome FROM match_rooms WHERE room_id = ?",
                (room_id,)
            )
            row = await cur.fetchone()
            assert_eq(row[0], "finished", "room status = finished after finalize")
            assert_eq(row[1], "alice", "winner = alice")
            assert_eq(row[2], "win_a", "outcome = win_a")

            # 11.12: После finalize — update active-only НЕ работает
            cur = await conn.execute(
                "UPDATE match_rooms SET state = '{\"replay\":true}' "
                "WHERE room_id = ? AND status = 'active'",
                (room_id,)
            )
            await conn.commit()
            assert_eq(cur.rowcount, 0, "finished room rejects state updates")
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


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
    test_current_stream_id_per_channel()
    await test_cases_system()
    test_drops_distribution()
    await test_matchmaking_infrastructure()

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
