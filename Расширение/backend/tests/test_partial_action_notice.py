"""
test_partial_action_notice.py — «сработало, но не всё» доходит до зрителя.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_partial_action_notice.py

## Зачем

Призыв со свитой резолвит бойцов по сохранённым идентификаторам юнитов. На
сборке, заменившей контент, часть из них не находится — боец пропускается
молча, а действие всё равно отмечается успешным. Зритель платит 50💎 за «героя
со свитой 5/5» и может получить героя одного, не узнав об этом: ни отказа, ни
следа, кроме строки в логе мода (аудит 06.09).

Возвращать деньги не за что — герой пришёл. Поэтому появился отдельный вид
события: не failed и не успех, а «выполнено не полностью».

## Чего требуем

1. Событие `action.partial` кладёт зрителю уведомление с числами.
2. Сумма возврата в нём нулевая — деньги не трогаем.
3. Полный успех (done == requested) уведомления НЕ создаёт — иначе зритель
   получал бы тост после каждого удачного призыва.
4. Мусорные данные (нет зрителя, requested=0) молча игнорируются.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

for _k, _v in (
    ("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "test_client"),
    ("TWITCH_CLIENT_SECRET", "test_secret"), ("TWITCH_BOT_ID", "test_bot"),
    ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
    ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
    ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
):
    os.environ.setdefault(_k, _v)

CH = 990377
USER = "partial_viewer"
fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


async def main() -> int:
    from database import Database
    from dependencies import set_db
    from modules._base import ModuleEnvelope
    from modules.bannerlord._adapter import BannerlordAdapter

    db = Database("viewers.db")
    await db.init_pool()
    set_db(db)
    # Таблицу уведомлений создаёт миграция; в локальной тестовой базе её может
    # не быть, а гонять все миграции ради одной таблицы — минуты.
    async with db._connect() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS viewer_notices ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " channel_id INTEGER NOT NULL, username TEXT NOT NULL,"
            " kind TEXT NOT NULL, text TEXT NOT NULL, amount INTEGER DEFAULT 0,"
            " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, seen_at TIMESTAMP)")
        await conn.commit()
    adapter = BannerlordAdapter.__new__(BannerlordAdapter)

    async def notices():
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT kind, text, amount FROM viewer_notices "
                "WHERE channel_id=? AND username=? ORDER BY id", (CH, USER))
            return await cur.fetchall()

    async def cleanup():
        async with db._connect() as conn:
            await conn.execute("DELETE FROM viewer_notices WHERE channel_id=?", (CH,))
            await conn.commit()

    def env(data):
        return ModuleEnvelope(id="ev", kind="event", type="action.partial", ts=0, data=data)

    try:
        await cleanup()

        await adapter._on_action_partial(CH, env(
            {"action_id": "a1", "username": USER, "kind": "свита", "done": 2, "requested": 5}))
        rows = await notices()
        check("неполный результат оставляет уведомление", len(rows) == 1, str(rows))
        if rows:
            kind, text, amount = rows[0]
            print(f"     (текст: {text!r})")
            check("в тексте есть оба числа", "2" in text and "5" in text, text)
            check("деньги не трогаются", amount == 0, str(amount))

        await adapter._on_action_partial(CH, env(
            {"action_id": "a2", "username": USER, "kind": "свита", "done": 5, "requested": 5}))
        check("полный успех молчит", len(await notices()) == 1, str(await notices()))

        await adapter._on_action_partial(CH, env({"action_id": "a3", "done": 1, "requested": 3}))
        await adapter._on_action_partial(CH, env(
            {"action_id": "a4", "username": USER, "done": 0, "requested": 0}))
        check("мусор игнорируется без падения", len(await notices()) == 1, str(await notices()))
    finally:
        await cleanup()
        try:
            await db._pool.close()
        except Exception:
            pass

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
