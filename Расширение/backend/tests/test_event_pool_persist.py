"""
test_event_pool_persist.py — REGRESSION: копилка ивента переживает рестарт.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_event_pool_persist.py

## Что за дыра

Зритель скидывает крустики в копилку «рулекциона». Списание шло в базу, а сама
копилка жила полем `EventManager.event_pool` в ПАМЯТИ ПРОЦЕССА. Любой рестарт
бэкенда — деплой, перезапуск supervisor'ом, падение — обнулял её. Крустики при
этом уже списаны: ни возврата, ни записи о взносе, ни следа в базе.

Копилка запускает ивент при 100 000💎 и копится днями. Деплой в середине
накопления стирал всё собранное — то есть при регулярных деплоях порог мог не
достигаться в принципе, а зрители платили в дырявое ведро.

Второй дефект того же места: списание шло `remove_points(username, amount)`
БЕЗ канала, то есть всегда с канала по умолчанию. На одном канале незаметно,
на втором — чужие деньги.

Третий: списание и зачёт взноса были двумя независимыми шагами со своими
коммитами. Сбой между ними съедал крустики без взноса.

## Чего требуем

1. Взнос списывает ровно столько, сколько сказано.
2. Копилка растёт на ту же сумму.
3. **Новый экземпляр EventManager (это и есть рестарт) видит копилку.**
4. Не хватает крустиков — не списывается НИЧЕГО и копилка не растёт.
5. Взнос идёт с канала зрителя, а не с канала по умолчанию.
6. Вкладчик попадает в список вкладчиков (для топа).

## Красный до фикса

    ❌ [3] копилка пережила рестарт: expected 700, got 0
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
OTHER_CHANNEL = 55500111
USER = "donor"
START_POINTS = 1000

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


class _FakeBot:
    """Бот нужен менеджеру только чтобы объявить старт ивента в чат."""
    async def on_event_start(self, *a, **kw):
        return None


def _new_manager(db):
    """Свежий EventManager = то, что получается после рестарта процесса."""
    from event_manager import EventManager
    return EventManager(_FakeBot(), db)


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
        for cid, login in ((CHANNEL_ID, "chan"), (OTHER_CHANNEL, "other")):
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
                "VALUES (?, ?, ?, 'free')", (cid, login, login))
            await conn.execute(
                "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
                (cid, USER, START_POINTS))
        await conn.commit()
    return test_db


async def _points(db, cid: int) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (cid, USER))
        row = await cur.fetchone()
        return row[0] if row else -1


async def main_async():
    tmp = tempfile.mkdtemp(prefix="event_pool_")
    db = await _build_db(os.path.join(tmp, "test.db"))
    try:
        em = _new_manager(db)

        print("\n[1-2] Взнос списывает ровно столько и растит копилку")
        ok, pool, reason = await em.charge_and_add_to_pool(USER, 300, CHANNEL_ID)
        assert_eq(ok, True, "[1] взнос принят")
        ok2, pool, _ = await em.charge_and_add_to_pool(USER, 400, CHANNEL_ID)
        assert_eq(await _points(db, CHANNEL_ID), START_POINTS - 700,
                  "[1b] списано ровно 700")
        assert_eq(pool, 700, "[2] копилка выросла на ту же сумму")

        print("\n[3] РЕСТАРТ: новый экземпляр менеджера видит копилку")
        em2 = _new_manager(db)
        assert_eq(em2.event_pool, 0, "[3a] свежий менеджер стартует с нуля")
        await em2.load_pool(CHANNEL_ID)
        assert_eq(em2.event_pool, 700, "[3] копилка пережила рестарт")
        assert_eq(em2.event_pool_contributors.get(USER), 700,
                  "[6] вкладчик поднялся вместе с копилкой")

        print("\n[4] Не хватает крустиков — не списывается ничего")
        before_pts = await _points(db, CHANNEL_ID)
        before_pool = em2.event_pool
        ok3, pool3, reason3 = await em2.charge_and_add_to_pool(
            USER, before_pts + 1, CHANNEL_ID)
        assert_eq(ok3, False, "[4] взнос отклонён")
        assert_eq(reason3, "insufficient points", "[4b] причина названа")
        assert_eq(await _points(db, CHANNEL_ID), before_pts, "[4c] баланс не тронут")
        await em2.load_pool(CHANNEL_ID)
        assert_eq(em2.event_pool, before_pool, "[4d] копилка не выросла")

        print("\n[5] Взнос идёт с канала зрителя, а не с канала по умолчанию")
        em3 = _new_manager(db)
        await em3.charge_and_add_to_pool(USER, 100, OTHER_CHANNEL)
        assert_eq(await _points(db, OTHER_CHANNEL), START_POINTS - 100,
                  "[5] списано на своём канале")
        assert_eq(await _points(db, CHANNEL_ID), before_pts,
                  "[5b] чужой канал не тронут")
        await em3.load_pool(OTHER_CHANNEL)
        assert_eq(em3.event_pool, 100, "[5c] копилки каналов раздельные")
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
