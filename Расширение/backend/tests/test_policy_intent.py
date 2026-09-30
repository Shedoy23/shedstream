"""30.09: законы королевства — панель показывает последний итог, мод получает намерение зрителя."""
from __future__ import annotations

import asyncio
import json
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
USER = "policy_king"


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
            await _scenario(db, app_main, diplo)
        finally:
            await db._pool.close()


async def _scenario(db, app_main, diplo):
    if True:
        await db.init_tables()
        await app_main.run_migrations()
        async with db._connect() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id,login,display_name,tier) VALUES (?,'test','Test','free')", (CH,))
            await conn.execute(
                "INSERT INTO bannerlord_heroes (channel_id,username,hero_id,display_name,gold,is_alive,kingdom_id,kingdom_name,is_king,is_clan_leader) "
                "VALUES (?,?,?,?,?,1,'k1','Kingdom',1,1)", (CH, USER, "hero_k", "King", 1000))
            rows = [("serfdom", "enacted", "2026-09-20 10:00:00"), ("serfdom", "removed", "2026-09-21 10:00:00"),
                    ("royal_guard", "enacted", "2026-09-21 11:00:00")]
            for pid, st, at in rows:
                await conn.execute(
                    "INSERT INTO bannerlord_policy_requests (channel_id,requester,kingdom_id,policy_id,policy_name,status,requested_at) "
                    "VALUES (?,?,?,?,?,?,?)", (CH, USER, "k1", pid, pid, st, at))
            await conn.commit()

        # 30.09: закон, отменённый позже, панель показывала действующим.
        old_auth = diplo.require_jwt_user
        diplo.require_jwt_user = lambda _r: (USER, CH)
        try:
            state = await diplo.my_kingdom_state(None)
        finally:
            diplo.require_jwt_user = old_auth
        enacted = {p["policy_id"] for p in state["policies_enacted"]}
        assert enacted == {"royal_guard"}, f"panel shows removed law as active: {enacted}"

        # Что зритель видел, то и хочет: отменённый — ввести, действующий — отменить.
        async with db._connect() as conn:
            r1 = await diplo.handle_enact_policy(conn, CH, USER, {"policy_id": "serfdom", "price": 1500})
            r2 = await diplo.handle_enact_policy(conn, CH, USER, {"policy_id": "royal_guard", "price": 1500})
            await conn.commit()
            wants = {}
            for (data,) in await (await conn.execute(
                    "SELECT data FROM module_actions WHERE channel_id=? AND type='hero.enact_policy'", (CH,))).fetchall():
                d = json.loads(data)
                wants[d["policy_id"]] = d.get("want")
        assert r1.get("success") and r2.get("success"), (r1, r2)
        assert wants == {"serfdom": "enact", "royal_guard": "remove"}, f"intent sent to the game: {wants}"
        print("OK: policy panel shows latest state; intent (enact/remove) sent to the mod")


asyncio.run(main())
