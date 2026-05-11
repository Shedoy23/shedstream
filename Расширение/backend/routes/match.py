"""
routes/match.py — generic matchmaking endpoints (Phase 5.0 of
COMPLIANCE_REWORK_PLAN.md).

Multi-game queue + rooms. Поверх этой инфры будут жить game-specific
endpoints (RPS / TicTacToe / Dice) которые обрабатывают свои moves и
финализируют матчи через db.finalize_match + ELO update.

Endpoints (generic):
  POST /api/match/queue                  — встать в очередь
  GET  /api/match/queue/status           — мой текущий статус (queued/matched/in_room)
  POST /api/match/queue/cancel           — выйти из очереди
  GET  /api/match/room/{room_id}/state   — состояние комнаты (для polling клиентов)

Game-specific endpoints (RPS / TicTacToe / Dice) — отдельные routers,
вызывают эту инфру через БД-helpers.
"""
from fastapi import APIRouter, Request

from config import MATCHMAKING_GAME_TYPES, MATCHMAKING_DEFAULT_ELO_SPREAD
from dependencies import get_db, require_jwt_user

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}


@router.post("/api/match/queue")
async def match_queue_enqueue(request: Request):
    """Встать в очередь matchmaking.

    Body: {"game_type": str, "elo_spread": int (опц)}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    game_type = (data.get("game_type") or "").lower().strip()
    if game_type not in MATCHMAKING_GAME_TYPES:
        return {
            "success": False,
            "message": f"Unsupported game_type. Available: {list(MATCHMAKING_GAME_TYPES)}",
        }

    try:
        elo_spread = int(data.get("elo_spread", MATCHMAKING_DEFAULT_ELO_SPREAD))
    except (TypeError, ValueError):
        elo_spread = MATCHMAKING_DEFAULT_ELO_SPREAD
    # Clamp 50..500 — защита от too-narrow (никогда не матчит) или too-wide (unfair)
    elo_spread = max(50, min(500, elo_spread))

    db = get_db()
    result = await db.enqueue_match(
        username, game_type, elo_spread=elo_spread, channel_id=channel_id,
    )

    if result.get("enqueued"):
        return {
            "success": True,
            "queue_id": result["queue_id"],
            "elo_at_queue": result["elo_at_queue"],
            "message": f"⏳ В очереди {game_type}. Ищем противника...",
        }

    reason = result.get("reason")
    if reason == "already_queued":
        return {
            "success": False,
            "reason": "already_queued",
            "queue_id": result.get("queue_id"),
            "message": "Ты уже в очереди этой игры",
        }
    if reason == "in_active_room":
        return {
            "success": False,
            "reason": "in_active_room",
            "room_id": result.get("room_id"),
            "message": "У тебя уже идёт матч",
        }
    return {"success": False, "message": "Не удалось встать в очередь"}


@router.get("/api/match/queue/status")
async def match_queue_status(request: Request, game_type: str = "rps"):
    """Текущий статус юзера в matchmaking-системе.

    Query: ?game_type=rps (default)
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    game_type = game_type.lower().strip()
    if game_type not in MATCHMAKING_GAME_TYPES:
        return {"success": False, "message": "Unknown game_type"}

    db = get_db()
    status = await db.get_queue_status(username, game_type, channel_id=channel_id)
    return {"success": True, **status}


@router.post("/api/match/queue/cancel")
async def match_queue_cancel(request: Request):
    """Выйти из очереди.

    Body: {"game_type": str}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    game_type = (data.get("game_type") or "").lower().strip()
    if game_type not in MATCHMAKING_GAME_TYPES:
        return {"success": False, "message": "Unknown game_type"}

    db = get_db()
    result = await db.cancel_queue(username, game_type, channel_id=channel_id)

    if result.get("cancelled"):
        return {"success": True, "message": "Вышел из очереди"}
    return {"success": False, "reason": "not_queued", "message": "Ты не в очереди"}


@router.get("/api/match/room/{room_id}/state")
async def match_room_state(room_id: str, request: Request):
    """Состояние комнаты (для polling клиентов после match'а).

    Access-control: только player_a / player_b видят полную state.
    Cross-channel attack blocked.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    room = await db.get_room(room_id, username=username, channel_id=channel_id)

    if not room:
        return {"success": False, "message": "Комната не найдена или нет доступа"}

    return {"success": True, "room": room}
