# -*- coding: utf-8 -*-
"""routes/notices.py — панель забирает уведомления зрителя (M103, 2026-07-29).

Два эндпоинта, оба под JWT зрителя:

  GET  /api/notices       — непрочитанное (до 10 штук, старые первыми)
  POST /api/notices/ack   — подтвердить, что показали: {"ids": [...]}

Почему подтверждение отдельным запросом, а не «выдал и сразу пометил»: панель
может не получить ответ (свернули оверлей, пропала сеть). Пометить на выдаче —
значит потерять ровно то уведомление, ради которого всё и делалось.

Обратная сторона честная: если панель забрала, показала и не подтвердила,
зритель увидит то же самое ещё раз. Повтор безобиднее пропажи.
"""
from fastapi import APIRouter, Request

import notices as notices_store
from dependencies import get_db, require_jwt_user

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}


@router.get("/api/notices")
async def get_notices(request: Request):
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    items = await notices_store.fetch_unseen(get_db(), channel_id, username)
    return {"success": True, "notices": items}


@router.post("/api/notices/ack")
async def ack_notices(request: Request):
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    try:
        body = await request.json()
    except Exception:
        body = {}
    ids = body.get("ids") or []
    if not isinstance(ids, list):
        return {"success": False, "message": "ids должен быть списком"}
    marked = await notices_store.mark_seen(get_db(), channel_id, username, ids)
    return {"success": True, "marked": marked}
