"""
test_quest_reward_atomic.py — REGRESSION-тест на дыру S-18
(внешний аудит 2026-07-30, подтверждена по коду 2026-08-01).

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_quest_reward_atomic.py

## Что за дыра

`BotCore._update_quest_progress` отмечал квест завершённым и КОММИТИЛ отметку,
а награду выдавал следующей строкой — отдельным вызовом `_complete_quest()`,
то есть вторым соединением и вторым коммитом.

Если в этом окне процесс падал (или `add_points` бросал исключение):
  • `quests.completed_at` уже закоммичен;
  • крустики НЕ начислены;
  • повторное событие видит `if completed: return` и молча выходит.
Награда терялась НАВСЕГДА — 1500/3000/6000💎 за квест, у каждого зрителя,
каждый день, без следа в базе и без возможности повтора.

Зеркальный сценарий — гонка: два события над одним незавершённым квестом
успевают пройти проверку `if completed` до того, как первое закоммитило
отметку, и награда выдаётся ДВАЖДЫ.

Тот же класс, что S-06 (Channel Points) и семь случаев аудита 2026-07-02.
Прямое нарушение правила проекта «источник и эффект — в одной транзакции».

## Как чинится

Отметка «завершён» и начисление идут одним коммитом на ОДНОМ соединении:
`UPDATE quests SET completed_at=... WHERE id=? AND completed_at IS NULL`
(rowcount=0 → квест уже закрыл кто-то другой, выходим не заплатив) плюс
`add_points_tx` на том же `conn`. Сбой откатывает ОБА действия → следующее
событие по квесту отработает штатно и зритель получит своё.

## Тест видели красным (правило CLAUDE.md 2b)

До фикса, на существующем квесте:
    ❌ после сбоя квест НЕ отмечен завершённым: expected None, got '2026-08-01 ...'
    ❌ повтор события выдал награду: expected 1500, got 0
До фикса, на квесте, который создаётся сразу завершённым:
    ❌ после сбоя квест НЕ отмечен завершённым: expected None, got '2026-08-01 ...'
    ❌ повтор события выдал награду: expected 3000, got 0
После фикса — зелёное.
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
VIEWER = "alice"

# Квест на существующей строке (сначала прогресс, потом добивка до цели).
QUEST_STEP = "watch_time_30"        # target 30, reward 1500
# Квест, который создаётся сразу завершённым (increment >= target на первом же
# событии) — это ВТОРАЯ ветка с тем же дефектом, её легко упустить.
QUEST_INSTANT = "watch_time_60"     # target 60, reward 3000

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


async def _get_points(db, username: str = VIEWER):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, username))
        row = await cur.fetchone()
    return (row[0] if row else 0)


async def _completed_at(db, quest_type: str, username: str = VIEWER):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT completed_at FROM quests "
            "WHERE channel_id=? AND username=? AND quest_type=?",
            (CHANNEL_ID, username, quest_type))
        row = await cur.fetchone()
    return (row[0] if row else None)


async def _reset_points(db, username: str = VIEWER):
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE viewers SET points=0 WHERE channel_id=? AND username=?",
            (CHANNEL_ID, username))
        await conn.commit()


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
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 0)",
            (CHANNEL_ID, VIEWER))
        for extra in ("bob", "carol", "dave"):
            await conn.execute(
                "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 0)",
                (CHANNEL_ID, extra))
        await conn.commit()

    return test_db


class _Boom(RuntimeError):
    pass


async def _crash_on_credit(bot, db, quest_type: str, increment: int):
    """Довести квест до цели, но упасть ровно на выдаче награды."""
    from database import Database

    original_tx = Database.add_points_tx
    original_plain = Database.add_points

    async def _boom(*args, **kwargs):
        raise _Boom("имитация сбоя ровно на начислении награды")

    Database.add_points_tx = _boom
    Database.add_points = _boom
    try:
        try:
            await bot._update_quest_progress(
                VIEWER, quest_type, increment, channel_id=CHANNEL_ID)
        except _Boom:
            pass    # падение ожидаемо — смотрим, что осталось в базе
    finally:
        Database.add_points_tx = original_tx
        Database.add_points = original_plain


async def test_crash_on_existing_quest(bot, db):
    """Сбой на начислении не должен запирать уже начатый квест."""
    print("\n[1] S-18: сбой между отметкой «завершён» и наградой (существующий квест)")

    reward = 1500     # QUESTS_CONFIG[QUEST_STEP]['reward_points']

    # Первое событие — прогресс без завершения, штатный путь.
    await bot._update_quest_progress(VIEWER, QUEST_STEP, 10, channel_id=CHANNEL_ID)
    assert_eq(await _completed_at(db, QUEST_STEP), None,
              "недобитый квест не помечен завершённым")

    # Второе событие добивает до цели — и падает на выдаче награды.
    await _crash_on_credit(bot, db, QUEST_STEP, 20)

    assert_eq(await _completed_at(db, QUEST_STEP), None,
              "после сбоя квест НЕ отмечен завершённым (повтор возможен)")

    # Следующее событие, добивающее квест до цели, обязано выдать награду.
    # Инкремент 20, а не 1: сбой откатил и прогресс тоже, счётчик снова на 10.
    await bot._update_quest_progress(VIEWER, QUEST_STEP, 20, channel_id=CHANNEL_ID)
    assert_eq(await _get_points(db), reward, "повтор события выдал награду")
    assert_eq((await _completed_at(db, QUEST_STEP)) is not None, True,
              "после успешной выдачи квест отмечен завершённым")


async def test_crash_on_instant_quest(bot, db):
    """Та же дыра на второй ветке: квест создаётся сразу завершённым."""
    print("\n[2] S-18: сбой на квесте, который завершается первым же событием")

    reward = 3000     # QUESTS_CONFIG[QUEST_INSTANT]['reward_points']
    await _reset_points(db)

    # Строки квеста ещё нет — путь INSERT + немедленное завершение.
    await _crash_on_credit(bot, db, QUEST_INSTANT, 60)

    assert_eq(await _completed_at(db, QUEST_INSTANT), None,
              "после сбоя квест НЕ отмечен завершённым (повтор возможен)")

    # Повтор — снова событие на полную цель (сбой откатил и вставку строки).
    await bot._update_quest_progress(VIEWER, QUEST_INSTANT, 60, channel_id=CHANNEL_ID)
    assert_eq(await _get_points(db), reward, "повтор события выдал награду")
    assert_eq((await _completed_at(db, QUEST_INSTANT)) is not None, True,
              "после успешной выдачи квест отмечен завершённым")


async def test_no_double_reward_under_concurrency(bot, db):
    """Гонка двух событий над одним квестом платит РОВНО один раз."""
    print("\n[3] S-18 зеркало: одновременные события не платят дважды")

    reward = 1500
    await _reset_points(db, "bob")

    # Восемь одновременных событий, каждое само по себе добивает квест до цели.
    await asyncio.gather(*[
        bot._update_quest_progress("bob", QUEST_STEP, 30, channel_id=CHANNEL_ID)
        for _ in range(8)
    ], return_exceptions=True)

    assert_eq(await _get_points(db, "bob"), reward,
              "награда за квест начислена ровно один раз при 8 гонщиках")


async def test_normal_path_still_works(bot, db):
    """Штатный путь не сломан фиксом: квест доходит до цели и платит."""
    print("\n[4] Штатное завершение квеста продолжает работать")

    reward = 1500
    await _reset_points(db, "carol")

    await bot._update_quest_progress("carol", QUEST_STEP, 15, channel_id=CHANNEL_ID)
    assert_eq(await _get_points(db, "carol"), 0, "на полпути награды нет")

    await bot._update_quest_progress("carol", QUEST_STEP, 15, channel_id=CHANNEL_ID)
    assert_eq(await _get_points(db, "carol"), reward, "по достижении цели награда выдана")

    # Дальнейшие события не доплачивают.
    await bot._update_quest_progress("carol", QUEST_STEP, 5, channel_id=CHANNEL_ID)
    assert_eq(await _get_points(db, "carol"), reward, "после завершения повтор не доплачивает")


async def test_instant_quest_pays_once(bot, db):
    """Квест, закрытый ПЕРВЫМ ЖЕ событием, не платит повторно на следующем.

    Найдено этим тестом 2026-08-01, сверх формулировки S-18: ветка INSERT
    выдавала награду, но НЕ проставляла `completed_at`. Следующее событие по
    тому же квесту видело незакрытую строку, добивало её до цели и платило
    ВТОРОЙ раз. То есть у зрителя, набравшего цель одним событием, каждый
    такой квест стоил каналу двойную награду.
    """
    print("\n[5] Квест, завершённый сразу, оплачивается ровно один раз")

    reward = 3000
    await _reset_points(db, "dave")

    await bot._update_quest_progress("dave", QUEST_INSTANT, 60, channel_id=CHANNEL_ID)
    assert_eq(await _get_points(db, "dave"), reward,
              "мгновенно закрытый квест выдал награду")
    assert_eq((await _completed_at(db, QUEST_INSTANT, "dave")) is not None, True,
              "мгновенно закрытый квест отмечен завершённым")

    await bot._update_quest_progress("dave", QUEST_INSTANT, 5, channel_id=CHANNEL_ID)
    assert_eq(await _get_points(db, "dave"), reward,
              "следующее событие не доплатило второй раз")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_quest_atomic_")
    os.close(fd)
    os.unlink(db_path)

    db = await _build_db(db_path)
    from bot_core import BotCore
    bot = BotCore(db)

    try:
        await test_crash_on_existing_quest(bot, db)
        await test_crash_on_instant_quest(bot, db)
        await test_no_double_reward_under_concurrency(bot, db)
        await test_normal_path_still_works(bot, db)
        await test_instant_quest_pays_once(bot, db)
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
    print("REGRESSION S-18: награда за квест — отметка и выдача одной транзакцией")
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
    print("ALL GREEN ✅ — награда за квест не теряется и не удваивается.")
    sys.exit(0)


if __name__ == "__main__":
    main()
