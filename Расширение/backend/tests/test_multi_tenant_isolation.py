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

# Windows console (cp1251) не умеет emoji — переключаем stdout/stderr на UTF-8.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

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
# Подавляем warning-emoji в dependencies.py при импорте (см. test_eventsub.py).
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")


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
    from config import CHAT_BONUS_PER_CHARS, CHAT_BONUS_MAX
    expected = min(len("Hello chat folks!") // CHAT_BONUS_PER_CHARS, CHAT_BONUS_MAX)
    assert_eq(bonus1, expected, f"bonus = min(len/{CHAT_BONUS_PER_CHARS}, {CHAT_BONUS_MAX}) = {expected}")

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
# Test 12: TicTacToe game logic (Phase 5.1)
# ─────────────────────────────────────────────────────────────────────────────
def test_tictactoe_game_logic():
    """Phase 5.1: проверяет pure game helpers через прямой import.

    Покрывает:
      - WIN_LINES охватывают все 8 winning paths
      - _check_winner detects rows / cols / diagonals для 'a' и 'b'
      - _check_winner возвращает '' если нет winner
      - _is_full корректно работает
      - _elo_update math (K=32, win/loss/draw)
      - _initial_state — empty board, next_turn='a', moves=0
    """
    print("\n[12] TicTacToe game logic (Phase 5.1)")
    from routes.tictactoe import (
        WIN_LINES, _check_winner, _is_full, _elo_update,
        _initial_state, _current_board, ELO_START, ELO_K,
        BOARD_SIZE, CELLS_TOTAL, ROUNDS_MAX,
    )

    # 2026-06-11: тест был захардкожен под 3×3, а игра с Sprint 5.24 — 4×4.
    # Выводим ожидания из BOARD_SIZE → смена размера доски больше не ломает тест.
    N = BOARD_SIZE
    CELLS = CELLS_TOTAL          # N*N
    empty = [""] * CELLS

    # 12.1 WIN_LINES = N рядов + N столбцов + 2 диагонали; каждая длиной N.
    assert_eq(len(WIN_LINES), 2 * N + 2, f"win lines = 2*N+2 (N={N})")
    for line in WIN_LINES:
        assert_eq(len(line), N, f"win line has N={N} cells: {line}")
        for cell in line:
            assert_true(0 <= cell < CELLS, f"cell index in 0..{CELLS - 1}: {cell}")

    # 12.2 _initial_state — это BO3-матч (v2): список досок + счёт раундов,
    # а не одна доска (v1 board/next_turn/moves больше нет на верхнем уровне).
    state = _initial_state()
    assert_eq(state["board_size"], N, f"board_size = {N}")
    assert_eq(state["rounds_total"], ROUNDS_MAX, f"BO{ROUNDS_MAX}")
    assert_eq(state["current_round"], 1, "стартовый раунд = 1")
    assert_eq(state["wins"], {"a": 0, "b": 0}, "счёт раундов 0:0")
    assert_eq(state["phase"], "playing", "фаза = playing")
    assert_eq(len(state["boards"]), 1, "одна доска на старте")

    # 12.2b первая доска матча
    board = _current_board(state)
    assert_eq(board["cells"], empty, f"пустая доска ({CELLS} клеток)")
    assert_eq(board["next_turn"], "a", "первый ход = a")
    assert_eq(board["moves"], 0, "счётчик ходов = 0")
    assert_eq(board["winner"], None, "победителя нет")

    # 12.3 No winner на пустой доске
    assert_eq(_check_winner(empty), "", "empty board → no winner")
    assert_eq(_is_full(empty), False, "empty board not full")

    # 12.4 Row wins — первые N линий
    for row_idx, line in enumerate(WIN_LINES[:N]):
        b = list(empty)
        for cell in line:
            b[cell] = "a"
        assert_eq(_check_winner(b), "a", f"row {row_idx}: a wins on {line}")

    # 12.5 Column wins — следующие N линий
    for col_idx, line in enumerate(WIN_LINES[N:2 * N]):
        b = list(empty)
        for cell in line:
            b[cell] = "b"
        assert_eq(_check_winner(b), "b", f"col {col_idx}: b wins on {line}")

    # 12.6 Diagonal wins — последние 2 линии
    for diag_idx, line in enumerate(WIN_LINES[2 * N:2 * N + 2]):
        b = list(empty)
        for cell in line:
            b[cell] = "a"
        assert_eq(_check_winner(b), "a", f"diag {diag_idx}: a wins on {line}")

    # 12.7 Полная доска без победителя = ничья (сконструирована без N-в-ряд для 4×4)
    if N == 4:
        draw = ["a", "a", "b", "b",
                "b", "b", "a", "a",
                "a", "a", "b", "b",
                "b", "b", "a", "a"]
        assert_eq(_check_winner(draw), "", "full 4x4 mixed: no winner (draw)")
        assert_eq(_is_full(draw), True, "all cells filled → is_full True")

    # 12.8 _elo_update — equal ratings: win = +K/2, loss = -K/2, draw = 0
    half_k = ELO_K // 2
    assert_eq(_elo_update(1100, 1100, 1.0), 1100 + half_k, f"equal ELO + win = +{half_k}")
    assert_eq(_elo_update(1100, 1100, 0.0), 1100 - half_k, f"equal ELO + loss = -{half_k}")
    assert_eq(_elo_update(1100, 1100, 0.5), 1100, "equal ELO + draw = unchanged")

    # 12.9 upset > fair > favorite (направление изменения ELO)
    fair_win = _elo_update(1100, 1100, 1.0) - 1100
    upset = _elo_update(1000, 1400, 1.0) - 1000
    fav = _elo_update(1400, 1000, 1.0) - 1400
    assert_true(upset > fair_win, f"upset win > fair win: {upset} > {fair_win}")
    assert_true(fav < fair_win, f"favorite win < fair win: {fav} < {fair_win}")

    # 12.10 Constants
    assert_eq(ELO_START, 1000, "ELO_START = 1000")
    assert_eq(ELO_K, 32, "ELO_K = 32 (standard)")


# ─────────────────────────────────────────────────────────────────────────────
# Test 13: TicTacToe end-to-end via /move endpoint logic (in-memory БД)
# ─────────────────────────────────────────────────────────────────────────────
async def test_tictactoe_match_flow():
    """Phase 5.1: full match flow через прямое манипулирование state +
    проверка БД transitions. Не дёргает endpoint (требует JWT), но
    воспроизводит SQL что endpoint делает.

    Проверки:
      - State JSON roundtrip
      - Win condition triggers finalize_match
      - Cross-player access denied
      - Turn validation
    """
    print("\n[13] TicTacToe match flow (Phase 5.1)")
    import aiosqlite as _aio
    import json as _json
    import uuid as _uuid

    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        async with _aio.connect(db_path) as conn:
            await conn.execute("CREATE TABLE viewers (channel_id INTEGER, username TEXT, points INTEGER DEFAULT 0, last_seen DATETIME, join_time DATETIME, is_afk INTEGER DEFAULT 0, PRIMARY KEY(channel_id, username))")
            from migrations import m10_matchmaking
            await m10_matchmaking.apply(conn)
            await conn.commit()

            cid = 98319857
            room_id = f"room_tictactoe_{_uuid.uuid4().hex[:12]}"

            # Setup: создаём активную ttt комнату alice vs bob
            await conn.execute(
                "INSERT INTO match_rooms (room_id, channel_id, game_type, player_a, player_b, "
                "player_a_elo, player_b_elo, state, status) "
                "VALUES (?, ?, 'tictactoe', 'alice', 'bob', 1100, 1100, '{}', 'active')",
                (room_id, cid)
            )
            await conn.commit()

            from routes.tictactoe import _check_winner, _initial_state, _current_board

            # 13.1 First move (alice=a). v2: ходы на ТЕКУЩЕЙ доске матча
            # (_current_board), а не на state["board"] — в v1 был один board,
            # сейчас BO3 со списком state["boards"].
            state = _initial_state()
            board = _current_board(state)
            assert_eq(board["next_turn"], "a", "initial turn = a")

            board["cells"][0] = "a"; board["moves"] = 1; board["next_turn"] = "b"
            await conn.execute(
                "UPDATE match_rooms SET state = ? WHERE room_id = ? AND status = 'active'",
                (_json.dumps(state), room_id)
            )
            await conn.commit()
            assert_eq(_check_winner(board["cells"]), "", "no winner yet (1 move)")

            # 13.2-13.5 alice выигрывает row 0 (на 4x4 нужно 4-в-ряд: 0,1,2,3);
            # bob ходит в ряд 1 (4,5,6) — без своей линии.
            board["cells"][4] = "b"; board["moves"] = 2; board["next_turn"] = "a"
            board["cells"][1] = "a"; board["moves"] = 3; board["next_turn"] = "b"
            board["cells"][5] = "b"; board["moves"] = 4; board["next_turn"] = "a"
            board["cells"][2] = "a"; board["moves"] = 5; board["next_turn"] = "b"
            board["cells"][6] = "b"; board["moves"] = 6; board["next_turn"] = "a"
            board["cells"][3] = "a"; board["moves"] = 7   # row 0 готов: 0,1,2,3
            winner_role = _check_winner(board["cells"])
            assert_eq(winner_role, "a", "alice wins row 0 (0,1,2,3)")

            # Finalize в БД
            await conn.execute(
                "UPDATE match_rooms SET state = ?, status = 'finished', "
                "winner = 'alice', outcome = 'win_a', player_a_elo = 1116, player_b_elo = 1084, "
                "finished_at = CURRENT_TIMESTAMP WHERE room_id = ? AND status = 'active'",
                (_json.dumps(state), room_id)
            )
            await conn.commit()

            # Verify
            cur = await conn.execute(
                "SELECT status, winner, outcome, player_a_elo, player_b_elo FROM match_rooms WHERE room_id = ?",
                (room_id,)
            )
            row = await cur.fetchone()
            assert_eq(row[0], "finished", "room status finished")
            assert_eq(row[1], "alice", "winner = alice")
            assert_eq(row[2], "win_a", "outcome = win_a")
            assert_eq(row[3], 1116, "alice ELO updated")
            assert_eq(row[4], 1084, "bob ELO updated")

            # 13.6 Cross-player access: charlie не должен видеть комнату как player
            cur = await conn.execute(
                "SELECT room_id FROM match_rooms WHERE room_id = ? AND "
                "(player_a = 'charlie' OR player_b = 'charlie')",
                (room_id,)
            )
            row = await cur.fetchone()
            assert_true(row is None, "charlie has no access to alice-vs-bob room")

            # 13.7 После finalize — другой move attempt должен fail (status != active)
            cur = await conn.execute(
                "UPDATE match_rooms SET state = '{\"hack\":true}' "
                "WHERE room_id = ? AND status = 'active'",
                (room_id,)
            )
            await conn.commit()
            assert_eq(cur.rowcount, 0, "finished room rejects post-game moves")

            # 13.8 Sезонная статистика после match: duel_stats записи созданы
            # (в реальном flow это делает /move endpoint после finalize)
            await conn.execute(
                "INSERT INTO duel_stats (channel_id, username, game_type, elo, win_streak, season_id) "
                "VALUES (?, 'alice', 'tictactoe', 1116, 1, 1)",
                (cid,)
            )
            await conn.execute(
                "INSERT INTO duel_stats (channel_id, username, game_type, elo, win_streak, season_id) "
                "VALUES (?, 'bob', 'tictactoe', 1084, 0, 1)",
                (cid,)
            )
            await conn.commit()

            # Leaderboard: alice выше bob
            cur = await conn.execute(
                "SELECT username, elo FROM duel_stats "
                "WHERE channel_id = ? AND game_type = 'tictactoe' ORDER BY elo DESC",
                (cid,)
            )
            rows = await cur.fetchall()
            assert_eq(rows[0][0], "alice", "alice top of tictactoe leaderboard")
            assert_eq(rows[0][1], 1116, "alice ELO = 1116")
            assert_eq(rows[1][0], "bob", "bob second")
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 14: Dice game logic (Phase 5.2) — pure helpers + lexicon scrub
# ─────────────────────────────────────────────────────────────────────────────
def test_dice_game_logic():
    """Sprint 5.24a v2: dice pure helpers (3-round / reroll model) + lexicon scrub.

    Покрывает:
      - _roll_2d6 / _roll_d6 диапазоны
      - _new_dice_state: v2 schema (version=2, 3 раунда, phase=rolling)
      - _player_has_initial / _player_has_decided
      - _compute_phase: rolling → deciding → advancing
      - _recompute_totals: сумма final-кубиков по сыгранным раундам
      - _resolve_pvp_winner: a/b/draw по totals (заменил старый _resolve_winner)
      - _elo_update K=32
      - Constants: GAME_TYPE / ELO_START=1000 / ELO_K / ROUNDS_TOTAL
      - Lexicon scrub: dice.js НЕ содержит casino/jackpot/lucky/bet
    """
    print("\n[14] Dice v2 game logic + lexicon scrub (Sprint 5.24a)")
    from routes.dice import (
        _roll_2d6, _roll_d6, _new_dice_state,
        _player_has_initial, _player_has_decided,
        _compute_phase, _recompute_totals, _resolve_pvp_winner, _elo_update,
        ELO_START, ELO_K, GAME_TYPE, ROUNDS_TOTAL,
    )

    # helper: собрать стейт из готовых раундов (keep-решения, final = initial)
    def _mk_state(a_rounds, b_rounds):
        s = _new_dice_state()
        for dice in a_rounds:
            s["rolls"]["a"].append({"initial": dice, "final": dice, "reroll_index": None})
        for dice in b_rounds:
            s["rolls"]["b"].append({"initial": dice, "final": dice, "reroll_index": None})
        _recompute_totals(s)
        return s

    # 14.1 Roll structure: 2 кубика 1..6 + одиночный d6
    for _ in range(200):
        roll = _roll_2d6()
        assert_eq(len(roll), 2, "roll имеет 2 кубика")
        for d in roll:
            assert_true(1 <= d <= 6, f"кубик в 1..6: {d}")
        assert_true(1 <= _roll_d6() <= 6, "_roll_d6 в 1..6")

    # 14.2 Sum range 2..12
    for _ in range(200):
        assert_true(2 <= sum(_roll_2d6()) <= 12, "sum в 2..12")

    # 14.3 Fresh state — v2 schema
    st = _new_dice_state()
    assert_eq(st["version"], 2, "state version = 2")
    assert_eq(st["rounds_total"], ROUNDS_TOTAL, "rounds_total = 3")
    assert_eq(st["current_round"], 1, "current_round = 1 (1-indexed)")
    assert_eq(st["rolls"], {"a": [], "b": []}, "rolls пустые на старте")
    assert_eq(st["phase"], "rolling", "стартовая фаза = rolling")
    assert_eq(_compute_phase(st), "rolling", "compute_phase пустого = rolling")

    # 14.4 Phase machine на раунде 0: rolling → deciding → advancing
    st["rolls"]["a"].append({"initial": [6, 5], "final": None, "reroll_index": None})
    assert_true(_player_has_initial(st, "a", 0), "a has initial")
    assert_true(not _player_has_initial(st, "b", 0), "b не has initial")
    assert_eq(_compute_phase(st), "rolling", "один бросил → всё ещё rolling (ждём b)")
    st["rolls"]["b"].append({"initial": [3, 3], "final": None, "reroll_index": None})
    assert_eq(_compute_phase(st), "deciding", "оба бросили, никто не решил → deciding")
    assert_true(not _player_has_decided(st, "a", 0), "a ещё не decided (final=None)")
    st["rolls"]["a"][0]["final"] = [6, 5]
    st["rolls"]["b"][0]["final"] = [3, 3]
    assert_true(_player_has_decided(st, "a", 0), "a decided (final выставлен)")
    assert_eq(_compute_phase(st), "advancing", "оба decided → advancing")

    # 14.5 _recompute_totals + _resolve_pvp_winner (заменил _resolve_winner)
    s_a = _mk_state([[6, 6], [5, 5], [4, 4]], [[1, 1], [2, 2], [3, 3]])   # 30 vs 12
    assert_eq(s_a["totals"]["a"], 30, "totals.a = 30 (12+10+8)")
    assert_eq(s_a["totals"]["b"], 12, "totals.b = 12 (2+4+6)")
    assert_eq(_resolve_pvp_winner(s_a), "a", "30 > 12 → a")

    s_b = _mk_state([[1, 1], [1, 2], [2, 2]], [[6, 6], [5, 5], [4, 4]])   # 9 vs 30
    assert_eq(_resolve_pvp_winner(s_b), "b", "9 < 30 → b")

    s_d = _mk_state([[3, 4], [2, 2], [6, 1]], [[5, 2], [3, 1], [3, 4]])   # 18 vs 18
    assert_eq(s_d["totals"]["a"], 18, "totals.a = 18 (draw)")
    assert_eq(s_d["totals"]["b"], 18, "totals.b = 18 (draw)")
    assert_eq(_resolve_pvp_winner(s_d), "draw", "18 == 18 → draw")

    # 14.5b Partial totals: только final-кубики считаются (final=None пропускается)
    s_p = _new_dice_state()
    s_p["rolls"]["a"].append({"initial": [6, 6], "final": [6, 6], "reroll_index": None})
    s_p["rolls"]["b"].append({"initial": [2, 2], "final": None, "reroll_index": None})
    _recompute_totals(s_p)
    assert_eq(s_p["totals"]["a"], 12, "partial: a final учтён")
    assert_eq(s_p["totals"]["b"], 0, "partial: b final=None не учтён")

    # 14.6 _elo_update (same K=32, базовое ELO 1000)
    assert_eq(_elo_update(1000, 1000, 1.0), 1016, "equal win = +16")
    assert_eq(_elo_update(1000, 1000, 0.0), 984, "equal loss = -16")
    assert_eq(_elo_update(1000, 1000, 0.5), 1000, "equal draw = unchanged")

    # 14.7 Constants
    assert_eq(GAME_TYPE, "dice", "GAME_TYPE = 'dice'")
    assert_eq(ELO_START, 1000, "ELO_START = 1000 (Sprint 5.24)")
    assert_eq(ELO_K, 32, "ELO_K = 32")
    assert_eq(ROUNDS_TOTAL, 3, "ROUNDS_TOTAL = 3")

    # 14.8 LEXICON SCRUB: dice.js НЕ содержит запрещённых слов
    import os.path
    # __file__ = .../Расширение/backend/tests/test_multi_tenant_isolation.py
    # tests_dir → backend_dir → extension_dir → frontend/dice.js
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    extension_dir = os.path.dirname(backend_dir)
    dice_js_path = os.path.join(extension_dir, "frontend", "dice.js")
    if os.path.exists(dice_js_path):
        with open(dice_js_path, encoding="utf-8") as f:
            content = f.read().lower()
        forbidden = ['casino', 'jackpot', 'lucky', 'gamble',
                     'высокая ставка', 'крутка', 'спин',
                     'высокий ролл', 'high roller']
        for word in forbidden:
            assert_true(word not in content,
                        f"dice.js не содержит '{word}' (compliance lexicon)")
        print(f"  Lexicon scrub: checked {len(forbidden)} forbidden words — clean")
    else:
        print(f"  ⚠️  dice.js не найден по {dice_js_path} — lexicon scrub skipped")


# ─────────────────────────────────────────────────────────────────────────────
# Test 15: Dice match flow (vs bot endpoint + PvP roll logic)
# ─────────────────────────────────────────────────────────────────────────────
async def test_dice_match_flow():
    """Sprint 5.24a v2: full 3-round PvP flow через прямой SQL для match_rooms.

    Проверяет:
      - State JSON v2 roundtrip в БД
      - Wait-state: только один игрок бросил в раунде → phase=rolling
      - 3-раундовый прогон → _resolve_pvp_winner → finalize + ELO
      - Cross-player blocked (charlie не в комнате)
      - Cross-channel isolation (room невидим под чужим channel_id)
    """
    print("\n[15] Dice v2 match flow (Sprint 5.24a)")
    import aiosqlite as _aio
    import json as _json
    import uuid as _uuid
    from routes.dice import (
        _new_dice_state, _recompute_totals, _resolve_pvp_winner,
        _compute_phase, _elo_update,
    )

    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        async with _aio.connect(db_path) as conn:
            await conn.execute("CREATE TABLE viewers (channel_id INTEGER, username TEXT, points INTEGER DEFAULT 0, last_seen DATETIME, join_time DATETIME, is_afk INTEGER DEFAULT 0, PRIMARY KEY(channel_id, username))")
            from migrations import m10_matchmaking
            await m10_matchmaking.apply(conn)
            await conn.commit()

            cid = 98319857
            room_id = f"room_dice_{_uuid.uuid4().hex[:12]}"

            await conn.execute(
                "INSERT INTO match_rooms (room_id, channel_id, game_type, player_a, player_b, "
                "player_a_elo, player_b_elo, state, status) "
                "VALUES (?, ?, 'dice', 'alice', 'bob', 1000, 1000, ?, 'active')",
                (room_id, cid, _json.dumps(_new_dice_state()))
            )
            await conn.commit()

            # 15.1 Раунд 1: только alice бросила — wait state (phase=rolling), v2 roundtrip
            state = _new_dice_state()
            state["rolls"]["a"].append({"initial": [6, 5], "final": None, "reroll_index": None})
            assert_eq(_compute_phase(state), "rolling", "одна бросила → rolling (ждём bob)")
            await conn.execute(
                "UPDATE match_rooms SET state = ? WHERE room_id = ? AND status = 'active'",
                (_json.dumps(state), room_id)
            )
            await conn.commit()

            cur = await conn.execute("SELECT state, status FROM match_rooms WHERE room_id = ?", (room_id,))
            row = await cur.fetchone()
            saved = _json.loads(row[0])
            assert_eq(saved["version"], 2, "state v2 roundtrip через БД")
            assert_eq(saved["rolls"]["a"][0]["initial"], [6, 5], "alice initial [6,5] сохранён")
            assert_eq(len(saved["rolls"]["b"]), 0, "bob ещё не бросил")
            assert_eq(row[1], "active", "status still active (waiting)")

            # 15.2 Полный 3-раундовый прогон (keep на всех), детерминированные кубики.
            # alice 12+10+8=30, bob 2+4+6=12 → alice wins
            full = _new_dice_state()
            for d in [[6, 6], [5, 5], [4, 4]]:
                full["rolls"]["a"].append({"initial": d, "final": d, "reroll_index": None})
            for d in [[1, 1], [2, 2], [3, 3]]:
                full["rolls"]["b"].append({"initial": d, "final": d, "reroll_index": None})
            full["current_round"] = 4   # все 3 сыграны (1-indexed > rounds_total)
            full["phase"] = "finished"
            _recompute_totals(full)
            assert_eq(full["totals"]["a"], 30, "alice total 30")
            assert_eq(full["totals"]["b"], 12, "bob total 12")
            assert_eq(_resolve_pvp_winner(full), "a", "alice 30 > bob 12 → a")

            new_elo_a = _elo_update(1000, 1000, 1.0)
            new_elo_b = _elo_update(1000, 1000, 0.0)
            await conn.execute(
                "UPDATE match_rooms SET state = ?, status = 'finished', "
                "winner = 'alice', outcome = 'win_a', "
                "player_a_elo = ?, player_b_elo = ?, "
                "finished_at = CURRENT_TIMESTAMP WHERE room_id = ? AND status = 'active'",
                (_json.dumps(full), new_elo_a, new_elo_b, room_id)
            )
            await conn.commit()

            cur = await conn.execute(
                "SELECT status, winner, outcome, player_a_elo, player_b_elo FROM match_rooms WHERE room_id = ?",
                (room_id,)
            )
            row = await cur.fetchone()
            assert_eq(row[0], "finished", "room finished после 3 раундов")
            assert_eq(row[1], "alice", "alice winner")
            assert_eq(row[2], "win_a", "outcome win_a")
            assert_eq(row[3], 1016, "alice ELO +16")
            assert_eq(row[4], 984, "bob ELO -16")

            # 15.3 Cross-player access блок: charlie не player
            cur = await conn.execute(
                "SELECT room_id FROM match_rooms WHERE room_id = ? AND "
                "(player_a = 'charlie' OR player_b = 'charlie')",
                (room_id,)
            )
            assert_true((await cur.fetchone()) is None, "charlie blocked from dice room")

            # 15.4 Cross-channel isolation: тот же room_id под другим channel_id не виден
            cur = await conn.execute(
                "SELECT room_id FROM match_rooms WHERE room_id = ? AND channel_id = ?",
                (room_id, cid + 1)
            )
            assert_true((await cur.fetchone()) is None, "room невидим под чужим channel_id")

            # 15.5 Draw scenario через _resolve_pvp_winner (18 vs 18)
            draw = _new_dice_state()
            for d in [[3, 4], [2, 2], [6, 1]]:
                draw["rolls"]["a"].append({"initial": d, "final": d, "reroll_index": None})
            for d in [[5, 2], [3, 1], [3, 4]]:
                draw["rolls"]["b"].append({"initial": d, "final": d, "reroll_index": None})
            _recompute_totals(draw)
            assert_eq(_resolve_pvp_winner(draw), "draw", "18 == 18 → draw")
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 16: Guilds system (Phase 3) — multi-tenant + cost + skills
# ─────────────────────────────────────────────────────────────────────────────
async def test_guilds_system():
    """Phase 3 Guilds: проверяет через raw SQL основные invariants:
      - Cost-списание при create (атомарно)
      - Name UNIQUE per channel (не глобально)
      - Один user = одна guild per channel
      - Multi-tenant: same name on different channels OK
      - Kick: master only, cannot kick self
      - Upgrade skill: master only, balance-check, max_level
      - Disband: master only, soft-delete
    """
    print("\n[16] Guilds system (Phase 3)")
    import aiosqlite as _aio

    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        async with _aio.connect(db_path) as conn:
            # Setup viewers + guilds schemas
            await conn.execute("""
                CREATE TABLE viewers (
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    points INTEGER DEFAULT 0,
                    last_seen DATETIME,
                    join_time DATETIME,
                    is_afk INTEGER DEFAULT 0,
                    PRIMARY KEY(channel_id, username)
                )
            """)
            from migrations import m11_guilds
            await m11_guilds.apply(conn)
            await conn.commit()

            cid_a = 98319857
            cid_b = 99999
            COST = 100_000

            # Seed viewers с балансом для create
            for u in ('alice', 'bob', 'charlie'):
                for cid in (cid_a, cid_b):
                    await conn.execute(
                        "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
                        (cid, u, 200_000)
                    )
            await conn.commit()

            # 16.1 Insufficient funds — попытка create без денег
            await conn.execute("UPDATE viewers SET points = 0 WHERE channel_id = ? AND username = 'alice'", (cid_a,))
            await conn.commit()
            cur = await conn.execute(
                "UPDATE viewers SET points = points - ? "
                "WHERE channel_id = ? AND username = 'alice' AND points >= ?",
                (COST, cid_a, COST)
            )
            assert_eq(cur.rowcount, 0, "insufficient funds: UPDATE rowcount=0 (защита от race)")
            await conn.execute("UPDATE viewers SET points = 200000 WHERE channel_id = ? AND username = 'alice'", (cid_a,))
            await conn.commit()

            # 16.2 Create guild alice на cid_a — должно списать 100k
            await conn.execute(
                "UPDATE viewers SET points = points - ? WHERE channel_id = ? AND username = 'alice'",
                (COST, cid_a)
            )
            cur = await conn.execute(
                "INSERT INTO guilds (channel_id, name, tagline, master_username) "
                "VALUES (?, 'Alpha', 'For glory!', 'alice')",
                (cid_a,)
            )
            guild_alpha_a = cur.lastrowid
            await conn.execute(
                "INSERT INTO guild_members (guild_id, channel_id, username, role) "
                "VALUES (?, ?, 'alice', 'master')",
                (guild_alpha_a, cid_a)
            )
            await conn.commit()
            assert_true(guild_alpha_a > 0, "Alpha guild создан на cid_a")
            cur = await conn.execute("SELECT points FROM viewers WHERE channel_id = ? AND username = 'alice'", (cid_a,))
            assert_eq((await cur.fetchone())[0], 100_000, "alice потеряла 100k (200k → 100k)")

            # 16.3 Name UNIQUE per channel — повтор Alpha на cid_a должен fail
            from aiosqlite import IntegrityError as _IE
            try:
                await conn.execute(
                    "INSERT INTO guilds (channel_id, name, master_username) VALUES (?, 'Alpha', 'bob')",
                    (cid_a,)
                )
                await conn.commit()
                assert_true(False, "duplicate name on same channel should fail")
            except _IE:
                assert_true(True, "duplicate name on same channel rejected")
                await conn.rollback()

            # 16.4 Multi-tenant: same name на cid_b — OK
            cur = await conn.execute(
                "INSERT INTO guilds (channel_id, name, master_username) VALUES (?, 'Alpha', 'bob')",
                (cid_b,)
            )
            guild_alpha_b = cur.lastrowid
            await conn.execute(
                "INSERT INTO guild_members (guild_id, channel_id, username, role) "
                "VALUES (?, ?, 'bob', 'master')",
                (guild_alpha_b, cid_b)
            )
            await conn.commit()
            assert_true(guild_alpha_b > 0, "Alpha на cid_b — OK (multi-tenant)")
            assert_true(guild_alpha_a != guild_alpha_b, "разные guild_id")

            # 16.5 Один user = одна guild per channel — повтор INSERT alice в другую guild
            cur = await conn.execute(
                "INSERT INTO guilds (channel_id, name, master_username) VALUES (?, 'Beta', 'bob')",
                (cid_a,)
            )
            beta_a = cur.lastrowid
            try:
                await conn.execute(
                    "INSERT INTO guild_members (guild_id, channel_id, username, role) "
                    "VALUES (?, ?, 'alice', 'member')",
                    (beta_a, cid_a)
                )
                await conn.commit()
                assert_true(False, "alice second guild membership on same channel should fail (UNIQUE)")
            except _IE:
                assert_true(True, "second guild membership blocked by uq_guild_members_user_per_channel")
                await conn.rollback()

            # 16.6 bob может вступить в Alpha alice — добавим
            await conn.execute(
                "INSERT INTO guild_members (guild_id, channel_id, username, role) "
                "VALUES (?, ?, 'bob', 'member')",
                (guild_alpha_a, cid_a)
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM guild_members WHERE guild_id = ?", (guild_alpha_a,)
            )
            assert_eq((await cur.fetchone())[0], 2, "Alpha теперь 2 members (alice + bob)")

            # 16.7 Contribute: bob кладёт 5k → balance Alpha = 5k, audit запись
            await conn.execute(
                "UPDATE viewers SET points = points - 5000 WHERE channel_id = ? AND username = 'bob'",
                (cid_a,)
            )
            await conn.execute(
                "UPDATE guilds SET balance = balance + 5000 WHERE id = ?",
                (guild_alpha_a,)
            )
            await conn.execute(
                "INSERT INTO guild_contributions (guild_id, channel_id, username, amount) "
                "VALUES (?, ?, 'bob', 5000)",
                (guild_alpha_a, cid_a)
            )
            await conn.commit()
            cur = await conn.execute("SELECT balance FROM guilds WHERE id = ?", (guild_alpha_a,))
            assert_eq((await cur.fetchone())[0], 5000, "Alpha balance = 5000 after bob contrib")

            cur = await conn.execute(
                "SELECT amount FROM guild_contributions WHERE guild_id = ? AND username = 'bob'",
                (guild_alpha_a,)
            )
            assert_eq((await cur.fetchone())[0], 5000, "audit запись 5000 от bob")

            # 16.8 Kick: master может удалить bob (charlie не master — попытка fail)
            # Сначала charlie joins Alpha
            await conn.execute(
                "INSERT INTO guild_members (guild_id, channel_id, username, role) "
                "VALUES (?, ?, 'charlie', 'member')",
                (guild_alpha_a, cid_a)
            )
            await conn.commit()

            # charlie пытается kick bob — fail (он member, не master)
            cur = await conn.execute(
                "SELECT role FROM guild_members WHERE guild_id = ? AND username = 'charlie'",
                (guild_alpha_a,)
            )
            assert_eq((await cur.fetchone())[0], 'member', "charlie role = member")

            # alice (master) kicks bob — OK
            cur = await conn.execute(
                "DELETE FROM guild_members WHERE guild_id = ? AND username = 'bob' AND role != 'master'",
                (guild_alpha_a,)
            )
            await conn.commit()
            assert_eq(cur.rowcount, 1, "bob kicked by master alice")

            # Cannot kick self (master): DELETE WHERE role != 'master' защищает
            cur = await conn.execute(
                "DELETE FROM guild_members WHERE guild_id = ? AND username = 'alice' AND role != 'master'",
                (guild_alpha_a,)
            )
            await conn.commit()
            assert_eq(cur.rowcount, 0, "alice (master) cannot self-kick via this query pattern")

            # 16.9 Upgrade skill: insufficient balance fail; sufficient OK
            # Alpha balance = 5000; первый level extra_member_slots cost = 50_000
            cur = await conn.execute(
                "UPDATE guilds SET balance = balance - 50000 WHERE id = ? AND balance >= 50000",
                (guild_alpha_a,)
            )
            assert_eq(cur.rowcount, 0, "5k balance < 50k cost → 0 rowcount (защита)")

            # Boost balance and retry
            await conn.execute(
                "UPDATE guilds SET balance = balance + 100000 WHERE id = ?",
                (guild_alpha_a,)
            )
            cur = await conn.execute(
                "UPDATE guilds SET balance = balance - 50000 WHERE id = ? AND balance >= 50000",
                (guild_alpha_a,)
            )
            assert_eq(cur.rowcount, 1, "now 105k balance, cost 50k → upgrade OK")

            # Insert skill level 1
            await conn.execute(
                "INSERT INTO guild_skills (guild_id, skill_key, level) VALUES (?, 'extra_member_slots', 1)",
                (guild_alpha_a,)
            )
            await conn.commit()

            cur = await conn.execute(
                "SELECT level FROM guild_skills WHERE guild_id = ? AND skill_key = 'extra_member_slots'",
                (guild_alpha_a,)
            )
            assert_eq((await cur.fetchone())[0], 1, "skill level = 1 after upgrade")

            # 16.10 Disband alpha_a — soft delete
            await conn.execute(
                "UPDATE guilds SET disbanded_at = CURRENT_TIMESTAMP WHERE id = ?",
                (guild_alpha_a,)
            )
            await conn.execute("DELETE FROM guild_members WHERE guild_id = ?", (guild_alpha_a,))
            await conn.commit()

            cur = await conn.execute("SELECT disbanded_at FROM guilds WHERE id = ?", (guild_alpha_a,))
            assert_true((await cur.fetchone())[0] is not None, "disbanded_at set")

            cur = await conn.execute("SELECT COUNT(*) FROM guild_members WHERE guild_id = ?", (guild_alpha_a,))
            assert_eq((await cur.fetchone())[0], 0, "all members purged after disband")

            # 16.11 После disband — name «Alpha» снова доступно на cid_a (partial UNIQUE active only)
            cur = await conn.execute(
                "INSERT INTO guilds (channel_id, name, master_username) VALUES (?, 'Alpha', 'charlie')",
                (cid_a,)
            )
            new_alpha = cur.lastrowid
            await conn.commit()
            assert_true(new_alpha != guild_alpha_a, "новая Alpha на cid_a — другой id")
            assert_true(new_alpha is not None, "name 'Alpha' переиспользуется после disband")

            # 16.12 Cross-channel boundary: alpha_b на cid_b НЕ виден из cid_a context
            cur = await conn.execute(
                "SELECT id FROM guilds WHERE channel_id = ? AND name = 'Alpha' AND disbanded_at IS NULL",
                (cid_a,)
            )
            row = await cur.fetchone()
            assert_true(row is not None and row[0] == new_alpha, "cid_a sees only its own Alpha")
            assert_true(row[0] != guild_alpha_b, "cid_b's Alpha не виден через WHERE channel_id=cid_a")
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 17: Voting events system (Phase 4)
# ─────────────────────────────────────────────────────────────────────────────
async def test_voting_system():
    """Phase 4 Voting: проверяет основные invariants через raw SQL.

    Severity-grouped (per code-review-excellence skill):
      BLOCKING (correctness):
        - Atomic bid: списание + pool incr + audit в одной TX
        - Active event UNIQUE per channel (uq_voting_events_active)
        - Default template UNIQUE per channel (uq_voting_templates_default)
      IMPORTANT (multi-tenant):
        - Bid не проходит между каналами
        - Pool counter per-channel независимы
      MINOR (logic):
        - Finalize выбирает max-pool option
        - Empty event (no bids) → cancelled, not finished
    """
    print("\n[17] Voting events (Phase 4)")
    import aiosqlite as _aio
    import json as _json
    from datetime import datetime as _dt, timedelta as _td

    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        async with _aio.connect(db_path) as conn:
            await conn.execute("""
                CREATE TABLE viewers (
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    points INTEGER DEFAULT 0,
                    last_seen DATETIME,
                    join_time DATETIME,
                    is_afk INTEGER DEFAULT 0,
                    PRIMARY KEY(channel_id, username)
                )
            """)
            from migrations import m12_voting
            await m12_voting.apply(conn)
            await conn.commit()

            cid_a = 98319857
            cid_b = 99999

            # Seed viewers
            for u in ('alice', 'bob', 'charlie'):
                for cid in (cid_a, cid_b):
                    await conn.execute(
                        "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
                        (cid, u, 100000)
                    )
            await conn.commit()

            # 17.1 Create template на cid_a, is_default=True
            template_a_opts = [
                {"key": "rimworld", "label": "RimWorld", "description": "Колония"},
                {"key": "bannerlord", "label": "Bannerlord", "description": "Битвы"},
            ]
            cur = await conn.execute(
                "INSERT INTO streamer_voting_templates (channel_id, name, options_json, is_default) "
                "VALUES (?, ?, ?, 1)",
                (cid_a, "Что играть?", _json.dumps(template_a_opts))
            )
            tpl_a = cur.lastrowid
            await conn.commit()
            assert_true(tpl_a > 0, "template на cid_a создан с is_default=1")

            # 17.2 Default UNIQUE per channel — повторный is_default=1 → fail
            from aiosqlite import IntegrityError as _IE
            try:
                await conn.execute(
                    "INSERT INTO streamer_voting_templates (channel_id, name, options_json, is_default) "
                    "VALUES (?, ?, ?, 1)",
                    (cid_a, "Alt", _json.dumps(template_a_opts))
                )
                await conn.commit()
                assert_true(False, "second default template should fail")
            except _IE:
                assert_true(True, "second default template blocked by uq_voting_templates_default")
                await conn.rollback()

            # 17.3 Multi-tenant: default на другом канале — OK
            await conn.execute(
                "INSERT INTO streamer_voting_templates (channel_id, name, options_json, is_default) "
                "VALUES (?, ?, ?, 1)",
                (cid_b, "B default", _json.dumps(template_a_opts))
            )
            await conn.commit()
            assert_true(True, "default template на cid_b — independent")

            # 17.4 Start event для cid_a + snapshot options
            ends_at = (_dt.utcnow() + _td(seconds=300)).isoformat()
            cur = await conn.execute(
                "INSERT INTO voting_events "
                "(channel_id, template_id, template_name, ends_at, status) "
                "VALUES (?, ?, 'Что играть?', ?, 'active')",
                (cid_a, tpl_a, ends_at)
            )
            event_a = cur.lastrowid

            for opt in template_a_opts:
                await conn.execute(
                    "INSERT INTO voting_options (event_id, option_key, label, description, pool) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (event_a, opt["key"], opt["label"], opt["description"])
                )
            await conn.commit()
            assert_true(event_a > 0, "voting event на cid_a создан")

            # 17.5 Active event UNIQUE per channel — повторный start → fail
            try:
                await conn.execute(
                    "INSERT INTO voting_events "
                    "(channel_id, template_id, template_name, ends_at, status) "
                    "VALUES (?, ?, 'X', ?, 'active')",
                    (cid_a, tpl_a, ends_at)
                )
                await conn.commit()
                assert_true(False, "second active event on same channel should fail")
            except _IE:
                assert_true(True, "second active event blocked by uq_voting_events_active_per_channel")
                await conn.rollback()

            # 17.6 Multi-tenant: active event на cid_b — OK
            cur = await conn.execute(
                "INSERT INTO voting_events "
                "(channel_id, template_id, template_name, ends_at, status) "
                "VALUES (?, ?, 'B event', ?, 'active')",
                (cid_b, None, ends_at)
            )
            event_b = cur.lastrowid
            await conn.commit()
            assert_true(event_b != event_a, "event на cid_b — отдельный id")

            # Получаем option_ids на cid_a event
            cur = await conn.execute(
                "SELECT id, option_key FROM voting_options WHERE event_id = ? ORDER BY id",
                (event_a,)
            )
            opt_rows = await cur.fetchall()
            opt_rimworld = opt_rows[0][0]
            opt_bannerlord = opt_rows[1][0]

            # 17.7 Atomic bid: списание + pool incr + audit
            # alice кладёт 500 в RimWorld
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "UPDATE viewers SET points = points - 500 "
                "WHERE channel_id = ? AND username = 'alice' AND points >= 500",
                (cid_a,)
            )
            assert_eq(cur.rowcount, 1, "списание прошло")
            await conn.execute(
                "UPDATE voting_options SET pool = pool + 500 WHERE id = ?",
                (opt_rimworld,)
            )
            await conn.execute(
                "UPDATE voting_events SET total_pool = total_pool + 500 WHERE id = ?",
                (event_a,)
            )
            await conn.execute(
                "INSERT INTO voting_bids (event_id, option_id, channel_id, username, amount) "
                "VALUES (?, ?, ?, 'alice', 500)",
                (event_a, opt_rimworld, cid_a)
            )
            await conn.commit()

            cur = await conn.execute(
                "SELECT pool FROM voting_options WHERE id = ?", (opt_rimworld,)
            )
            assert_eq((await cur.fetchone())[0], 500, "RimWorld pool = 500 after alice bid")
            cur = await conn.execute("SELECT total_pool FROM voting_events WHERE id = ?", (event_a,))
            assert_eq((await cur.fetchone())[0], 500, "event total_pool = 500")

            # 17.8 bob кладёт 1000 в Bannerlord → Bannerlord wins
            await conn.execute(
                "UPDATE viewers SET points = points - 1000 WHERE channel_id = ? AND username = 'bob'",
                (cid_a,)
            )
            await conn.execute(
                "UPDATE voting_options SET pool = pool + 1000 WHERE id = ?",
                (opt_bannerlord,)
            )
            await conn.execute(
                "UPDATE voting_events SET total_pool = total_pool + 1000 WHERE id = ?",
                (event_a,)
            )
            await conn.execute(
                "INSERT INTO voting_bids (event_id, option_id, channel_id, username, amount) "
                "VALUES (?, ?, ?, 'bob', 1000)",
                (event_a, opt_bannerlord, cid_a)
            )
            await conn.commit()

            # 17.9 Finalize: max-pool option wins
            cur = await conn.execute(
                "SELECT id, option_key, label, pool FROM voting_options "
                "WHERE event_id = ? ORDER BY pool DESC, id LIMIT 1",
                (event_a,)
            )
            winner = await cur.fetchone()
            assert_eq(winner[1], "bannerlord", "Bannerlord wins (1000 > 500)")
            assert_eq(winner[3], 1000, "winner pool = 1000")

            await conn.execute(
                "UPDATE voting_events SET status = 'finished', winning_option_id = ?, "
                "winning_option_key = ?, winning_option_label = ? WHERE id = ?",
                (winner[0], winner[1], winner[2], event_a)
            )
            await conn.commit()

            cur = await conn.execute("SELECT status FROM voting_events WHERE id = ?", (event_a,))
            assert_eq((await cur.fetchone())[0], "finished", "event a status finished")

            # 17.10 После finalize — новый active event на cid_a возможен
            new_ends = (_dt.utcnow() + _td(seconds=300)).isoformat()
            cur = await conn.execute(
                "INSERT INTO voting_events "
                "(channel_id, template_name, ends_at, status) VALUES (?, 'Next', ?, 'active')",
                (cid_a, new_ends)
            )
            await conn.commit()
            assert_true(cur.lastrowid > event_a, "new active event after finalize — OK")

            # 17.11 Empty event scenario (no bids): finalize → 'cancelled'
            # event_b на cid_b ещё active, total_pool = 0. Finalize:
            await conn.execute(
                "UPDATE voting_events SET status = 'cancelled' WHERE id = ? AND total_pool = 0",
                (event_b,)
            )
            await conn.commit()
            cur = await conn.execute("SELECT status FROM voting_events WHERE id = ?", (event_b,))
            assert_eq((await cur.fetchone())[0], "cancelled", "empty event → cancelled, not finished")

            # 17.12 Pool counter per-channel независимы
            await conn.execute(
                "INSERT INTO voting_pool_counters (channel_id, pool_units) VALUES (?, 500)",
                (cid_a,)
            )
            await conn.execute(
                "INSERT INTO voting_pool_counters (channel_id, pool_units) VALUES (?, 100)",
                (cid_b,)
            )
            await conn.commit()
            cur = await conn.execute("SELECT pool_units FROM voting_pool_counters WHERE channel_id = ?", (cid_a,))
            assert_eq((await cur.fetchone())[0], 500, "cid_a pool = 500")
            cur = await conn.execute("SELECT pool_units FROM voting_pool_counters WHERE channel_id = ?", (cid_b,))
            assert_eq((await cur.fetchone())[0], 100, "cid_b pool = 100 (independent)")

            # 17.13 Cross-channel boundary: bid с cid_a не должен попасть в event cid_b
            cur = await conn.execute(
                "SELECT id FROM voting_events WHERE id = ? AND channel_id = ?",
                (event_a, cid_b)  # ищем event_a на чужом канале
            )
            row = await cur.fetchone()
            assert_true(row is None, "cross-channel event lookup blocked")
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 18: Pets system (Phase 7) — CROSS-CHANNEL (explicit invariant exception)
# ─────────────────────────────────────────────────────────────────────────────
async def test_pets_system():
    """Phase 7 Pets: проверяет cross-channel persistence + channel-scoped settings.

    EXPLICIT INVARIANT EXCEPTION: pets, pet_inventory, pet_equipped — global
    per user (без channel_id в PK). Этот тест — guard rail: чтобы случайно
    не вернули channel_id в PK и не сломали cross-channel UX.

    Severity-grouped (per code-review-excellence skill):
      BLOCKING (correctness):
        - pet purchased на cid_a → owned также на cid_b (global)
        - already_owned guard работает (нельзя купить дважды)
        - bits_receipt UNIQUE — один и тот же чек не применить дважды
      IMPORTANT (multi-tenant):
        - pet_purchases.channel_id хранится правильно (revenue attribution §7.5)
        - channel_pet_settings per-channel независимы (А выключил — Б не задет)
      MINOR (logic):
        - equip slot — replace, не дублировать
        - unequip удаляет slot row
        - catalog deprecate скрывает item из active-list
    """
    print("\n[18] Pets system (Phase 7) — CROSS-CHANNEL invariant")
    import aiosqlite as _aio

    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        async with _aio.connect(db_path) as conn:
            from migrations import m13_pets
            await m13_pets.apply(conn)
            await conn.commit()

            cid_a = 98319857
            cid_b = 99999
            user = 'alice'

            # 18.1 Catalog seeded (M13 PETS_CATALOG_SEED — 5 items)
            cur = await conn.execute("SELECT COUNT(*) FROM pet_catalog WHERE deprecated = 0")
            (cnt,) = await cur.fetchone()
            assert_true(cnt >= 5, f"catalog seeded ({cnt} active items)")

            # 18.2 BLOCKING: pets.username is PK без channel_id (cross-channel by design)
            cur = await conn.execute("PRAGMA table_info(pets)")
            cols = await cur.fetchall()
            pk_cols = [c[1] for c in cols if c[5] == 1]  # c[5] = pk flag
            assert_eq(pk_cols, ['username'], "pets PK = (username,) без channel_id [CROSS-CHANNEL]")

            cur = await conn.execute("PRAGMA table_info(pet_inventory)")
            cols = await cur.fetchall()
            pk_cols = [c[1] for c in cols if c[5] > 0]
            assert_true(
                set(pk_cols) == {'username', 'item_id'},
                "pet_inventory PK = (username, item_id) без channel_id [CROSS-CHANNEL]"
            )

            cur = await conn.execute("PRAGMA table_info(pet_equipped)")
            cols = await cur.fetchall()
            pk_cols = [c[1] for c in cols if c[5] > 0]
            assert_true(
                set(pk_cols) == {'username', 'slot'},
                "pet_equipped PK = (username, slot) без channel_id [CROSS-CHANNEL]"
            )

            # 18.3 Ensure pet (idempotent)
            await conn.execute(
                "INSERT OR IGNORE INTO pets (username, pet_type) VALUES (?, 'egg')",
                (user,)
            )
            await conn.execute(
                "INSERT OR IGNORE INTO pets (username, pet_type) VALUES (?, 'egg')",
                (user,)
            )  # second call no-op
            cur = await conn.execute("SELECT COUNT(*) FROM pets WHERE username = ?", (user,))
            (pcount,) = await cur.fetchone()
            assert_eq(pcount, 1, "pet ensure idempotent (1 row даже после повтора)")

            # 18.4 Purchase на cid_a (audit-row с channel_id для §7.5)
            await conn.execute(
                "INSERT INTO pet_inventory (username, item_id) VALUES (?, 'hat_cap')",
                (user,)
            )
            await conn.execute(
                "INSERT INTO pet_purchases "
                "(username, item_id, channel_id, bits_amount, bits_receipt, mode) "
                "VALUES (?, 'hat_cap', ?, 300, 'receipt-A1', 'bits')",
                (user, cid_a)
            )
            await conn.commit()

            # 18.5 BLOCKING: owned виден на cid_b (cross-channel)
            cur = await conn.execute(
                "SELECT COUNT(*) FROM pet_inventory WHERE username = ? AND item_id = 'hat_cap'",
                (user,)
            )
            (ocount,) = await cur.fetchone()
            assert_eq(ocount, 1, "[CROSS-CHANNEL] hat_cap owned by alice независимо от канала")

            # 18.6 BLOCKING: already_owned — повторный INSERT в inventory падает (PK)
            from aiosqlite import IntegrityError as _IE
            try:
                await conn.execute(
                    "INSERT INTO pet_inventory (username, item_id) VALUES (?, 'hat_cap')",
                    (user,)
                )
                await conn.commit()
                assert_true(False, "повторный INSERT должен fail")
            except _IE:
                assert_true(True, "already_owned guard работает (PK constraint)")
                await conn.rollback()

            # 18.7 BLOCKING: bits_receipt UNIQUE — один receipt дважды не применить
            try:
                await conn.execute(
                    "INSERT INTO pet_purchases "
                    "(username, item_id, channel_id, bits_amount, bits_receipt, mode) "
                    "VALUES (?, 'hat_crown', ?, 800, 'receipt-A1', 'bits')",
                    (user, cid_b)
                )
                await conn.commit()
                assert_true(False, "дубль receipt должен fail")
            except _IE:
                assert_true(True, "bits_receipt UNIQUE — дубль чека отбит")
                await conn.rollback()

            # 18.8 IMPORTANT: pet_purchases.channel_id хранит правильный канал (§7.5)
            cur = await conn.execute(
                "SELECT channel_id FROM pet_purchases WHERE bits_receipt = 'receipt-A1'"
            )
            (saved_cid,) = await cur.fetchone()
            assert_eq(saved_cid, cid_a, "pet_purchases.channel_id = cid_a (revenue attribution)")

            # 18.9 Покупка с другого канала идёт под cid_b
            await conn.execute(
                "INSERT INTO pet_inventory (username, item_id) VALUES (?, 'hat_crown')",
                (user,)
            )
            await conn.execute(
                "INSERT INTO pet_purchases "
                "(username, item_id, channel_id, bits_amount, bits_receipt, mode) "
                "VALUES (?, 'hat_crown', ?, 800, 'receipt-B1', 'bits')",
                (user, cid_b)
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM pet_purchases WHERE username = ? AND channel_id = ?",
                (user, cid_b)
            )
            (bcount,) = await cur.fetchone()
            assert_eq(bcount, 1, "pet_purchases — отдельная audit row под cid_b")

            cur = await conn.execute(
                "SELECT COUNT(DISTINCT channel_id) FROM pet_purchases WHERE username = ?",
                (user,)
            )
            (distinct_cid,) = await cur.fetchone()
            assert_eq(distinct_cid, 2, "audit-trail видит обе покупки (cid_a + cid_b)")

            # 18.10 MINOR: equip — один slot, один item per user. Replace при повторе.
            await conn.execute(
                "INSERT INTO pet_equipped (username, slot, item_id) VALUES (?, 'head', 'hat_cap')",
                (user,)
            )
            # equip другой head item — должен replace
            await conn.execute(
                "INSERT OR REPLACE INTO pet_equipped (username, slot, item_id) "
                "VALUES (?, 'head', 'hat_crown')",
                (user,)
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT item_id FROM pet_equipped WHERE username = ? AND slot = 'head'",
                (user,)
            )
            (eq_item,) = await cur.fetchone()
            assert_eq(eq_item, 'hat_crown', "equip replace: head=hat_crown (один slot)")

            # 18.11 unequip — DELETE row
            await conn.execute(
                "DELETE FROM pet_equipped WHERE username = ? AND slot = 'head'",
                (user,)
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM pet_equipped WHERE username = ? AND slot = 'head'",
                (user,)
            )
            (uqcount,) = await cur.fetchone()
            assert_eq(uqcount, 0, "unequip: row удалён из pet_equipped")

            # 18.12 IMPORTANT: channel_pet_settings per-channel независимы
            await conn.execute(
                "INSERT INTO channel_pet_settings (channel_id, overlay_enabled) VALUES (?, 0)",
                (cid_a,)
            )
            await conn.execute(
                "INSERT INTO channel_pet_settings (channel_id, overlay_enabled) VALUES (?, 1)",
                (cid_b,)
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT overlay_enabled FROM channel_pet_settings WHERE channel_id = ?",
                (cid_a,)
            )
            (a_setting,) = await cur.fetchone()
            cur = await conn.execute(
                "SELECT overlay_enabled FROM channel_pet_settings WHERE channel_id = ?",
                (cid_b,)
            )
            (b_setting,) = await cur.fetchone()
            assert_eq(a_setting, 0, "cid_a overlay выключен (independent)")
            assert_eq(b_setting, 1, "cid_b overlay включён (independent)")

            # 18.13 MINOR: catalog deprecate скрывает item из active list
            await conn.execute("UPDATE pet_catalog SET deprecated = 1 WHERE item_id = 'hat_cap'")
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM pet_catalog WHERE deprecated = 0 AND item_id = 'hat_cap'"
            )
            (active,) = await cur.fetchone()
            assert_eq(active, 0, "deprecated item исчез из active-list (но row остался)")

            # И при этом owned-row не сломалась (FK на item_id):
            cur = await conn.execute(
                "SELECT COUNT(*) FROM pet_inventory WHERE username = ? AND item_id = 'hat_cap'",
                (user,)
            )
            (still_owned,) = await cur.fetchone()
            assert_eq(still_owned, 1, "deprecated item остался в inventory (FK не сломан)")

            # 18.14 Sanity: name setter (last write wins, может быть None)
            await conn.execute("UPDATE pets SET name = 'Гриша' WHERE username = ?", (user,))
            await conn.commit()
            cur = await conn.execute("SELECT name FROM pets WHERE username = ?", (user,))
            (nm,) = await cur.fetchone()
            assert_eq(nm, 'Гриша', "pet.name стал 'Гриша'")

            await conn.execute("UPDATE pets SET name = NULL WHERE username = ?", (user,))
            await conn.commit()
            cur = await conn.execute("SELECT name FROM pets WHERE username = ?", (user,))
            (nm2,) = await cur.fetchone()
            assert_eq(nm2, None, "pet.name можно сбросить в NULL")

            # 18.15 Hatch logic (Phase 8.B.2): первая покупка → egg → hatched.
            # Fresh user (bob) — у alice состояние уже сложное.
            bob = 'bob_hatch'
            await conn.execute(
                "INSERT INTO pets (username, pet_type) VALUES (?, 'egg')",
                (bob,)
            )
            await conn.commit()
            cur = await conn.execute("SELECT pet_type FROM pets WHERE username = ?", (bob,))
            (start_type,) = await cur.fetchone()
            assert_eq(start_type, 'egg', "bob_hatch стартует как egg")

            # Симулируем purchase_pet_item TX: count inventory BEFORE INSERT
            cur = await conn.execute(
                "SELECT COUNT(*) FROM pet_inventory WHERE username = ?", (bob,)
            )
            (before,) = await cur.fetchone()
            is_first = (before == 0)
            assert_true(is_first, "первая покупка флаг = True (inventory empty)")

            await conn.execute(
                "INSERT INTO pet_inventory (username, item_id) VALUES (?, 'acc_glasses')",
                (bob,)
            )
            # Hatch only если pet_type='egg'
            cur = await conn.execute(
                "UPDATE pets SET pet_type = 'hatched' WHERE username = ? AND pet_type = 'egg'",
                (bob,)
            )
            assert_eq(cur.rowcount, 1, "egg → hatched (1 row updated)")
            await conn.commit()

            cur = await conn.execute("SELECT pet_type FROM pets WHERE username = ?", (bob,))
            (new_type,) = await cur.fetchone()
            assert_eq(new_type, 'hatched', "bob_hatch теперь в state hatched")

            # 18.16 Hatch idempotent: вторая покупка НЕ должна сменить state
            cur = await conn.execute(
                "SELECT COUNT(*) FROM pet_inventory WHERE username = ?", (bob,)
            )
            (before2,) = await cur.fetchone()
            is_first2 = (before2 == 0)
            assert_true(not is_first2, "вторая покупка флаг = False (inventory > 0)")

            await conn.execute(
                "INSERT INTO pet_inventory (username, item_id) VALUES (?, 'acc_scarf')",
                (bob,)
            )
            # UPDATE с WHERE pet_type='egg' — должен 0 rows (bob уже hatched)
            cur = await conn.execute(
                "UPDATE pets SET pet_type = 'hatched' WHERE username = ? AND pet_type = 'egg'",
                (bob,)
            )
            assert_eq(cur.rowcount, 0, "hatch UPDATE idempotent (no rows changed на 2-й покупке)")
            await conn.commit()

    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 19: Bannerlord module (Sprint 1.4) — TENANT-scoped (channel_id в PK)
# ─────────────────────────────────────────────────────────────────────────────
async def test_bannerlord_system():
    """Sprint 1 Bannerlord: проверяет multi-tenant isolation 5 таблиц M14.

    Severity-grouped:
      BLOCKING (correctness):
        - heroes / skills / attributes / equipment scoped per channel_id
        - hero_id UNIQUE per (channel_id, hero_id) — нельзя одного NPC
          adopt'ить дважды на одном канале
        - cascade unlink: удаление hero сметает skills/attrs/equipment
      IMPORTANT (multi-tenant):
        - viewer @alice имеет разных heroes на cid_a vs cid_b
        - events_log изолированы per channel
      MINOR (logic):
        - is_alive=0 для dead hero, last_sync обновляется
        - equipment unequip удаляет row
        - skills upsert (level=N на повторный insert обновляет)
    """
    print("\n[19] Bannerlord system (Sprint 1) — TENANT-scoped")
    import aiosqlite as _aio

    db_path = tempfile.mktemp(suffix="_test.db")
    try:
        async with _aio.connect(db_path) as conn:
            from migrations import m14_bannerlord
            await m14_bannerlord.apply(conn)
            await conn.commit()

            cid_a = 98319857
            cid_b = 99999
            user = 'alice'

            # 19.1 Verify все 5 таблиц созданы
            cur = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'bannerlord_%' ORDER BY name"
            )
            tables = [r[0] for r in await cur.fetchall()]
            assert_eq(
                tables,
                ['bannerlord_attributes', 'bannerlord_equipment',
                 'bannerlord_events_log', 'bannerlord_heroes',
                 'bannerlord_skills'],
                "M14: 5 bannerlord_* таблиц созданы"
            )

            # 19.2 BLOCKING: heroes PK = (channel_id, username) — TENANT scope
            cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
            cols = await cur.fetchall()
            pk_cols = sorted([c[1] for c in cols if c[5] > 0])
            assert_eq(pk_cols, ['channel_id', 'username'],
                      "bannerlord_heroes PK = (channel_id, username) [TENANT]")

            # 19.3 Same viewer — разные heroes per channel (multi-tenant)
            await conn.execute(
                "INSERT INTO bannerlord_heroes "
                "(channel_id, username, hero_id, display_name, culture) "
                "VALUES (?, ?, 'hero_A1', 'Alice on A', 'vlandian')",
                (cid_a, user))
            await conn.execute(
                "INSERT INTO bannerlord_heroes "
                "(channel_id, username, hero_id, display_name, culture) "
                "VALUES (?, ?, 'hero_B1', 'Alice on B', 'aserai')",
                (cid_b, user))
            await conn.commit()

            cur = await conn.execute(
                "SELECT hero_id, culture FROM bannerlord_heroes "
                "WHERE channel_id=? AND username=?", (cid_a, user))
            row = await cur.fetchone()
            assert_eq(row, ('hero_A1', 'vlandian'), "alice@cid_a → hero_A1/vlandian")

            cur = await conn.execute(
                "SELECT hero_id, culture FROM bannerlord_heroes "
                "WHERE channel_id=? AND username=?", (cid_b, user))
            row = await cur.fetchone()
            assert_eq(row, ('hero_B1', 'aserai'), "alice@cid_b → hero_B1/aserai (isolated)")

            # 19.4 BLOCKING: hero_id UNIQUE per channel (uq_bannerlord_heroes_hero_id)
            from aiosqlite import IntegrityError as _IE
            try:
                # bob пытается adopt уже adopted hero_A1 на cid_a → fail
                await conn.execute(
                    "INSERT INTO bannerlord_heroes "
                    "(channel_id, username, hero_id, display_name, culture) "
                    "VALUES (?, ?, 'hero_A1', 'Bob', 'empire')",
                    (cid_a, 'bob'))
                await conn.commit()
                assert_true(False, "second adopt того же hero_id должен fail")
            except _IE:
                assert_true(True, "hero_id UNIQUE per channel — duplicate adopt отбит")
                await conn.rollback()

            # 19.5 НО hero_A1 на cid_b — OK (UNIQUE per channel_id)
            await conn.execute(
                "INSERT INTO bannerlord_heroes "
                "(channel_id, username, hero_id, display_name) "
                "VALUES (?, ?, 'hero_A1', 'Charlie')",
                (cid_b, 'charlie'))
            await conn.commit()
            assert_true(True, "hero_A1 reused на cid_b — channels изолированы")

            # 19.6 Skills + Attributes + Equipment per-hero per-channel
            await conn.execute(
                "INSERT INTO bannerlord_skills "
                "(channel_id, username, skill_key, level, xp) "
                "VALUES (?, ?, 'bow', 50, 1200)", (cid_a, user))
            await conn.execute(
                "INSERT INTO bannerlord_skills "
                "(channel_id, username, skill_key, level, xp) "
                "VALUES (?, ?, 'bow', 10, 50)", (cid_b, user))
            await conn.execute(
                "INSERT INTO bannerlord_equipment "
                "(channel_id, username, slot, item_id, item_name) "
                "VALUES (?, ?, 'weapon_0', 'sword_t3', 'Sword of Valor')",
                (cid_a, user))
            await conn.execute(
                "INSERT INTO bannerlord_attributes "
                "(channel_id, username, attribute, value) "
                "VALUES (?, ?, 'vigor', 7)", (cid_a, user))
            await conn.commit()

            cur = await conn.execute(
                "SELECT level FROM bannerlord_skills "
                "WHERE channel_id=? AND username=? AND skill_key='bow'",
                (cid_a, user))
            (lvl_a,) = await cur.fetchone()
            cur = await conn.execute(
                "SELECT level FROM bannerlord_skills "
                "WHERE channel_id=? AND username=? AND skill_key='bow'",
                (cid_b, user))
            (lvl_b,) = await cur.fetchone()
            assert_eq((lvl_a, lvl_b), (50, 10),
                      "alice bow level разный per channel (50 vs 10)")

            # 19.7 Skill upsert — повторный INSERT обновляет level
            await conn.execute("""
                INSERT INTO bannerlord_skills (channel_id, username, skill_key, level, xp)
                VALUES (?, ?, 'bow', 60, 1500)
                ON CONFLICT(channel_id, username, skill_key) DO UPDATE SET
                    level = excluded.level,
                    xp    = excluded.xp
            """, (cid_a, user))
            await conn.commit()
            cur = await conn.execute(
                "SELECT level FROM bannerlord_skills "
                "WHERE channel_id=? AND username=? AND skill_key='bow'",
                (cid_a, user))
            (lvl,) = await cur.fetchone()
            assert_eq(lvl, 60, "skill upsert: level обновлён до 60")

            # 19.8 player.died — is_alive=0
            await conn.execute(
                "UPDATE bannerlord_heroes SET is_alive=0 "
                "WHERE channel_id=? AND username=?", (cid_a, user))
            await conn.commit()
            cur = await conn.execute(
                "SELECT is_alive FROM bannerlord_heroes "
                "WHERE channel_id=? AND username=?", (cid_a, user))
            (alive,) = await cur.fetchone()
            assert_eq(alive, 0, "alice@cid_a dead (is_alive=0)")

            # 19.9 player.respawned — новый hero_id, is_alive=1
            await conn.execute(
                "UPDATE bannerlord_heroes SET hero_id='hero_A2', is_alive=1, is_prisoner=0 "
                "WHERE channel_id=? AND username=?", (cid_a, user))
            await conn.commit()
            cur = await conn.execute(
                "SELECT hero_id, is_alive FROM bannerlord_heroes "
                "WHERE channel_id=? AND username=?", (cid_a, user))
            row = await cur.fetchone()
            assert_eq(row, ('hero_A2', 1), "alice respawned → hero_A2, is_alive=1")

            # 19.10 Equipment unequip
            await conn.execute(
                "DELETE FROM bannerlord_equipment "
                "WHERE channel_id=? AND username=? AND slot='weapon_0'",
                (cid_a, user))
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_equipment "
                "WHERE channel_id=? AND username=?", (cid_a, user))
            (cnt,) = await cur.fetchone()
            assert_eq(cnt, 0, "unequip weapon_0 удалил row")

            # 19.11 Events log — per channel scope
            await conn.execute(
                "INSERT INTO bannerlord_events_log "
                "(channel_id, event_type, username, payload) "
                "VALUES (?, 'player.died', ?, '{\"killer\": \"bandit\"}')",
                (cid_a, user))
            await conn.execute(
                "INSERT INTO bannerlord_events_log "
                "(channel_id, event_type, username, payload) "
                "VALUES (?, 'world.siege_won', NULL, '{}')",
                (cid_b,))
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_events_log WHERE channel_id=?",
                (cid_a,))
            (a_evt,) = await cur.fetchone()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_events_log WHERE channel_id=?",
                (cid_b,))
            (b_evt,) = await cur.fetchone()
            assert_eq((a_evt, b_evt), (1, 1),
                      "events_log: 1 запись на каждом канале (изолированно)")

            # 19.12 Cascade unlink — удаление hero сметает связанные
            for tbl in ('bannerlord_skills', 'bannerlord_attributes',
                         'bannerlord_equipment', 'bannerlord_heroes'):
                await conn.execute(
                    f"DELETE FROM {tbl} WHERE channel_id=? AND username=?",
                    (cid_a, user))
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_heroes WHERE channel_id=?",
                (cid_a,))
            (cnt,) = await cur.fetchone()
            assert_eq(cnt, 0, "cascade unlink alice@cid_a удалил hero")
            cur = await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_skills WHERE channel_id=? AND username=?",
                (cid_a, user))
            (cnt,) = await cur.fetchone()
            assert_eq(cnt, 0, "cascade unlink удалил alice skills")

            # 19.13 Cross-channel НЕ затронут
            cur = await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_heroes WHERE channel_id=?",
                (cid_b,))
            (b_cnt,) = await cur.fetchone()
            assert_true(b_cnt >= 2, "cid_b heroes (alice + charlie) не задеты unlink'ом")

    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────
# 2026-06-11: тесты разделены на CRITICAL (tenant/security/инфра — ГЕЙТЯТ деплой)
# и GAMES (мини-игры + соц-фичи — НЕ гейтят: их internals часто меняются при
# реворках, протухший игровой тест не должен блокировать security-фикс).
# Каждый тест обёрнут в try/except → один краш не обрывает прогон, видны ВСЕ
# поломки разом. Гейт деплоя: `python <this> --critical` (см. deploy.ps1).
# Формат: (callable, is_async).
CRITICAL_TESTS = [
    (test_resolve_channel_id, False),
    (test_module_token, False),
    (test_channel_isolation, True),
    (test_action_queue_isolation, True),
    (test_catalog_replace_semantics, True),
    (test_in_memory_cache_keys, False),
    (test_chat_bonus_antifraud, False),
    (test_current_stream_id_per_channel, False),
    (test_cases_system, True),
    (test_drops_distribution, False),
    (test_matchmaking_infrastructure, True),
]
GAME_TESTS = [
    (test_tictactoe_game_logic, False),
    (test_tictactoe_match_flow, True),
    (test_dice_game_logic, False),
    (test_dice_match_flow, True),
    (test_guilds_system, True),
    (test_voting_system, True),
    (test_pets_system, True),
    (test_bannerlord_system, True),
]


async def _run_one(test, is_async):
    """Прогнать один тест, поймав хард-исключения (ImportError и т.п.) — чтобы
    один протухший тест не обрывал весь прогон (видны все поломки разом)."""
    try:
        if is_async:
            await test()
        else:
            test()
    except Exception as e:
        msg = f"  ❌ {test.__name__} CRASHED: {type(e).__name__}: {e}"
        _failures.append(msg)
        print(msg)


async def run_all_tests(critical_only: bool = False):
    print("=" * 70)
    label = "CRITICAL only (deploy gate)" if critical_only else "FULL (critical + games)"
    print(f"Multi-tenant isolation smoke-tests — {label}")
    print("=" * 70)

    suite = CRITICAL_TESTS if critical_only else (CRITICAL_TESTS + GAME_TESTS)
    for _test, _is_async in suite:
        await _run_one(_test, _is_async)

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
    # `--critical` → только tenant/security инварианты (гейт деплоя, deploy.ps1).
    # без флага → полный прогон (критичные + игровые, для ручной проверки).
    _critical_only = "--critical" in sys.argv
    try:
        rc = asyncio.run(run_all_tests(critical_only=_critical_only))
    except Exception as e:
        traceback.print_exc()
        rc = 2
    sys.exit(rc)
