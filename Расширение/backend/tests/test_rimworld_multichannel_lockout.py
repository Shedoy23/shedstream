"""
test_rimworld_multichannel_lockout.py — внешний аудит, находка 2: легаси-RimWorld
закрывается, как только каналов становится больше одного.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_rimworld_multichannel_lockout.py

## Что за дыра

`rimworld.py` — легаси-монолит вне tenant-линтера. Изоляции по каналу нет
сразу на трёх путях:

  * `/api/rimworld/commands` берёт канал из токена и НЕ использует его; очередь
    процесса общая, восстановление из БД выбирает команды без `channel_id` —
    мод канала B забирает команду канала A (аудитор воспроизвёл: токен канала
    222 получил команду канала 111 на 150💎);
  * ACK ищет и удаляет строку только по `cmd_id`, без канала;
  * `/api/rimworld/session-start` делает ГЛОБАЛЬНЫЙ `DELETE FROM rimworld_pawns`
    — запуск игры на канале B стирает пешек канала A.

## Почему замок, а не изоляция

Правильная починка — переписать монолит, но в RimWorld сейчас никто не играет,
и проверить правку в игре нечем. Поэтому закрываем ровно то условие, при котором
дефект становится реальным: больше одного канала. Пока канал один — путать
нечего; появится второй — легаси откажет ГРОМКО (503), а не испортит данные тихо.

## Красный до фикса

    ❌ [2] при двух каналах дверь закрыта: expected 503, got пропустила
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
os.environ.setdefault("RIMWORLD_REQUIRE_TOKEN", "0")   # проверяем замок, не токен

CHANNEL_A = 98319857
CHANNEL_B = 12345678

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


class _Req:
    headers: dict = {}


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
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, "
            " tier, approved) VALUES (?, 'a', 'A', 'free', 1)", (CHANNEL_A,))
        await conn.commit()
    return test_db


async def _door_open(rw) -> bool:
    """True, если дверь пропускает (замок не сработал)."""
    from fastapi import HTTPException
    rw._mc_lockout_cache = None          # сбрасываем кэш между сценариями
    try:
        await rw.rimworld_mod_auth(_Req())
        return True
    except HTTPException as ex:
        if ex.status_code == 503:
            return False
        raise


async def _run():
    db_path = tempfile.mktemp(suffix="_rw_lock.db")
    db = await _build_db(db_path)
    try:
        import rimworld as rw

        print("\n[1] Один канал — легаси-RimWorld работает как раньше")
        assert_eq(await _door_open(rw), True,
                  "[1] при одном канале дверь открыта (ничего не сломали)")

        print("\n[2] Появился второй канал — легаси закрывается")
        async with db._connect() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, login, display_name, "
                " tier, approved) VALUES (?, 'b', 'B', 'free', 1)", (CHANNEL_B,))
            await conn.commit()
        assert_eq(await _door_open(rw), False,
                  "[2] при двух каналах дверь закрыта (503)")

        print("\n[3] Неодобренный канал не считается — заявка мода не имеет")
        async with db._connect() as conn:
            await conn.execute("DELETE FROM channels WHERE channel_id=?", (CHANNEL_B,))
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, login, display_name, "
                " tier, approved) VALUES (?, 'c', 'C', 'free', 0)", (CHANNEL_B,))
            await conn.commit()
        assert_eq(await _door_open(rw), True,
                  "[3] ожидающий одобрения канал не запирает работающий")
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
    print("Внешний аудит, находка 2 — замок легаси-RimWorld на мультиканал")
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
    print("ALL GREEN ✅ — второй канал не сможет тихо испортить данные первого.")
    sys.exit(0)


if __name__ == "__main__":
    main()
