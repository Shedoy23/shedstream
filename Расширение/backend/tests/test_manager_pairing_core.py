"""Manager pairing core: approve/deny/expire/exchange/session negative tests."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))
os.environ["MANAGER_CREDENTIAL_PEPPER"] = "test-manager-pepper-at-least-32-characters"


async def expect_code(awaitable, expected: str) -> None:
    from manager_auth import ManagerAuthError
    try:
        await awaitable
    except ManagerAuthError as exc:
        assert exc.code == expected, (exc.code, expected)
        return
    raise AssertionError("expected " + expected)


async def main() -> int:
    import aiosqlite
    import manager_auth
    from migrations import m110_manager_credentials

    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_manager_pairing_")
    os.close(fd)
    try:
        secret = "device-secret-with-enough-entropy-for-test"
        async with aiosqlite.connect(path) as conn:
            await m110_manager_credentials.apply(conn)

            created = await manager_auth.create_pairing(
                conn, "installation-0001", "rimworld",
                manager_auth.device_challenge(secret), now=1000,
            )
            row = await manager_auth.find_pairing_by_user_code(
                conn, created["user_code"].lower(), now=1001,
            )
            assert row[0] == created["pairing_id"]
            await expect_code(
                manager_auth.exchange_pairing(conn, created["pairing_id"], "wrong", now=1002),
                "invalid_device_secret",
            )
            await expect_code(
                manager_auth.exchange_pairing(conn, created["pairing_id"], secret, now=1002),
                "authorization_pending",
            )

            await manager_auth.decide_pairing(
                conn, created["pairing_id"], 98319857, True, now=1003,
            )
            tokens = await manager_auth.exchange_pairing(
                conn, created["pairing_id"], secret, now=1004,
            )
            assert tokens["channel_id"] == 98319857
            claims = await manager_auth.verify_access_token(
                conn, tokens["access_token"], now=1005,
            )
            assert claims and claims["channel_id"] == 98319857
            assert await manager_auth.verify_access_token(
                conn, tokens["access_token"][:-1] + "0", now=1005
            ) is None
            assert await manager_auth.verify_access_token(
                conn, tokens["access_token"], now=2000
            ) is None
            await expect_code(
                manager_auth.exchange_pairing(conn, created["pairing_id"], secret, now=1005),
                "pairing_exchanged",
            )

            cur = await conn.execute(
                "SELECT device_challenge,user_code_hash,installation_id_hash FROM manager_pairings "
                "WHERE id=?", (created["pairing_id"],)
            )
            stored = await cur.fetchone()
            assert secret not in stored and created["user_code"] not in stored
            cur = await conn.execute("SELECT refresh_hash FROM manager_sessions")
            assert tokens["refresh_token"] != (await cur.fetchone())[0]

            denied_secret = "second-device-secret-with-32-plus-characters"
            denied = await manager_auth.create_pairing(
                conn, "installation-0002", "rimworld",
                manager_auth.device_challenge(denied_secret), now=2000,
            )
            await manager_auth.decide_pairing(
                conn, denied["pairing_id"], 98319857, False, now=2001,
            )
            await expect_code(
                manager_auth.exchange_pairing(
                    conn, denied["pairing_id"], denied_secret, now=2002
                ),
                "pairing_denied",
            )

            expired = await manager_auth.create_pairing(
                conn, "installation-0003", "rimworld",
                manager_auth.device_challenge("third-device-secret"), now=3000,
            )
            await expect_code(
                manager_auth.find_pairing_by_user_code(
                    conn, expired["user_code"], now=3000 + manager_auth.PAIRING_TTL_SECONDS + 1
                ),
                "pairing_expired",
            )

        # Persistence: access validation still works after reopening the DB.
        async with aiosqlite.connect(path) as reopened:
            claims = await manager_auth.verify_access_token(
                reopened, tokens["access_token"], now=1006,
            )
            assert claims and claims["channel_id"] == 98319857

            pepper = os.environ.pop("MANAGER_CREDENTIAL_PEPPER")
            try:
                try:
                    await manager_auth.create_pairing(
                        reopened, "installation-0004", "rimworld",
                        manager_auth.device_challenge("fourth-device-secret-with-32-plus-characters"),
                        now=4000,
                    )
                    raise AssertionError("missing Manager pepper was accepted")
                except manager_auth.ManagerAuthUnavailable:
                    pass
            finally:
                os.environ["MANAGER_CREDENTIAL_PEPPER"] = pepper
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass

    print("ALL GREEN — pairing transitions, one-time exchange and sessions are safe.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
