"""
test_peace_offer_lifecycle.py — REGRESSION на зависшие заявки о мире.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_peace_offer_lifecycle.py

## Что за дыра

Зритель-король предлагает мир: бэкенд пишет строку в `bannerlord_peace_offers`
со статусом 'pending' и ставит действие в очередь мода. Закрывать эту строку
было НЕЧЕМ — связи с действием у неё не существовало.

И это не мусор в таблице, а замок. Уникальный индекс `idx_peace_pending_unique`
частичный, `WHERE status = 'pending'`: пока строка висит, повторная вставка
той же пары королевств падает на UNIQUE, и зритель читает «Peace offer уже
отправлен». Один неудачный запрос закрывал направление НАВСЕГДА.

На проде 28.07 в этом состоянии висела заявка id=1.

## Чего требуем

1. Отказ действия (включая истечение по TTL) переводит заявку в терминальный
   статус — связь через `action_id`, добавленный миграцией M101.
2. После этого король может предложить мир той же фракции снова: замок снят.
3. Заявка, по которой отказ так и не пришёл, истекает по возрасту (сторож
   добирает в том числе строки, созданные до M101, — у них action_id пустой).
4. Свежая заявка НЕ истекает — порог по времени работает, а не сносит всё
   подряд.

## Красный до фикса

Проверено снятием UPDATE в `_adapter._drop_placeholder_rows`:
    ❌ [1] отказ закрывает заявку: expected True, got False
    ❌ [2] после отказа можно предложить мир снова: expected True, got False
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
KING = "alice"
TARGET = "kingdom_vlandia"

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


async def _offer_status(db, action_id: str = None):
    async with db._connect() as conn:
        if action_id:
            cur = await conn.execute(
                "SELECT status FROM bannerlord_peace_offers "
                "WHERE channel_id=? AND action_id=?", (CHANNEL_ID, action_id))
        else:
            cur = await conn.execute(
                "SELECT status FROM bannerlord_peace_offers "
                "WHERE channel_id=? ORDER BY id DESC LIMIT 1", (CHANNEL_ID,))
        row = await cur.fetchone()
    return (row[0] if row else None)


async def _make_peace(db) -> dict:
    """Настоящий путь покупки — тот же, что зовёт эндпоинт."""
    from routes.bannerlord_diplomacy import handle_make_peace
    async with db._connect() as conn:
        res = await handle_make_peace(conn, CHANNEL_ID, KING, {
            "target_kingdom_id": TARGET,
            "target_kingdom_name": "Вландия",
            "offered_tribute": 0,
        })
        await conn.commit()
    return res


async def _last_action_id(db):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT action_id FROM module_actions "
            "WHERE channel_id=? AND type='hero.make_peace' "
            "ORDER BY rowid DESC LIMIT 1", (CHANNEL_ID,))
        row = await cur.fetchone()
    return (row[0] if row else None)


async def _fail_action(db, action_id: str, reason: str = "no_target_kingdom"):
    from modules._loader import get_module, discover_modules
    from modules._base import ModuleEnvelope
    adapter = get_module("bannerlord") or discover_modules().get("bannerlord")
    await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
        id="ev", kind="event", type="action.failed", ts=0,
        data={"action_id": action_id, "reason": reason}))


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
            (CHANNEL_ID, KING))
        # Король своего королевства — иначе make_peace отсечётся раньше и тест
        # был бы зелёным не по той причине.
        await conn.execute(
            "INSERT INTO bannerlord_heroes "
            "(channel_id, username, hero_id, display_name, gold, "
            " kingdom_id, kingdom_name, is_king, is_clan_leader) "
            "VALUES (?, ?, 'hero_alice', 'Alice Hero', 100000, "
            "        'kingdom_battania', 'Батания', 1, 1)",
            (CHANNEL_ID, KING))
        await conn.commit()
    return test_db


async def test_migration_added_column(db):
    print("\n[0] Миграция M101 добавила связь заявки с действием")
    async with db._connect() as conn:
        cur = await conn.execute("PRAGMA table_info(bannerlord_peace_offers)")
        cols = [r[1] for r in await cur.fetchall()]
    assert_eq("action_id" in cols, True, "[0] колонка action_id на месте")


async def test_failed_action_closes_offer(db):
    print("\n[1] Отказ действия закрывает заявку")
    res = await _make_peace(db)
    if not res.get("success"):
        print(f"     (заявка не создалась: {res.get('message')})")
    action_id = await _last_action_id(db)
    assert_eq(await _offer_status(db, action_id), "pending", "[1] заявка создана как pending")

    await _fail_action(db, action_id)

    st = await _offer_status(db, action_id)
    assert_eq(st != "pending", True, f"[1] отказ закрывает заявку (статус={st})")


async def test_lock_released(db):
    print("\n[2] После отказа можно предложить мир той же фракции снова")
    res = await _make_peace(db)
    if not res.get("success"):
        print(f"     (отказ: {res.get('message')})")
    assert_eq(bool(res.get("success")), True,
              "[2] замок снят — повторная заявка проходит")


async def test_stale_offer_expires(db):
    print("\n[3] Заявка без отказа истекает по возрасту")
    from routes.bannerlord_diplomacy import expire_old_peace_offers
    # Строка «из прошлого»: до M101 такие писались вообще без action_id.
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE bannerlord_peace_offers "
            "SET offered_at = datetime('now', '-48 hours'), action_id = NULL "
            "WHERE status='pending'")
        await conn.commit()

    affected = await expire_old_peace_offers()
    assert_eq(affected >= 1, True, "[3] сторож закрыл протухшую заявку")

    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM bannerlord_peace_offers "
            "WHERE channel_id=? AND status='pending'", (CHANNEL_ID,))
        left = (await cur.fetchone())[0]
    assert_eq(left, 0, "[3] зависших заявок не осталось")


async def test_fresh_offer_survives(db):
    print("\n[4] АНТИ-РЕГРЕСС: свежая заявка не истекает")
    res = await _make_peace(db)
    assert_eq(bool(res.get("success")), True, "[4] свежая заявка создана")

    from routes.bannerlord_diplomacy import expire_old_peace_offers
    await expire_old_peace_offers()

    assert_eq(await _offer_status(db), "pending",
              "[4] свежая заявка пережила проход сторожа")


async def main_async():
    tmp = tempfile.mkdtemp(prefix="peace_lc_")
    db_path = os.path.join(tmp, "test.db")
    db = await _build_db(db_path)
    try:
        await test_migration_added_column(db)
        await test_failed_action_closes_offer(db)
        await test_lock_released(db)
        await test_stale_offer_expires(db)
        await test_fresh_offer_survives(db)
    finally:
        try:
            await db._pool.close()
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
