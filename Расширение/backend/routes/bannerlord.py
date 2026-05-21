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


@router.get("/api/bannerlord/tournament")
async def bannerlord_tournament(request: Request):
    """Турнир: queue + state + my bet status.

    Frontend polling ~3s для UI update:
      - "Турнир: idle (3 в очереди)" → можно join
      - "Турнир: running, раунд 2/4, ставки открыты на участников X/Y" → можно bet
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        # Queue (ordered by joined_at)
        cur = await conn.execute("""
            SELECT q.username, q.entry_fee, q.joined_at,
                   c.class_key
            FROM bannerlord_tournament_queue q
            LEFT JOIN bannerlord_hero_class c
              ON c.channel_id = q.channel_id AND c.username = q.username
            WHERE q.channel_id=?
            ORDER BY q.joined_at ASC
        """, (channel_id,))
        queue = []
        for r in await cur.fetchall():
            queue.append({
                "username":  r[0],
                "entry_fee": r[1] or 0,
                "class_key": r[3],
            })

        # State
        cur = await conn.execute("""
            SELECT status, current_round, participants, last_winner, started_at
            FROM bannerlord_tournament_state WHERE channel_id=?
        """, (channel_id,))
        row = await cur.fetchone()
        if row:
            try:
                participants = json.loads(row[2] or "[]")
            except Exception:
                participants = []
            state = {
                "status":        row[0] or "idle",
                "current_round": row[1] or 0,
                "participants":  participants,
                "last_winner":   row[3],
                "started_at":    row[4],
            }
        else:
            state = {
                "status":        "idle",
                "current_round": 0,
                "participants":  [],
                "last_winner":   None,
                "started_at":    None,
            }

        # My bet (этот раунд)
        my_bet = None
        if state["status"] == "running":
            cur = await conn.execute("""
                SELECT target, amount FROM bannerlord_tournament_bets
                WHERE channel_id=? AND bettor=? AND round_index=?
            """, (channel_id, username, state["current_round"]))
            br = await cur.fetchone()
            if br:
                my_bet = {"target": br[0], "amount": br[1]}

        # In queue?
        in_queue = any(q["username"] == username for q in queue)

    return {
        "success":     True,
        "queue":       queue,
        "state":       state,
        "in_queue":    in_queue,
        "my_bet":      my_bet,
        "my_username": username,
        "config": {
            "entry_fee_gold": TOURNAMENT_ENTRY_FEE_GOLD,
            "min_bet":        TOURNAMENT_MIN_BET,
            "max_bet":        TOURNAMENT_MAX_BET,
        },
    }


@router.get("/api/bannerlord/battle-status")
async def bannerlord_battle_status(request: Request):
    """Sprint 5.5: viewer-side battle indicator.

    Returns:
      {in_battle: bool,         # идёт ли активный бой в игре
       participant_count: int,
       my_stats: {hp, hp_max, alive, state, kills, gold_earned, xp_earned}
                                # — null если viewer не участвует}

    Polling ~2с в extension'е — banner показывает "⚔️ Бой идёт" +
    мою HP/kills/gold/xp. На transition new-battle backend автоматически
    сбрасывает мои cooldowns (см. _adapter._on_battle_stats).
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    from modules.bannerlord._adapter import get_my_battle_stats
    data = get_my_battle_stats(channel_id, username)
    return {"success": True, **data}


@router.get("/api/overlay/bannerlord/summoned")
async def overlay_bannerlord_summoned(channel_id: int = 0):
    """Sprint 5.4: Active summoned heroes в Mission — для overlay рендера.

    Public endpoint (no JWT) т.к. overlay.html запускается в OBS без
    Twitch auth context. Защита через channel_id query param.

    Mod пушит battle.stats_snapshot каждые ~1.5s, мы храним in-memory.
    Если TTL истёк (>8s) или isFinal=true → active=false (overlay скрывает).

    Returns:
      {success, active, participants: [{username, hp, hp_max, alive,
       kills, gold_earned, xp_earned}], age_sec}
    """
    if channel_id <= 0:
        from dependencies import resolve_channel_id_or_default
        channel_id = resolve_channel_id_or_default()

    from modules.bannerlord._adapter import get_battle_stats
    snapshot = get_battle_stats(channel_id)
    return {
        "success":      True,
        "channel_id":   channel_id,
        **snapshot,
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
    "hero.join_tournament",      # Sprint 5.3: BLT-style viewer tournament queue
    "tournament.bet",            # Sprint 5.3: viewer ставит крустики на участника
    "hero.add_focus",            # Sprint 5.8: focus point в skill (Hero.Gold tier-based)
    "hero.add_attribute",        # Sprint 5.8: attribute point (Hero.Gold flat)
    "hero.create_clan",          # Sprint 5.9: BLT-style clan creation (Hero.Gold 1M)
    "hero.create_kingdom",       # Sprint 5.12: kingdom creation (Hero.Gold 5M)
    "hero.leave_clan",           # Sprint 5.12: leave own clan (free)
    "hero.leave_kingdom",        # Sprint 5.12: clan leaves kingdom (free)
    "hero.join_clan",            # Sprint 5.12: join existing clan (Hero.Gold 50K)
    "hero.join_kingdom",         # Sprint 5.12: clan joins kingdom (Hero.Gold 100K)
    "hero.create_party",         # Sprint 5.13: clan-leader creates MobileParty (Hero.Gold 200K)
)

# Sprint 5.18 (refactor): helper для повторяющегося Hero.Gold pre-check.
# Используется в нескольких action handlers (create_clan, create_kingdom,
# join_clan, join_kingdom, create_party, recruit_troops, add_focus,
# add_attribute, upgrade_gear). Source-of-truth — backend cache
# `bannerlord_heroes.gold` (mod пушит на каждом HeroStateSync).
async def _fetch_hero_gold(channel_id: int, username: str) -> int:
    """Возвращает cached Hero.Gold (или 0 если героя нет)."""
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT gold FROM bannerlord_heroes WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
    return (row[0] if row else 0) or 0


# Sprint 5.9: clan creation cost — mirror C# CreateClanHandler.CREATE_COST.
CLAN_CREATE_COST = 1_000_000   # 1M динаров

# Sprint 5.12: kingdom / join / leave costs — mirror соответствующих C# handlers.
KINGDOM_CREATE_COST = 5_000_000   # 5M динаров — premium prestige
CLAN_JOIN_COST = 50_000           # вступление в clan
KINGDOM_JOIN_COST = 100_000       # clan вступает в kingdom вассалом
PARTY_CREATE_COST = 200_000       # MobileParty создание (стартовый loot + морал)
# leave_clan и leave_kingdom — бесплатно

# Sprint 5.8: focus cost tier-based (mirror C# AddFocusHandler.FOCUS_TIER_COSTS).
FOCUS_TIER_COSTS = [30_000, 40_000, 50_000, 60_000, 75_000]
ATTRIBUTE_COST = 50_000  # flat Hero.Gold per attribute point

# Whitelist skill keys (vanilla Bannerlord 1.3.15).
ALLOWED_SKILLS = {
    "OneHanded", "TwoHanded", "Polearm", "Bow", "Crossbow", "Throwing",
    "Athletics", "Riding", "Smithing", "Scouting", "Tactics", "Roguery",
    "Charm", "Leadership", "Trade", "Steward", "Medicine", "Engineering",
}
ALLOWED_ATTRIBUTES = {"Vigor", "Control", "Endurance", "Cunning", "Social", "Intelligence"}

# Sprint 5.3: tournament entry fee — Hero.Gold (списывается mod-side).
# Backend хранит mirror для UI + bets resolution.
TOURNAMENT_ENTRY_FEE_GOLD = 5_000          # in-game динары
TOURNAMENT_MIN_BET = 100                   # крустиков
TOURNAMENT_MAX_BET = 10_000                # крустиков

# Sprint M20: gear upgrade costs в Hero.Gold (in-game динары, не крустики).
# Mod-side source-of-truth — mod проверяет Hero.Gold ≥ cost и списывает.
# Backend нужны только для UI display (показать "T2 — 100K динаров").
# Должны совпадать с HERO_GOLD_TIER_COSTS в C# UpgradeGearHandler.
HERO_GOLD_TIER_COSTS = {
    1:    50_000,
    2:   100_000,
    3:   200_000,
    4:   400_000,
    5:   800_000,
    6: 1_500_000,
}

# Sprint M21: give_gold presets — 1000⦷ → 5000 динаров (1:5).
# Маппинг {крустики: динары} — server-side override клиентского amount.
GIVE_GOLD_PRESETS = {
    1_000:   5_000,
    5_000:  25_000,
    20_000: 100_000,
}

# Sprint M21: add_skill_xp presets — 1000⦷ → 100 XP.
# Маппинг {крустики: xp} в random skill.
ADD_SKILL_XP_PRESETS = {
      500:    50,
    1_000:   100,
    5_000:   500,
}

# Actions которые НЕ требуют existing alive hero (adopt + respawn + bet).
_ACTIONS_WITHOUT_HERO_REQUIREMENT = (
    "hero.create",
    "player.respawn",
    "tournament.bet",     # bettor может ставить и без своего героя
)

# Actions которые НЕ enqueue'аться в module_actions (pure backend ops).
_BACKEND_ONLY_ACTIONS = ("tournament.bet",)


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
        # Hero base + M19 meta + M20 gear_tier + M27 clan/kingdom info
        cur = await conn.execute(
            "SELECT hero_id, display_name, culture, is_alive, is_prisoner, gold, "
            "       location, adopted_at, last_sync, level, clan_name, kingdom_name, "
            "       gear_tier, clan_info_json, kingdom_info_json "
            "FROM bannerlord_heroes WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
        if not row:
            return {"success": True, "has_hero": False}

        def _safe_json(s):
            if not s:
                return None
            try:
                return json.loads(s)
            except Exception:
                return None

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
            "clan_info":    _safe_json(row[13]),
            "kingdom_info": _safe_json(row[14]),
        }

        # Skills + Sprint 5.8 focus
        cur = await conn.execute(
            "SELECT skill_key, level, xp, COALESCE(focus, 0) "
            "FROM bannerlord_skills "
            "WHERE channel_id=? AND username=? ORDER BY level DESC, skill_key ASC",
            (channel_id, username))
        skills = [
            {"skill_key": r[0], "level": r[1], "xp": r[2], "focus": r[3] or 0}
            for r in await cur.fetchall()
        ]

        # Attributes
        cur = await conn.execute(
            "SELECT attribute, value FROM bannerlord_attributes "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        attributes = {r[0]: r[1] for r in await cur.fetchall()}

        # Equipment + M21 stats
        cur = await conn.execute(
            "SELECT slot, item_id, item_name, tier, item_value, weight, stats_json "
            "FROM bannerlord_equipment WHERE channel_id=? AND username=?",
            (channel_id, username))
        equipment = {}
        for r in await cur.fetchall():
            slot_name, item_id, item_name, tier, item_value, weight, stats_json = r
            stats = None
            if stats_json:
                try:
                    stats = json.loads(stats_json)
                except Exception:
                    stats = None
            equipment[slot_name] = {
                "item_id":    item_id,
                "item_name":  item_name,
                "tier":       tier,           # 0-5 (frontend +1 для UI T1-T6)
                "item_value": item_value,     # base game price
                "weight":     weight,
                "stats":      stats,          # dict с per-type stats
            }

        # Retinue (M23) — BLT-style свита, sorted by slot_index
        # M28 (5.14): include is_elite flag для UI badge "★ Элит"
        cur = await conn.execute(
            "SELECT slot_index, troop_id, troop_name, tier, COALESCE(is_elite, 0) "
            "FROM bannerlord_retinue "
            "WHERE channel_id=? AND username=? ORDER BY slot_index",
            (channel_id, username))
        retinue = [
            {
                "slot_index": r[0],
                "troop_id":   r[1],
                "troop_name": r[2],
                "tier":       r[3] or 0,
                "is_elite":   bool(r[4]),
            }
            for r in await cur.fetchall()
        ]

    return {
        "success":    True,
        "has_hero":   True,
        "hero":       hero,
        "skills":     skills,
        "attributes": attributes,
        "equipment":  equipment,
        "retinue":    retinue,
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
    # Random equip — БЕСПЛАТНО в крустиках (price=0), mod-side списывает
    # Hero.Gold (in-game динары) — fairness через game economy.
    # Mirror HERO_GOLD_RANDOM_PRICES в C# EquipItemHandler.
    RANDOM_EQUIP_HERO_GOLD = {
        "weapon": 50_000,
        "armor":  25_000,
        "horse":  80_000,
    }
    RANDOM_EQUIP_PRICES = RANDOM_EQUIP_HERO_GOLD  # legacy name (some refs ниже)
    SPAWN_PRICES = {
        "player": 100,    # на сторону стримера (ally) — 5.4: было 500
        "enemy":  200,    # против стримера — 2× as тролл-tax — 5.4: было 1000
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
            # Random equip теперь оплачивается Hero.Gold (in-game), не
            # крустиками. Frontend показывает 💰 (динары); mod проверяет
            # hero.Gold перед apply.
            data["hero_gold_cost"] = RANDOM_EQUIP_HERO_GOLD[random_category]
            data["price"] = 0  # крустики free

    if action_type == "player.spawn":
        side = (data.get("side") or "player").strip().lower()
        if side not in SPAWN_PRICES:
            return {"success": False, "message": f"Side '{side}' не разрешён"}
        data["side"] = side
        data["price"] = SPAWN_PRICES[side]

    # hero.recruit_troops: backend passes current retinue snapshot в data
    # чтобы mod знал какие slots filled (для add vs upgrade decision).
    # Also: player.spawn — pass retinue для spawn вместе с hero.
    # Recruit: 100💎 в крустиках за попытку (mod ещё проверяет Hero.Gold).
    # MIRROR mod TIER_COSTS из RecruitTroopsHandler.cs — для pre-check Hero.Gold.
    RECRUIT_TIER_COSTS = [5_000, 10_000, 20_000, 30_000, 50_000, 80_000]
    ELITE_COST_MULTIPLIER = 3
    if action_type in ("hero.recruit_troops", "player.spawn", "hero.create_party"):
        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            cur = await conn.execute(
                "SELECT slot_index, troop_id, troop_name, tier, "
                "       COALESCE(is_elite, 0) "
                "FROM bannerlord_retinue "
                "WHERE channel_id=? AND username=? ORDER BY slot_index",
                (channel_id, username))
            retinue_rows = [
                {
                    "slot_index": r[0],
                    "troop_id":   r[1],
                    "troop_name": r[2],
                    "tier":       r[3] or 0,
                    "is_elite":   bool(r[4]),
                }
                for r in await cur.fetchall()
            ]
            data["retinue"] = retinue_rows

            if action_type == "hero.recruit_troops":
                # Sprint 5.14: is_elite flag — 3× cost для elite troops
                want_elite = bool(data.get("is_elite", False))
                MAX_RETINUE = 5

                # Sprint 5.14: проверяем slots ТОГО же типа (basic vs elite)
                # для upgrade-decision. Empty slots → new troop.
                if len(retinue_rows) < MAX_RETINUE:
                    needed = RECRUIT_TIER_COSTS[0]
                    cost_label = f"найм нового {'elite' if want_elite else 'basic'}"
                else:
                    same_type = [s for s in retinue_rows if s["is_elite"] == want_elite]
                    if not same_type:
                        return {
                            "success": False,
                            "message": f"Нет {'elite' if want_elite else 'basic'} войнов "
                                       f"для прокачки. Сначала найми хотя бы одного.",
                        }
                    lowest_tier = min(s["tier"] for s in same_type)
                    idx = min(lowest_tier, len(RECRUIT_TIER_COSTS) - 1)
                    needed = RECRUIT_TIER_COSTS[idx]
                    cost_label = f"прокачка T{lowest_tier + 1} " \
                                 f"{'elite' if want_elite else 'basic'}"

                if want_elite:
                    needed *= ELITE_COST_MULTIPLIER

                cur = await conn.execute(
                    "SELECT gold FROM bannerlord_heroes WHERE channel_id=? AND username=?",
                    (channel_id, username))
                row = await cur.fetchone()
                hero_gold = (row[0] if row else 0) or 0
                if hero_gold < needed:
                    return {
                        "success": False,
                        "message": f"Нужно {needed:,}💰 динаров для {cost_label}, "
                                   f"у тебя {hero_gold:,}💰 (накопи в игре).",
                    }
                data["hero_gold_cost"] = needed
                data["is_elite"] = want_elite

        if action_type == "hero.recruit_troops":
            # Sprint 5.14: elite — 300💎 крустиков (3×) для UX consistency
            data["price"] = 300 if data.get("is_elite") else 100

    # hero.create: culture choice (empire/sturgia/vlandia/aserai/khuzait/battania).
    # Validate whitelist; null/empty = mod выберет random wanderer.
    if action_type == "hero.create":
        ALLOWED_CULTURES = {"empire", "sturgia", "vlandia", "aserai", "khuzait", "battania"}
        culture = (data.get("culture") or "").strip().lower()
        if culture and culture not in ALLOWED_CULTURES:
            return {
                "success": False,
                "message": f"Культура '{culture}' не разрешена "
                           f"(допустимо: {sorted(ALLOWED_CULTURES)})",
            }
        data["culture"] = culture  # mod resolve'ит '' → random

        # Defense-in-depth: ещё один guard против opaque-ID adoption.
        # Если username длинный (>25) ИЛИ выглядит как opaque (u_xxx, длинная
        # base64url-строка) — refuse. Real Twitch login ≤25 символов
        # [a-z0-9_].
        import re as _re_local
        if (len(username) > 25
                or _re_local.fullmatch(r"u[a-z0-9_-]{15,}", username)):
            return {
                "success": False,
                "message": "Нужно войти через Twitch ('Share Identity'), "
                           "иначе твой герой будет создан с opaque ID. "
                           "Нажми 'Login' в шапке.",
            }

    # Sprint M20+M21: hero.upgrade_gear — БЕСПЛАТНО в крустиках, mod
    # списывает Hero.Gold (in-game динары) — см. UpgradeGearHandler.cs.
    # Backend только validates eligibility и enqueue'ит action.
    # Backend НЕ обновляет gear_tier сам — mod пушит hero.gear_tier_changed
    # после successful in-game upgrade.
    if action_type == "hero.upgrade_gear":
        db_tmp = get_db()
        async with db_tmp._connect() as conn:
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
        data["hero_gold_cost"] = HERO_GOLD_TIER_COSTS[target_tier]
        data["price"] = 0   # крустики: бесплатно

    # Sprint M21: player.give_item (gold) — server-side amount по крустики preset.
    if action_type == "player.give_item":
        item_type = (data.get("item_type") or "gold").strip().lower()
        if item_type == "gold":
            try:
                crusticov = int(data.get("price") or 0)
            except (TypeError, ValueError):
                return {"success": False, "message": "Неверная цена"}
            if crusticov not in GIVE_GOLD_PRESETS:
                return {
                    "success": False,
                    "message": f"Неизвестный пресет {crusticov}⦷ "
                               f"(допустимы: {sorted(GIVE_GOLD_PRESETS.keys())})",
                }
            data["item_type"] = "gold"
            data["amount"] = GIVE_GOLD_PRESETS[crusticov]
            # price остаётся = crusticov (передан клиентом, validated в preset map)

    # Sprint M21: hero.add_skill — server-side xp по крустики preset.
    # skill_key опциональный — если пуст, mod random pick.
    if action_type == "hero.add_skill":
        try:
            crusticov = int(data.get("price") or 0)
        except (TypeError, ValueError):
            return {"success": False, "message": "Неверная цена"}
        if crusticov not in ADD_SKILL_XP_PRESETS:
            return {
                "success": False,
                "message": f"Неизвестный пресет {crusticov}⦷ "
                           f"(допустимы: {sorted(ADD_SKILL_XP_PRESETS.keys())})",
            }
        data["xp"] = ADD_SKILL_XP_PRESETS[crusticov]
        # skill_key может быть пустым = random skill в mod

    # Sprint 5.8: hero.add_focus — БЕСПЛАТНО в крустиках, mod списывает
    # Hero.Gold tier-based. Validation skill_key + pre-check Hero.Gold.
    if action_type == "hero.add_focus":
        skill_key = (data.get("skill_key") or "").strip()
        try:
            amount = int(data.get("amount") or 1)
        except (TypeError, ValueError):
            amount = 1
        amount = max(1, min(5, amount))

        if skill_key and skill_key not in ALLOWED_SKILLS:
            return {
                "success": False,
                "message": f"Skill '{skill_key}' не разрешён "
                           f"(допустимо: {sorted(ALLOWED_SKILLS)})",
            }

        # Pre-check Hero.Gold (cached). Worst case: amount=1 → 30K.
        # Точная стоимость зависит от текущего focus в skill (mod знает),
        # но мы здесь делаем conservative check на самый низкий tier.
        # Mod сам проверит реальную стоимость и откажет если не хватит.
        hero_gold = await _fetch_hero_gold(channel_id, username)
        min_needed = FOCUS_TIER_COSTS[0] * amount  # хотя бы amount × cheapest tier
        if hero_gold < min_needed:
            return {
                "success": False,
                "message": f"Минимум {min_needed:,}💰 динаров нужно "
                           f"(у тебя {hero_gold:,}💰).",
            }
        data["skill_key"] = skill_key  # '' = random
        data["amount"] = amount
        data["hero_gold_cost_min"] = min_needed  # for UI display
        data["price"] = 0   # крустики free

    # Sprint 5.8: hero.add_attribute — БЕСПЛАТНО в крустиках, mod списывает
    # Hero.Gold flat 50K per point.
    if action_type == "hero.add_attribute":
        attr_key = (data.get("attribute_key") or "").strip()
        try:
            amount = int(data.get("amount") or 1)
        except (TypeError, ValueError):
            amount = 1
        amount = max(1, min(10, amount))

        if attr_key and attr_key not in ALLOWED_ATTRIBUTES:
            return {
                "success": False,
                "message": f"Attribute '{attr_key}' не разрешён "
                           f"(допустимо: {sorted(ALLOWED_ATTRIBUTES)})",
            }

        cost = ATTRIBUTE_COST * amount
        hero_gold = await _fetch_hero_gold(channel_id, username)
        if hero_gold < cost:
            return {
                "success": False,
                "message": f"Нужно {cost:,}💰 динаров (у тебя {hero_gold:,}💰).",
            }
        data["attribute_key"] = attr_key  # '' = random
        data["amount"] = amount
        data["hero_gold_cost"] = cost
        data["price"] = 0

    # Sprint 5.9: hero.create_clan — БЕСПЛАТНО в крустиках, mod списывает
    # 100K Hero.Gold. Validation clan_name + Hero.Gold pre-check + check
    # что viewer не лидер clan'а (через bannerlord_heroes.clan_name).
    if action_type == "hero.create_clan":
        clan_name = (data.get("clan_name") or "").strip()
        # Allow empty (mod выберет дефолтное "{username}'s Clan").
        # Basic sanity: длина и недопустимые символы.
        if clan_name and len(clan_name) > 32:
            return {
                "success": False,
                "message": "Имя клана слишком длинное (макс 32 символа)",
            }
        if clan_name and any(c in clan_name for c in ('<', '>', '"', "'", '`', '\\')):
            return {
                "success": False,
                "message": "Недопустимые символы в имени клана",
            }

        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            cur = await conn.execute(
                "SELECT gold, clan_name FROM bannerlord_heroes "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            row = await cur.fetchone()
        if not row:
            return {"success": False, "message": "Сначала создай героя"}
        hero_gold = (row[0] if row else 0) or 0
        current_clan = (row[1] if len(row) > 1 else None) or ""
        # Если cached clan_name содержит [BLink] prefix → viewer уже лидер
        if current_clan.startswith("[BLink]"):
            return {
                "success": False,
                "message": f"Ты уже лидер клана '{current_clan}'",
            }
        if hero_gold < CLAN_CREATE_COST:
            return {
                "success": False,
                "message": f"Нужно {CLAN_CREATE_COST:,}💰 динаров для создания клана "
                           f"(у тебя {hero_gold:,}💰).",
            }
        data["clan_name"] = clan_name   # '' = mod default
        data["hero_gold_cost"] = CLAN_CREATE_COST
        data["price"] = 0               # крустики free

    # Sprint 5.12: hero.create_kingdom — 5M Hero.Gold, clan-leader only
    if action_type == "hero.create_kingdom":
        kingdom_name = (data.get("kingdom_name") or "").strip()
        if kingdom_name and len(kingdom_name) > 32:
            return {"success": False, "message": "Имя королевства слишком длинное (макс 32)"}
        if kingdom_name and any(c in kingdom_name for c in ('<', '>', '"', "'", '`', '\\')):
            return {"success": False, "message": "Недопустимые символы в имени"}

        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            cur = await conn.execute(
                "SELECT gold, clan_name, kingdom_name FROM bannerlord_heroes "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            row = await cur.fetchone()
        if not row:
            return {"success": False, "message": "Сначала создай героя"}
        hero_gold = (row[0] if row else 0) or 0
        clan_name = (row[1] if len(row) > 1 else None) or ""
        kingdom_name_cur = (row[2] if len(row) > 2 else None) or ""
        if not clan_name.startswith("[BLink]"):
            return {
                "success": False,
                "message": "Сначала создай свой клан — королевство только для лидеров.",
            }
        if kingdom_name_cur:
            return {
                "success": False,
                "message": f"Твой клан уже в королевстве '{kingdom_name_cur}'. Сначала покинь.",
            }
        if hero_gold < KINGDOM_CREATE_COST:
            return {
                "success": False,
                "message": f"Нужно {KINGDOM_CREATE_COST:,}💰 динаров (у тебя {hero_gold:,}💰).",
            }
        data["kingdom_name"] = kingdom_name
        data["hero_gold_cost"] = KINGDOM_CREATE_COST
        data["price"] = 0

    # Sprint 5.12: hero.leave_clan / hero.leave_kingdom — free actions, no extra validation
    # (mod-side проверки делают всё)
    if action_type in ("hero.leave_clan", "hero.leave_kingdom"):
        data["price"] = 0

    # Sprint 5.12: hero.join_clan — 50K Hero.Gold, requires clan_name input
    if action_type == "hero.join_clan":
        clan_name_in = (data.get("clan_name") or "").strip()
        if not clan_name_in:
            return {"success": False, "message": "Имя клана обязательно"}
        if len(clan_name_in) > 64:
            return {"success": False, "message": "Имя клана слишком длинное"}
        hero_gold = await _fetch_hero_gold(channel_id, username)
        if hero_gold < CLAN_JOIN_COST:
            return {
                "success": False,
                "message": f"Нужно {CLAN_JOIN_COST:,}💰 динаров (у тебя {hero_gold:,}💰).",
            }
        data["clan_name"] = clan_name_in
        data["hero_gold_cost"] = CLAN_JOIN_COST
        data["price"] = 0

    # Sprint 5.13: hero.create_party — 200K, requires clan + clan-leader
    if action_type == "hero.create_party":
        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            cur = await conn.execute(
                "SELECT gold, clan_name FROM bannerlord_heroes "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            row = await cur.fetchone()
        if not row:
            return {"success": False, "message": "Сначала создай героя"}
        hero_gold = (row[0] if row else 0) or 0
        clan_name = (row[1] if len(row) > 1 else None) or ""
        if not clan_name.startswith("[BLink]"):
            return {
                "success": False,
                "message": "Сначала создай свой клан — party требует clan-leader статус.",
            }
        if hero_gold < PARTY_CREATE_COST:
            return {
                "success": False,
                "message": f"Нужно {PARTY_CREATE_COST:,}💰 динаров (у тебя {hero_gold:,}💰).",
            }
        data["hero_gold_cost"] = PARTY_CREATE_COST
        data["price"] = 0

    # Sprint 5.12: hero.join_kingdom — 100K Hero.Gold, requires kingdom_name + clan
    if action_type == "hero.join_kingdom":
        kingdom_name_in = (data.get("kingdom_name") or "").strip()
        if not kingdom_name_in:
            return {"success": False, "message": "Имя королевства обязательно"}
        if len(kingdom_name_in) > 64:
            return {"success": False, "message": "Имя слишком длинное"}
        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            cur = await conn.execute(
                "SELECT gold, clan_name FROM bannerlord_heroes "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            row = await cur.fetchone()
        hero_gold = (row[0] if row else 0) or 0
        clan_name = (row[1] if len(row) > 1 else None) or ""
        if not clan_name.startswith("[BLink]"):
            return {
                "success": False,
                "message": "Сначала создай свой клан — королевства только для лидеров кланов.",
            }
        if hero_gold < KINGDOM_JOIN_COST:
            return {
                "success": False,
                "message": f"Нужно {KINGDOM_JOIN_COST:,}💰 динаров (у тебя {hero_gold:,}💰).",
            }
        data["kingdom_name"] = kingdom_name_in
        data["hero_gold_cost"] = KINGDOM_JOIN_COST
        data["price"] = 0

    # Sprint 5.3: hero.join_tournament — БЕСПЛАТНО в крустиках,
    # mod списывает TOURNAMENT_ENTRY_FEE_GOLD динаров. Backend
    # вставляет row в bannerlord_tournament_queue только когда mod
    # пушит event tournament.joined (mod = source-of-truth для очереди).
    if action_type == "hero.join_tournament":
        # Check status — не пускаем в running tournament
        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            cur = await conn.execute(
                "SELECT status FROM bannerlord_tournament_state WHERE channel_id=?",
                (channel_id,))
            row = await cur.fetchone()
            status = (row[0] if row else "idle") or "idle"
            if status == "running":
                return {
                    "success": False,
                    "message": "Турнир уже идёт — подожди следующий",
                }
            # Already in queue?
            cur = await conn.execute(
                "SELECT 1 FROM bannerlord_tournament_queue "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            if await cur.fetchone():
                return {
                    "success": False,
                    "message": "Ты уже в очереди на турнир",
                }
        data["hero_gold_cost"] = TOURNAMENT_ENTRY_FEE_GOLD
        data["price"] = 0   # крустики free

    # Sprint 5.3: tournament.bet — крустики ставка на участника turnir'а.
    # Atomic charge крустиков; запись в bannerlord_tournament_bets.
    if action_type == "tournament.bet":
        target = (data.get("target") or "").strip().lower()
        try:
            amount = int(data.get("amount") or 0)
        except (TypeError, ValueError):
            return {"success": False, "message": "Неверная сумма ставки"}
        if not target:
            return {"success": False, "message": "Не указан участник"}
        if amount < TOURNAMENT_MIN_BET or amount > TOURNAMENT_MAX_BET:
            return {
                "success": False,
                "message": f"Ставка от {TOURNAMENT_MIN_BET} до "
                           f"{TOURNAMENT_MAX_BET}⦷",
            }
        # Tournament must be running + target в participants
        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            cur = await conn.execute(
                "SELECT status, current_round, participants "
                "FROM bannerlord_tournament_state WHERE channel_id=?",
                (channel_id,))
            row = await cur.fetchone()
        if not row or (row[0] or "idle") != "running":
            return {"success": False, "message": "Турнир не идёт"}
        try:
            participants = json.loads(row[2] or "[]")
        except Exception:
            participants = []
        if target not in [str(p).lower() for p in participants]:
            return {
                "success": False,
                "message": f"@{target} не участвует в турнире",
            }
        round_index = int(row[1] or 0)
        # Already bet this round?
        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            cur = await conn.execute(
                "SELECT 1 FROM bannerlord_tournament_bets "
                "WHERE channel_id=? AND bettor=? AND round_index=?",
                (channel_id, username, round_index))
            if await cur.fetchone():
                return {
                    "success": False,
                    "message": f"Ты уже ставил в раунде {round_index + 1}",
                }
        data["target"] = target
        data["amount"] = amount
        data["round_index"] = round_index
        data["price"] = amount   # списать ставку как price крустиков

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
            # Sprint 5.10c: pass current gear_tier — иначе SetClassHandler даёт
            # random T0-T2 шмот, viewer теряет прогрессию tier'а.
            cur = await conn.execute(
                "SELECT gear_tier FROM bannerlord_heroes "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            row = await cur.fetchone()
            data["gear_tier"] = (row[0] if row else 0) or 0

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

            # Enqueue action в outbox (через тот же conn — atomic с charge).
            # tournament.bet — backend-only (не идёт в mod), пропускаем enqueue.
            action_id = uuid.uuid4().hex
            payload = dict(data)
            payload["initiated_by"] = username
            if action_type not in _BACKEND_ONLY_ACTIONS:
                await conn.execute("""
                    INSERT INTO module_actions
                        (channel_id, module_id, action_id, type, data, status)
                    VALUES (?, 'bannerlord', ?, ?, ?, 'queued')
                """, (channel_id, action_id, action_type,
                      json.dumps(payload, ensure_ascii=False)))

            # Sprint 5.3: tournament.bet — записываем в bets table.
            if action_type == "tournament.bet":
                await conn.execute("""
                    INSERT INTO bannerlord_tournament_bets
                        (channel_id, bettor, target, amount, round_index)
                    VALUES (?, ?, ?, ?, ?)
                """, (channel_id, username,
                      data.get("target"),
                      data.get("amount"),
                      data.get("round_index", 0)))

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

            # Sprint M21: hero.upgrade_gear — backend НЕ обновляет gear_tier.
            # Mod source-of-truth: списывает Hero.Gold и пушит
            # hero.gear_tier_changed event только при successful upgrade.
            # Это страхует race condition если mod не может списать (insufficient
            # in-game gold) — backend остаётся синхронизирован с реальным state.

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


# ════════ Sprint 5.26: Clan Upgrades (BLT-style) ════════

import json as _bnr_clan_json


@router.get("/api/bannerlord/clan-upgrades")
async def bannerlord_clan_upgrades_list(request: Request):
    """Список clan upgrades для текущего канала + own/locked status юзера.

    Response:
      {
        success: True,
        upgrades: [
          {upgrade_id, name, description, tier, required_upgrade_id,
           gold_cost, effects, owned: bool, locked: bool},
          ...
        ],
        hero_gold: int
      }
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT upgrade_id, name, description, tier, required_upgrade_id, "
            "gold_cost, effects_json FROM bannerlord_clan_upgrades_catalog "
            "WHERE channel_id = ? AND deprecated = 0 "
            "ORDER BY tier ASC, gold_cost ASC",
            (channel_id,)
        )
        rows = await cur.fetchall()

        cur = await conn.execute(
            "SELECT upgrade_id FROM bannerlord_clan_upgrades_owned "
            "WHERE channel_id = ? AND username = ?",
            (channel_id, username)
        )
        owned_set = {r[0] for r in await cur.fetchall()}

    upgrades = []
    for upg_id, name, desc, tier, req, cost, effects_json in rows:
        owned = upg_id in owned_set
        # Locked если prereq exists и не куплен
        locked = bool(req and req not in owned_set)
        upgrades.append({
            "upgrade_id":          upg_id,
            "name":                name,
            "description":         desc or '',
            "tier":                tier,
            "required_upgrade_id": req,
            "gold_cost":           cost,
            "effects":             _bnr_clan_json.loads(effects_json or '{}'),
            "owned":               owned,
            "locked":              locked and not owned,
        })

    hero_gold = await _fetch_hero_gold(channel_id, username)
    return {"success": True, "upgrades": upgrades, "hero_gold": hero_gold}


@router.post("/api/bannerlord/clan-upgrades/buy")
async def bannerlord_clan_upgrades_buy(request: Request):
    """Купить апгрейд клана за hero.gold.

    Body: {"upgrade_id": str}
    Валидации:
      - upgrade exists и not deprecated
      - не куплен уже
      - prereq куплен (если есть)
      - hero.gold >= cost
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    upgrade_id = (data.get("upgrade_id") or '').strip()
    if not upgrade_id:
        return {"success": False, "message": "upgrade_id обязателен"}

    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")

            # Load upgrade
            cur = await conn.execute(
                "SELECT name, required_upgrade_id, gold_cost, deprecated "
                "FROM bannerlord_clan_upgrades_catalog "
                "WHERE channel_id = ? AND upgrade_id = ?",
                (channel_id, upgrade_id)
            )
            row = await cur.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Апгрейд не найден"}
            name, req, cost, deprecated = row
            if deprecated:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Апгрейд недоступен"}

            # Check not already owned
            cur = await conn.execute(
                "SELECT 1 FROM bannerlord_clan_upgrades_owned "
                "WHERE channel_id = ? AND username = ? AND upgrade_id = ?",
                (channel_id, username, upgrade_id)
            )
            if await cur.fetchone():
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Уже куплено"}

            # Check prereq
            if req:
                cur = await conn.execute(
                    "SELECT 1 FROM bannerlord_clan_upgrades_owned "
                    "WHERE channel_id = ? AND username = ? AND upgrade_id = ?",
                    (channel_id, username, req)
                )
                if not await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    return {"success": False,
                            "message": f"Сначала купи предыдущий апгрейд"}

            # Check gold
            cur = await conn.execute(
                "SELECT gold FROM bannerlord_heroes WHERE channel_id = ? AND username = ?",
                (channel_id, username)
            )
            hero_row = await cur.fetchone()
            current_gold = (hero_row[0] if hero_row else 0) or 0
            if current_gold < cost:
                await conn.execute("ROLLBACK")
                return {
                    "success": False,
                    "message": f"Нужно {cost:,}💰 (у тебя {current_gold:,}💰)",
                }

            # Debit + insert ownership
            await conn.execute(
                "UPDATE bannerlord_heroes SET gold = gold - ? "
                "WHERE channel_id = ? AND username = ?",
                (cost, channel_id, username)
            )
            await conn.execute(
                "INSERT INTO bannerlord_clan_upgrades_owned "
                "(channel_id, username, upgrade_id, gold_paid) VALUES (?, ?, ?, ?)",
                (channel_id, username, upgrade_id, cost)
            )

            # Enqueue action для мода (применит эффекты in-game).
            # Mod polls module_actions через /api/module/actions.
            import uuid as _uuid
            action_id = _uuid.uuid4().hex
            await conn.execute("""
                INSERT INTO module_actions
                    (channel_id, module_id, action_id, type, data, status)
                VALUES (?, 'bannerlord', ?, 'clan.upgrade_purchased', ?, 'queued')
            """, (channel_id, action_id,
                  _bnr_clan_json.dumps({
                      "username":   username,
                      "upgrade_id": upgrade_id,
                  }, ensure_ascii=False)))

            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    return {
        "success":    True,
        "upgrade_id": upgrade_id,
        "message":    f"✨ {name} куплено (-{cost:,}💰)",
    }
