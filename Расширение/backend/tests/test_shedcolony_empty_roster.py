"""
test_shedcolony_empty_roster.py — пустая колония значит «пусто», а не «не знаю».

Standalone (без pytest). Запуск из backend/:
    python tests/test_shedcolony_empty_roster.py

ЗАЧЕМ. 28.08 владелец создал НОВУЮ колонию в старом мире. Мод прислал
`colony.snapshot — 0 colonists`, и защита `if not snap: return` с подписью
«colony not loaded yet» пропустила сверку. В результате четверо зрителей
остались `status='active'` на колонистов, которых в колонии нет; каждый из них
заплатил за своего 1000 крустиков.

Допущение защиты было неверным: мод не шлёт снимок для незагруженной колонии —
`ShedReporter.postSnapshot` вызывается только после `targetColony() != null`.
Пустой ростер приходит ровно тогда, когда колония загружена и пуста.

Тест держит три границы:

1. **Пустой ростер убивает старые линки.** Иначе призраки копятся при каждой
   новой колонии.
2. **Грейс 60 секунд переживает пустой ростер.** `player.linked` и снимок
   приходят одной пачкой, и снимок может быть старше свежей привязки —
   без грейса зритель терял бы колониста через секунду после покупки.
3. **Непустой ростер работает как раньше.** Присутствующий в снимке остаётся
   живым, отсутствующий умирает — правку сверки легко перекосить в обе стороны.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
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
os.environ.setdefault("TWITCH_CHANNEL_NAME", "test_channel")

_temp = tempfile.NamedTemporaryFile(prefix="shedlink-empty-roster-", suffix=".db", delete=False)
_temp.close()
_TEST_DB_PATH = Path(_temp.name)
os.environ["DB_PATH"] = str(_TEST_DB_PATH)

from database import Database                              # noqa: E402
from dependencies import set_db, get_db                    # noqa: E402
from modules._base import ModuleEnvelope                   # noqa: E402
from modules.shedcolony._adapter import ShedColonyAdapter  # noqa: E402
import main as main_mod                                    # noqa: E402

CH = 990098                       # синтетический канал — живой мод его не видит
_fails: list = []


def check(name: str, cond: bool) -> None:
    print(("  ✅ " if cond else "  ❌ ") + name)
    if not cond:
        _fails.append(name)


async def _cleanup() -> None:
    async with get_db()._connect() as conn:
        await conn.execute("DELETE FROM shedcolony_colony_link WHERE channel_id=?", (CH,))
        await conn.execute("DELETE FROM shedcolony_colonist_state WHERE channel_id=?", (CH,))
        await conn.execute("DELETE FROM module_actions WHERE channel_id=?", (CH,))
        await conn.commit()


async def _link(viewer: str, citizen: str, age: str) -> None:
    """age — SQL-выражение для linked_at, чтобы отличать старый линк от свежего."""
    async with get_db()._connect() as conn:
        await conn.execute(
            "INSERT INTO shedcolony_colony_link "
            "(channel_id, viewer_id, citizen_id, colony_id, colony_dim, status, linked_at) "
            f"VALUES (?,?,?,'1','','active',{age})", (CH, viewer, citizen))
        await conn.commit()


async def _status(viewer: str):
    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT status FROM shedcolony_colony_link WHERE channel_id=? AND viewer_id=?",
            (CH, viewer))
        r = await cur.fetchone()
    return r[0] if r else None


async def _snapshot(adapter, colonists: list) -> None:
    await adapter._on_colony_snapshot(CH, ModuleEnvelope(
        id="snap", kind="event", type="colony.snapshot", ts=0,
        data={"colonists": colonists}))          # без world_id → world-switch не трогаем


async def main() -> None:
    db = Database(str(_TEST_DB_PATH))
    await db.init_pool()
    await db.init_tables()
    await main_mod.run_migrations()
    set_db(db)
    adapter = ShedColonyAdapter.__new__(ShedColonyAdapter)
    try:
        await _cleanup()

        print("\n[1] Новая колония: снимок пуст — старые привязки умирают")
        # Ровно расклад прода 28.08: линки июля против пустого ростера.
        await _link("july_viewer", "2", "datetime('now','-30 days')")
        await _link("another_july", "18", "datetime('now','-30 days')")
        await _snapshot(adapter, [])
        check("привязка от июля помечена dead", await _status("july_viewer") == "dead")
        check("вторая июльская тоже dead", await _status("another_july") == "dead")

        print("\n[2] Грейс 60 секунд переживает пустой ростер")
        # Продуктовая граница: снимок и player.linked приходят одной пачкой,
        # и снимок бывает старше привязки. Без грейса покупка за 1000 крустиков
        # умирала бы через секунду после оплаты.
        await _link("just_bought", "1", "datetime('now')")
        await _snapshot(adapter, [])
        check("только что купивший остался живым",
              await _status("just_bought") == "active")

        print("\n[3] Непустой ростер работает как раньше")
        await _cleanup()
        await _link("present", "7", "datetime('now','-30 days')")
        await _link("absent", "8", "datetime('now','-30 days')")
        await _snapshot(adapter, [{"id": 7, "name": "[MCLink] present"}])
        check("присутствующий в снимке жив", await _status("present") == "active")
        check("отсутствующий помечен dead", await _status("absent") == "dead")

        print("\n[4] Пустой ростер чистит и стейт-строки, а не падает на SQL")
        # `NOT IN ()` — синтаксическая ошибка SQLite; на пустом snap ветку надо
        # разводить руками, иначе сверка падает ровно в тот момент, ради
        # которого её и правили.
        await _cleanup()
        async with get_db()._connect() as conn:
            await conn.execute(
                "INSERT INTO shedcolony_colonist_state (channel_id, citizen_id) VALUES (?,?)",
                (CH, "42"))
            await conn.commit()
        await _snapshot(adapter, [])
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM shedcolony_colonist_state WHERE channel_id=?", (CH,))
            left = (await cur.fetchone())[0]
        check(f"стейт колонистов вычищен (осталось {left})", left == 0)

    finally:
        await _cleanup()
        await get_db()._pool.close()
        _TEST_DB_PATH.unlink(missing_ok=True)

    print("\n" + "=" * 58)
    if _fails:
        print(f"ПРОВАЛЕНО: {len(_fails)}")
        for f in _fails:
            print("  -", f)
        sys.exit(1)
    print("Все проверки прошли")


if __name__ == "__main__":
    asyncio.run(main())
