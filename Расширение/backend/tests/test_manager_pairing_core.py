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
    from migrations import m110_manager_credentials, m111_manager_session_scope

    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_manager_pairing_")
    os.close(fd)
    try:
        secret = "device-secret-with-enough-entropy-for-test"
        async with aiosqlite.connect(path) as conn:
            await m110_manager_credentials.apply(conn)
            await m111_manager_session_scope.apply(conn)

            csrf = manager_auth.issue_approval_csrf("pairing-csrf", 11, now=100)
            assert manager_auth.verify_approval_csrf(csrf, "pairing-csrf", 11, now=101)
            assert not manager_auth.verify_approval_csrf(csrf, "pairing-csrf", 12, now=101)
            assert not manager_auth.verify_approval_csrf(csrf, "pairing-csrf", 11, now=401)

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
            assert claims["module_id"] == "rimworld"
            await expect_code(
                manager_auth.issue_module_credential(
                    conn, claims, "bannerlord", now=1005
                ),
                "module_scope_mismatch",
            )
            credential = await manager_auth.issue_module_credential(
                conn, claims, "rimworld", "Living room PC", now=1005,
            )
            assert credential["module_token"].startswith("slmod_v1.")
            verified_credential = await manager_auth.verify_module_credential(
                conn, credential["module_token"], "rimworld", now=1006,
            )
            assert verified_credential and verified_credential["channel_id"] == 98319857
            assert await manager_auth.verify_module_credential(
                conn, credential["module_token"], "bannerlord", now=1006,
            ) is None
            module_tampered = credential["module_token"][:-1] + (
                "0" if credential["module_token"][-1] != "0" else "1"
            )
            assert await manager_auth.verify_module_credential(
                conn, module_tampered, "rimworld", now=1006,
            ) is None

            rotated = await manager_auth.rotate_module_credential(
                conn, claims, credential["credential_id"], now=1010,
            )
            assert rotated["module_token"] != credential["module_token"]
            assert await manager_auth.verify_module_credential(
                conn, credential["module_token"], "rimworld", now=1011,
            )
            assert await manager_auth.verify_module_credential(
                conn,
                credential["module_token"],
                "rimworld",
                now=1010 + manager_auth.ROTATION_OVERLAP_SECONDS + 1,
            ) is None
            assert await manager_auth.verify_module_credential(
                conn, rotated["module_token"], "rimworld", now=1011,
            )
            await manager_auth.revoke_module_credential(
                conn, claims, rotated["credential_id"], now=1012,
            )
            await manager_auth.revoke_module_credential(
                conn, claims, rotated["credential_id"], now=1013,
            )
            assert await manager_auth.verify_module_credential(
                conn, rotated["module_token"], "rimworld", now=1014,
            ) is None
            persistent_credential = await manager_auth.issue_module_credential(
                conn, claims, "rimworld", "Restart test", now=1015,
            )
            tampered = tokens["access_token"][:-1] + (
                "0" if tokens["access_token"][-1] != "0" else "1"
            )
            assert await manager_auth.verify_access_token(
                conn, tampered, now=1005
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
            cur = await conn.execute(
                "SELECT secret_hash FROM module_credentials WHERE id=?",
                (persistent_credential["credential_id"],),
            )
            assert persistent_credential["module_token"] != (await cur.fetchone())[0]

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

            logout_secret = "logout-device-secret-with-32-plus-characters"
            logout_pairing = await manager_auth.create_pairing(
                conn, "installation-logout", "rimworld",
                manager_auth.device_challenge(logout_secret), now=4000,
            )
            await manager_auth.decide_pairing(
                conn, logout_pairing["pairing_id"], 98319857, True, now=4001,
            )
            logout_tokens = await manager_auth.exchange_pairing(
                conn, logout_pairing["pairing_id"], logout_secret, now=4002,
            )
            logout_claims = await manager_auth.verify_access_token(
                conn, logout_tokens["access_token"], now=4003,
            )
            await manager_auth.revoke_manager_session(conn, logout_claims, now=4004)
            assert await manager_auth.verify_access_token(
                conn, logout_tokens["access_token"], now=4005,
            ) is None
            await expect_code(
                manager_auth.refresh_manager_session(
                    conn, logout_tokens["refresh_token"], now=4005
                ),
                "refresh_reuse_detected",
            )

            expiry_secret = "expiry-device-secret-with-32-plus-characters"
            expiry_pairing = await manager_auth.create_pairing(
                conn, "installation-expiry", "rimworld",
                manager_auth.device_challenge(expiry_secret), now=5000,
            )
            await manager_auth.decide_pairing(
                conn, expiry_pairing["pairing_id"], 98319857, True, now=5001,
            )
            expiry_tokens = await manager_auth.exchange_pairing(
                conn, expiry_pairing["pairing_id"], expiry_secret, now=5002,
            )
            await expect_code(
                manager_auth.refresh_manager_session(
                    conn,
                    expiry_tokens["refresh_token"],
                    now=expiry_tokens["session_expires_at"] + 1,
                ),
                "manager_session_expired",
            )

        # Persistence: access validation still works after reopening the DB.
        async with aiosqlite.connect(path) as reopened:
            claims = await manager_auth.verify_access_token(
                reopened, tokens["access_token"], now=1006,
            )
            assert claims and claims["channel_id"] == 98319857
            assert await manager_auth.verify_module_credential(
                reopened,
                persistent_credential["module_token"],
                "rimworld",
                now=1016,
            )

            # Two simultaneous refreshes: one rotates, reuse of the old token
            # revokes the complete family, including the winner's new session.
            async with aiosqlite.connect(path) as competitor:
                results = await asyncio.gather(
                    manager_auth.refresh_manager_session(
                        reopened, tokens["refresh_token"], now=1007
                    ),
                    manager_auth.refresh_manager_session(
                        competitor, tokens["refresh_token"], now=1007
                    ),
                    return_exceptions=True,
                )
            rotations = [item for item in results if isinstance(item, dict)]
            reuses = [
                item for item in results
                if isinstance(item, manager_auth.ManagerAuthError)
                and item.code == "refresh_reuse_detected"
            ]
            assert len(rotations) == 1 and len(reuses) == 1, results
            assert await manager_auth.verify_access_token(
                reopened, rotations[0]["access_token"], now=1008,
            ) is None

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

    print("ALL GREEN — pairing, scoped sessions and revocable module credentials are safe.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
