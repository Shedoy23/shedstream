# -*- coding: utf-8 -*-
"""RimWorld paid actions switch to generic outbox only for a live new connector."""
import asyncio
import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
for key, value in (("TWITCH_OAUTH_TOKEN", "x"), ("TWITCH_CLIENT_ID", "x"),
                   ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
                   ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(key, value)


async def main():
    import database
    import module_liveness
    import rimworld
    import dependencies
    from modules._base import ModuleEnvelope
    from modules._loader import load_manifest
    from modules.rimworld._adapter import RimWorldAdapter
    from migrations import m1_multitenant, m5_module_actions, m97_rimworld_tenant_scope
    import aiosqlite

    channel, user, price = 98319857, "moduleviewer", 1500
    path = os.path.join(tempfile.mkdtemp(prefix="rwmodule_"), "test.db")
    db = database.Database(path)
    await db.init_tables()
    async with aiosqlite.connect(path) as conn:
        await m1_multitenant.apply(conn)
        await m5_module_actions.apply(conn)
        await m97_rimworld_tenant_scope.apply(conn)
        await conn.commit()
    await db.add_points(user, 5000, channel_id=channel)
    rimworld.get_db = lambda: db
    dependencies.get_db = lambda: db
    module_liveness._cache[(channel, "rimworld")] = time.time()

    command = {"id": "transport", "type": "equip_item", "username": user,
               "def_name": "TestGun", "channel_id": channel}
    assert await rimworld._charge_and_enqueue(user, channel, price, command)
    async with db._connect() as conn:
        row = await (await conn.execute(
            "SELECT action_id FROM module_actions WHERE channel_id=? AND module_id='rimworld'",
            (channel,))).fetchone()
        generic = (await (await conn.execute(
            "SELECT COUNT(*) FROM module_actions WHERE channel_id=? AND module_id='rimworld'",
            (channel,))).fetchone())[0]
        legacy = (await (await conn.execute(
            "SELECT COUNT(*) FROM rimworld_pending_commands WHERE channel_id=?",
            (channel,))).fetchone())[0]
    assert generic == 1, "new connector must receive exactly one generic action"
    assert legacy == 0, "new connector must not receive a duplicate legacy action"
    assert await db.get_points(user, channel_id=channel) == 3500

    manifest = load_manifest(pathlib.Path(__file__).resolve().parent.parent /
                             "modules" / "rimworld" / "manifest.yaml")
    adapter = RimWorldAdapter(manifest)
    await adapter.handle_event(channel, ModuleEnvelope(
        id="fail-event", kind="event", type="action.failed", ts=0,
        data={"action_id": row[0], "reason": "test_no_effect"}))
    assert await db.get_points(user, channel_id=channel) == 5000
    # Retry must be idempotent.
    await adapter.handle_event(channel, ModuleEnvelope(
        id="fail-event-2", kind="event", type="action.failed", ts=0,
        data={"action_id": row[0], "reason": "retry"}))
    assert await db.get_points(user, channel_id=channel) == 5000
    print("ALL GREEN — generic routing is exclusive and failed ACK refunds once.")
    if getattr(db, "_pool", None):
        await db._pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
