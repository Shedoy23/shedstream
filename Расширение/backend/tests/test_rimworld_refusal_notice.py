"""
test_rimworld_refusal_notice.py — отказ в RimWorld объясняет себя зрителю.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_rimworld_refusal_notice.py

ЧТО ДОКАЗЫВАЕТ (найдено постстрим-триажом 2026-09-09).
    Отказ платного действия в RimWorld возвращал крустики МОЛЧА. Зритель видел
    уход и возврат денег без единого слова и не мог отличить «я сделал не то»
    от «у них сломалось» — отсюда повторные нажатия платных действий (ровно
    ради этого в июле заведён M103).

    Bannerlord и ShedColony пишут `add_notice_tx` в той же транзакции, что
    возвращает деньги; в RimWorld этой строки не было. На эфире 09.09 два
    отказа с возвратом дали НОЛЬ уведомлений — последняя запись в
    `viewer_notices` была от 04.09.

    Проверяется поведение исполнением настоящего `_on_action_failed` с
    настоящей БД: после отказа обязаны существовать и возврат, и уведомление.
    Поиск строки в исходнике этого не доказывает — дыра была в ОТСУТСТВИИ кода.

ТЕСТЫ:
    [1] отказ возвращает ровно списанное
    [2] отказ пишет уведомление зрителю, kind='refused'
    [3] текст уведомления человеческий, без сырого кода
    [4] повторный отказ по тому же action_id не платит и не дублирует
    [5] неизвестный код отказа даёт общую фразу, а не пустоту
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

HERE = Path(__file__).parent.absolute()
sys.path.insert(0, str(HERE.parent))

for _v, _d in (("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "c"),
               ("TWITCH_CLIENT_SECRET", "s"), ("TWITCH_BOT_ID", "b"),
               ("TWITCH_CHANNEL_NAME", "ch"),
               ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
               ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
               ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_v, _d)

CHANNEL_ID = 98319857
USER = "alice"
PRICE = 5047

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


async def _points(db) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, USER))
        row = await cur.fetchone()
    return row[0] if row else None


async def _notices(db) -> list:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT kind, text FROM viewer_notices "
            "WHERE channel_id=? AND username=? ORDER BY id",
            (CHANNEL_ID, USER))
        return list(await cur.fetchall())


async def _seed_action(db, action_id: str, price: int):
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'rimworld', ?, 'equip_item', ?, 'dispatched')",
            (CHANNEL_ID, action_id,
             json.dumps({"initiated_by": USER, "price": price})))
        await conn.commit()


async def _fail(adapter, action_id: str, reason: str):
    from modules._base import ModuleEnvelope
    env = ModuleEnvelope(id=f"e-{action_id}-{reason}", kind="event",
                         type="action.failed", ts=0,
                         data={"action_id": action_id, "reason": reason})
    await adapter.handle_event(CHANNEL_ID, env)


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
            "VALUES (?, 'alice_chan', 'Alice', 'free')", (CHANNEL_ID,))
        await conn.execute(
            "INSERT OR IGNORE INTO viewers (channel_id, username, points) "
            "VALUES (?, ?, 10000)", (CHANNEL_ID, USER))
        await conn.commit()
    return test_db


async def run():
    db_path = tempfile.mktemp(suffix="_rw_notice_test.db")
    db = await _build_db(db_path)
    try:
        from modules._loader import get_module, discover_modules
        adapter = get_module("rimworld") or discover_modules().get("rimworld")
        if adapter is None:
            raise RuntimeError("адаптер rimworld не загрузился")

        print("\n[1-3] Отказ: деньги назад И объяснение")
        before = await _points(db)
        await _seed_action(db, "act-1", PRICE)
        async with db._connect() as conn:      # эмулируем списание при покупке
            await conn.execute(
                "UPDATE viewers SET points = points - ? WHERE channel_id=? AND username=?",
                (PRICE, CHANNEL_ID, USER))
            await conn.commit()
        await _fail(adapter, "act-1", "no_effect")

        after = await _points(db)
        check("возвращено ровно списанное", after == before,
              f"было {before}, стало {after}")

        notices = await _notices(db)
        check("уведомление зрителю записано", len(notices) == 1,
              f"уведомлений: {len(notices)}")
        if notices:
            kind, text = notices[0]
            check("kind = 'refused'", kind == "refused", f"got {kind!r}")
            check("текст человеческий, без сырого кода",
                  "no_effect" not in text and len(text) > 20,
                  f"текст: {text!r}")

        print("\n[4] Повторный отказ по тому же действию")
        await _fail(adapter, "act-1", "no_effect")
        check("второй раз не платит", await _points(db) == before,
              f"баланс {await _points(db)}, ожидался {before}")
        check("второй раз не дублирует уведомление",
              len(await _notices(db)) == 1,
              f"уведомлений: {len(await _notices(db))}")

        print("\n[5] Неизвестный код отказа")
        await _seed_action(db, "act-2", 100)
        async with db._connect() as conn:
            await conn.execute(
                "UPDATE viewers SET points = points - 100 WHERE channel_id=? AND username=?",
                (CHANNEL_ID, USER))
            await conn.commit()
        await _fail(adapter, "act-2", "какой_то_новый_код")
        notices = await _notices(db)
        check("на неизвестный код тоже есть объяснение", len(notices) == 2,
              f"уведомлений: {len(notices)}")
        if len(notices) == 2:
            check("сырой код зрителю не показан",
                  "какой_то_новый_код" not in notices[1][1],
                  f"текст: {notices[1][1]!r}")
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


def main() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    print()
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print(" ", f.strip())
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
