"""
routes/pets.py — Pets MVP endpoints (Phase 7 of COMPLIANCE_REWORK_PLAN.md).

Compliance critical:
  - §6.2.8: catalog задан extension dev'ом (config + M13 seed), не
    streamer'ом. Endpoint /api/pet/catalog только READS, не accepts
    streamer-uploaded items.
  - §6.2.4: НЕ mystery box. Каждый purchase = specific item_id, не RNG.
  - §5.2: specific cosmetics are exchanged only for loyalty crystals.  There
    is no Bits or real-money purchase path in the current release.

Endpoints:
  Viewer (JWT-protected):
    GET  /api/pet/my                  — pet + inventory + equipped
    GET  /api/pet/catalog             — список catalog + owned flag
    POST /api/pet/purchase            — body {item_id}
    POST /api/pet/equip               — body {item_id} или {slot, item_id:null}
    POST /api/pet/name                — body {name}

  Overlay (public-ish, requires channel_id):
    GET  /api/overlay/pets?channel_id=X — active viewers + pets для render'а

  Streamer:
    POST /api/streamer/pets/overlay-toggle — body {enabled: bool}

DEFERRED post-MVP (известно, по плану):
  - Bits monetization is intentionally not implemented.  If introduced later,
    it needs a separate Twitch product-catalog and verified transaction flow.
  - [BROADCASTER-JWT] ✅ DONE — /api/streamer/pets/overlay-toggle принимает
    broadcaster-JWT (role='broadcaster' в Twitch ext token); self-serve через
    Twitch config.html без require_admin. (Запись о закрытии пункта.)
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from auth import verify_twitch_jwt
from config import PET_COSMETIC_PRICES, PET_SLOTS
from dependencies import (
    get_db, require_admin, require_jwt_user, resolve_channel_id_or_default,
)

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}


@router.get("/api/pet/my")
async def pet_my(request: Request):
    """Pet + inventory + equipped slots для текущего юзера.

    Cross-channel: pets state global, не зависит от channel_id.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, _channel_id = auth

    db = get_db()
    data = await db.get_my_pet(username)
    return {"success": True, **data}


@router.get("/api/pet/catalog")
async def pet_catalog(request: Request):
    """Список catalog items + owned flag для текущего юзера.

    Public для НЕ авторизованных (без owned-flag). С JWT — с owned-flag.
    """
    auth = require_jwt_user(request)
    username = auth[0] if auth else None

    db = get_db()
    items = await db.list_pet_catalog(include_owned=username)
    # Цена — backend-истина по редкости (тонкий фронт просто рисует price_crustics).
    for it in items:
        it["price_crustics"] = PET_COSMETIC_PRICES.get(it.get("rarity"), PET_COSMETIC_PRICES["common"])
    return {
        "success": True,
        "items":   items,
    }


@router.post("/api/pet/purchase")
async def pet_purchase(request: Request):
    """Купить cosmetic.

    Body: {"item_id": str}.  Price and ownership are enforced server-side.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    item_id = (data.get("item_id") or "").strip()
    if not item_id:
        return {"success": False, "message": "item_id обязателен"}

    db = get_db()
    result = await db.purchase_pet_item(username, item_id, channel_id=channel_id)

    if result.get("purchased"):
        hatched = result.get("hatched", False)
        return {
            "success":  True,
            "item_id":  result["item_id"],
            "price":    result["price"],
            "hatched":  hatched,
            "message":  (
                "🐣 Твой пет ВЫЛУПИЛСЯ! Иди наряжай его!" if hatched
                else "✨ Куплено! Иди надевай в инвентарь."
            ),
        }
    price = result.get("price")
    need = f"{price:,}".replace(",", " ") if price else "?"
    reason_msg = {
        "item_not_found":        "Предмет не найден в каталоге",
        "deprecated":            "Предмет больше не доступен",
        "already_owned":         "У тебя уже есть этот предмет",
        "insufficient_crustics": f"Не хватает крустиков (нужно {need}💎)",
    }.get(result.get("reason"), "Не удалось купить")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/pet/equip")
async def pet_equip(request: Request):
    """Equip cosmetic (catalog slot auto-detected) или unequip slot.

    Body: {"item_id": str} → equip
        OR {"item_id": null, "slot": str} → unequip
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, _channel_id = auth

    data = await request.json()
    item_id = data.get("item_id")
    slot = data.get("slot")

    if item_id is None and slot is None:
        return {"success": False, "message": "item_id или slot обязателен"}
    if slot and slot not in PET_SLOTS:
        return {"success": False, "message": f"Slot должен быть из {PET_SLOTS}"}

    db = get_db()
    result = await db.equip_pet_item(username, item_id, slot)

    if result.get("equipped"):
        action = result.get("action", "equip")
        return {
            "success":  True,
            "slot":     result["slot"],
            "item_id":  result.get("item_id"),
            "action":   action,
            "message":  "✨ Надето!" if action == "equip" else "🗑️ Снято",
        }
    reason_msg = {
        "not_owned":      "Сначала купи этот item",
        "item_not_found": "Item не найден",
        "deprecated":     "Item больше не доступен",
        "invalid_args":   "Неверные параметры",
    }.get(result.get("reason"), "Не удалось")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/pet/name")
async def pet_set_name(request: Request):
    """Юзер задаёт имя своему pet.

    Body: {"name": str | null} (null = удалить имя)
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, _channel_id = auth

    data = await request.json()
    name = data.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            name = None

    db = get_db()
    # ensure pet exists first
    await db.ensure_pet(username)
    updated = await db.set_pet_name(username, name)
    return {"success": True, "name": name, "updated": updated}


# ── Overlay endpoint (для рендера на стрим) ───────────────────────────────────

@router.get("/api/overlay/pets")
async def overlay_pets(channel_id: int = 0):
    """Active viewers с их pets для overlay-рендера.

    Public endpoint (no JWT) т.к. overlay.html не имеет Twitch auth context.
    Защищаем через required channel_id query param.

    Checks: streamer overlay-toggle (если off → []).
    """
    if channel_id <= 0:
        channel_id = resolve_channel_id_or_default()

    db = get_db()
    enabled = await db.get_channel_pets_setting(channel_id)
    if not enabled:
        return {"success": True, "enabled": False, "viewers": []}

    viewers = await db.get_active_viewers_with_pets(channel_id, limit=20)  # ↑ overlay capacity (was 10) — more viewers' pets visible = more activity incentive
    return {"success": True, "enabled": True, "viewers": viewers}


# ── Streamer-control (broadcaster-JWT, self-serve from the Twitch config view) ────

@router.post("/api/streamer/pets/overlay-toggle")
async def streamer_pets_toggle(request: Request):
    """Стример вкл/выкл pets-overlay на СВОЁМ канале — self-serve из Twitch config view.

    Auth: broadcaster-JWT (role='broadcaster'). channel_id берётся ТОЛЬКО из токена —
    бродкастер не может переключать чужой канал (body.channel_id игнорируется).
    Body: {"enabled": bool}
    """
    auth = verify_twitch_jwt(request)
    if auth.get("status") != "valid" or auth.get("role") != "broadcaster":
        return JSONResponse(
            {"success": False, "message": "Доступно только бродкастеру своего канала"},
            status_code=403)
    try:
        channel_id = int(auth.get("channel_id") or 0)
    except (TypeError, ValueError):
        channel_id = 0
    if channel_id <= 0:
        return {"success": False, "message": "В токене нет channel_id"}

    body = await request.json()
    enabled = bool(body.get("enabled", True))

    db = get_db()
    await db.set_channel_pets_setting(channel_id, enabled)
    return {
        "success": True,
        "channel_id": channel_id,
        "enabled": enabled,
        "message": f"🎨 Pets-overlay {'включён' if enabled else 'выключен'}",
    }
