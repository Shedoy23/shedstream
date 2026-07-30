"""
test_background_loops_survive.py — аудит по спеке §6: фоновая задача обязана
пережить исключение внутри итерации.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_background_loops_survive.py

## Почему это важнее, чем выглядит

`asyncio.create_task(loop())` запускает задачу и БОЛЬШЕ О НЕЙ НЕ ВСПОМИНАЕТ.
Если исключение вылетает из тела `while`, задача завершается — навсегда, до
рестарта процесса. Не падает сервис, не растёт счётчик ошибок, не приходит
алерт: механика просто перестаёт работать, а `/health` продолжает отвечать 200.

Этот проект уже дважды жил с такой поломкой: награды за очки Twitch были мертвы
с 8 июля (заметили 27-го), токен OAuth умер 10-го и кричал в лог 448 раз, пока
на него не наткнулись. Оба раза симптом был один — «зритель не получает
крустики», и оба раза узнали от зрителя, а не от системы.

## Что проверяем

`reward_points_loop` — начисление крустиков за просмотр, самый дорогой цикл в
проекте. До фикса 30.07 под `try` стоял только `_is_stream_live`, а само
начисление — нет.

    [1] тик, упавший с исключением, НЕ убивает цикл — следующий тик проходит;
    [2] исключение из handle_stream_start (первый вход в live) тоже переживается;
    [3] нормальные тики начисляют как раньше — фикс не проглотил работу.

## Красный до фикса

    ❌ [1] цикл пережил упавший тик: expected 2, got 1
"""
from __future__ import annotations

import asyncio
import os
import sys
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


class _FakeDB:
    async def list_channels(self):
        return [{"channel_id": CHANNEL_ID, "login": "alice_chan"}]

    async def end_stream_session(self, *a, **kw):
        return None


def _make_bot(fail_on: str, fail_times: int):
    """BotCore без __init__ (сеть/пул не нужны) + подменённые зависимости.

    `fail_on` — какой шаг тика бросает: 'reward' или 'stream_start'.
    """
    import bot_core
    bot = bot_core.BotCore.__new__(bot_core.BotCore)
    bot.running = True
    bot.db = _FakeDB()
    bot.current_stream_id = {}
    calls = {"reward": 0, "stream_start": 0}

    async def _is_live(channel_id=None, login=None):
        return True

    async def _presence(channel_id, login):
        return None

    async def _stream_start(stream_id, channel_id=None):
        calls["stream_start"] += 1
        if fail_on == "stream_start" and calls["stream_start"] <= fail_times:
            raise RuntimeError("boom в handle_stream_start")
        # Настоящий handle_stream_start запоминает id сессии (set_current_stream_id).
        # Без этого цикл считает сессию неоткрытой и переоткрывает её каждый тик.
        bot.current_stream_id[channel_id] = stream_id

    async def _reward(channel_id):
        calls["reward"] += 1
        if fail_on == "reward" and calls["reward"] <= fail_times:
            raise RuntimeError("boom в _reward_points")

    bot._is_stream_live = _is_live
    bot._refresh_presence_from_chat = _presence
    bot.handle_stream_start = _stream_start
    bot._reward_points = _reward
    return bot, calls


async def _run_ticks(bot, ticks: int):
    """Дать циклу отработать N тиков и остановить его.

    CHECK_INTERVAL подменяем на 0 — цикл спит первым делом, ждать минуту нельзя.
    """
    import bot_core
    original = bot_core.CHECK_INTERVAL
    bot_core.CHECK_INTERVAL = 0
    try:
        task = asyncio.create_task(bot.reward_points_loop())
        # Отдаём управление циклу: каждый тик = sleep(0) + работа.
        for _ in range(ticks * 20):
            await asyncio.sleep(0)
        bot.running = False
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        return task
    finally:
        bot_core.CHECK_INTERVAL = original


async def test_reward_failure_does_not_kill_loop():
    print("\n[1] Упавшее начисление не убивает цикл")
    bot, calls = _make_bot(fail_on="reward", fail_times=1)
    await _run_ticks(bot, ticks=3)
    # Первый тик бросил. Если цикл жив — начисление звалось ещё хотя бы раз.
    assert_eq(calls["reward"] >= 2, True,
              f"[1] цикл пережил упавший тик (вызовов начисления: {calls['reward']})")


async def test_stream_start_failure_does_not_kill_loop():
    print("\n[2] Упавший старт сессии не убивает цикл")
    bot, calls = _make_bot(fail_on="stream_start", fail_times=1)
    await _run_ticks(bot, ticks=3)
    assert_eq(calls["reward"] >= 1, True,
              f"[2] начисление пошло после падения старта сессии "
              f"(вызовов: {calls['reward']})")


async def test_healthy_loop_still_pays():
    print("\n[3] Здоровый цикл начисляет как раньше")
    bot, calls = _make_bot(fail_on="none", fail_times=0)
    await _run_ticks(bot, ticks=3)
    assert_eq(calls["reward"] >= 2, True,
              f"[3] начисление идёт каждый тик (вызовов: {calls['reward']})")
    assert_eq(calls["stream_start"], 1,
              "[3] сессия открыта один раз, а не на каждом тике")


async def _run():
    await test_reward_failure_does_not_kill_loop()
    await test_stream_start_failure_does_not_kill_loop()
    await test_healthy_loop_still_pays()


def main():
    print("=" * 70)
    print("AUDIT_SPEC §6 — фоновый цикл переживает исключение в итерации")
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
    print("ALL GREEN ✅ — плохой тик стоит одного тика, а не механики.")
    sys.exit(0)


if __name__ == "__main__":
    main()
