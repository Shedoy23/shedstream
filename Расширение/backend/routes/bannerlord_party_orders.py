"""
Sprint 5.33 (BLT-parity SIEGE) — Party orders.

Endpoints:
  GET /api/bannerlord/party-orders   — мой active order
  GET /api/bannerlord/siege-targets  — list settlement targets viewer'у можно
                                       приказать (proxy для UI dropdown)

Actions:
  hero.party_order_set    — установить новый order (siege/defend/raid/garrison/patrol)
  hero.party_order_release — отменить active order

При set: backend INSERT в bannerlord_party_orders (status='active') —
UNIQUE partial idx гарантирует один active per viewer (другой autoматом
expire'нется до replace), затем enqueue mod-action для engine apply.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request

from auth import require_jwt_user
from dependencies import get_db

log = logging.getLogger(__name__)
router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "auth required"}

VALID_ORDER_TYPES = {"siege", "defend", "patrol", "raid", "garrison"}


@router.get("/api/bannerlord/party-orders")
async def my_party_order(request: Request):
    """Active party order для viewer'а (один максимум)."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT id, order_type, target_settlement_id, target_settlement_name, "
            "       issued_at, expires_at "
            "FROM bannerlord_party_orders "
            "WHERE channel_id=? AND owner_username=? AND status='active' "
            "LIMIT 1",
            (channel_id, username))
        row = await cur.fetchone()

    if not row:
        return {"success": True, "active": None}
    return {
        "success": True,
        "active": {
            "id":                    row[0],
            "order_type":            row[1],
            "target_settlement_id":  row[2],
            "target_settlement_name": row[3],
            "issued_at":             row[4],
            "expires_at":            row[5],
        },
    }


# ─── Action handlers ──────────────────────────────────────────────────────────


async def handle_set_party_order(conn, channel_id: int, owner: str, data: dict) -> dict:
    """Sprint 5.33 SIEGE — set new party order (atomic в TX).

    Cancel old active order (UNIQUE constraint защищает) → INSERT new → enqueue mod.
    Validation: order_type valid, target_settlement_id present для siege/defend/raid/garrison.
    """
    import json as _json
    import uuid as _uuid

    order_type = (data.get("order_type") or "").strip().lower()
    target_id = (data.get("target_settlement_id") or "").strip()
    target_name = (data.get("target_settlement_name") or "").strip() or target_id

    log.info("[SIEGE-SET ENTRY] ch=%s @%s order=%s target='%s' (id=%s)",
             channel_id, owner, order_type, target_name, target_id)

    if order_type not in VALID_ORDER_TYPES:
        log.info("[SIEGE-SET REFUSE] invalid order_type ch=%s @%s raw=%r",
                 channel_id, owner, order_type)
        return {"success": False,
                "message": f"order_type должен быть {'/'.join(VALID_ORDER_TYPES)}"}
    # patrol не требует strict target (area scan), но для UI consistency требуем.
    if not target_id:
        log.info("[SIEGE-SET REFUSE] missing target_settlement_id ch=%s @%s",
                 channel_id, owner)
        return {"success": False, "message": "target_settlement_id required"}

    # Cancel old active order (если есть) — UNIQUE partial idx не позволил бы INSERT.
    await conn.execute(
        "UPDATE bannerlord_party_orders SET status='cancelled' "
        "WHERE channel_id=? AND owner_username=? AND status='active'",
        (channel_id, owner))

    # INSERT new active order. Expiry = +7 game-days (real-time ~30 минут).
    # Backend сам не tracks expiry — mod-side PartyOrderBehavior auto-clears.
    await conn.execute(
        "INSERT INTO bannerlord_party_orders "
        "(channel_id, owner_username, order_type, target_settlement_id, "
        " target_settlement_name, expires_at, status) "
        "VALUES (?, ?, ?, ?, ?, datetime('now', '+30 minutes'), 'active')",
        (channel_id, owner, order_type, target_id, target_name))

    # Enqueue mod-action для apply.
    action_id = _uuid.uuid4().hex
    payload = {
        "initiated_by":           owner,
        "target":                 owner,
        "order_type":             order_type,
        "target_settlement_id":   target_id,
        "target_settlement_name": target_name,
    }
    await conn.execute(
        "INSERT INTO module_actions "
        "(channel_id, module_id, action_id, type, data, status) "
        "VALUES (?, 'bannerlord', ?, 'hero.party_order_set', ?, 'queued')",
        (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))

    log.info("[SIEGE-SET] ch=%s user=@%s order=%s → %s (%s)",
             channel_id, owner, order_type, target_name, target_id)
    return {
        "success": True,
        "message": f"⚔ Приказ: {order_type} → '{target_name}'",
    }


async def handle_release_party_order(conn, channel_id: int, owner: str, data: dict) -> dict:
    """Cancel active order + enqueue mod action для clear engine state."""
    import json as _json
    import uuid as _uuid

    log.info("[SIEGE-RELEASE ENTRY] ch=%s @%s", channel_id, owner)

    cur = await conn.execute(
        "UPDATE bannerlord_party_orders SET status='cancelled' "
        "WHERE channel_id=? AND owner_username=? AND status='active'",
        (channel_id, owner))
    affected = cur.rowcount or 0
    if affected == 0:
        log.info("[SIEGE-RELEASE REFUSE] no active order ch=%s @%s",
                 channel_id, owner)
        return {"success": False, "message": "Нет активного приказа"}

    action_id = _uuid.uuid4().hex
    payload = {
        "initiated_by": owner,
        "target":       owner,
        "order_type":   "release",
    }
    await conn.execute(
        "INSERT INTO module_actions "
        "(channel_id, module_id, action_id, type, data, status) "
        "VALUES (?, 'bannerlord', ?, 'hero.party_order_release', ?, 'queued')",
        (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))

    log.info("[SIEGE-RELEASE] ch=%s user=@%s order cancelled",
             channel_id, owner)
    return {"success": True, "message": "🏳 Приказ отменён"}
