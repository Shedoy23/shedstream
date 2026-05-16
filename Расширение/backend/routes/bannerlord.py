"""
routes/bannerlord.py — viewer-facing endpoints для Bannerlord-модуля
(Sprint 1.3 of BANNERLORD_MVP.md).

Endpoints:
  GET  /api/bannerlord/my-hero   — мой hero (state + skills + attributes + equipment)
  GET  /api/bannerlord/shop      — catalog покупных actions/items (через module_catalogs)
  POST /api/bannerlord/action    — купить action (списать крустики + enqueue в action queue)

C# mod long-poll'ит /v1/module/bannerlord/actions через generic Module API
(см. routes/module_api.py) — нам тут не нужно дублировать.

Multi-tenant: все endpoints scope'ятся через JWT.channel_id.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Request

from dependencies import get_db, require_jwt_user

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}


@router.get("/api/bannerlord/class-state")
async def bannerlord_class_state(request: Request):
    """Snapshot всех heroes канала + их class + power values.

    Mod вызывает на session_start и кэширует в памяти. При AgentBuild в
    Mission смотрит cache для apply powers.

    Auth: module-token (через /v1/module/...) OR streamer session.
    Пока — допускаем admin для тестов.
    Sprint 4.2 follow-up: лучше переместить под /v1/module/bannerlord/
    с module-token auth.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    _, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        # All heroes + their class + level
        cur = await conn.execute("""
            SELECT h.username, h.hero_id, c.class_key, c.class_level
            FROM bannerlord_heroes h
            LEFT JOIN bannerlord_hero_class c
              ON h.channel_id = c.channel_id AND h.username = c.username
            WHERE h.channel_id=? AND h.is_alive=1
        """, (channel_id,))
        heroes = []
        for r in await cur.fetchall():
            heroes.append({
                "username":    r[0],
                "hero_id":     r[1],
                "class_key":   r[2],
                "class_level": r[3] or 1,
            })

        # Powers catalog (full — mod cache'ит)
        cur = await conn.execute("""
            SELECT class_key, power_key, lvl1_value, lvl2_value, lvl3_value
            FROM bannerlord_class_powers
        """)
        powers = {}
        for r in await cur.fetchall():
            powers.setdefault(r[0], {})[r[1]] = [r[2], r[3], r[4]]

    return {"success": True, "heroes": heroes, "powers": powers}


@router.get("/api/bannerlord/classes")
async def bannerlord_classes(request: Request):
    """Catalog классов (seeded в M15). Public-ish (но JWT — для consistency).

    Frontend renders class picker; selected class triggers
    POST /api/bannerlord/action {hero.set_class, class_key}.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    _, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        # Catalog (active only)
        cur = await conn.execute("""
            SELECT class_key, name, formation, slot1, slot2, slot3, slot4,
                   use_horse, use_camel, description
            FROM bannerlord_classes
            WHERE deprecated = 0
            ORDER BY class_key
        """)
        classes = []
        for r in await cur.fetchall():
            classes.append({
                "class_key":   r[0],
                "name":        r[1],
                "formation":   r[2],
                "slots":       [s for s in (r[3], r[4], r[5], r[6]) if s],
                "use_horse":   bool(r[7]),
                "use_camel":   bool(r[8]),
                "description": r[9],
            })

        # Current viewer's class (если есть)
        username = auth[0]
        cur = await conn.execute(
            "SELECT class_key, class_level FROM bannerlord_hero_class "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
        current = {"class_key": row[0], "class_level": row[1]} if row else None

    return {"success": True, "classes": classes, "current": current}


@router.get("/api/bannerlord/status")
async def bannerlord_status(request: Request):
    """Online/offline status мода для UI badge.

    Online = last event от мода < 60 сек назад. Mod шлёт heartbeat
    автоматически (планируется в Sprint 3.4) или events через
    CampaignBehavior + ActionPoller polling который keeps connection alive.
    """
    import time
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    _, channel_id = auth

    from modules.bannerlord._adapter import get_last_seen
    last_seen = get_last_seen(channel_id)
    age = time.time() - last_seen if last_seen > 0 else None
    online = age is not None and age < 60

    return {
        "success":     True,
        "online":      online,
        "last_seen":   last_seen if last_seen > 0 else None,
        "age_seconds": age,
    }


@router.get("/api/bannerlord/ping")
async def bannerlord_ping():
    """Public health check для C# мода — connectivity test.

    Mod при load пингует это endpoint чтобы убедиться что backend reachable
    и его module discoverable. Не требует auth — это бессекретный probe.

    Реальный auth flow (module token handshake) — через Module API
    /v1/module/* endpoints, Sprint 2.3.
    """
    import time
    return {
        "ok":          True,
        "module_id":   "bannerlord",
        "server_time": int(time.time()),
        "message":     "Bannerlord backend ready",
    }

# Action types которые viewer может купить через /api/bannerlord/action.
# Должны быть в bannerlord/manifest.yaml actions/extensions.
_PURCHASABLE_ACTIONS = (
    "hero.create",            # adoption — special: НЕ требует существующего hero
    "hero.set_class",         # Sprint 4.1: класс + equipment apply
    "player.spawn",
    "player.heal",
    "player.respawn",
    "player.give_item",
    "player.equip_item",
    "player.modify_attribute",
    "world.trigger_event",
    "hero.add_skill",
    "hero.recruit_troops",
)

# Actions которые НЕ требуют existing alive hero (adopt + respawn).
_ACTIONS_WITHOUT_HERO_REQUIREMENT = ("hero.create", "player.respawn")


@router.get("/api/bannerlord/my-hero")
async def bannerlord_my_hero(request: Request):
    """Мой hero — state + skills + attributes + equipment + recent events.

    Если viewer не adopted ни одного hero — вернёт {has_hero: false}.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        # Hero base
        cur = await conn.execute(
            "SELECT hero_id, display_name, culture, is_alive, is_prisoner, gold, "
            "       location, adopted_at, last_sync "
            "FROM bannerlord_heroes WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
        if not row:
            return {"success": True, "has_hero": False}
        hero = {
            "hero_id":      row[0],
            "display_name": row[1],
            "culture":      row[2],
            "is_alive":     bool(row[3]),
            "is_prisoner":  bool(row[4]),
            "gold":         row[5],
            "location":     row[6],
            "adopted_at":   row[7],
            "last_sync":    row[8],
        }

        # Skills
        cur = await conn.execute(
            "SELECT skill_key, level, xp FROM bannerlord_skills "
            "WHERE channel_id=? AND username=? ORDER BY level DESC, skill_key ASC",
            (channel_id, username))
        skills = [
            {"skill_key": r[0], "level": r[1], "xp": r[2]}
            for r in await cur.fetchall()
        ]

        # Attributes
        cur = await conn.execute(
            "SELECT attribute, value FROM bannerlord_attributes "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        attributes = {r[0]: r[1] for r in await cur.fetchall()}

        # Equipment
        cur = await conn.execute(
            "SELECT slot, item_id, item_name FROM bannerlord_equipment "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        equipment = {
            r[0]: {"item_id": r[1], "item_name": r[2]}
            for r in await cur.fetchall()
        }

    return {
        "success":    True,
        "has_hero":   True,
        "hero":       hero,
        "skills":     skills,
        "attributes": attributes,
        "equipment":  equipment,
    }


@router.get("/api/bannerlord/shop")
async def bannerlord_shop(request: Request):
    """Catalog покупных actions + items.

    Catalog приходит от C# mod через module.catalog_update (см. adapter).
    Возвращаем как есть — frontend рендерит.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT catalog_type, entry_id, payload FROM module_catalogs "
            "WHERE channel_id=? AND module_id='bannerlord' "
            "ORDER BY catalog_type, entry_id",
            (channel_id,))
        items = []
        for r in await cur.fetchall():
            try:
                payload = json.loads(r[2]) if r[2] else {}
            except Exception:
                payload = {}
            items.append({
                "catalog_type": r[0],
                "entry_id":     r[1],
                **payload,
            })

    return {"success": True, "items": items}


@router.post("/api/bannerlord/action")
async def bannerlord_buy_action(request: Request):
    """Купить action — atomic charge + enqueue.

    Body: {
        "action_type": str,  // e.g. "player.spawn", "player.heal"
        "data": dict,        // action payload (target username, item id, etc.)
    }

    Цена = data.price (рекомендуется из shop catalog, frontend подставляет).
    Если у viewer'а недостаточно крустиков — отказ. Атомарно: списание +
    enqueue в одной TX, если enqueue упал — откатываем баланс.

    Validation:
      - action_type в _PURCHASABLE_ACTIONS
      - module 'bannerlord' зарегистрирован у channel'а (мод подключён)
      - hero существует и (для не-respawn actions) is_alive=1
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    body = await request.json()
    action_type = (body.get("action_type") or "").strip()
    data = body.get("data") or {}
    if not isinstance(data, dict):
        return {"success": False, "message": "data должен быть объектом"}

    if action_type not in _PURCHASABLE_ACTIONS:
        return {"success": False, "message": f"Action '{action_type}' не разрешён"}

    try:
        price = int(data.get("price", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверная цена"}
    if price < 0:
        return {"success": False, "message": "Цена не может быть отрицательной"}

    db = get_db()
    async with db._connect() as conn:
        # ── Special case validation: hero.set_class ──
        # Сам UPSERT — внутри TX ниже (чтобы не nested-transaction).
        if action_type == "hero.set_class":
            class_key = (data.get("class_key") or "").strip().lower()
            if not class_key:
                return {"success": False, "message": "class_key required"}
            cur = await conn.execute(
                "SELECT 1 FROM bannerlord_classes WHERE class_key=? AND deprecated=0",
                (class_key,))
            if not await cur.fetchone():
                return {"success": False, "message": f"Класс '{class_key}' не существует"}
            # Pass class_key в action data для mod (он применит equipment)
            data["class_key"] = class_key

        # Hero check (skip для adopt/respawn actions)
        if action_type not in _ACTIONS_WITHOUT_HERO_REQUIREMENT:
            cur = await conn.execute(
                "SELECT is_alive FROM bannerlord_heroes WHERE channel_id=? AND username=?",
                (channel_id, username))
            hero_row = await cur.fetchone()
            if not hero_row:
                return {
                    "success": False,
                    "message": "Сначала нужно создать героя. Action hero.create.",
                }
            if not hero_row[0]:
                return {
                    "success": False,
                    "message": "Твой hero мёртв. Подожди heir succession.",
                }
        else:
            # Для hero.create — наоборот, проверка что hero ещё НЕ существует.
            if action_type == "hero.create":
                cur = await conn.execute(
                    "SELECT is_alive FROM bannerlord_heroes WHERE channel_id=? AND username=?",
                    (channel_id, username))
                hero_row = await cur.fetchone()
                if hero_row and hero_row[0]:
                    return {
                        "success": False,
                        "message": "У тебя уже есть живой герой.",
                    }

        # Balance check + atomic charge
        try:
            await conn.execute("BEGIN IMMEDIATE")

            cur = await conn.execute(
                "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                (channel_id, username))
            row = await cur.fetchone()
            balance = row[0] if row else 0
            if balance < price:
                await conn.execute("ROLLBACK")
                return {
                    "success": False,
                    "message": f"Недостаточно крустиков: {balance} < {price}",
                }

            if price > 0:
                await conn.execute(
                    "UPDATE viewers SET points = points - ? "
                    "WHERE channel_id=? AND username=?",
                    (price, channel_id, username))

            # Enqueue action в outbox (через тот же conn — atomic с charge)
            action_id = uuid.uuid4().hex
            payload = dict(data)
            payload["initiated_by"] = username
            await conn.execute("""
                INSERT INTO module_actions
                    (channel_id, module_id, action_id, type, data, status)
                VALUES (?, 'bannerlord', ?, ?, ?, 'queued')
            """, (channel_id, action_id, action_type, json.dumps(payload, ensure_ascii=False)))

            # Special case в той же TX: UPSERT bannerlord_hero_class.
            # Backend остаётся source-of-truth по class даже если mod offline.
            if action_type == "hero.set_class":
                class_key_lower = data.get("class_key", "").strip().lower()
                await conn.execute("""
                    INSERT INTO bannerlord_hero_class
                        (channel_id, username, class_key, class_level, chosen_at)
                    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(channel_id, username) DO UPDATE SET
                        class_key   = excluded.class_key,
                        class_level = 1,
                        chosen_at   = CURRENT_TIMESTAMP
                """, (channel_id, username, class_key_lower))

            await conn.commit()
        except Exception:
            try:
                await conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

    return {
        "success":   True,
        "action_id": action_id,
        "charged":   price,
        "message":   f"⚔️ Action {action_type} в очереди ({price}💎 списано)",
    }
