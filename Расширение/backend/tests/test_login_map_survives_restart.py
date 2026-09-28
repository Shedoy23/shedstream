"""
test_login_map_survives_restart.py — перезапуск не ослепляет открытые панели.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_login_map_survives_restart.py

## Зачем

07.09 владелец прислал скриншот: панель показывает его ник, но баланс 0, доход
+0, квесты 0/0, кейсы 0 и бейдж «Зритель». В базе прода у него в этот момент
лежало 11 058 327💎.

Механизм: логин зрителя резолвится через `dependencies.resolve_jwt_login`,
который для opaque-токена смотрит в `_twitch_login_cache` — словарь В ПАМЯТИ
ПРОЦЕССА, заполняемый при загрузке панели. В базу он не писался. Перезапуск
бэкенда очищал словарь, и у всех, у кого панель УЖЕ открыта, `require_jwt_user`
переставал опознавать зрителя: эндпоинт отвечал HTTP 200 с
`{"status": "unauthorized"}` без поля `points`, а фронт рисовал ноль.

То есть КАЖДЫЙ деплой молча обнулял панель каждому зрителю до перезагрузки
страницы. Триггером того случая был выкат фикса озвучки за 25 минут до
скриншота.

## Чего требуем

1. Связка «Twitch ID → логин» переживает перезапуск: сохранённая до рестарта,
   она поднимается прогревом и логин снова резолвится.
2. Прогрев поднимает ВСЕ ключи, по которым ищет `resolve_jwt_login`, — и
   числовой user_id, и opaque_user_id.
3. Связка обновляется, а не задваивается: сменился логин у того же ID — в базе
   одна строка с новым значением.

## Красный до фикса

С `persist_twitch_login`, превращённой в no-op (то есть с поведением до 07.09),
падает [1]:
    ❌ [1] после рестарта логин резолвится: expected 'alice', got ''
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

USER_ID = "445566778"
OPAQUE = "U7SM4O56SUT9PGNKUOBVH"
LOGIN = "alice"

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
    return test_db


def _simulate_restart():
    """Ровно то, что делает перезапуск процесса: память пуста, база цела."""
    import dependencies
    dependencies._twitch_login_cache.clear()


async def test_survives_restart(db):
    print("\n[1] Связка переживает перезапуск бэкенда")
    import dependencies
    from dependencies import (cache_twitch_login, persist_twitch_login,
                              warm_twitch_login_cache, resolve_jwt_login)

    # Панель зрителя загрузилась и опознала его — как в живом резолве.
    cache_twitch_login(USER_ID, OPAQUE, LOGIN)
    await persist_twitch_login(USER_ID, OPAQUE, LOGIN)

    # JWT такой, какой приходит от Twitch у зрителя, поделившегося личностью:
    # sub — opaque, user_id — числовой.
    jwt_result = {"status": "valid", "username": OPAQUE, "user_id": USER_ID}
    assert_eq(resolve_jwt_login(jwt_result), LOGIN, "[1] до рестарта логин резолвится")

    _simulate_restart()
    assert_eq(resolve_jwt_login(jwt_result), "",
              "[1] сразу после рестарта память пуста — это и ломало панель")

    await warm_twitch_login_cache(db)
    assert_eq(resolve_jwt_login(jwt_result), LOGIN,
              "[1] после рестарта логин резолвится")


async def test_all_lookup_keys_warmed(db):
    print("\n[2] Прогрев поднимает все ключи, по которым идёт поиск")
    import dependencies
    from dependencies import warm_twitch_login_cache, resolve_jwt_login

    _simulate_restart()
    await warm_twitch_login_cache(db)

    # Поиск по opaque без числового user_id — так выглядит токен зрителя,
    # который личностью не делился, но был опознан раньше.
    assert_eq(resolve_jwt_login({"status": "valid", "username": OPAQUE}),
              LOGIN, "[2] по opaque_user_id")
    assert_eq(dependencies._twitch_login_cache.get(USER_ID), LOGIN,
              "[2] по числовому user_id")


async def test_mapping_updates_not_duplicates(db):
    print("\n[3] Смена логина обновляет строку, а не плодит вторую")
    from dependencies import persist_twitch_login

    await persist_twitch_login(USER_ID, OPAQUE, "alice_renamed")
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*), MAX(login) FROM twitch_login_map WHERE key=?",
            (USER_ID,))
        count, login = await cur.fetchone()
    assert_eq(count, 1, "[3] одна строка на ключ")
    assert_eq(login, "alice_renamed", "[3] логин обновился")


async def main_async():
    tmp = tempfile.mkdtemp(prefix="login_map_")
    db_path = os.path.join(tmp, "test.db")
    db = await _build_db(db_path)
    try:
        await test_survives_restart(db)
        await test_all_lookup_keys_warmed(db)
        await test_mapping_updates_not_duplicates(db)
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
