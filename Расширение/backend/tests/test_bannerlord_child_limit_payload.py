"""
test_bannerlord_child_limit_payload.py — предел детей задаёт СЕРВЕР.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_bannerlord_child_limit_payload.py

ЧТО ДОКАЗЫВАЕТ.
    `MakeBabyHandler.cs` читает предел живых детей из data["max_alive_children"]
    и принимает любое значение 1..20. Бэкенд это поле НЕ ставил, а
    `_charge_execute_enqueue` копирует тело запроса зрителя в mod-bound payload
    (`payload = dict(data)`). Значит `{"max_alive_children": 20}` из панели
    доезжал до мода и поднимал предел впятеро; `1` — наоборот, занижал.

    Прежний гейт проверял наличие строки "DEFAULT_MAX_ALIVE_CHILDREN = 5" в
    исходнике мода и был ЗЕЛЁНЫМ всё время, пока дыра существовала: наличие
    умолчания ничего не говорит о том, можно ли его переопределить.

    Поэтому здесь проверяется ФАКТИЧЕСКИЙ payload в `module_actions` после
    покупки через существующий тестовый путь (тот же, что в
    test_bannerlord_target_spoof.py) — а не текст в файле и не возврат
    внутренней функции.

ТЕСТЫ:
    [1] max_alive_children=20 (завышение)     → в очереди 5
    [2] max_alive_children=1  (занижение)     → в очереди 5
    [3] max_alive_children="много" (мусор)    → в очереди 5
    [4] поле не прислано вовсе                → в очереди 5
    Плюс: цена и прочие условия зачатия не затронуты (hero_gold_cost на месте).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
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
START_POINTS = 500_000

_failures: list = []


def assert_eq(actual, expected, label: str):
    if actual == expected:
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected {expected!r}, got {actual!r}"
        _failures.append(msg)
        print(msg)


def assert_true(cond: bool, label: str):
    if cond:
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected truthy"
        _failures.append(msg)
        print(msg)


def _make_anon_request():
    from starlette.requests import Request
    scope = {"type": "http", "method": "POST",
             "path": "/api/bannerlord/action", "headers": [], "query_string": b""}
    return Request(scope)


async def _latest_payload(db, action_type: str):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT data FROM module_actions "
            "WHERE channel_id=? AND module_id='bannerlord' AND type=? "
            "ORDER BY rowid DESC LIMIT 1",
            (CHANNEL_ID, action_type))
        row = await cur.fetchone()
    return json.loads(row[0] or "{}") if row else None


async def _seed_viewer_with_hero(db, username: str):
    """Зритель + живой герой с КЛАНОМ и золотом: минимум для hero.make_baby.

    Клан обязателен (бесклановый родитель крашит ванильную беременность),
    золото — BABY_COST берётся из Hero.Gold, а не из крустиков.
    """
    from routes.bannerlord import BABY_COST
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
            (CHANNEL_ID, username, START_POINTS))
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_heroes "
            "(channel_id, username, hero_id, display_name, is_alive, gold, clan_name) "
            "VALUES (?, ?, ?, ?, 1, ?, 'ТестКлан')",
            (CHANNEL_ID, username, f"hero_{username}", f"{username} Hero",
             BABY_COST * 10))
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
            "VALUES (?, 'alice_chan', 'Alice Channel', 'free')", (CHANNEL_ID,))
        await conn.commit()
    return test_db


async def _buy_baby(db, buy, username: str, data: dict, label: str):
    """Одна покупка hero.make_baby и разбор того, что легло в очередь."""
    await _seed_viewer_with_hero(db, username)
    payload_data = dict(data)
    payload_data["client_action_id"] = f"baby-{username}"
    res = await buy(_make_anon_request(), username, CHANNEL_ID,
                    "hero.make_baby", payload_data)
    if not res.get("success"):
        assert_true(False, f"{label}: покупка отклонена — {res.get('message')!r}")
        return None
    payload = await _latest_payload(db, "hero.make_baby")
    assert_true(payload is not None, f"{label}: действие попало в очередь")
    return payload


async def run():
    from routes.bannerlord import MAX_ALIVE_CHILDREN, BABY_COST

    # Тот же способ уборки, что в test_bannerlord_target_spoof.py: на Windows
    # TemporaryDirectory падает, пока пул держит файл БД.
    db_path = tempfile.mktemp(suffix="_bnr_child_limit_test.db")
    db = await _build_db(db_path)
    from routes.bannerlord import _bannerlord_buy_action_locked as buy
    try:
        print("\n[1] Клиент завышает предел: max_alive_children=20")
        p = await _buy_baby(db, buy, "greedy", {"max_alive_children": 20},
                            "завышение")
        if p is not None:
            assert_eq(p.get("max_alive_children"), MAX_ALIVE_CHILDREN,
                      "в очередь ушёл СЕРВЕРНЫЙ предел, а не 20")
            assert_eq(p.get("hero_gold_cost"), BABY_COST,
                      "стоимость зачатия не затронута")

        print("\n[2] Клиент занижает предел: max_alive_children=1")
        p = await _buy_baby(db, buy, "shy", {"max_alive_children": 1}, "занижение")
        if p is not None:
            assert_eq(p.get("max_alive_children"), MAX_ALIVE_CHILDREN,
                      "занижение тоже перезаписано серверным пределом")

        print("\n[3] Клиент шлёт мусор: max_alive_children='много'")
        p = await _buy_baby(db, buy, "junk", {"max_alive_children": "много"},
                            "мусор")
        if p is not None:
            assert_eq(p.get("max_alive_children"), MAX_ALIVE_CHILDREN,
                      "нечисловое значение не доезжает до мода")

        print("\n[4] Поле не прислано вовсе (обычная покупка из панели)")
        p = await _buy_baby(db, buy, "normal", {}, "без поля")
        if p is not None:
            assert_eq(p.get("max_alive_children"), MAX_ALIVE_CHILDREN,
                      "мод получает серверный предел и в обычной покупке")

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
