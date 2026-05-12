"""
routes/pets.py — Pets MVP endpoints (Phase 7 of COMPLIANCE_REWORK_PLAN.md).

Compliance critical:
  - §6.2.8: catalog задан extension dev'ом (config + M13 seed), не
    streamer'ом. Endpoint /api/pet/catalog только READS, не accepts
    streamer-uploaded items.
  - §6.2.4: НЕ mystery box. Каждый purchase = specific item_id, не RNG.
  - §5.2: items за loyalty-points OR Bits. У нас — за Bits (когда
    PETS_BITS_REQUIRED=True) или mock (development).
  - §7.5 revenue attribution: pet_purchases.channel_id хранится =
    канал где совершена покупка (revenue split идёт его стримеру).

Endpoints:
  Viewer (JWT-protected):
    GET  /api/pet/my                  — pet + inventory + equipped
    GET  /api/pet/catalog             — список catalog + owned flag
    POST /api/pet/purchase            — body {item_id, bits_receipt?}
    POST /api/pet/equip               — body {item_id} или {slot, item_id:null}
    POST /api/pet/name                — body {name}

  Overlay (public-ish, requires channel_id):
    GET  /api/overlay/pets?channel_id=X — active viewers + pets для render'а

  Streamer:
    POST /api/streamer/pets/overlay-toggle — body {enabled: bool}

DEFERRED post-MVP (известно, по плану):
  - [BITS-SIG] mock-mode default. Production-режим (PETS_BITS_REQUIRED=true)
    включит проверку Twitch Bits transaction JWT signature через
    Twitch extensions JWT lib (HS256 + extension secret). См. покупку
    в `purchase_pet_item` — receipt-idempotency через UNIQUE уже на месте,
    остаётся только signature verify шаг перед TX.
  - [BROADCASTER-JWT] /api/streamer/pets/overlay-toggle сейчас под
    require_admin (HTTPBasic). Self-serve через Twitch config.html будет
    после внедрения broadcaster-JWT (role='broadcaster' в Twitch ext token).
    До тех пор streamer переключает через /admin или просит саппорт.
"""
from fastapi import APIRouter, Depends, Request

from config import PETS_BITS_REQUIRED, PET_SLOTS
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
    return {
        "success":      True,
        "items":        items,
        "bits_required": PETS_BITS_REQUIRED,
    }


@router.post("/api/pet/purchase")
async def pet_purchase(request: Request):
    """Купить cosmetic.

    Body: {"item_id": str, "bits_receipt": str (опц для bits mode)}

    Логика:
      - PETS_BITS_REQUIRED=False → mode='mock', receipt не нужен
      - PETS_BITS_REQUIRED=True → mode='bits', receipt обязателен,
        проверяется UNIQUE-индексом (idempotency)
        Полная signature-verification — см. DEFERRED [BITS-SIG] в docstring модуля

    channel_id из JWT — для revenue attribution (§7.5).
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    item_id = (data.get("item_id") or "").strip()
    bits_receipt = data.get("bits_receipt")
    if not item_id:
        return {"success": False, "message": "item_id обязателен"}

    mode = "bits" if PETS_BITS_REQUIRED else "mock"

    db = get_db()
    result = await db.purchase_pet_item(
        username, item_id,
        channel_id=channel_id,
        bits_receipt=bits_receipt,
        mode=mode,
    )

    if result.get("purchased"):
        hatched = result.get("hatched", False)
        return {
            "success":   True,
            "item_id":   result["item_id"],
            "price_bits": result["price_bits"],
            "mode":      result["mode"],
            "hatched":   hatched,
            "message":   (
                "🐣 Твой пет ВЫЛУПИЛСЯ! Иди наряжай его!" if hatched
                else "✨ Куплено! Иди надевай в инвентарь."
            ),
        }
    reason_msg = {
        "item_not_found":      "Item не найден в catalog",
        "deprecated":          "Item больше не доступен",
        "already_owned":       "У тебя уже есть этот item",
        "receipt_already_used": "Этот чек уже использован",
        "receipt_required":    "Bits-чек обязателен (production mode)",
        "mock_mode_disabled":  "Mock-mode отключён, нужен реальный Bits чек",
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

    viewers = await db.get_active_viewers_with_pets(channel_id, limit=10)
    return {"success": True, "enabled": True, "viewers": viewers}


# ── Streamer-control (admin auth) ─────────────────────────────────────────────

@router.post("/api/streamer/pets/overlay-toggle")
async def streamer_pets_toggle(
    request: Request,
    _admin: str = Depends(require_admin),
):
    """Стример: вкл/выкл pets-overlay на своём канале.

    Body: {"channel_id": int, "enabled": bool}
    """
    data = await request.json()
    try:
        channel_id = int(data.get("channel_id", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверный channel_id"}
    enabled = bool(data.get("enabled", True))

    if channel_id <= 0:
        return {"success": False, "message": "channel_id обязателен"}

    db = get_db()
    await db.set_channel_pets_setting(channel_id, enabled)
    return {
        "success": True,
        "channel_id": channel_id,
        "enabled": enabled,
        "message": f"🎨 Pets-overlay {'включён' if enabled else 'выключен'}",
    }
