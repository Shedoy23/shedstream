"""
test_drop_engagement.py — кейс достаётся тому, кто смотрит, а не открытой вкладке.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_drop_engagement.py

ЗАЧЕМ. Замер на проде 28.08, через ДВЕ МИНУТЫ после конца эфира: десять
зрителей имели `last_seen` = «сейчас», а последнее их действие было за 5-8
часов до того, двое не взаимодействовали ни разу. Панель шлёт heartbeat, пока
открыта вкладка, поэтому по одному `last_seen` брошенная вкладка неотличима от
зрителя. `_process_drop` выбирал получателя равномерно из этого списка — и
кейсы уходили в пустые вкладки, отбирая шанс у тех, кто смотрит.

Ставку за просмотр (`_reward_points`) починили 23.08, введя `last_interaction_at`
и `ENGAGED_WINDOW`. Дроп кейсов остался на старом определении «зритель тут» —
тот же класс дефекта пережил свой же фикс в соседней функции.

Тест держит три границы:

1. **Взаимодействие повышает шанс.** Один смотрящий против девяти вкладок
   обязан выигрывать заметно чаще, чем один из десяти.
2. **Лёркер не исключён совсем.** На мобильном мышью не двигают; пул из одних
   лёркеров обязан по-прежнему давать кейсы, иначе мобильная аудитория
   выпадает из розыгрыша целиком.
3. **Чёрный список сильнее всего.** Стример в пул не попадает, как бы активно
   он ни кликал.
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile
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
os.environ.setdefault("TWITCH_BROADCASTER_ID", "4242")

_failures: list = []
CH = 4242
ROUNDS = 4000


def check(cond: bool, label: str):
    if cond:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}")
        _failures.append(label)


async def _draw(bot, rounds: int = ROUNDS) -> dict:
    """Прогнать розыгрыш N раз и вернуть {ник: сколько раз выиграл}."""
    tally: dict = {}

    async def _fake_grant(username, tier=None, source=None, channel_id=None):
        tally[username] = tally.get(username, 0) + 1
        return {"granted": True, "case_id": 0}

    bot.db.grant_case = _fake_grant
    for _ in range(rounds):
        await bot._process_drop(channel_id=CH)
    return tally


async def run() -> int:
    import bot_core
    import dependencies
    from bot_core import BotCore
    from database import Database
    from migrations import m1_multitenant, m116_engagement_watchtime

    db_path = tempfile.mktemp(suffix="_drop.db")
    db = Database(db_path=db_path)
    await db.init_pool()
    await db.init_tables()
    async with db._connect() as conn:
        await m1_multitenant.apply(conn)
        # m116 добавляет last_interaction_at — без неё тест проверял бы не ту
        # схему, что живёт на проде.
        await m116_engagement_watchtime.apply(conn)
        await conn.commit()
    dependencies.set_db(db)
    bot = BotCore(db)

    # Стрим «идёт», кубик дропа всегда выпадает, чат и оверлей молчат:
    # проверяем ВЫБОР получателя, а не обвязку вокруг него.
    async def _live(channel_id=None, login=None):
        return True
    bot._is_stream_live = _live
    async def _noop_msg(*a, **kw):
        return None
    bot.send_message = _noop_msg
    async def _noop_drop(*a, **kw):
        return None
    bot.on_drop = _noop_drop
    bot_core.DROP_CHANCE = 1.0
    random.seed(20260828)   # выбор случаен, но прогон повторяем

    async def _seed(rows):
        async with db._connect() as conn:
            await conn.execute("DELETE FROM viewers WHERE channel_id=?", (CH,))
            for name, interact in rows:
                await conn.execute(
                    "INSERT INTO viewers (channel_id, username, points, last_seen, "
                    f"last_interaction_at) VALUES (?, ?, 0, datetime('now'), {interact})",
                    (CH, name))
            await conn.commit()

    print("\n[1] Один смотрящий против девяти брошенных вкладок")
    # Ровно расклад прода 28.08: у всех свежий last_seen, взаимодействие — нет.
    rows = [("watcher", "datetime('now', '-60 seconds')")]
    rows += [(f"tab{i}", "NULL") for i in range(9)]
    await _seed(rows)
    tally = await _draw(bot)
    share = tally.get("watcher", 0) / ROUNDS
    uniform = 1 / 10
    print(f"      доля смотрящего: {share:.1%} (равномерно было бы {uniform:.0%})")
    check(share > 0.14,
          f"смотрящий выигрывает заметно чаще равномерного ({share:.1%} > 14%)")
    check(sum(tally.values()) == ROUNDS, "каждый розыгрыш нашёл получателя")

    print("\n[2] Давнее взаимодействие не считается свежим")
    # Именно этот случай на проде выглядел как «зритель»: действие 5 часов назад.
    await _seed([("watcher", "datetime('now', '-60 seconds')"),
                 ("morning", "datetime('now', '-5 hours')")])
    tally = await _draw(bot)
    check(tally.get("watcher", 0) > tally.get("morning", 0),
          f"свежее действие сильнее пятичасовой давности "
          f"({tally.get('watcher', 0)} против {tally.get('morning', 0)})")

    print("\n[3] Пул из одних лёркеров всё равно получает кейсы")
    # Продуктовая граница, а не деталь: на мобильном мышью не двигают. Если
    # кто-то однажды «оптимизирует» вес лёркера до нуля, здесь станет красно.
    await _seed([(f"tab{i}", "NULL") for i in range(3)])
    tally = await _draw(bot, rounds=200)
    check(sum(tally.values()) == 200,
          f"мобильная аудитория не выпадает из розыгрыша ({sum(tally.values())}/200)")

    print("\n[4] Чёрный список сильнее активности")
    await _seed([("shedoy23", "datetime('now', '-1 seconds')"),
                 ("watcher", "datetime('now', '-60 seconds')")])
    tally = await _draw(bot, rounds=200)
    check("shedoy23" not in tally,
          f"стример не в пуле, хотя кликал секунду назад (выиграл {tally.get('shedoy23', 0)} раз)")

    await db._pool.close()
    try:
        os.unlink(db_path)
    except OSError:
        pass

    print("\n" + "=" * 58)
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print("  -", f)
        return 1
    print("Все проверки прошли")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
