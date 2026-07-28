"""
test_vassal_placeholder_lifecycle.py — REGRESSION на фантомных вассалов.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_vassal_placeholder_lifecycle.py

## Что за дыра

Создание вассал-клана идёт в два шага: бэкенд СРАЗУ пишет строку-заготовку с
`vassal_clan_id = "pending_<action_id>"`, мод создаёт клан в игре и присылает
событие `hero.vassal_created` с настоящим id — бэкенд заменяет заготовку.

Если мод до второго шага не дошёл (не нашёл наследника, игра закрыта, действие
истекло по TTL), заготовка остаётся в базе НАВСЕГДА и ведёт себя как настоящий
вассал:
  · показывается зрителю в списке вассалов, хотя в игре его нет;
  · навсегда занимает наследника — тот пропадает из списка кандидатов;
  · занимает слот из лимита в 5 вассалов на зрителя.

На проде 27.07 так накопилось 5 фантомов, и 4 попытки создания подряд упали на
поиске наследника — то есть путь отказа рабочий, а уборки за ним нет.

## Чего требуем

1. Протухшая заготовка не показывается зрителю как вассал.
2. Протухшая заготовка не держит наследника заблокированным.
3. Протухшая заготовка не занимает слот лимита.
4. Отказ действия (в том числе истечение по TTL) СНОСИТ заготовку — жизненный
   цикл закрывается сам, без ручной уборки базы.
5. Свежая заготовка продолжает защищать от дубля: два клика подряд по одному
   наследнику не должны заводить двух вассалов.

Пункт 5 — анти-регресс: соблазнительно «просто игнорировать все pending», и это
открыло бы двойное создание.

## Красный до фикса

    ❌ [1] протухшая заготовка не показывается зрителю: expected 0, got 1
    ❌ [2] протухшая заготовка не держит наследника: expected 1, got 0
    ❌ [3] протухшая заготовка не занимает слот лимита: expected True, got False
    ❌ [4] отказ действия сносит заготовку: expected 0, got 1
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
USER = "alice"
VASSAL_GOLD = 250_000

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


async def _add_heir(db, heir_id: str, name: str):
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO bannerlord_heirs "
            "(channel_id, parent_username, heir_hero_id, heir_name, alive, activated) "
            "VALUES (?, ?, ?, ?, 1, 0)",
            (CHANNEL_ID, USER, heir_id, name))
        await conn.commit()


async def _add_placeholder(db, action_id: str, heir_id: str, age_minutes: int,
                           name: str = "Фантом"):
    """Заготовка ровно того вида, что пишет handle_create_vassal."""
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO bannerlord_vassals "
            "(channel_id, parent_username, vassal_clan_id, vassal_leader_hero_id, "
            " vassal_name, income_share_pct, created_at) "
            "VALUES (?, ?, ?, ?, ?, 25.0, datetime('now', ?))",
            (CHANNEL_ID, USER, f"pending_{action_id[:16]}", heir_id, name,
             f"-{age_minutes} minutes"))
        await conn.commit()


async def _count_vassal_rows(db) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM bannerlord_vassals WHERE channel_id=?",
            (CHANNEL_ID,))
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
            "VALUES (?, 'alice_chan', 'Alice Channel', 'free')", (CHANNEL_ID,))
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 10000)",
            (CHANNEL_ID, USER))
        # Герой с деньгами — иначе создание вассала отсекается по золоту раньше,
        # чем дойдёт до проверки лимита, и тест был бы зелёным не по той причине.
        await conn.execute(
            "INSERT INTO bannerlord_heroes "
            "(channel_id, username, hero_id, display_name, gold) "
            "VALUES (?, ?, 'hero_alice', 'Alice Hero', ?)",
            (CHANNEL_ID, USER, VASSAL_GOLD * 10))
        await conn.commit()
    return test_db


async def test_stale_placeholder_hidden(db):
    print("\n[1] Протухшая заготовка не показывается зрителю")
    from routes.bannerlord_vassals import list_real_vassals
    await _add_heir(db, "heir_1", "Первый")
    await _add_placeholder(db, "aaaabbbbccccdddd1", "heir_1", age_minutes=120)

    async with db._connect() as conn:
        vassals = await list_real_vassals(conn, CHANNEL_ID, USER)
    assert_eq(len(vassals), 0, "[1] протухшая заготовка не показывается зрителю")


async def test_stale_placeholder_frees_heir(db):
    print("\n[2] Протухшая заготовка не держит наследника")
    from routes.bannerlord_vassals import list_eligible_heirs
    async with db._connect() as conn:
        heirs = await list_eligible_heirs(conn, CHANNEL_ID, USER)
    names = [h["hero_id"] for h in heirs]
    assert_eq("heir_1" in names, True, "[2] протухшая заготовка не держит наследника")


async def test_stale_placeholder_frees_slot(db):
    print("\n[3] Протухшая заготовка не занимает слот лимита")
    from routes.bannerlord_vassals import handle_create_vassal
    # Пять протухших заготовок = весь лимит, если считать их настоящими.
    for i in range(2, 7):
        await _add_heir(db, f"heir_{i}", f"Наследник {i}")
        await _add_placeholder(db, f"stale{i}" + "0" * 12, f"heir_{i}",
                               age_minutes=120)
    await _add_heir(db, "heir_fresh", "Свежий")

    async with db._connect() as conn:
        res = await handle_create_vassal(conn, CHANNEL_ID, USER, {
            "heir_hero_id": "heir_fresh", "vassal_name": "Новый клан"})
        await conn.commit()
    ok = bool(res.get("success"))
    if not ok:
        print(f"     (отказ: {res.get('message')})")
    assert_eq(ok, True, "[3] протухшая заготовка не занимает слот лимита")


async def test_failed_action_removes_placeholder(db):
    print("\n[4] Отказ действия сносит заготовку")
    from modules._loader import get_module, discover_modules
    from modules._base import ModuleEnvelope

    action_id = "deadbeefdeadbeef99"
    await _add_heir(db, "heir_fail", "Неудачник")
    await _add_placeholder(db, action_id, "heir_fail", age_minutes=1,
                           name="Не родился")
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'bannerlord', ?, 'hero.create_vassal_clan', "
            "        '{\"initiated_by\": \"alice\", \"price\": 0}', 'queued')",
            (CHANNEL_ID, action_id))
        await conn.commit()

    before = await _count_vassal_rows(db)
    adapter = get_module("bannerlord") or discover_modules().get("bannerlord")
    await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
        id="ev", kind="event", type="action.failed", ts=0,
        data={"action_id": action_id, "reason": "heir_not_found"}))

    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM bannerlord_vassals "
            "WHERE channel_id=? AND vassal_clan_id=?",
            (CHANNEL_ID, f"pending_{action_id[:16]}"))
        left = (await cur.fetchone())[0]
    print(f"     (строк вассалов до отказа: {before})")
    assert_eq(left, 0, "[4] отказ действия сносит заготовку")


async def test_fresh_placeholder_still_blocks_duplicate(db):
    print("\n[5] АНТИ-РЕГРЕСС: свежая заготовка защищает от дубля")
    from routes.bannerlord_vassals import handle_create_vassal
    await _add_heir(db, "heir_dup", "Двойник")
    await _add_placeholder(db, "freshfreshfresh01", "heir_dup", age_minutes=0,
                           name="Только что")

    async with db._connect() as conn:
        res = await handle_create_vassal(conn, CHANNEL_ID, USER, {
            "heir_hero_id": "heir_dup", "vassal_name": "Дубль"})
        await conn.commit()
    assert_eq(bool(res.get("success")), False,
              "[5] свежая заготовка всё ещё блокирует дубль")


async def main_async():
    tmp = tempfile.mkdtemp(prefix="vassal_ph_")
    db_path = os.path.join(tmp, "test.db")
    db = await _build_db(db_path)
    try:
        await test_stale_placeholder_hidden(db)
        await test_stale_placeholder_frees_heir(db)
        await test_stale_placeholder_frees_slot(db)
        await test_failed_action_removes_placeholder(db)
        await test_fresh_placeholder_still_blocks_duplicate(db)
    finally:
        try:
            await db.close_pool()
        except Exception:
            pass

    print("\n" + "=" * 62)
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}, пройдено: {len(_successes)}")
        for f in _failures:
            print(f)
        return 1
    print(f"ВСЁ ЗЕЛЁНОЕ: {len(_successes)} проверок")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async()))
    except Exception:
        traceback.print_exc()
        sys.exit(2)
