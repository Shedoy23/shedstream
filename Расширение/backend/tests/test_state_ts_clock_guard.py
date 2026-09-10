"""
test_state_ts_clock_guard.py — часы мода не должны замораживать зеркало.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_state_ts_clock_guard.py

ЧТО ДОКАЗЫВАЕТ (найдено внешним обзором 2026-09-10).
    Порядок снимков Bannerlord выводится из `ts` — обычных настенных часов на
    машине игрока. Часы врут: NTP-коррекция, севшая батарейка CMOS, разъезд
    UTC/локального времени при двойной загрузке.

    Опасен прыжок ВПЕРЁД. Один снимок с меткой из будущего записывает эту
    метку в `state_ts`, и дальше каждый настоящий снимок оказывается «старее
    применённого» — зеркало зрителя замирает, пока часы не догонят записанное.
    Молча и до перезапуска игры, то есть ровно тот отказ, от которого гейт
    защищает.

    Сервер под NTP, поэтому его часам верить можно. Метка вне правдоподобного
    окна теперь означает «порядок неизвестен»: снимок применяется (потерять
    состояние хуже, чем потерять порядок), но `state_ts` им НЕ отравляется.

    ЭТО СМЯГЧЕНИЕ, А НЕ РЕШЕНИЕ. Порядок, выведенный из настенных часов,
    неверен по построению — надёжно чинится только монотонным счётчиком
    отправок из самого мода. См. `DEFERRED.md`, «Порядок снимков висит на
    часах».

ТЕСТЫ:
    [1] снимок с меткой из будущего всё равно применяется
    [2] метка из будущего НЕ записана в state_ts — маркер не отравлен
    [3] следующий нормальный снимок применяется: зеркало не замёрзло
    [4] защита не отключилась: настоящий устаревший снимок по-прежнему отвергнут
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
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
MIN_MS = 60 * 1000

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


async def _hero(db):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT gold, state_ts FROM bannerlord_heroes "
            "WHERE channel_id=? AND username=?", (CHANNEL_ID, USER))
        return await cur.fetchone()


async def _push(adapter, ts: int, gold: int):
    from modules._base import ModuleEnvelope
    await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
        id=f"env-{ts}-{gold}", kind="event", type="player.state_update", ts=ts,
        data={"username": USER, "gold": gold}))


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
            "VALUES (?, ?, 1000)", (CHANNEL_ID, USER))
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_heroes "
            "(channel_id, username, hero_id, display_name, gold, is_alive) "
            "VALUES (?, ?, 'h1', 'Alice', 0, 1)", (CHANNEL_ID, USER))
        await conn.commit()
    return test_db


async def run():
    db_path = tempfile.mktemp(suffix="_state_ts_clock.db")
    db = await _build_db(db_path)
    try:
        from modules._loader import get_module, discover_modules
        adapter = get_module("bannerlord") or discover_modules().get("bannerlord")
        if adapter is None:
            raise RuntimeError("адаптер bannerlord не загрузился")

        now = int(time.time() * 1000)

        print("\n[1-2] Снимок с часами, убежавшими на 10 минут вперёд")
        await _push(adapter, now + 10 * MIN_MS, 111)
        gold, state_ts = await _hero(db)
        check("снимок применён, состояние не потеряно", gold == 111,
              f"gold={gold}")
        check("метка из будущего не записана в state_ts", state_ts is None,
              f"state_ts={state_ts} — маркер отравлен меткой из будущего")

        print("\n[3] Зеркало не замёрзло: следующий нормальный снимок")
        await _push(adapter, now, 222)
        gold, state_ts = await _hero(db)
        check("нормальный снимок применился", gold == 222,
              f"gold={gold} — зеркало замёрзло из-за чужих часов")

        print("\n[4] Защита порядка при этом не отключилась")
        await _push(adapter, now - 5 * MIN_MS, 333)
        gold, _ = await _hero(db)
        check("настоящий устаревший снимок отвергнут", gold == 222,
              f"gold={gold}, ожидался 222 — устаревший снимок обогнал свежий")
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
