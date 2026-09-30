"""01.10, багрепорт #97: заявка на мир не держит замок после того, как её действие завершилось.

Было: король предложил мир, игра его заключила, строка осталась 'pending'. Война началась
снова — и новое предложение той же фракции падало на частичный UNIQUE: «уже отправлен»,
пока суточный сторож не закроет старую строку.

Свойства:
  1. заявка по ещё живому действию (queued/dispatched) — замок: второе предложение отказ;
  2. действие выполнено (acked/done) — старая заявка 'accepted', новое предложение проходит;
  3. действие провалилось (failed) — старая заявка 'rejected', новое проходит;
  4. чужое направление (другая цель) не трогается.

Запуск:  python tests/test_peace_offer_lock.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test")
os.environ.setdefault("TWITCH_BOT_ID", "test")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CH = 98319857
KING = "peace_king"
passed = failed = 0


def check(cond, msg):
    global passed, failed
    passed, failed = (passed + 1, failed) if cond else (passed, failed + 1)
    print(("  OK   " if cond else "  FAIL ") + msg)


async def main():
    import dependencies
    import main as app_main
    from database import Database
    from routes import bannerlord_diplomacy as diplo

    with tempfile.TemporaryDirectory() as td:
        db = Database(str(Path(td) / "test.db"))
        app_main.db = db
        dependencies.set_db(db)
        await db.init_pool()
        try:
            await db.init_tables()
            await app_main.run_migrations()
            await scenario(db, diplo)
        finally:
            await db._pool.close()
    print("\n%d OK, %d FAIL" % (passed, failed))
    return failed == 0


async def scenario(db, diplo):
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id,login,display_name,tier) VALUES (?,'t','T','free')", (CH,))
        await conn.execute(
            "INSERT INTO bannerlord_heroes (channel_id,username,hero_id,display_name,gold,is_alive,"
            "kingdom_id,kingdom_name,is_king,is_clan_leader) VALUES (?,?,?,?,?,1,'my_k','Моё',1,1)",
            (CH, KING, "hero_k", "King", 1000))
        await conn.commit()

    async def propose(target):
        async with db._connect() as conn:
            r = await diplo.handle_make_peace(conn, CH, KING, {
                "target_kingdom_id": target, "target_kingdom_name": target, "offered_tribute": 100})
            await conn.commit()
            return r

    async def last_offer(target):
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT action_id, status FROM bannerlord_peace_offers WHERE channel_id=? AND target_kingdom_id=? "
                "ORDER BY id DESC LIMIT 1", (CH, target))
            return await cur.fetchone()

    async def set_action(action_id, status):
        async with db._connect() as conn:
            await conn.execute("UPDATE module_actions SET status=? WHERE channel_id=? AND action_id=?",
                               (status, CH, action_id))
            await conn.commit()

    async def statuses(target):
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT status FROM bannerlord_peace_offers WHERE channel_id=? AND target_kingdom_id=? ORDER BY id",
                (CH, target))
            return [r[0] for r in await cur.fetchall()]

    r = await propose("vlandia")
    check(r.get("success") is True, "первое предложение мира проходит")
    first_action, _ = await last_offer("vlandia")

    r = await propose("vlandia")
    check(r.get("success") is False and "уже" in r.get("message", ""),
          "пока действие в пути (queued) — второе предложение той же фракции отказ")

    await set_action(first_action, "acked")
    r = await propose("vlandia")
    check(r.get("success") is True, "мир заключён (действие acked) — новое предложение той же фракции проходит")
    check(await statuses("vlandia") == ["accepted", "pending"],
          "старая заявка закрыта как 'accepted', новая ждёт (%s)" % await statuses("vlandia"))

    second_action, _ = await last_offer("vlandia")
    r2 = await propose("battania")
    check(r2.get("success") is True, "другое направление подаётся независимо")
    await set_action(second_action, "failed")
    r = await propose("vlandia")
    check(r.get("success") is True and (await statuses("vlandia"))[1] == "rejected",
          "действие провалилось — заявка 'rejected', новое предложение проходит")
    check(await statuses("battania") == ["pending"], "заявка к другой фракции не тронута")


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
