"""
test_bannerlord_target_spoof.py — SECURITY test: cross-user target spoof guard.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_bannerlord_target_spoof.py

ЧТО ДОКАЗЫВАЕТ (gap найден 2026-06-18):
    Mod-хендлеры резолвят «кто действует» как data["target"] ?? data["initiated_by"]
    (target побеждает). Раньше backend форсил только initiated_by, а client-supplied
    data["target"] уходил в mod-bound payload БЕЗ изменений → crafted-запрос с
    data.target=<жертва> на FREE self-action (напр. hero.reequip_gear) заставил бы
    мод ре-роллить/командовать ЧУЖИМ героем, без списания у атакующего (griefing).

    Фикс (routes/bannerlord.py:_charge_execute_enqueue): для всех action'ов КРОМЕ
    _CROSS_USER_TARGET_ACTIONS форсим payload["target"] = requester. Мутируем КОПИЮ
    (payload), не data → backend-логика (запись ставки по data.get("target")) цела.

ТЕСТЫ:
    [1] Spoof self-action: alice шлёт hero.reequip_gear с data.target='victim'
        → enqueued payload.target == 'alice' (НЕ 'victim'), initiated_by == 'alice'.
    [2] No-target sanity: обычный hero.reequip_gear (без target) → payload.target
        проставлен на requester'а ('alice'), нормальный путь не сломан.
    [3] Whitelist preserved: tournament.bet (legit viewer↔viewer, backend-only)
        → НЕ enqueue'ится в mod + запись ставки сохраняет target='victim' (участник).
"""
from __future__ import annotations

import asyncio
import json
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

# Setup imports — script запускается из backend/, добавляем его в path.
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
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CHANNEL_ID = 98319857
START_POINTS = 100_000
ATTACKER = "alice"     # requester (JWT user в проде; здесь — явный arg)
VICTIM = "victim"      # чужой зритель, на которого пытаются нацелиться


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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — фейковый Request + DB-инспекция
# ─────────────────────────────────────────────────────────────────────────────
def _make_anon_request():
    """Минимальный Request без X-Twitch-JWT и без client → роль 'viewer'.

    (см. test_bannerlord_buy_action.py — тот же baseline.) username/channel_id
    в функцию под тестом передаются явными args, а не из JWT, поэтому спуф
    моделируем через содержимое `data`, как сделал бы атакующий в реальном
    POST /api/bannerlord/action.
    """
    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/bannerlord/action",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


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


async def _latest_action_payload(db, channel_id: int, action_type: str):
    """Парсит data-JSON самой свежей module_actions строки данного типа."""
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT data FROM module_actions "
            "WHERE channel_id=? AND module_id='bannerlord' AND type=? "
            "ORDER BY rowid DESC LIMIT 1",
            (channel_id, action_type))
        row = await cur.fetchone()
    if not row:
        return None
    return json.loads(row[0] or "{}")


async def _seed_hero(db, channel_id: int, username: str, gear_tier: int = 3):
    """Живой герой + класс (archer) — минимум для прохождения hero.reequip_gear."""
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_heroes "
            "(channel_id, username, hero_id, display_name, is_alive, gear_tier) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (channel_id, username, f"hero_{username}", f"{username} Hero", gear_tier))
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_hero_class "
            "(channel_id, username, class_key) VALUES (?, ?, 'archer')",
            (channel_id, username))
        await conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# DB setup — реальный Database + полная схема через main.run_migrations()
# ─────────────────────────────────────────────────────────────────────────────
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
        # Атакующий и жертва — оба реальные зрители на одном канале.
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
            (CHANNEL_ID, ATTACKER, START_POINTS))
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
            (CHANNEL_ID, VICTIM, START_POINTS))
        await conn.commit()

    return test_db


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────
async def test_spoofed_self_action_targets_requester(db, buy):
    """[1] Spoof: data.target=victim на self-action → mod видит requester, не жертву."""
    print("\n[1] Spoofed data.target on free self-action (hero.reequip_gear)")
    await _seed_hero(db, CHANNEL_ID, ATTACKER, gear_tier=3)
    await _seed_hero(db, CHANNEL_ID, VICTIM, gear_tier=5)  # реальная жертва с героем
    await _set_points(db, CHANNEL_ID, ATTACKER, START_POINTS)

    res = await buy(
        _make_anon_request(), ATTACKER, CHANNEL_ID, "hero.reequip_gear",
        {"target": VICTIM, "client_action_id": "spoof-reequip-1"})

    assert_eq(res.get("success"), True, "reequip_gear succeeds (action не отклонён)")

    payload = await _latest_action_payload(db, CHANNEL_ID, "hero.reequip_gear")
    assert_true(payload is not None, "mod-bound action enqueued (есть payload)")
    if payload is not None:
        assert_eq(payload.get("initiated_by"), ATTACKER,
                  "payload.initiated_by == requester (alice)")
        assert_eq(payload.get("target"), ATTACKER,
                  "payload.target FORCED to requester (alice), НЕ victim — FIX")
        assert_true(payload.get("target") != VICTIM,
                    "payload.target != victim (спуф нейтрализован)")


async def test_normal_self_action_unbroken(db, buy):
    """[2] Sanity: обычный self-action БЕЗ target → payload.target = requester.

    Свежий пользователь bob (не alice) — у reequip_gear 30s cooldown, а alice
    уже дёргала его в тесте [1]; иначе тут был бы ложный cooldown-refuse.
    """
    print("\n[2] Normal self-action without target — happy path не сломан")
    fresh = "bob"
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
            (CHANNEL_ID, fresh, START_POINTS))
        await conn.commit()
    await _seed_hero(db, CHANNEL_ID, fresh, gear_tier=3)

    res = await buy(
        _make_anon_request(), fresh, CHANNEL_ID, "hero.reequip_gear",
        {"client_action_id": "normal-reequip-1"})

    assert_eq(res.get("success"), True, "reequip_gear без target тоже succeeds")
    payload = await _latest_action_payload(db, CHANNEL_ID, "hero.reequip_gear")
    if payload is not None:
        assert_eq(payload.get("target"), fresh,
                  "payload.target проставлен на requester (bob) даже без входного target")
        assert_eq(payload.get("initiated_by"), fresh,
                  "payload.initiated_by == bob")


async def test_whitelisted_cross_user_preserved(db, buy):
    """[3] Whitelist: tournament.bet (legit viewer↔viewer) НЕ затирается + backend-only."""
    print("\n[3] Whitelisted cross-user action (tournament.bet) — target сохранён")
    # Турнир идёт, victim — участник; alice делает no-loss прогноз на victim.
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO bannerlord_tournament_state "
            "(channel_id, status, current_round, participants) "
            "VALUES (?, 'running', 0, ?)",
            (CHANNEL_ID, json.dumps([VICTIM])))
        await conn.commit()
    await _set_points(db, CHANNEL_ID, ATTACKER, START_POINTS)

    actions_before = await _count_actions(db, CHANNEL_ID, "tournament.bet")
    res = await buy(
        _make_anon_request(), ATTACKER, CHANNEL_ID, "tournament.bet",
        {"target": VICTIM, "client_action_id": "bet-1"})

    assert_eq(res.get("success"), True, "tournament.bet на участника succeeds")

    # Backend-only: НЕ должно быть mod-action в outbox.
    actions_after = await _count_actions(db, CHANNEL_ID, "tournament.bet")
    assert_eq(actions_after - actions_before, 0,
              "tournament.bet НЕ enqueue'ится в mod (backend-only)")

    # Кросс-юзер target сохранён в записи ставки (НЕ затёрт на alice).
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT bettor, target FROM bannerlord_tournament_bets "
            "WHERE channel_id=? AND bettor=? AND round_index=0",
            (CHANNEL_ID, ATTACKER))
        row = await cur.fetchone()
    assert_true(row is not None, "запись ставки создана")
    if row is not None:
        assert_eq(row[0], ATTACKER, "bettor == alice")
        assert_eq(row[1], VICTIM,
                  "target == victim СОХРАНЁН (whitelist: legit viewer↔viewer, data не затёрт)")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def _run():
    db_path = tempfile.mktemp(suffix="_bnr_spoof_test.db")
    db = await _build_db(db_path)
    from routes.bannerlord import _bannerlord_buy_action_locked as buy

    try:
        await test_spoofed_self_action_targets_requester(db, buy)
        await test_normal_self_action_unbroken(db, buy)
        await test_whitelisted_cross_user_preserved(db, buy)
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
    print("SECURITY: cross-user target spoof guard (Bannerlord action enqueue)")
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
    print("ALL GREEN ✅ — спуф target нейтрализован, whitelist цел.")
    sys.exit(0)


if __name__ == "__main__":
    main()
