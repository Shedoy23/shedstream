"""
test_viewer_notices.py — REGRESSION на молчаливый возврат крустиков.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_viewer_notices.py

## Что за дыра

Мод отказал в платном действии → бэкенд вернул крустики и записал причину в
`module_actions.error_msg`. Дальше причина не шла НИКУДА: панель канала о ней
не знала, зритель видел только, что баланс вернулся к прежнему.

Наблюдаемое следствие уже ловили: зритель повторяет платное действие подряд
(баги #16/#17 — объявление войны 4×), потому что «ничего не произошло»
неотличимо от «не нажалось».

## Чего требуем

1. Отказ платного действия оставляет зрителю уведомление с ЧЕЛОВЕЧЕСКОЙ
   причиной — не кодом мода.
2. Сумма возврата в уведомлении совпадает с реально возвращённой.
3. Бесплатное действие тоже не проваливается молча.
4. Повторное событие об отказе не плодит второе уведомление (возврат
   идемпотентен — объяснение обязано быть идемпотентным вместе с ним).
5. Панель забирает непрочитанное, подтверждает показ, и второй раз того же
   не получает.
6. Подтверждение чужим зрителем не закрывает чужое уведомление.
7. Неизвестный код отказа не показывается зрителю сырым и не даёт пустоту.
8. Известный код переводится в текст, где нет самого кода.

Пункт 4 — анти-регресс: соблазнительно писать уведомление до проверки
идемпотентности, и тогда поздний повтор события даёт второй тост.

## Красный до фикса

    ❌ [1] отказ оставляет уведомление: expected 1, got 0
    ❌ [2] сумма возврата в уведомлении: expected 500, got None
    ❌ [3] бесплатный отказ тоже не молчит: expected 1, got 0
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
OTHER_USER = "mallory"
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
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 1000)",
            (CHANNEL_ID, USER))
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 1000)",
            (CHANNEL_ID, OTHER_USER))
        await conn.commit()
    return test_db


async def _queue_action(db, action_id: str, price: int, user: str = USER):
    import json
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'bannerlord', ?, 'hero.declare_war', ?, 'queued')",
            (CHANNEL_ID, action_id,
             json.dumps({"initiated_by": user, "price": price})))
        await conn.commit()


async def _fail_action(db, action_id: str, reason: str):
    from modules._loader import get_module, discover_modules
    from modules._base import ModuleEnvelope
    adapter = get_module("bannerlord") or discover_modules().get("bannerlord")
    await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
        id="ev", kind="event", type="action.failed", ts=0,
        data={"action_id": action_id, "reason": reason}))


async def _notices_of(db, user: str = USER):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT id, kind, text, amount FROM viewer_notices "
            "WHERE channel_id=? AND username=? ORDER BY id",
            (CHANNEL_ID, user))
        return await cur.fetchall()


async def test_paid_refusal_leaves_notice(db):
    print("\n[1-2] Отказ платного действия объясняется зрителю")
    await _queue_action(db, "paid0000000000001", PRICE)
    await _fail_action(db, "paid0000000000001", "in_mission")

    rows = await _notices_of(db)
    assert_eq(len(rows), 1, "[1] отказ оставляет уведомление")
    if not rows:
        return
    _id, kind, text, amount = rows[0]
    print(f"     (текст: {text!r})")
    assert_eq(amount, PRICE, "[2] сумма возврата в уведомлении")
    assert_eq(kind, "refund", "[2b] вид уведомления — возврат")
    # Код мода зрителю не показываем.
    assert_eq("in_mission" in text, False, "[2c] в тексте нет кода мода")


async def test_free_refusal_also_speaks(db):
    print("\n[3] Бесплатное действие тоже не проваливается молча")
    await _queue_action(db, "free0000000000001", 0)
    await _fail_action(db, "free0000000000001", "no_clan")

    rows = await _notices_of(db)
    assert_eq(len(rows), 2, "[3] бесплатный отказ тоже не молчит")
    if len(rows) >= 2:
        assert_eq(rows[1][3], 0, "[3b] у бесплатного отказа сумма ноль")


async def test_repeat_event_no_second_notice(db):
    print("\n[4] АНТИ-РЕГРЕСС: повтор события не плодит второе уведомление")
    before = len(await _notices_of(db))
    # То же самое событие приходит второй раз (мод перезапустился, курсор
    # опроса сбросился) — возврат идемпотентен, объяснение обязано быть тоже.
    await _fail_action(db, "paid0000000000001", "in_mission")
    after = len(await _notices_of(db))
    assert_eq(after, before, "[4] повтор отказа не даёт второго уведомления")


async def test_fetch_and_ack(db):
    print("\n[5] Панель забирает непрочитанное и подтверждает показ")
    import notices as store
    unseen = await store.fetch_unseen(db, CHANNEL_ID, USER)
    assert_eq(len(unseen), 2, "[5] непрочитанного ровно столько, сколько отказов")

    marked = await store.mark_seen(db, CHANNEL_ID, USER,
                                   [n["id"] for n in unseen])
    assert_eq(marked, 2, "[5b] подтверждение закрывает показанное")

    again = await store.fetch_unseen(db, CHANNEL_ID, USER)
    assert_eq(len(again), 0, "[5c] подтверждённое второй раз не приходит")


async def test_ack_is_scoped_to_owner(db):
    print("\n[6] Чужое подтверждение не закрывает чужое уведомление")
    import notices as store
    await store.add_notice(db, CHANNEL_ID, USER, "refund", "Тестовая причина", 7)
    unseen = await store.fetch_unseen(db, CHANNEL_ID, USER)
    assert_eq(len(unseen), 1, "[6] уведомление на месте")
    if not unseen:
        return
    stolen = await store.mark_seen(db, CHANNEL_ID, OTHER_USER,
                                  [unseen[0]["id"]])
    assert_eq(stolen, 0, "[6b] чужой id не закрывается")
    still = await store.fetch_unseen(db, CHANNEL_ID, USER)
    assert_eq(len(still), 1, "[6c] уведомление владельца уцелело")


def test_refusal_dictionary():
    print("\n[7-8] Словарь причин")
    from modules.bannerlord.refusals import describe

    known = describe("not_clan_leader")
    assert_eq("глава клана" in known, True, "[7] известный код переведён")
    assert_eq("not_clan_leader" in known, False, "[7b] кода в тексте нет")

    # Код с уточнением после двоеточия — тот же смысл.
    assert_eq(describe("crashed:NullReference") == describe("crashed"), True,
              "[7c] уточнение после двоеточия не ломает разбор")

    unknown = describe("totally_new_reason_from_future_mod")
    assert_eq(bool(unknown.strip()), True, "[8] неизвестный код даёт текст")
    assert_eq("totally_new_reason_from_future_mod" in unknown, False,
              "[8b] неизвестный код не показывается сырым")
    assert_eq(bool(describe("").strip()), True, "[8c] пустая причина даёт текст")


async def main_async():
    tmp = tempfile.mkdtemp(prefix="notices_")
    db_path = os.path.join(tmp, "test.db")
    db = await _build_db(db_path)
    try:
        await test_paid_refusal_leaves_notice(db)
        await test_free_refusal_also_speaks(db)
        await test_repeat_event_no_second_notice(db)
        await test_fetch_and_ack(db)
        await test_ack_is_scoped_to_owner(db)
        test_refusal_dictionary()
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
