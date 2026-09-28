"""
test_module_action_races.py — у платной заявки один исход: эффект ИЛИ возврат.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_module_action_races.py

ЧТО ДОКАЗЫВАЕТ (внешний обзор 2026-09-11, P1 в facdea1).
    Жизнь заявки в module_actions: queued → dispatched (игра забрала) →
    acked/failed. Три участника меняют её статус независимо: опрос мода,
    сторож просроченных `queued` и сторож зависших `dispatched`. У каждого
    проверка «можно ли» и само действие были РАЗНЕСЕНЫ по транзакциям — ровно
    класс из CLAUDE.md «Проверка и действие, которое она разрешает, — в ОДНОЙ
    транзакции». Итог у всех трёх один: зритель получает и эффект, и деньги
    назад.

    [1] Сторож выбрал старую `queued`, игра её забрала, сторож вернул деньги и
        перетёр статус в `failed` (найдено обзором; у ShedColony с 04.07, у
        Bannerlord с 28.07, у RimWorld с 11.09).
    [4] Зеркало: опрос прочитал `queued`, сторож вернул деньги, опрос всё
        равно отдал заявку игре — он отдавал всё прочитанное, а не то, что
        реально пометил. Правка одного обработчика возврата этого не закрывает.
    [5] Сторож `dispatched` вернул в очередь заявку, которую игра только что
        подтвердила: безусловный UPDATE перетёр `acked` в `queued`.

КАК ВОСПРОИЗВОДИМ ДЕТЕРМИНИРОВАННО.
    Соединение подменяется прокси, который ставит ПОМЕЧЕННУЮ задачу на паузу
    ровно перед заданным SQL. Пока она стоит, тест делает то, что сделала бы
    игра или другой участник, затем отпускает. Никаких «запустим и понадеемся».
    Вызываются настоящие сторожа (`main._expire_stale_queued`,
    `main._requeue_stale_dispatched`), настоящие обработчики возврата трёх
    модулей и настоящий опрос `Database.fetch_pending_actions`.

ТЕСТЫ:
    [1] ×3 модуля ×2 статуса: игра забрала заявку между выборкой сторожа и
        возвратом → возврата нет, статус не перетёрт, ложного уведомления нет
    [2] ×3 контроль: заявку никто не забрал → сторож по-прежнему возвращает
    [3] ×3 контроль: отказ, присланный модом по взятой заявке, возвращается
    [4] опрос не отдаёт игре заявку, за которую сторож вернул деньги
    [5] сторож `dispatched` не возвращает в очередь подтверждённую заявку
"""
from __future__ import annotations

import asyncio
import json
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

CH = 98319857
USER = "alice"
START = 100000
PRICE = 200
TTL = 1800
MODULES = ("shedcolony", "bannerlord", "rimworld")
TYPES = {"shedcolony": "colony.festival", "bannerlord": "player.spawn",
         "rimworld": "spawn_pawn"}

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


# ── пауза помеченной задачи перед заданным SQL ──────────────────────────────
_plan: dict = {}


def _pause_at(task_name: str, sql_prefix: str) -> dict:
    p = {"prefix": sql_prefix.upper(), "hit": False,
         "arrived": asyncio.Event(), "go": asyncio.Event()}
    _plan[task_name] = p
    return p


class _Conn:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def execute(self, sql, *a, **kw):
        task = asyncio.current_task()
        p = _plan.get(task.get_name() if task else None)
        if p and not p["hit"] and sql.strip().upper().startswith(p["prefix"]):
            p["hit"] = True
            p["arrived"].set()
            await p["go"].wait()
        return await self._real.execute(sql, *a, **kw)


class _Ctx:
    def __init__(self, real_ctx):
        self._rc = real_ctx

    async def __aenter__(self):
        return _Conn(await self._rc.__aenter__())

    async def __aexit__(self, *a):
        return await self._rc.__aexit__(*a)


class _DB:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def _connect(self):
        return _Ctx(self._real._connect())


async def _wait_paused(p, what: str) -> bool:
    try:
        await asyncio.wait_for(p["arrived"].wait(), timeout=5)
        return True
    except asyncio.TimeoutError:
        check(f"{what}: участник дошёл до точки гонки", False,
              "пауза не сработала — сценарий не воспроизведён, вывод был бы ложным")
        p["go"].set()
        return False


# ── база и заявки ────────────────────────────────────────────────────────────
async def _rows(db, sql, params=()):
    async with db._connect() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


async def _run_sql(db, sql, params=()):
    async with db._connect() as conn:
        await conn.execute(sql, params)
        await conn.commit()


async def _points(db):
    return (await _rows(db, "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                        (CH, USER)))[0][0]


async def _status(db, aid):
    r = await _rows(db, "SELECT status FROM module_actions WHERE channel_id=? AND action_id=?",
                    (CH, aid))
    return r[0][0] if r else None


async def _notices(db):
    return (await _rows(db, "SELECT COUNT(*) FROM viewer_notices WHERE channel_id=? AND username=?",
                        (CH, USER)))[0][0]


async def _new_paid_action(db, module, aid):
    """Платная заявка, купленная два часа назад: деньги списаны, лежит в queued."""
    await _run_sql(db,
        "INSERT INTO module_actions (channel_id, module_id, action_id, type, data, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'queued', datetime('now', '-7200 seconds'))",
        (CH, module, aid, TYPES[module],
         json.dumps({"price": PRICE, "initiated_by": USER})))
    await _run_sql(db, "UPDATE viewers SET points = points - ? WHERE channel_id=? AND username=?",
                   (PRICE, CH, USER))


def _failed_env(aid, reason):
    from modules._base import ModuleEnvelope
    return ModuleEnvelope(id=f"test-{aid}-{reason}", kind="event", type="action.failed",
                          ts=0, data={"action_id": aid, "reason": reason})


async def _build_db(db_path: str):
    import main
    import dependencies
    from database import Database

    real = Database(db_path)
    main.db = real
    dependencies.set_db(real)
    await real.init_pool()
    await real.init_tables()
    await main.run_migrations()
    async with real._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
            "VALUES (?, 'alice_chan', 'Alice', 'free')", (CH,))
        await conn.execute(
            "INSERT OR IGNORE INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
            (CH, USER, START))
        await conn.commit()
    return real


async def run():
    db_path = tempfile.mktemp(suffix="_action_races.db")
    real = await _build_db(db_path)
    try:
        import main
        import dependencies
        from database import Database
        from modules._loader import get_module, discover_modules

        discover_modules()
        adapters = {m: get_module(m) for m in MODULES}
        for m, a in adapters.items():
            if a is None:
                raise RuntimeError(f"адаптер {m} не загрузился")

        proxy = _DB(real)
        dependencies.set_db(proxy)          # обработчики возврата — через прокси
        main.db = real                      # выборка сторожа — напрямую

        print("\n[1] Игра забрала заявку между выборкой сторожа и возвратом")
        for m in MODULES:
            for taken in ("dispatched", "acked"):
                aid = f"race-{m}-{taken}"
                await _new_paid_action(real, m, aid)
                bal, notes = await _points(real), await _notices(real)
                name = f"sweep-{aid}"
                p = _pause_at(name, "BEGIN IMMEDIATE")
                task = asyncio.create_task(main._expire_stale_queued(TTL), name=name)
                if await _wait_paused(p, f"{m}/{taken}"):
                    await _run_sql(real,
                        "UPDATE module_actions SET status=?, dispatched_at=CURRENT_TIMESTAMP "
                        "WHERE channel_id=? AND action_id=?", (taken, CH, aid))
                    p["go"].set()
                await task
                got = await _points(real) - bal
                check(f"{m}/{taken}: за взятую игрой заявку денег не вернули", got == 0,
                      f"вернулось {got}💎 — зритель получил эффект бесплатно "
                      f"(продовый сценарий обзора: queued → выбран → {taken} → возврат → failed)")
                st = await _status(real, aid)
                check(f"{m}/{taken}: статус не перетёрт в failed", st == taken,
                      f"стал {st!r} — успешная заявка записана ошибочной")
                check(f"{m}/{taken}: ложного «крустики вернулись» нет",
                      await _notices(real) == notes,
                      f"уведомлений было {notes}, стало {await _notices(real)}")

        print("\n[2] Контроль: заявку никто не забрал — сторож по-прежнему возвращает")
        for m in MODULES:
            aid = f"ttl-{m}"
            await _new_paid_action(real, m, aid)
            bal = await _points(real)
            await main._expire_stale_queued(TTL)
            check(f"{m}: просроченная невзятая заявка возвращена",
                  await _points(real) - bal == PRICE,
                  f"вернулось {await _points(real) - bal}")
            check(f"{m}: и стала терминальной", await _status(real, aid) == "failed",
                  f"статус {await _status(real, aid)!r}")

        print("\n[3] Контроль: отказ, присланный модом по взятой заявке, возвращается")
        for m in MODULES:
            aid = f"mod-refused-{m}"
            await _new_paid_action(real, m, aid)
            await _run_sql(real,
                "UPDATE module_actions SET status='dispatched', dispatched_at=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND action_id=?", (CH, aid))
            bal = await _points(real)
            await adapters[m].handle_event(CH, _failed_env(aid, "no_effect"))
            check(f"{m}: отказ мода вернул деньги", await _points(real) - bal == PRICE,
                  f"вернулось {await _points(real) - bal} — гейт задел обычный отказ")

        print("\n[4] Опрос не отдаёт игре заявку, за которую уже вернули деньги")
        aid = "poll-race"
        await _new_paid_action(real, "rimworld", aid)
        p = _pause_at("poll", "BEGIN IMMEDIATE")
        poll = asyncio.create_task(
            Database.fetch_pending_actions(proxy, CH, "rimworld", 0, 50), name="poll")
        if await _wait_paused(p, "опрос"):
            # опрос прочитал queued и стоит перед захватом — сторож возвращает деньги
            await adapters["rimworld"].handle_event(CH, _failed_env(aid, "queued_ttl_expired"))
            p["go"].set()
        batch = await poll
        delivered = [r["action_id"] for r in batch]
        check("возвращённая заявка не уехала в игру", aid not in delivered,
              f"опрос выдал {delivered} — игра исполнит то, за что уже вернули деньги")
        check("строка осталась failed", await _status(real, aid) == "failed",
              f"статус {await _status(real, aid)!r}")

        print("\n[5] Сторож dispatched не возвращает в очередь подтверждённую заявку")
        aid = "requeue-race"
        await _new_paid_action(real, "bannerlord", aid)
        await _run_sql(real,
            "UPDATE module_actions SET status='dispatched', dispatched_at=datetime('now','-7200 seconds') "
            "WHERE channel_id=? AND action_id=?", (CH, aid))
        main.db = proxy
        p = _pause_at("requeue", "UPDATE MODULE_ACTIONS SET STATUS='QUEUED'")
        task = asyncio.create_task(main._requeue_stale_dispatched(600), name="requeue")
        if await _wait_paused(p, "сторож dispatched"):
            await _run_sql(real,
                "UPDATE module_actions SET status='acked', acked_at=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND action_id=?", (CH, aid))
            p["go"].set()
        await task
        main.db = real
        st = await _status(real, aid)
        check("подтверждённая заявка осталась acked", st == "acked",
              f"стала {st!r} — выполненная заявка вернулась в очередь, игра исполнит её снова")
    finally:
        _plan.clear()
        try:
            await real._pool.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass


def main_() -> int:
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
    sys.exit(main_())
