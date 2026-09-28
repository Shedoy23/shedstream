"""
test_mod_offline_gate.py — не принимать заявки, когда игры нет на связи.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_mod_offline_gate.py

ПОВОД (пост-стрим-триаж 06.08). Стрим 05.08 шёл под ДРУГОЙ игрой, а
`active_module` канала остался прежним — расширение продолжало принимать
заявки Bannerlord. Пять зрителей забрали ежедневный бонус: отметка «сегодня
забрал» записалась, заявка легла в очередь, мода не было, через 30 минут
сторож пометил её провалом и вернул `REFUNDED:0`. Ноль здесь ВЕРЕН — дейлик
бесплатный; пропала не валюта, а право забрать бонус в тот день.

Класс ошибки шире, чем «списание и эффект в одной транзакции» в привычном
денежном смысле: невозвратным ресурсом бывает и кулдаун, и лимит, и попытка.

Сценарии:
  1. сигнала не было НИКОГДА → пропускаем (ложный отказ хуже редкой заявки
     в очередь: свежий канал или только что перезапущенный бэкенд);
  2. мод отметился только что → пропускаем;
  3. мод молчит дольше порога → НЕ пропускаем (это и есть фикс);
  4. живы два модуля → активным считается тот, чей сигнал свежее;
  5. отметка переживает перезапуск процесса (кэш в памяти пуст, читаем БД).
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
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


def check(actual, expected, label: str):
    if actual == expected:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: ожидалось {expected!r}, получено {actual!r}"
        _failures.append(msg)
        print(msg)


async def run() -> None:
    import dependencies
    from database import Database
    from migrations import m109_module_last_seen
    import module_liveness
    from routes.bannerlord import _require_live_mod

    tmp = tempfile.mkdtemp(prefix="mod-offline-gate-")
    db = Database(os.path.join(tmp, "test.db"))
    dependencies.set_db(db)
    await db.init_pool()
    await db.init_tables()
    async with db._connect() as conn:
        await m109_module_last_seen.apply(conn)

    try:
        print("\n[1] сигнала не было никогда")
        check(await _require_live_mod(db, CHANNEL_ID), True,
              "пустая история не блокирует заявку")

        print("\n[2] мод отметился только что")
        await module_liveness.touch(db, CHANNEL_ID, "bannerlord")
        check(await _require_live_mod(db, CHANNEL_ID), True,
              "живой мод пропускает заявку")
        check(await module_liveness.is_on_air(db, CHANNEL_ID, "bannerlord"), True,
              "мод считается на связи")

        print("\n[3] мод молчит дольше порога")
        stale = time.time() - (module_liveness.ONLINE_WINDOW_SEC + 120)
        async with db._connect() as conn:
            await conn.execute(
                "UPDATE module_last_seen SET last_seen_ts=? "
                "WHERE channel_id=? AND module_id='bannerlord'",
                (stale, CHANNEL_ID))
            await conn.commit()
        module_liveness._cache.clear()
        module_liveness._last_write.clear()
        check(await module_liveness.is_on_air(db, CHANNEL_ID, "bannerlord"), False,
              "молчащий мод не считается на связи")
        check(await _require_live_mod(db, CHANNEL_ID), False,
              "заявка при молчащем моде ОТКЛОНЯЕТСЯ (это и есть фикс)")

        print("\n[4] живы два модуля — активен тот, чей сигнал свежее")
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO module_last_seen (channel_id, module_id, last_seen_ts) "
                "VALUES (?, 'bannerlord', ?), (?, 'shedcolony', ?) "
                "ON CONFLICT(channel_id, module_id) DO UPDATE SET last_seen_ts=excluded.last_seen_ts",
                (CHANNEL_ID, time.time() - 30, CHANNEL_ID, time.time() - 2))
            await conn.commit()
        module_liveness._cache.clear()
        check(await module_liveness.live_module(db, CHANNEL_ID), "shedcolony",
              "активной считается игра со свежим сигналом")

        print("\n[5] отметка переживает перезапуск процесса")
        module_liveness._cache.clear()
        module_liveness._last_write.clear()
        check(await module_liveness.is_on_air(db, CHANNEL_ID, "shedcolony"), True,
              "после сброса кэша отметка читается из базы")
    finally:
        await db._pool.close()

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("ЕСТЬ ПРОВАЛЫ — гейт не работает:")
        for f in _failures:
            print(f)
    else:
        print("ALL GREEN ✅ — заявки при выключенной игре не принимаются.")


def main() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    # Судим по коду возврата, а не по печати.
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
