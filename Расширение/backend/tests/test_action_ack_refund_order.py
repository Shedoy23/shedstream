"""
test_action_ack_refund_order.py — REGRESSION на T-02 (внешний триаж 2026-07-27,
подтверждён мной на боевой базе 2026-07-28).

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_action_ack_refund_order.py

## Что за дыра

Мод отвечает из `ExecuteAsync` РАНЬШЕ, чем реально выполняет действие. Поэтому
`action.failed` иногда приходит на бэкенд раньше, чем поллер пришлёт
`ACK success=true`. Тогда:

1. `_on_action_failed` возвращает крустики и пишет маркер `REFUNDED:…` в
   `module_actions.error_msg`, **статус строки не меняя**;
2. следом `Database.ack_action` делает
   `SET status=?, error_msg=? WHERE status IN ('queued','dispatched')` —
   условие выполняется, `error_msg` перезаписывается в NULL, статус → `acked`.

Маркер `REFUNDED:` — ЕДИНСТВЕННАЯ защита от повторного возврата
(`modules/bannerlord/_adapter.py`). Он стёрт → защита снята. Следующий
`action.failed` по тому же действию вернёт деньги ВТОРОЙ раз.

На проде 27.07 так вышло минимум у четырёх действий: `status=acked`,
`error_msg=NULL`, при этом в логе по двум видно `REFUND ok +50`.

## Чего требуем от правильного поведения

- `ACK(success) → failed` — ШТАТНЫЙ поток (мод подтверждает до работы, потом
  сообщает об отказе): возврат обязан пройти. Это регресс-сторож, не даёт
  «починить» дыру, сломав нормальный путь.
- `failed → ACK(success)` — деньги уже вернули: поздний ACK не должен ни
  стирать маркер, ни объявлять действие успешным.
- `failed → failed` — второго возврата нет.
- `failed → ACK → failed` — ГЛАВНОЕ: второго возврата нет. Именно эта
  последовательность сегодня приводит к двойной выплате.

## Тест видели красным (правило CLAUDE.md 2b)

До фикса, на текущем коде:
    ❌ [A] маркер возврата пережил ACK: expected True, got False
    ❌ [A] статус после отказа терминальный (не acked): expected 'failed', got 'acked'
    ❌ [B] failed → ACK → failed НЕ вернул деньги второй раз: expected 50, got 100
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
START_POINTS = 1_000
PRICE = 50

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


async def _row(db, action_id):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT status, COALESCE(error_msg,'') FROM module_actions "
            "WHERE channel_id=? AND module_id='bannerlord' AND action_id=?",
            (CHANNEL_ID, action_id))
        return await cur.fetchone()


async def _new_action(db, action_id, price=PRICE):
    """Кладём оплаченное действие в очередь (как это делает касса)."""
    import json
    data = {"initiated_by": "alice", "target": "alice", "price": price}
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'bannerlord', ?, 'player.spawn', ?, 'queued')",
            (CHANNEL_ID, action_id, json.dumps(data, ensure_ascii=False)))
        await conn.commit()


async def _send_failed(action_id, reason="test_refuse"):
    # discover_modules() обязателен: реестр наполняется на старте приложения
    # (main.py), в тесте его надо поднять руками, иначе get_module вернёт None.
    from modules._loader import get_module, discover_modules
    from modules._base import ModuleEnvelope
    adapter = get_module("bannerlord") or discover_modules().get("bannerlord")
    if adapter is None:
        raise RuntimeError("модуль bannerlord не загрузился — проверь manifest.yaml")
    await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
        id=action_id, kind="event", type="action.failed", ts=0,
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
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, 'alice', ?)",
            (CHANNEL_ID, START_POINTS))
        await conn.commit()
    return test_db


async def test_normal_ack_then_failed(db):
    """ШТАТНЫЙ поток: мод подтвердил (до работы), потом сообщил об отказе."""
    print("\n[Ш] Штатный порядок: ACK(успех) → отказ. Возврат обязан пройти")
    aid = "order-ack-then-failed"
    await _new_action(db, aid)
    before = await _points(db)

    await db.ack_action(channel_id=CHANNEL_ID, module_id="bannerlord",
                        action_id=aid, success=True, error_msg=None)
    await _send_failed(aid)

    assert_eq(await _points(db) - before, PRICE,
              "[Ш] поздний отказ вернул деньги (штатный путь не сломан)")


async def test_failed_then_ack_keeps_marker(db):
    """Отказ пришёл ПЕРВЫМ. Поздний ACK не должен ни стирать маркер, ни врать о статусе."""
    print("\n[A] Обратный порядок: отказ → ACK(успех)")
    aid = "order-failed-then-ack"
    await _new_action(db, aid)
    before = await _points(db)

    await _send_failed(aid)
    assert_eq(await _points(db) - before, PRICE, "[A] отказ вернул деньги")
    status, err = await _row(db, aid)
    assert_eq(err.startswith("REFUNDED:"), True, "[A] маркер возврата записан")

    # Поздний ACK об успехе — действие УЖЕ провалено и оплачено обратно.
    await db.ack_action(channel_id=CHANNEL_ID, module_id="bannerlord",
                        action_id=aid, success=True, error_msg=None)

    status, err = await _row(db, aid)
    assert_eq(err.startswith("REFUNDED:"), True, "[A] маркер возврата ПЕРЕЖИЛ ACK")
    assert_eq(status, "failed", "[A] статус после отказа терминальный (не acked)")


async def test_no_double_refund(db):
    """Дубликаты и главная последовательность: failed → ACK → failed."""
    print("\n[B] Повторы: отказ → отказ, и отказ → ACK → отказ")

    aid = "order-failed-twice"
    await _new_action(db, aid)
    before = await _points(db)
    await _send_failed(aid)
    await _send_failed(aid)
    assert_eq(await _points(db) - before, PRICE,
              "[B] два отказа подряд вернули деньги ОДИН раз")

    aid2 = "order-failed-ack-failed"
    await _new_action(db, aid2)
    before2 = await _points(db)
    await _send_failed(aid2)
    await db.ack_action(channel_id=CHANNEL_ID, module_id="bannerlord",
                        action_id=aid2, success=True, error_msg=None)
    await _send_failed(aid2)          # ← сюда и приходит двойная выплата
    assert_eq(await _points(db) - before2, PRICE,
              "[B] failed → ACK → failed НЕ вернул деньги второй раз")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_ack_order_")
    os.close(fd)
    os.unlink(db_path)

    db = await _build_db(db_path)
    try:
        await test_normal_ack_then_failed(db)
        await test_failed_then_ack_keeps_marker(db)
        await test_no_double_refund(db)
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
    print("REGRESSION T-02: порядок ACK и возврата (защита от двойной выплаты)")
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
    print("ALL GREEN ✅ — порядок ACK/возврата безопасен.")
    sys.exit(0)


if __name__ == "__main__":
    main()
