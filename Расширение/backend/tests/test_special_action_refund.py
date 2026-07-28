"""
test_special_action_refund.py — REGRESSION на PB-01 / PB-03.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_special_action_refund.py

## Что за дыра

Действия из `_BACKEND_ONLY_ACTIONS` (мастерские, караваны, приказы отряду,
дипломатия, вассалы, семья) проходят общую кассу — цена ставится, крустики
списываются — но **пропускают общий enqueue**. Их обработчики собирали payload
с нуля и теряли два кассовых поля:

* `price` → `_on_action_failed` читает `int(parsed.get("price") or 0)`, получает
  0, пишет `REFUNDED:0 (no_price)` и НЕ ВОЗВРАЩАЕТ ДЕНЕГ;
* `client_action_id` → защита от повторного нажатия ищет по нему строку и не
  находит.

На проде 2026-07-28: 74 таких случая (приказ отряду ×63 по 500💎, мастерская ×5
по 2500💎, караван ×5 по 4000💎, мир ×1 за 2000💎), и у ВСЕХ спец-действий
`client_action_id` был `NULL`.

## Что проверяем

Тест бьёт по контракту очереди, а не по конкретной механике: любое действие,
попавшее в `module_actions`, обязано нести цену и ключ идемпотентности. Так он
поймает и четырнадцатый обработчик, который заведут завтра.

## Тест видели красным (правило CLAUDE.md 2b)

До фикса:
    ❌ [1] цена сохранена в задании: expected 500, got None
    ❌ [1] ключ идемпотентности сохранён: expected True, got False
    ❌ [2] отказ вернул РОВНО списанное: expected 500, got 0
"""
from __future__ import annotations

import asyncio
import json
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
PRICE = 500

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


async def _points(db, username="alice"):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, username))
        row = await cur.fetchone()
    return (row[0] if row else 0)


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
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, 'alice', 100000)",
            (CHANNEL_ID,))
        await conn.commit()
    return test_db


async def test_queue_contract_carries_cash_fields(db):
    """Контракт очереди: цена и ключ идемпотентности обязаны доехать."""
    print("\n[1] Контракт очереди: enqueue_mod_action переносит кассовые поля")
    from routes._mod_queue import enqueue_mod_action

    aid = "special-contract-1"
    # `src` — тело запроса, каким его видит спец-обработчик: касса уже
    # проставила фактическую цену, фронт прислал ключ идемпотентности.
    src = {"price": PRICE, "client_action_id": "cid-abc", "initiated_by": "alice"}
    payload = {"initiated_by": "alice", "target": "alice", "order_type": "siege"}

    async with db._connect() as conn:
        await enqueue_mod_action(conn, CHANNEL_ID, aid,
                                 "hero.party_order_set", payload, src)
        await conn.commit()
        cur = await conn.execute(
            "SELECT data, client_action_id FROM module_actions "
            "WHERE channel_id=? AND action_id=?", (CHANNEL_ID, aid))
        row = await cur.fetchone()

    stored = json.loads(row[0])
    assert_eq(stored.get("price"), PRICE, "[1] цена сохранена в задании")
    assert_eq(bool(row[1]), True, "[1] ключ идемпотентности сохранён")
    assert_eq(stored.get("order_type"), "siege", "[1] доменные поля не потерялись")


async def test_refusal_refunds_exact_amount(db):
    """Отказ мода по спец-действию возвращает РОВНО списанное, а не ноль."""
    print("\n[2] Отказ по спец-действию возвращает ровно списанное")
    from routes._mod_queue import enqueue_mod_action
    from modules._loader import get_module, discover_modules
    from modules._base import ModuleEnvelope

    aid = "special-refund-1"
    src = {"price": PRICE, "client_action_id": "cid-xyz", "initiated_by": "alice"}
    payload = {"initiated_by": "alice", "target": "alice"}

    async with db._connect() as conn:
        # Имитируем кассу: списываем и кладём в очередь одной транзакцией.
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute(
            "UPDATE viewers SET points = points - ? WHERE channel_id=? AND username='alice'",
            (PRICE, CHANNEL_ID))
        await enqueue_mod_action(conn, CHANNEL_ID, aid,
                                 "hero.party_order_set", payload, src)
        await conn.commit()

    after_charge = await _points(db)

    adapter = get_module("bannerlord") or discover_modules().get("bannerlord")
    await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
        id=aid, kind="event", type="action.failed", ts=0,
        data={"action_id": aid, "reason": "test_refuse"}))

    assert_eq(await _points(db) - after_charge, PRICE,
              "[2] отказ вернул РОВНО списанное")

    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COALESCE(error_msg,'') FROM module_actions "
            "WHERE channel_id=? AND action_id=?", (CHANNEL_ID, aid))
        err = (await cur.fetchone())[0]
    assert_eq(err.startswith(f"REFUNDED:{PRICE}"), True,
              "[2] в журнале записана реальная сумма, не ноль")


async def test_no_direct_inserts_left(db):
    """Ни один спец-обработчик больше не пишет в очередь в обход общей функции."""
    print("\n[3] Прямых вставок в обход общей функции не осталось")
    import glob
    offenders = []
    for path in glob.glob(str(BACKEND / "routes" / "bannerlord_*.py")):
        text = Path(path).read_text(encoding="utf-8")
        if "INSERT INTO module_actions" in text:
            offenders.append(Path(path).name)
    assert_eq(offenders, [], "[3] обходных INSERT нет ни в одном файле")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_special_refund_")
    os.close(fd)
    os.unlink(db_path)

    db = await _build_db(db_path)
    try:
        await test_queue_contract_carries_cash_fields(db)
        await test_refusal_refunds_exact_amount(db)
        await test_no_direct_inserts_left(db)
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
    print("REGRESSION PB-01/PB-03: спец-действия несут цену и ключ повтора")
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
    print("ALL GREEN ✅ — касса не теряет цену на спец-ветке.")
    sys.exit(0)


if __name__ == "__main__":
    main()
