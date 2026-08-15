# -*- coding: utf-8 -*-
"""Manager pairing/auth core.

No HTTP or UI lives here. State transitions are persistent and testable before
public endpoints are exposed. Raw device/refresh secrets are never stored.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

PAIRING_TTL_SECONDS = 10 * 60
ACCESS_TTL_SECONDS = 15 * 60
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
MODULE_CREDENTIAL_TTL_SECONDS = 90 * 24 * 60 * 60
ROTATION_OVERLAP_SECONDS = 10 * 60
APPROVAL_CSRF_TTL_SECONDS = 5 * 60
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_USER_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class ManagerAuthUnavailable(RuntimeError):
    pass


@dataclass
class ManagerAuthError(RuntimeError):
    code: str

    def __str__(self) -> str:
        return self.code


def _pepper() -> bytes:
    value = os.getenv("MANAGER_CREDENTIAL_PEPPER", "").strip()
    if len(value) < 32:
        raise ManagerAuthUnavailable(
            "MANAGER_CREDENTIAL_PEPPER must be a separate secret of at least 32 characters"
        )
    return value.encode("utf-8")


def _hash(label: str, value: str) -> str:
    return hmac.new(_pepper(), f"{label}|{value}".encode(), hashlib.sha256).hexdigest()


def device_challenge(device_secret: str) -> str:
    digest = hashlib.sha256(device_secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _new_user_code() -> str:
    raw = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return raw[:4] + "-" + raw[4:]


def _access_token(session_id: str, channel_id: int, expires_at: int) -> str:
    message = f"{session_id}|{int(channel_id)}|{int(expires_at)}"
    signature = hmac.new(_pepper(), f"access|{message}".encode(), hashlib.sha256).hexdigest()
    return f"slmgr_v1.{session_id}.{expires_at}.{signature}"


def issue_approval_csrf(
    pairing_id: str,
    channel_id: int,
    now: Optional[float] = None,
) -> str:
    now = float(time.time() if now is None else now)
    expires_at = int(now + APPROVAL_CSRF_TTL_SECONDS)
    message = f"{pairing_id}|{int(channel_id)}|{expires_at}"
    signature = hmac.new(
        _pepper(), f"approval_csrf|{message}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{expires_at}.{signature}"


def verify_approval_csrf(
    token: str,
    pairing_id: str,
    channel_id: int,
    now: Optional[float] = None,
) -> bool:
    now = float(time.time() if now is None else now)
    parts = (token or "").split(".")
    if len(parts) != 2:
        return False
    try:
        expires_at = int(parts[0])
    except ValueError:
        return False
    if expires_at <= now:
        return False
    expected = issue_approval_csrf(
        pairing_id, channel_id, now=expires_at - APPROVAL_CSRF_TTL_SECONDS
    )
    return hmac.compare_digest(token, expected)


async def create_pairing(
    conn,
    installation_id: str,
    module_id: str,
    challenge: str,
    now: Optional[float] = None,
) -> dict:
    now = float(time.time() if now is None else now)
    installation_id = (installation_id or "").strip()
    module_id = (module_id or "").strip()
    if not (8 <= len(installation_id) <= 128):
        raise ManagerAuthError("invalid_installation_id")
    if not module_id or not module_id.replace("_", "").isalnum():
        raise ManagerAuthError("invalid_module_id")
    if not _CHALLENGE_RE.fullmatch(challenge or ""):
        raise ManagerAuthError("invalid_device_challenge")

    expires_at = now + PAIRING_TTL_SECONDS
    for _attempt in range(5):
        pairing_id = secrets.token_urlsafe(24)
        user_code = _new_user_code()
        try:
            await conn.execute(
                "INSERT INTO manager_pairings "
                "(id,device_challenge,user_code_hash,installation_id_hash,module_id,status,created_at,expires_at) "
                "VALUES (?,?,?,?,?,'pending',?,?)",
                (
                    pairing_id,
                    challenge,
                    _hash("user_code", user_code),
                    _hash("installation", installation_id),
                    module_id,
                    now,
                    expires_at,
                ),
            )
            break
        except sqlite3.IntegrityError:
            continue
    else:
        await conn.rollback()
        raise ManagerAuthError("pairing_id_collision")
    await conn.commit()
    return {
        "pairing_id": pairing_id,
        "user_code": user_code,
        "expires_at": expires_at,
        "interval": 3,
    }


async def find_pairing_by_user_code(conn, user_code: str, now: Optional[float] = None):
    now = float(time.time() if now is None else now)
    cur = await conn.execute(
        "SELECT id,module_id,status,expires_at,channel_id FROM manager_pairings "
        "WHERE user_code_hash=?",
        (_hash("user_code", (user_code or "").strip().upper()),),
    )
    row = await cur.fetchone()
    if not row:
        raise ManagerAuthError("pairing_not_found")
    if row[3] <= now and row[2] not in ("expired", "exchanged"):
        await conn.execute(
            "UPDATE manager_pairings SET status='expired' WHERE id=?", (row[0],)
        )
        await conn.commit()
        raise ManagerAuthError("pairing_expired")
    return row


async def decide_pairing(
    conn,
    pairing_id: str,
    channel_id: int,
    approve: bool,
    now: Optional[float] = None,
) -> None:
    now = float(time.time() if now is None else now)
    new_status = "approved" if approve else "denied"
    cur = await conn.execute(
        "UPDATE manager_pairings SET status=?,channel_id=?,approved_at=? "
        "WHERE id=? AND status='pending' AND expires_at>?",
        (new_status, int(channel_id), now, pairing_id, now),
    )
    if cur.rowcount != 1:
        await conn.rollback()
        raise ManagerAuthError("pairing_not_pending")
    await conn.commit()


async def exchange_pairing(
    conn,
    pairing_id: str,
    device_secret: str,
    now: Optional[float] = None,
) -> dict:
    now = float(time.time() if now is None else now)
    if len(device_secret or "") < 32:
        raise ManagerAuthError("invalid_device_secret")
    await conn.execute("BEGIN IMMEDIATE")
    try:
        cur = await conn.execute(
            "SELECT device_challenge,installation_id_hash,module_id,channel_id,status,expires_at "
            "FROM manager_pairings WHERE id=?",
            (pairing_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise ManagerAuthError("pairing_not_found")
        if not hmac.compare_digest(row[0], device_challenge(device_secret or "")):
            raise ManagerAuthError("invalid_device_secret")
        if row[5] <= now:
            await conn.execute(
                "UPDATE manager_pairings SET status='expired' "
                "WHERE id=? AND status!='exchanged'",
                (pairing_id,),
            )
            await conn.commit()
            raise ManagerAuthError("pairing_expired")
        if row[4] == "pending":
            raise ManagerAuthError("authorization_pending")
        if row[4] != "approved" or row[3] is None:
            raise ManagerAuthError("pairing_" + row[4])

        session_id = secrets.token_urlsafe(16)
        refresh_secret = secrets.token_urlsafe(32)
        refresh_token = f"slmgrr_v1.{session_id}.{refresh_secret}"
        session_expires = now + SESSION_TTL_SECONDS
        access_expires = int(now + ACCESS_TTL_SECONDS)
        await conn.execute(
            "INSERT INTO manager_sessions "
            "(id,channel_id,installation_id_hash,refresh_hash,refresh_family_id,created_at,expires_at,module_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                session_id,
                int(row[3]),
                row[1],
                _hash("refresh", refresh_token),
                secrets.token_urlsafe(16),
                now,
                session_expires,
                row[2],
            ),
        )
        cur = await conn.execute(
            "UPDATE manager_pairings SET status='exchanged',exchanged_at=? "
            "WHERE id=? AND status='approved'",
            (now, pairing_id),
        )
        if cur.rowcount != 1:
            raise ManagerAuthError("pairing_already_exchanged")
        await conn.commit()
        return {
            "access_token": _access_token(session_id, int(row[3]), access_expires),
            "access_expires_at": access_expires,
            "refresh_token": refresh_token,
            "session_expires_at": session_expires,
            "channel_id": int(row[3]),
            "module_id": row[2],
        }
    except ManagerAuthError:
        if conn.in_transaction:
            await conn.rollback()
        raise
    except Exception:
        if conn.in_transaction:
            await conn.rollback()
        raise


async def verify_access_token(conn, token: str, now: Optional[float] = None) -> Optional[dict]:
    now = float(time.time() if now is None else now)
    parts = (token or "").split(".")
    if len(parts) != 4 or parts[0] != "slmgr_v1":
        return None
    session_id, exp_text, signature = parts[1], parts[2], parts[3]
    try:
        access_expires = int(exp_text)
    except ValueError:
        return None
    if access_expires <= now:
        return None
    cur = await conn.execute(
        "SELECT channel_id,expires_at,revoked_at,module_id FROM manager_sessions WHERE id=?",
        (session_id,),
    )
    row = await cur.fetchone()
    if not row or row[2] is not None or row[1] <= now:
        return None
    expected = _access_token(session_id, int(row[0]), access_expires)
    if not hmac.compare_digest(token, expected):
        return None
    if not row[3]:
        return None
    return {
        "session_id": session_id,
        "channel_id": int(row[0]),
        "module_id": row[3],
    }


async def refresh_manager_session(
    conn,
    refresh_token: str,
    now: Optional[float] = None,
) -> dict:
    now = float(time.time() if now is None else now)
    parts = (refresh_token or "").split(".")
    if len(parts) != 3 or parts[0] != "slmgrr_v1" or not parts[1] or not parts[2]:
        raise ManagerAuthError("invalid_refresh_token")
    session_id = parts[1]
    await conn.execute("BEGIN IMMEDIATE")
    try:
        cur = await conn.execute(
            "SELECT channel_id,installation_id_hash,refresh_hash,refresh_family_id,"
            "expires_at,revoked_at,module_id FROM manager_sessions WHERE id=?",
            (session_id,),
        )
        row = await cur.fetchone()
        supplied_hash = _hash("refresh", refresh_token)
        if not row or not hmac.compare_digest(
            row[2] if row else ("0" * 64), supplied_hash
        ):
            raise ManagerAuthError("invalid_refresh_token")
        if row[5] is not None:
            await conn.execute(
                "UPDATE manager_sessions SET revoked_at=COALESCE(revoked_at,?) "
                "WHERE refresh_family_id=?",
                (now, row[3]),
            )
            await conn.commit()
            raise ManagerAuthError("refresh_reuse_detected")
        if row[4] <= now or int(row[4]) <= now or not row[6]:
            await conn.execute(
                "UPDATE manager_sessions SET revoked_at=COALESCE(revoked_at,?) "
                "WHERE refresh_family_id=?",
                (now, row[3]),
            )
            await conn.commit()
            raise ManagerAuthError("manager_session_expired")

        new_session_id = secrets.token_urlsafe(16)
        new_secret = secrets.token_urlsafe(32)
        new_refresh_token = f"slmgrr_v1.{new_session_id}.{new_secret}"
        access_expires = int(min(now + ACCESS_TTL_SECONDS, row[4]))
        await conn.execute(
            "INSERT INTO manager_sessions "
            "(id,channel_id,installation_id_hash,refresh_hash,refresh_family_id,"
            "created_at,expires_at,module_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                new_session_id,
                int(row[0]),
                row[1],
                _hash("refresh", new_refresh_token),
                row[3],
                now,
                row[4],
                row[6],
            ),
        )
        await conn.execute(
            "UPDATE manager_sessions SET revoked_at=?,last_used_at=? WHERE id=?",
            (now, now, session_id),
        )
        await conn.commit()
        return {
            "access_token": _access_token(
                new_session_id, int(row[0]), access_expires
            ),
            "access_expires_at": access_expires,
            "refresh_token": new_refresh_token,
            "session_expires_at": row[4],
            "channel_id": int(row[0]),
            "module_id": row[6],
        }
    except ManagerAuthError:
        if conn.in_transaction:
            await conn.rollback()
        raise
    except Exception:
        if conn.in_transaction:
            await conn.rollback()
        raise


async def revoke_manager_session(
    conn,
    session_claims: dict,
    now: Optional[float] = None,
) -> None:
    now = float(time.time() if now is None else now)
    session_id = str(session_claims.get("session_id") or "")
    cur = await conn.execute(
        "SELECT refresh_family_id FROM manager_sessions WHERE id=?", (session_id,)
    )
    row = await cur.fetchone()
    if not row:
        raise ManagerAuthError("invalid_manager_session")
    await conn.execute(
        "UPDATE manager_sessions SET revoked_at=COALESCE(revoked_at,?) "
        "WHERE refresh_family_id=?",
        (now, row[0]),
    )
    await conn.commit()


def _credential_scope(session_claims: dict, module_id: str) -> tuple[int, str]:
    module_id = (module_id or "").strip()
    if not module_id or session_claims.get("module_id") != module_id:
        raise ManagerAuthError("module_scope_mismatch")
    try:
        channel_id = int(session_claims["channel_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ManagerAuthError("invalid_manager_session") from exc
    return channel_id, module_id


def _credential_label(label: str) -> str:
    label = " ".join((label or "").strip().split())
    if len(label) > 80:
        raise ManagerAuthError("invalid_credential_label")
    return label


async def _insert_module_credential(
    conn,
    channel_id: int,
    module_id: str,
    label: str,
    now: float,
    rotated_from_id: Optional[str] = None,
) -> dict:
    expires_at = now + MODULE_CREDENTIAL_TTL_SECONDS
    for _attempt in range(5):
        credential_id = secrets.token_urlsafe(18)
        token = f"slmod_v1.{credential_id}.{secrets.token_urlsafe(32)}"
        try:
            await conn.execute(
                "INSERT INTO module_credentials "
                "(id,channel_id,module_id,secret_hash,label,created_at,expires_at,rotated_from_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    credential_id,
                    channel_id,
                    module_id,
                    _hash("module_credential", token),
                    label,
                    now,
                    expires_at,
                    rotated_from_id,
                ),
            )
            return {
                "credential_id": credential_id,
                "module_token": token,
                "module_id": module_id,
                "channel_id": channel_id,
                "label": label,
                "expires_at": expires_at,
            }
        except sqlite3.IntegrityError:
            continue
    raise ManagerAuthError("credential_id_collision")


async def issue_module_credential(
    conn,
    session_claims: dict,
    module_id: str,
    label: str = "",
    now: Optional[float] = None,
) -> dict:
    now = float(time.time() if now is None else now)
    channel_id, module_id = _credential_scope(session_claims, module_id)
    try:
        result = await _insert_module_credential(
            conn, channel_id, module_id, _credential_label(label), now
        )
        await conn.commit()
        return result
    except Exception:
        if conn.in_transaction:
            await conn.rollback()
        raise


async def verify_module_credential(
    conn,
    token: str,
    expected_module_id: str,
    now: Optional[float] = None,
) -> Optional[dict]:
    now = float(time.time() if now is None else now)
    parts = (token or "").split(".")
    if len(parts) != 3 or parts[0] != "slmod_v1" or not parts[1] or not parts[2]:
        return None
    cur = await conn.execute(
        "SELECT channel_id,module_id,secret_hash,expires_at,last_used_at,overlap_until,revoked_at "
        "FROM module_credentials WHERE id=?",
        (parts[1],),
    )
    row = await cur.fetchone()
    if not row or row[1] != expected_module_id or row[6] is not None or row[3] <= now:
        return None
    if row[5] is not None and row[5] <= now:
        return None
    if not hmac.compare_digest(row[2], _hash("module_credential", token)):
        return None
    if row[4] is None or row[4] <= now - 300:
        await conn.execute(
            "UPDATE module_credentials SET last_used_at=? WHERE id=?",
            (now, parts[1]),
        )
        await conn.commit()
    return {
        "credential_id": parts[1],
        "channel_id": int(row[0]),
        "module_id": row[1],
    }


async def rotate_module_credential(
    conn,
    session_claims: dict,
    credential_id: str,
    label: str = "",
    now: Optional[float] = None,
) -> dict:
    now = float(time.time() if now is None else now)
    channel_id, module_id = _credential_scope(
        session_claims, str(session_claims.get("module_id") or "")
    )
    await conn.execute("BEGIN IMMEDIATE")
    try:
        cur = await conn.execute(
            "SELECT label,expires_at,revoked_at,overlap_until FROM module_credentials "
            "WHERE id=? AND channel_id=? AND module_id=?",
            (credential_id, channel_id, module_id),
        )
        row = await cur.fetchone()
        if not row:
            raise ManagerAuthError("credential_not_found")
        if row[2] is not None or row[1] <= now or row[3] is not None:
            raise ManagerAuthError("credential_not_active")
        overlap_until = now + ROTATION_OVERLAP_SECONDS
        await conn.execute(
            "UPDATE module_credentials SET overlap_until=? WHERE id=?",
            (overlap_until, credential_id),
        )
        new_label = _credential_label(label) if label else row[0]
        result = await _insert_module_credential(
            conn, channel_id, module_id, new_label, now, credential_id
        )
        await conn.commit()
        result["overlap_until"] = overlap_until
        return result
    except Exception:
        if conn.in_transaction:
            await conn.rollback()
        raise


async def revoke_module_credential(
    conn,
    session_claims: dict,
    credential_id: str,
    now: Optional[float] = None,
) -> None:
    now = float(time.time() if now is None else now)
    channel_id, module_id = _credential_scope(
        session_claims, str(session_claims.get("module_id") or "")
    )
    cur = await conn.execute(
        "SELECT 1 FROM module_credentials WHERE id=? AND channel_id=? AND module_id=?",
        (credential_id, channel_id, module_id),
    )
    if not await cur.fetchone():
        raise ManagerAuthError("credential_not_found")
    await conn.execute(
        "UPDATE module_credentials SET revoked_at=COALESCE(revoked_at,?) "
        "WHERE id=? AND channel_id=? AND module_id=?",
        (now, credential_id, channel_id, module_id),
    )
    await conn.commit()
