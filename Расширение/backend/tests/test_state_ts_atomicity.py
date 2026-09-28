"""
test_state_ts_atomicity.py — проверка свежести снимка и его запись атомарны.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_state_ts_atomicity.py

ЧТО ДОКАЗЫВАЕТ (найдено внешним обзором 2026-09-10).
    Защита порядка снимков (M123) читала `state_ts` в ОДНОЙ транзакции, а
    применяла снимок в ДРУГОЙ. Между ними — окно, в которое успевает пролезть
    второй конверт. Классика check-then-act.

    Сценарий, который ломает зеркало НАВСЕГДА:
      1. конверт A (ts=1000) проходит проверку и записывает state_ts=1000;
      2. пока A не успел применить данные, приходит B (ts=2000) — он видит
         state_ts=1000, проходит, пишет state_ts=2000 и применяет gold=222;
      3. A просыпается и применяет свои gold=111.

    Итог: в базе `state_ts=2000`, а данные — от снимка 1000. База УТВЕРЖДАЕТ,
    что держит снимок новее, чем держит на самом деле. Любой настоящий снимок
    между 1000 и 2000 после этого отвергается как «устаревший», и зеркало
    зрителя замирает до перезапуска игры — то есть ровно тот дефект, ради
    которого M123 и заводилась.

    Это НЕ теория: окно открывается всегда, когда мод отправил снимок, не
    дождался ответа по таймауту и отправил следующий — сервер продолжает
    обрабатывать первый (доказано внешним обзором 09.09).

КАК ВОСПРОИЗВОДИМ ДЕТЕРМИНИРОВАННО.
    Не «запустим оба и понадеемся»: соединение подменяется прокси, который
    после ПЕРВОГО коммита помеченной задачи ставит её на паузу. У сломанного
    кода первый коммит — это запись state_ts в отдельной транзакции, у
    починенного — вся транзакция целиком, поэтому тест валиден для обеих
    версий и не виснет ни на одной.

ТЕСТЫ:
    [1] после гонки в базе лежат данные СВЕЖЕГО снимка, а не обогнавшего
    [2] state_ts соответствует тем данным, что реально применены
    [3] зеркало не замерло: следующий настоящий снимок принимается
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

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


# ── прокси соединения: пауза после N-го коммита помеченной задачи ────────────
_pause_plan: dict = {}     # имя задачи -> {"after_commit": N, "seen": 0, "ev": Event}


class _ConnProxy:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def execute(self, *a, **kw):
        return await self._real.execute(*a, **kw)

    async def commit(self):
        await self._real.commit()
        task = asyncio.current_task()
        plan = _pause_plan.get(task.get_name() if task else None)
        if plan is not None:
            plan["seen"] += 1
            if plan["seen"] == plan["after_commit"]:
                await plan["ev"].wait()


class _CtxProxy:
    def __init__(self, real_ctx):
        self._real_ctx = real_ctx

    async def __aenter__(self):
        return _ConnProxy(await self._real_ctx.__aenter__())

    async def __aexit__(self, *a):
        return await self._real_ctx.__aexit__(*a)


class _DBProxy:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def _connect(self):
        return _CtxProxy(self._real._connect())


async def _hero(db):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT gold, state_ts FROM bannerlord_heroes "
            "WHERE channel_id=? AND username=?", (CHANNEL_ID, USER))
        return await cur.fetchone()


async def _push(adapter, ts: int, gold: int):
    from modules._base import ModuleEnvelope
    await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
        id=f"env-{ts}", kind="event", type="player.state_update", ts=ts,
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
    db_path = tempfile.mktemp(suffix="_state_ts_atomic.db")
    real_db = await _build_db(db_path)
    import dependencies
    dependencies.set_db(_DBProxy(real_db))
    try:
        from modules._loader import get_module, discover_modules
        adapter = get_module("bannerlord") or discover_modules().get("bannerlord")
        if adapter is None:
            raise RuntimeError("адаптер bannerlord не загрузился")

        print("\n[1-2] Гонка: медленный старый снимок против быстрого нового")
        ev = asyncio.Event()
        _pause_plan["slow-A"] = {"after_commit": 1, "seen": 0, "ev": ev}

        task_a = asyncio.create_task(_push(adapter, 1000, 111), name="slow-A")
        for _ in range(200):                       # даём A дойти до паузы
            await asyncio.sleep(0.005)
            if _pause_plan["slow-A"]["seen"] >= 1:
                break

        # пока A стоит на паузе — B проходит целиком
        await asyncio.create_task(_push(adapter, 2000, 222), name="fast-B")

        ev.set()
        await task_a

        gold, state_ts = await _hero(real_db)
        check("применён свежий снимок, а не обогнавший старый", gold == 222,
              f"gold={gold}, ожидался 222 (снимок ts=2000)")
        check("state_ts описывает те данные, что реально лежат",
              (gold == 222 and state_ts == 2000) or (gold == 111 and state_ts == 1000),
              f"gold={gold} при state_ts={state_ts} — база врёт о своей свежести")

        print("\n[3] Зеркало не замерло: следующий настоящий снимок принят")
        await _push(adapter, 3000, 333)
        gold3, ts3 = await _hero(real_db)
        check("снимок ts=3000 применился", gold3 == 333,
              f"gold={gold3}, state_ts={ts3}")
    finally:
        _pause_plan.clear()
        try:
            await real_db._pool.close()
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
