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

        # Sprint 4.7: active powers для current класса viewer'а (для UI кнопок).
        # Фильтруем только active power_keys — passive (hp_multi / armor / skill
        # boosts) не покупаются runtime'ом. Heal_burst — special: доступен всем.
        ACTIVE_POWER_KEYS = (
            "shield_break_burst", "rage", "retribution_toggle"
        )
        current_powers = []
        if current:
            cur = await conn.execute(
                "SELECT power_key, lvl1_value, lvl2_value, lvl3_value "
                "FROM bannerlord_class_powers WHERE class_key = ?",
                (current["class_key"],))
            for pr in await cur.fetchall():
                pk = pr[0]
                if pk not in ACTIVE_POWER_KEYS:
                    continue
                lvl = max(1, min(3, current["class_level"] or 1))
                val = pr[lvl]  # 1→lvl1_value (idx 1), 2→lvl2_value (idx 2), 3→idx 3
                current_powers.append({"power_key": pk, "value": val})

        # heal_burst всегда доступен (не привязан к классу)
        current_powers.append({"power_key": "heal_burst", "value": 50.0})

    return {
        "success": True,
        "classes": classes,
        "current": current,
        "current_powers": current_powers,
    }


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


@router.get("/api/bannerlord/my-buffs")
async def bannerlord_my_buffs(request: Request):
    """Sprint 4.6/4.8 — active buffs + cooldowns для viewer'а.

    Buffs: текущие активные active powers (rage / retribution_toggle).
      State в `_adapter.py:_active_buffs`, обновляется через mod'овые
      buff.activated/buff.expired. Reset на supervisor restart — mod
      повторно пошлёт buff.activated если buff ещё активен.

    Cooldowns (4.8): remaining seconds до следующей разрешённой активации
      каждого power_key. Set'ится при /action для power.activate.

    Response: { success, buffs: [{power_key, remaining_s}],
                       cooldowns: [{power_key, remaining_s}] }
    Frontend polling 2.5с + client-side decrement для smooth countdown.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    from modules.bannerlord._adapter import get_active_buffs, get_active_cooldowns
    return {
        "success":   True,
        "buffs":     get_active_buffs(channel_id, username),
        "cooldowns": get_active_cooldowns(channel_id, username),
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
    "power.activate",         # Sprint 4.3: active power burst
    "hero.upgrade_gear",      # Sprint M20: 6-tier equipment progression
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

# Sprint M20: gear upgrade costs (крустиков) per target tier 1..6.
# Прогрессивно — T6 требует серьёзного гринда.
TIER_COSTS = {
    1:    50_000,
    2:   100_000,
    3:   200_000,
    4:   400_000,
    5:   800_000,
    6: 1_500_000,
}

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
        # Hero base + M19 meta + M20 gear_tier
        cur = await conn.execute(
            "SELECT hero_id, display_name, culture, is_alive, is_prisoner, gold, "
            "       location, adopted_at, last_sync, level, clan_name, kingdom_name, "
            "       gear_tier "
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
            "level":        row[9] or 1,
            "clan_name":    row[10],
            "kingdom_name": row[11],
            "gear_tier":    row[12] or 0,
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

    # Sprint 5.1c/5.2: server-side price enforcement.
    # Frontend ставит price для отображения, но мы OVERRIDE — viewer не
    # может отправить price:0 и купить за бесплатно.
    RANDOM_EQUIP_PRICES = {
        "weapon": 1_000_000,
        "armor":    500_000,
        "horse":  1_250_000,
    }
    SPAWN_PRICES = {
        "player": 500,    # на сторону стримера (ally)
        "enemy":  1000,   # против стримера — 2× as тролл-tax
    }
    MOUNTED_CLASSES = {
        "cavalry", "camel_cavalry", "horse_archer", "camel_archer", "knight"
    }

    if action_type == "player.equip_item":
        random_category = (data.get("random_category") or "").strip().lower()
        if random_category:
            if random_category not in RANDOM_EQUIP_PRICES:
                return {
                    "success": False,
                    "message": f"Категория '{random_category}' не разрешена "
                               "(weapon / armor / horse)",
                }
            # Mounted-class gate для horse
            if random_category == "horse":
                db_tmp = get_db()
                async with db_tmp._connect() as conn:
                    cur = await conn.execute(
                        "SELECT class_key FROM bannerlord_hero_class "
                        "WHERE channel_id=? AND username=?",
                        (channel_id, username))
                    row = await cur.fetchone()
                    class_key = (row[0] or "").lower() if row else ""
                if class_key not in MOUNTED_CLASSES:
                    return {
                        "success": False,
                        "message": "Конь доступен только для конных классов "
                                   "(cavalry / horse_archer / camel_* / knight)",
                    }
            # Server-side override клиентской цены
            data["price"] = RANDOM_EQUIP_PRICES[random_category]

    if action_type == "player.spawn":
        side = (data.get("side") or "player").strip().lower()
        if side not in SPAWN_PRICES:
            return {"success": False, "message": f"Side '{side}' не разрешён"}
        data["side"] = side
        data["price"] = SPAWN_PRICES[side]

    # Sprint M20: hero.upgrade_gear — server-side resolve target_tier + price.
    # Frontend кнопка не передаёт target_tier (защита от viewer-side абуза),
    # backend читает current gear_tier из БД и инкрементирует на +1.
    gear_upgrade_target_tier = None
    if action_type == "hero.upgrade_gear":
        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            # Need class_key + current gear_tier
            cur = await conn.execute(
                "SELECT h.gear_tier, c.class_key "
                "FROM bannerlord_heroes h "
                "LEFT JOIN bannerlord_hero_class c "
                "  ON c.channel_id=h.channel_id AND c.username=h.username "
                "WHERE h.channel_id=? AND h.username=?",
                (channel_id, username))
            row = await cur.fetchone()
        if not row:
            return {"success": False, "message": "Сначала создай героя"}
        current_tier = row[0] or 0
        class_key = (row[1] or "").lower()
        if not class_key:
            return {
                "success": False,
                "message": "Сначала выбери класс — он определяет slot template",
            }
        if current_tier >= 6:
            return {
                "success": False,
                "message": "Снаряжение уже T6 — выше некуда",
            }
        target_tier = current_tier + 1
        data["class_key"] = class_key
        data["target_tier"] = target_tier
        data["price"] = TIER_COSTS[target_tier]
        gear_upgrade_target_tier = target_tier

    try:
        price = int(data.get("price", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверная цена"}
    if price < 0:
        return {"success": False, "message": "Цена не может быть отрицательной"}

    # Sprint 4.8/5.0: server-side cooldown enforcement.
    # Для power.activate ключ cooldown'а = data.power_key (per-power).
    # Для player.spawn — сам action_type (один cooldown на summon вообще).
    # Frontend disable — UX only; реальная защита здесь.
    cooldown_key = None
    if action_type == "power.activate":
        cooldown_key = (data.get("power_key") or "").strip().lower() or None
    elif action_type == "player.spawn":
        cooldown_key = "player.spawn"

    if cooldown_key:
        from modules.bannerlord._adapter import check_cooldown
        remaining = check_cooldown(channel_id, username, cooldown_key)
        if remaining > 0:
            return {
                "success": False,
                "message": f"Способность на перезарядке ({int(remaining)}с)",
                "cooldown_remaining_s": round(remaining, 1),
            }

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

            # Sprint M20: hero.upgrade_gear — atomic increment gear_tier
            # (внутри той же TX что charge). Если backend упал между charge
            # и enqueue, rollback вернёт всё. Mod при следующем pull получит
            # action и применит equipment.
            if action_type == "hero.upgrade_gear" and gear_upgrade_target_tier:
                await conn.execute(
                    "UPDATE bannerlord_heroes SET gear_tier=?, last_sync=CURRENT_TIMESTAMP "
                    "WHERE channel_id=? AND username=?",
                    (gear_upgrade_target_tier, channel_id, username))

            await conn.commit()
        except Exception:
            try:
                await conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

    # Sprint 4.8/5.0: запустить cooldown ПОСЛЕ commit (если упало — cooldown
    # не считается). Происходит вне TX — cooldown это in-memory state.
    if cooldown_key:
        from modules.bannerlord._adapter import set_cooldown
        set_cooldown(channel_id, username, cooldown_key)

    return {
        "success":   True,
        "action_id": action_id,
        "charged":   price,
        "message":   f"⚔️ Action {action_type} в очереди ({price}💎 списано)",
    }
