# -*- coding: utf-8 -*-
"""Death notifications preserve pawn details and stay within their channel."""
import asyncio
import tempfile
from pathlib import Path
from test_rimworld_multichannel_runtime import _build_db, JsonRequest, CHANNEL_A, CHANNEL_B, USER

async def main():
    import rimworld as rw
    with tempfile.TemporaryDirectory(prefix="rw-death-") as tmp:
        db = await _build_db(str(Path(tmp) / "test.db"))
        try:
            full = {"username": USER, "pawn_name": "Viewer", "is_alive": True,
                    "health": 0.7, "world_id": "world-1", "world_name": "Colony",
                    "skills": [{"def_name": "Shooting", "level": 12}],
                    "equipment": [{"def_name": "Gun", "slot": "weapon"}]}
            for channel in (CHANNEL_A, CHANNEL_B):
                await rw.sync_pawns_bulk(JsonRequest([full]), mod_channel_id=channel)
            async def state(channel):
                async with db._connect() as conn:
                    row = await (await conn.execute(
                        "SELECT id,pawn_name,is_alive,health,world_id,world_name FROM rimworld_pawns WHERE channel_id=? AND username=?",
                        (channel, USER))).fetchone()
                    skills = await (await conn.execute(
                        "SELECT skill_name,skill_level FROM rimworld_pawn_skills WHERE channel_id=? AND pawn_id=?",
                        (channel,row[0]))).fetchall()
                    return tuple(row[1:]), [tuple(s) for s in skills]
            before = await state(CHANNEL_A)
            death = {"username": USER, "is_alive": False}
            for _ in range(2):
                await rw.sync_pawns_bulk(JsonRequest([death]), mod_channel_id=CHANNEL_A)
                current = await state(CHANNEL_A)
                assert current == (("Viewer",0,0.0,"world-1","Colony"), before[1]), current
                assert await state(CHANNEL_B) == before, "other channel changed"
            await rw.sync_pawns_bulk(JsonRequest([full]), mod_channel_id=CHANNEL_A)
            assert await state(CHANNEL_A) == before, "full snapshot must allow resurrection"
            await rw.sync_pawn(JsonRequest(death), mod_channel_id=CHANNEL_A)
            assert await state(CHANNEL_A) == (("Viewer",0,0.0,"world-1","Colony"),before[1])
            print("PASS: bulk/single death preserves details, retry, tenant isolation, resurrection")
        finally:
            await db._pool.close()

if __name__ == "__main__":
    asyncio.run(main())

