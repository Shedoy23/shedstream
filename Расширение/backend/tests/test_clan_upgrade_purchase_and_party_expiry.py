"""Regression checks for engine-authoritative clan purchases and stale orders."""
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
USER = "upgrade_tester"


class Request:
    async def json(self):
        return {"upgrade_id": "foundation_test"}


class BulkRequest:
    async def json(self):
        return {"upgrade_ids": ["bulk_a", "bulk_b"]}


async def main():
    import dependencies
    import main as app_main
    from database import Database
    from modules._base import ModuleEnvelope
    from modules.bannerlord._adapter import BannerlordAdapter
    from routes import bannerlord
    from routes.bannerlord_party_orders import expire_stale_party_orders

    with tempfile.TemporaryDirectory() as td:
        db = Database(str(Path(td) / "test.db"))
        app_main.db = db
        dependencies.set_db(db)
        await db.init_pool()
        await db.init_tables()
        await app_main.run_migrations()

        async with db._connect() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO channels "
                "(channel_id,login,display_name,tier) VALUES (?,'test','Test','free')",
                (CH,))
            await conn.execute(
                "INSERT INTO bannerlord_heroes "
                "(channel_id,username,hero_id,display_name,gold,is_alive) "
                "VALUES (?,?,?,?,?,1)", (CH, USER, "hero_test", "Test", 500000))
            await conn.execute(
                "INSERT INTO bannerlord_clan_upgrades_catalog "
                "(channel_id,upgrade_id,name,tier,gold_cost,effects_json,deprecated) "
                "VALUES (?,?,?,?,?,?,0)",
                (CH, "foundation_test", "Foundation Test", 1, 400000, "{}"))
            await conn.commit()

        old_auth = bannerlord.require_jwt_user
        old_live = bannerlord._require_live_mod
        bannerlord.require_jwt_user = lambda _request: (USER, CH)
        async def live_mod(_db, _channel_id):
            return True
        bannerlord._require_live_mod = live_mod
        try:
            result = await bannerlord.bannerlord_clan_upgrades_buy(Request())
        finally:
            bannerlord.require_jwt_user = old_auth
            bannerlord._require_live_mod = old_live
        assert result["success"] and result["pending"]

        async with db._connect() as conn:
            gold = (await (await conn.execute(
                "SELECT gold FROM bannerlord_heroes WHERE channel_id=? AND username=?",
                (CH, USER))).fetchone())[0]
            owned = (await (await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_clan_upgrades_owned "
                "WHERE channel_id=? AND username=?", (CH, USER))).fetchone())[0]
            action = await (await conn.execute(
                "SELECT action_id,data FROM module_actions "
                "WHERE channel_id=? AND type='hero.buy_clan_upgrades'", (CH,))).fetchone()
        payload = json.loads(action[1])
        assert gold == 500000, "backend must not debit cached Hero.Gold"
        assert owned == 0, "ownership must wait for engine confirmation"
        assert payload["hero_gold_cost"] == 400000

        adapter = BannerlordAdapter.__new__(BannerlordAdapter)
        async def no_log(*_args, **_kwargs):
            return None
        adapter._log_event = no_log
        env = ModuleEnvelope(
            id="evt", kind="event", type="hero.clan_upgrades_purchased", ts=0,
            data={"username": USER, "action_id": action[0], "gold_after": 100000})
        await adapter._on_clan_upgrades_purchased(CH, env)

        async with db._connect() as conn:
            row = await (await conn.execute(
                "SELECT o.gold_paid,h.gold FROM bannerlord_clan_upgrades_owned o "
                "JOIN bannerlord_heroes h ON h.channel_id=o.channel_id "
                "AND h.username=o.username WHERE o.channel_id=? AND o.username=?",
                (CH, USER))).fetchone()
            assert tuple(row) == (400000, 100000)
            await conn.execute(
                "INSERT INTO bannerlord_party_orders "
                "(channel_id,owner_username,order_type,expires_at,status) "
                "VALUES (?,?,'patrol',datetime('now','-1 minute'),'active')", (CH, USER))
            await conn.commit()
            assert await expire_stale_party_orders(conn, CH, USER) == 1
            await conn.commit()
            status = (await (await conn.execute(
                "SELECT status FROM bannerlord_party_orders "
                "WHERE channel_id=? AND owner_username=?", (CH, USER))).fetchone())[0]
            assert status == "expired"

            # Bulk purchase is only queued too: its toast must not claim success.
            for uid in ("bulk_a", "bulk_b"):
                await conn.execute(
                    "INSERT INTO bannerlord_clan_upgrades_catalog "
                    "(channel_id,upgrade_id,name,tier,gold_cost,effects_json,deprecated) "
                    "VALUES (?,?,?,?,?,?,0)", (CH, uid, uid, 1, 1000, "{}"))
            await conn.commit()

        bannerlord.require_jwt_user = lambda _request: (USER, CH)
        bannerlord._require_live_mod = live_mod
        try:
            bulk = await bannerlord.bannerlord_clan_upgrades_buy(BulkRequest())
        finally:
            bannerlord.require_jwt_user = old_auth
            bannerlord._require_live_mod = old_live
        assert bulk["success"] and bulk["pending"] and bulk["bulk"], bulk
        assert "Куплено" not in bulk["message"], \
            f"queued bulk purchase must not say it is bought: {bulk['message']}"
        assert "отправлена в игру" in bulk["message"], bulk["message"]

        await db._pool.close()
    print("OK: engine-confirmed clan purchase + stale party-order expiry + bulk pending text")


if __name__ == "__main__":
    asyncio.run(main())
