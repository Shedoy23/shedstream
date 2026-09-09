"""
test_state_update_ordering.py — устаревший снимок состояния НЕ перезаписывает свежий.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_state_update_ordering.py

ЧТО ДОКАЗЫВАЕТ.
    `player.state_update` перезаписывал строку героя вслепую: кто пришёл
    последним, тот и записал. Порядок прихода не связан с порядком отправки, и
    мод его гарантировать НЕ МОЖЕТ:

      * событийный `HeroStateSync.Push` (после покупки, левелапа) идёт
        параллельно периодическому зеркалу;
      * по HTTP-таймауту (35 с) мод не знает, применил сервер запрос или нет —
        «неудачная» отправка может завершиться на сервере ПОЗЖЕ следующей.

    Следствие: в базе остаётся устаревший снимок, а мод считает актуальный
    доставленным и больше его не шлёт — зеркало замирает до следующего
    изменения героя. Клиентская сериализация уменьшает вероятность, но случай
    таймаута не закрывает; порядок обязан защищать тот, кто ПРИМЕНЯЕТ.

    Здесь конверты доставляются НАСТОЯЩЕМУ обработчику в перепутанном порядке и
    проверяется фактическое содержимое `bannerlord_heroes`.

ТЕСТЫ:
    [1] снимки по возрастанию ts применяются
    [2] задержавшийся снимок (ts меньше применённого) ОТБРАСЫВАЕТСЯ
    [3] после отказа свежий снимок по-прежнему применяется (не заблокировали)
    [4] конверт без ts применяется (совместимость со старым модом)
    [5] прыжок часов мода назад (> часа) применяется, а не морозит зеркало
"""
from __future__ import annotations

import asyncio
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

_failures: list = []


def assert_eq(actual, expected, label: str):
    if actual == expected:
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected {expected!r}, got {actual!r}"
        _failures.append(msg)
        print(msg)


async def _gold(db) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT gold FROM bannerlord_heroes WHERE channel_id=? AND username=?",
            (CHANNEL_ID, USER))
        row = await cur.fetchone()
    return row[0] if row else None


async def _deliver(adapter, gold: int, ts):
    """Доставить снимок с заданным ts — как это делает module_api."""
    from modules._base import ModuleEnvelope
    env = ModuleEnvelope(id=f"env{ts}", kind="event", type="player.state_update",
                         ts=ts, data={"username": USER, "gold": gold})
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
            "INSERT OR IGNORE INTO bannerlord_heroes "
            "(channel_id, username, hero_id, display_name, is_alive, gold) "
            "VALUES (?, ?, 'hero_alice', 'Alice Hero', 1, 0)",
            (CHANNEL_ID, USER))
        await conn.commit()
    return test_db


async def run():
    db_path = tempfile.mktemp(suffix="_state_order_test.db")
    db = await _build_db(db_path)
    try:
        # discover_modules() обязателен: реестр наполняется на старте
        # приложения (main.py), в тесте его поднимаем руками — иначе
        # get_module вернёт None (тот же приём, что в
        # test_action_ack_refund_order.py).
        from modules._loader import get_module, discover_modules
        adapter = get_module("bannerlord") or discover_modules().get("bannerlord")
        if adapter is None:
            raise RuntimeError("адаптер bannerlord не загрузился")

        print("\n[1] Снимки по возрастанию ts")
        await _deliver(adapter, gold=100, ts=1_000)
        assert_eq(await _gold(db), 100, "первый снимок применён")
        await _deliver(adapter, gold=200, ts=2_000)
        assert_eq(await _gold(db), 200, "более свежий снимок применён")

        print("\n[2] Задержавшийся снимок приходит ПОСЛЕ свежего")
        # Ровно случай таймаута: мод счёл отправку неудачной и отправил новую,
        # а старый запрос долежал на сервере и завершился позже.
        await _deliver(adapter, gold=999, ts=1_500)
        assert_eq(await _gold(db), 200,
                  "устаревший снимок ОТБРОШЕН, в базе остался свежий")

        print("\n[3] Зеркало не заблокировано отказом")
        await _deliver(adapter, gold=300, ts=3_000)
        assert_eq(await _gold(db), 300, "следующий свежий снимок применён")

        print("\n[4] Конверт без ts (старый мод)")
        await _deliver(adapter, gold=444, ts=0)
        assert_eq(await _gold(db), 444, "без ts применяется как раньше")

        print("\n[5] Часы мода прыгнули назад больше чем на час")
        await _deliver(adapter, gold=500, ts=10_000_000)      # задаём базу
        assert_eq(await _gold(db), 500, "база ts выставлена")
        await _deliver(adapter, gold=600, ts=10_000_000 - 2 * 60 * 60 * 1000)
        assert_eq(await _gold(db), 600,
                  "сброс часов не морозит зеркало — снимок применён")
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
