# -*- coding: utf-8 -*-
"""RimWorld legacy runtime must be isolated by module-token channel.

Standalone:
    cd Расширение/backend
    python tests/test_rimworld_multichannel_runtime.py

This is deliberately stronger than the temporary multi-channel lockout test:
two approved channels must be able to run at the same time without sharing
commands, ACK/refunds, pawns, or session cleanup.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import traceback
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
os.environ.setdefault("RIMWORLD_REQUIRE_TOKEN", "0")

CHANNEL_A = 98319857
CHANNEL_B = 12345678
USER = "same_viewer"

_failures: list[str] = []
_successes: list[str] = []


def check(condition: bool, label: str) -> None:
    if condition:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        _failures.append(label)
        print(f"  ❌ {label}")


class JsonRequest:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


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
        for cid, login in ((CHANNEL_A, "channel_a"), (CHANNEL_B, "channel_b")):
            await conn.execute(
                "INSERT OR IGNORE INTO channels "
                "(channel_id, login, display_name, tier, approved) "
                "VALUES (?, ?, ?, 'free', 1)",
                (cid, login, login),
            )
            await conn.execute(
                "INSERT OR IGNORE INTO viewers (channel_id, username, points) "
                "VALUES (?, ?, 1000)",
                (cid, USER),
            )
        await conn.commit()
    return test_db


async def _balance(db, channel_id: int) -> int:
    return int(await db.get_points(USER, channel_id=channel_id))


async def _run() -> None:
    db_path = tempfile.mktemp(suffix="_rw_multichannel.db")
    db = await _build_db(db_path)
    try:
        import rimworld as rw

        rw.get_pending().clear()

        print("\n[1] Queue delivery is channel-scoped")
        cmd_a = {
            "id": "a_cmd",
            "type": "heal",
            "username": USER,
            "channel_id": CHANNEL_A,
            "price": 150,
        }
        cmd_b = {
            "id": "b_cmd",
            "type": "heal",
            "username": USER,
            "channel_id": CHANNEL_B,
            "price": 150,
        }
        check(
            await rw._charge_and_enqueue(USER, CHANNEL_A, 150, cmd_a),
            "channel A purchase enqueued",
        )
        check(
            await rw._charge_and_enqueue(USER, CHANNEL_B, 150, cmd_b),
            "channel B purchase enqueued",
        )

        commands_a = await rw._get_commands_inner(CHANNEL_A)
        check(
            len(commands_a) == 1 and commands_a[0].get("channel_id") == CHANNEL_A,
            "channel A receives only its own command",
        )
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT channel_id, status FROM rimworld_pending_commands "
                "ORDER BY channel_id"
            )
            statuses = {int(row[0]): row[1] for row in await cur.fetchall()}
        check(statuses.get(CHANNEL_A) == "delivered", "A command marked delivered")
        check(statuses.get(CHANNEL_B) == "queued", "B command remains queued")

        print("\n[2] Cross-channel ACK cannot delete or refund")
        a_id = commands_a[0]["id"]
        before_a = await _balance(db, CHANNEL_A)
        before_b = await _balance(db, CHANNEL_B)
        wrong_ack = await rw.ack_command(
            JsonRequest({"command_id": a_id, "success": False, "message": "wrong channel"}),
            CHANNEL_B,
        )
        check(wrong_ack.get("acked") is False, "foreign ACK is rejected as no-op")
        check(await _balance(db, CHANNEL_A) == before_a, "foreign ACK does not refund A")
        check(await _balance(db, CHANNEL_B) == before_b, "foreign ACK does not credit B")

        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM rimworld_pending_commands "
                "WHERE channel_id=? AND cmd_id=?",
                (CHANNEL_A, a_id),
            )
            still_there = int((await cur.fetchone())[0])
        check(still_there == 1, "foreign ACK does not delete A command")

        own_ack = await rw.ack_command(
            JsonRequest({"command_id": a_id, "success": False, "message": "game refused"}),
            CHANNEL_A,
        )
        check(own_ack.get("acked") is True, "own ACK processes command")
        check(
            await _balance(db, CHANNEL_A) == before_a + 150,
            "own failed ACK refunds exactly once",
        )

        print("\n[3] Pawn snapshots are channel-scoped")
        for cid, pawn_name, trait_def in (
            (CHANNEL_A, "Alice Pawn", "Kind"),
            (CHANNEL_B, "Bob Pawn", "Tough"),
        ):
            result = await rw.sync_pawns_bulk(
                JsonRequest([{
                    "username": USER,
                    "pawn_name": pawn_name,
                    "traits": [{
                        "def_name": trait_def,
                        "degree": 0,
                        "label": trait_def,
                    }],
                }]),
                cid,
            )
            check(result.get("status") == "ok", f"snapshot accepted for channel {cid}")

        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT channel_id, pawn_name FROM rimworld_pawns "
                "WHERE username=? ORDER BY channel_id",
                (USER,),
            )
            pawn_rows = [(int(row[0]), row[1]) for row in await cur.fetchall()]
            cur = await conn.execute(
                "SELECT p.channel_id, t.channel_id, t.trait_def "
                "FROM rimworld_pawns p "
                "JOIN rimworld_pawn_traits t ON t.pawn_id=p.id "
                "WHERE p.username=? ORDER BY p.channel_id",
                (USER,),
            )
            trait_rows = [
                (int(row[0]), int(row[1]), row[2])
                for row in await cur.fetchall()
            ]
        check(
            pawn_rows == [
                (CHANNEL_B, "Bob Pawn"),
                (CHANNEL_A, "Alice Pawn"),
            ],
            "same viewer has independent pawns on A and B",
        )
        check(
            trait_rows == [
                (CHANNEL_B, CHANNEL_B, "Tough"),
                (CHANNEL_A, CHANNEL_A, "Kind"),
            ],
            "pawn detail rows carry the same channel as their parent",
        )

        print("\n[4] Heartbeat status is channel-scoped")
        rw.rimworld_last_heartbeat.clear()
        await rw.rimworld_heartbeat(CHANNEL_A)
        original_require_jwt_channel = rw.require_jwt_channel
        try:
            rw.require_jwt_channel = lambda _request: CHANNEL_A
            status_a = await rw.rimworld_status(object())
            check(status_a.get("online") is True, "channel A sees its mod online")

            rw.require_jwt_channel = lambda _request: CHANNEL_B
            status_b = await rw.rimworld_status(object())
            check(status_b.get("online") is False, "channel B does not inherit A heartbeat")

            await rw.rimworld_offline(CHANNEL_B)
            rw.require_jwt_channel = lambda _request: CHANNEL_A
            status_a_after_b_offline = await rw.rimworld_status(object())
            check(
                status_a_after_b_offline.get("online") is True,
                "channel B offline signal does not hide A",
            )
            await rw.rimworld_offline(CHANNEL_A)
            status_a_offline = await rw.rimworld_status(object())
            check(status_a_offline.get("online") is False, "channel A can mark only itself offline")
        finally:
            rw.require_jwt_channel = original_require_jwt_channel

        print("\n[5] Heal cooldown is self-only and channel-scoped")
        await rw._set_last_heal_ts(USER, time.time(), CHANNEL_A)
        original_require_jwt_user = rw.require_jwt_user
        try:
            rw.require_jwt_user = lambda _request: (USER, CHANNEL_A)
            cooldown_a = await rw.get_heal_cooldown(USER, object())
            check(cooldown_a.get("cooldown_left", 0) > 0, "channel A reads its cooldown")

            rw.require_jwt_user = lambda _request: (USER, CHANNEL_B)
            cooldown_b = await rw.get_heal_cooldown(USER, object())
            check(cooldown_b.get("cooldown_left") == 0, "channel B does not inherit A cooldown")

            denied_status = None
            try:
                await rw.get_heal_cooldown("another_viewer", object())
            except Exception as exc:
                denied_status = getattr(exc, "status_code", None)
            check(denied_status == 403, "viewer cannot read another viewer's cooldown")
        finally:
            rw.require_jwt_user = original_require_jwt_user

        print("\n[6] Session cleanup is channel-scoped")
        async with db._connect() as conn:
            pawn_ids = {}
            for cid, suffix in ((CHANNEL_A, "a"), (CHANNEL_B, "b")):
                cur = await conn.execute(
                    "INSERT INTO rimworld_pawns "
                    "(channel_id, username, pawn_name, is_alive) VALUES (?, ?, ?, 1)",
                    (cid, f"pawn_{suffix}", f"Pawn {suffix.upper()}"),
                )
                pawn_ids[cid] = int(cur.lastrowid)
                await conn.execute(
                    "INSERT INTO rimworld_pawn_traits "
                    "(channel_id, pawn_id, trait_def, degree, label) "
                    "VALUES (?, ?, 'Kind', 0, 'Kind')",
                    (cid, pawn_ids[cid]),
                )
            await conn.commit()

        result = await rw.rimworld_session_start(CHANNEL_B)
        check(result.get("cleared") == 2, "session B reports only its two cleared pawns")
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT channel_id FROM rimworld_pawns "
                "WHERE id IN (?, ?) ORDER BY channel_id",
                (pawn_ids[CHANNEL_A], pawn_ids[CHANNEL_B]),
            )
            remaining_channels = [int(row[0]) for row in await cur.fetchall()]
            cur = await conn.execute(
                "SELECT COUNT(*) FROM rimworld_pawn_traits WHERE pawn_id=?",
                (pawn_ids[CHANNEL_A],),
            )
            a_traits = int((await cur.fetchone())[0])
        check(remaining_channels == [CHANNEL_A], "session B keeps channel A pawn")
        check(a_traits == 1, "session B keeps channel A pawn details")
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass


def main() -> int:
    print("=" * 72)
    print("RimWorld multi-channel runtime isolation")
    print("=" * 72)
    try:
        asyncio.run(_run())
    except Exception:
        print("\n💥 Test harness crashed:")
        traceback.print_exc()
        return 2

    print("\n" + "=" * 72)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        for failure in _failures:
            print(f"  - {failure}")
        return 1
    print("ALL GREEN ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
