"""
test_bannerlord_buy_action.py — CHARACTERIZATION test для "кассы" Bannerlord.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_bannerlord_buy_action.py

Цель: ЗАФИКСИРОВАТЬ ТЕКУЩЕЕ поведение
    routes/bannerlord.py → _bannerlord_buy_action_locked(...)
перед предстоящим рефакторингом. Это safety-net: тест должен быть ЗЕЛЁНЫМ
против текущего кода. Если что-то здесь упадёт ПОСЛЕ рефактора — рефактор
изменил наблюдаемое поведение «кассы» (charge / idempotency / refuse).

Тест НЕ "чинит" код — он утверждает то, что код РЕАЛЬНО делает сейчас.

Выбранные actions (пересечение _PURCHASABLE_ACTIONS ∩ ACTION_PRICES_DEFAULT
∩ _ACTIONS_WITHOUT_HERO_REQUIREMENT — чтобы не подделывать hero-state):
    - player.respawn  price=500  (НЕ backend-only → enqueue'ится; НЕТ cooldown'а)
    - hero.create     price=0    (freebie; НЕ требует hero; но требует чтобы
                                  hero ещё НЕ существовал)

Роль: request без X-Twitch-JWT + без client в ASGI-scope → verify_twitch_jwt
возвращает {"status":"none"} → роль "viewer" → price_mult=1.0 (чистый baseline,
без broadcaster-скидки даже в DEV_MODE — client=None не localhost).
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
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

# Required env vars для config.py / migrations.
os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")
# M1 migration backfill'ит channel_id существующим строкам из TWITCH_BROADCASTER_ID.
# Должно быть числом, иначе m1_multitenant.apply() бросит RuntimeError.
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CHANNEL_ID = 98319857  # == TWITCH_BROADCASTER_ID (совпадение с M1-backfill default)
START_POINTS = 100_000


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
# Helpers — фейковый Request + DB-инспекция
# ─────────────────────────────────────────────────────────────────────────────
def _make_anon_request():
    """Минимальный starlette.requests.Request без X-Twitch-JWT и без client.

    verify_twitch_jwt(request):
      - DEV_MODE-ветка читает request.client.host; client=None → "" → не
        localhost → bypass НЕ выдаётся (даже если DEV_MODE=true).
      - Дальше request.headers.get("X-Twitch-JWT") → "" → {"status":"none"}.
    Итог — роль "viewer", price_mult=1.0. Чистый baseline.
    """
    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/bannerlord/action",
        "headers": [],   # никаких заголовков → нет X-Twitch-JWT
        "query_string": b"",
        # намеренно НЕТ ключа "client" → request.client == None
    }
    return Request(scope)


async def _get_points(db, channel_id: int, username: str):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
    return (row[0] if row else None)


async def _set_points(db, channel_id: int, username: str, points: int):
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE viewers SET points=? WHERE channel_id=? AND username=?",
            (points, channel_id, username))
        await conn.commit()


async def _count_actions(db, channel_id: int, action_type: str):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM module_actions "
            "WHERE channel_id=? AND module_id='bannerlord' AND type=?",
            (channel_id, action_type))
        row = await cur.fetchone()
    return row[0]


# ─────────────────────────────────────────────────────────────────────────────
# DB setup — реальный Database + полная схема через main.run_migrations()
# ─────────────────────────────────────────────────────────────────────────────
async def _build_db(db_path: str):
    """Поднимает изолированную БД с ПОЛНОЙ схемой (init_tables + все миграции).

    main.run_migrations() ссылается на module-global `main.db`, поэтому
    подменяем его на наш temp Database ПЕРЕД вызовом. dependencies.set_db()
    тоже указываем на него — функция под тестом читает БД через get_db().
    """
    import main  # импорт безопасен: BotCore.__init__ in-memory, пул не открыт
    import dependencies
    from database import Database

    test_db = Database(db_path)
    main.db = test_db            # run_migrations() использует global `db`
    dependencies.set_db(test_db)  # get_db() в коде под тестом → наш db

    await test_db.init_pool()
    await test_db.init_tables()
    await main.run_migrations()

    # Test channel + viewer. После M1 viewers имеет channel_id + UNIQUE(channel_id, username).
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


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────
async def test_happy_path_charge(db, buy):
    """1. Happy path: player.respawn (price 500) списывает РОВНО 500 + enqueue."""
    print("\n[1] Happy path charge — player.respawn (price=500)")
    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)

    before = await _get_points(db, CHANNEL_ID, "alice")
    actions_before = await _count_actions(db, CHANNEL_ID, "player.respawn")

    res = await buy(
        _make_anon_request(), "alice", CHANNEL_ID, "player.respawn",
        {"client_action_id": "happy-respawn-1"})

    assert_eq(res.get("success"), True, "result.success is True")
    assert_eq(res.get("charged"), 500, "result.charged == 500 (server-side price)")
    assert_eq(res.get("perk"), "viewer", "role resolved to 'viewer' (no JWT)")
    assert_eq(res.get("perk_price_mult"), 1.0, "viewer → price_mult 1.0 (no discount)")
    assert_true(bool(res.get("action_id")), "result has an action_id (enqueued)")

    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(before - after, 500, "points dropped by EXACTLY 500")

    actions_after = await _count_actions(db, CHANNEL_ID, "player.respawn")
    assert_eq(actions_after - actions_before, 1,
              "exactly 1 module_actions row enqueued (player.respawn NOT backend-only)")


async def test_idempotency(db, buy):
    """2. Idempotency: тот же client_action_id дважды → charge ОДИН раз."""
    print("\n[2] Idempotency — same client_action_id twice charges once")
    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)

    cid = "idem-respawn-xyz"
    before = await _get_points(db, CHANNEL_ID, "alice")

    res1 = await buy(_make_anon_request(), "alice", CHANNEL_ID,
                     "player.respawn", {"client_action_id": cid})
    mid = await _get_points(db, CHANNEL_ID, "alice")

    res2 = await buy(_make_anon_request(), "alice", CHANNEL_ID,
                     "player.respawn", {"client_action_id": cid})
    after = await _get_points(db, CHANNEL_ID, "alice")

    assert_eq(res1.get("success"), True, "first call succeeds")
    assert_eq(before - mid, 500, "first call charged 500")

    assert_eq(res2.get("success"), True, "replay call still success=True")
    assert_eq(res2.get("idempotent_replay"), True,
              "replay response flagged idempotent_replay=True")
    assert_eq(res2.get("action_id"), res1.get("action_id"),
              "replay returns the SAME action_id as the first call")
    assert_eq(mid - after, 0, "second call did NOT charge again (points unchanged)")
    assert_eq(before - after, 500, "net charge across both calls == 500 (charged once)")

    # И ровно одна строка в outbox для этого client_action_id.
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM module_actions "
            "WHERE channel_id=? AND module_id='bannerlord' AND client_action_id=?",
            (CHANNEL_ID, cid))
        n = (await cur.fetchone())[0]
    assert_eq(n, 1, "exactly 1 module_actions row for that client_action_id")


async def test_insufficient_funds(db, buy):
    """3. Insufficient funds: баланс < price → refuse, баланс НЕ меняется."""
    print("\n[3] Insufficient funds — refuse, no partial charge")
    # Ставим баланс ниже цены respawn (500).
    await _set_points(db, CHANNEL_ID, "alice", 100)
    before = await _get_points(db, CHANNEL_ID, "alice")
    actions_before = await _count_actions(db, CHANNEL_ID, "player.respawn")

    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, "player.respawn",
                    {"client_action_id": "poor-respawn-1"})

    assert_eq(res.get("success"), False, "result.success is False (can't afford)")
    msg = (res.get("message") or "").lower()
    assert_true("недостаточно" in msg, "refusal message mentions 'недостаточно'")

    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(after, before, "points UNCHANGED (no partial charge)")
    actions_after = await _count_actions(db, CHANNEL_ID, "player.respawn")
    assert_eq(actions_after, actions_before, "no module_actions row enqueued on refusal")


async def test_unknown_action_refused(db, buy):
    """4. Unknown action: не в _PURCHASABLE_ACTIONS → refuse, ничего не списано."""
    print("\n[4] Unknown action — purchasable-whitelist guard")
    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)
    before = await _get_points(db, CHANNEL_ID, "alice")

    res = await buy(_make_anon_request(), "alice", CHANNEL_ID,
                    "hero.totally_fake_action",
                    {"client_action_id": "fake-1"})

    assert_eq(res.get("success"), False, "unknown action refused (success False)")
    msg = (res.get("message") or "").lower()
    assert_true("не разрешён" in msg, "message says action 'не разрешён'")
    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(after, before, "balance untouched for refused unknown action")


async def test_free_action_no_charge(db, buy):
    """5. Freebie sanity: hero.create (price=0) → success, 0 списано, enqueue.

    Характеризует поведение price=0 пути (charge-блок пропускается). hero.create
    требует, чтобы живого героя ещё НЕ было — у alice его нет, ок.
    """
    print("\n[5] Free action sanity — hero.create (price=0)")
    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)
    before = await _get_points(db, CHANNEL_ID, "alice")

    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, "hero.create",
                    {"client_action_id": "create-1"})

    assert_eq(res.get("success"), True, "hero.create succeeds")
    assert_eq(res.get("charged"), 0, "charged == 0 (free)")
    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(before - after, 0, "no crustics spent on free action")
    n = await _count_actions(db, CHANNEL_ID, "hero.create")
    assert_eq(n, 1, "hero.create enqueued (NOT backend-only)")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def _run():
    db_path = tempfile.mktemp(suffix="_bnr_buy_test.db")
    db = await _build_db(db_path)
    # Импортируем функцию под тестом ПОСЛЕ set_db (она читает get_db() в рантайме).
    from routes.bannerlord import _bannerlord_buy_action_locked as buy

    try:
        await test_happy_path_charge(db, buy)
        await test_idempotency(db, buy)
        await test_insufficient_funds(db, buy)
        await test_unknown_action_refused(db, buy)
        await test_free_action_no_charge(db, buy)
    finally:
        # Закрываем пул и удаляем temp-БД (реальную viewers.db НЕ трогаем).
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
    print("CHARACTERIZATION: _bannerlord_buy_action_locked (Bannerlord касса)")
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
    print("ALL GREEN ✅ — текущее поведение кассы зафиксировано.")
    sys.exit(0)


if __name__ == "__main__":
    main()
