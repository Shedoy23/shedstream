"""A game-side refusal must release the action cooldown immediately."""
import asyncio
import json
import tempfile
from pathlib import Path

from test_bannerlord_buy_action import CHANNEL_ID, _build_db


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / "cooldown.db"))
        try:
            from modules._base import ModuleEnvelope
            from modules.bannerlord._adapter import (
                BannerlordAdapter,
                _cooldowns,
                check_cooldown,
                set_cooldown,
            )

            username = "endorphine13"
            action_id = "create-kingdom-not-enough-gold"
            payload = json.dumps({
                "initiated_by": username,
                "target": username,
                "price": 0,
            })
            async with db._connect() as conn:
                await conn.execute(
                    "INSERT INTO module_actions "
                    "(channel_id,module_id,action_id,type,data,status) "
                    "VALUES(?,'bannerlord',?,'hero.create_kingdom',?,'dispatched')",
                    (CHANNEL_ID, action_id, payload),
                )
                await conn.commit()

            _cooldowns.clear()
            set_cooldown(CHANNEL_ID, username, "hero.create_kingdom")
            assert check_cooldown(CHANNEL_ID, username, "hero.create_kingdom") > 1100

            adapter = BannerlordAdapter(None)
            await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
                id="failed", kind="event", type="action.failed", ts=1,
                data={"action_id": action_id, "reason": "not_enough_gold"},
            ))
            assert check_cooldown(CHANNEL_ID, username, "hero.create_kingdom") == 0, (
                "A rejected kingdom action must not lock the viewer out for 1200 seconds"
            )

            # A repeated refusal remains harmless and must not recreate the cooldown.
            await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
                id="failed-again", kind="event", type="action.failed", ts=2,
                data={"action_id": action_id, "reason": "not_enough_gold"},
            ))
            assert check_cooldown(CHANNEL_ID, username, "hero.create_kingdom") == 0
            print("PASS failed action releases cooldown: kingdom refusal and duplicate event")
        finally:
            _cooldowns.clear()
            await db._pool.close()


if __name__ == "__main__":
    asyncio.run(main())
