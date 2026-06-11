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

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request

from dependencies import get_db, require_jwt_user

router = APIRouter()

# Sprint 5.29 audit fix #39 — per-(channel,user) asyncio.Lock для serializing
# actions того же viewer'а. Закрывает race condition:
#   1. Viewer spam'нул 2× hero.create_clan (1M динаров)
#   2. Backend ОБА раза читает кэшированный gold (мод ещё не успел deduct)
#   3. Оба validate → оба enqueue → mod успешно делает первый, отказывает
#      второй. Refund для второго работает (#21 уже задеплоен), но всё равно
#      ненужные round-trip'ы / spam в логах / risk нарваться на edge cases.
#
# Lock per-(channel,user) сериализует: второй action ждёт пока первый
# полностью закончит buy_action endpoint. Mod успевает применить + push'ить
# state_update до того как второй action прочитает gold.
#
# Lock держится только на время backend buy_action (charge + enqueue) —
# обычно <100ms. Не блокирует mod на main thread.
#
# Grows unbounded для new users — приемлемо на our scale (<100 active
# viewers per stream).
_user_action_locks: dict[tuple[int, str], asyncio.Lock] = {}
_user_action_locks_meta_lock = asyncio.Lock()


async def _get_user_lock(channel_id: int, username: str) -> asyncio.Lock:
    """Lazy-init per-user lock. Thread-safe через meta-lock."""
    key = (channel_id, (username or "").lower())
    if key not in _user_action_locks:
        async with _user_action_locks_meta_lock:
            if key not in _user_action_locks:   # double-check after acquire
                _user_action_locks[key] = asyncio.Lock()
    return _user_action_locks[key]

# Sprint 5.29 audit fix #34: action_id tracing logs + REFUSE prefix unification.
# Раньше большинство refuse paths логировали без префикса — нельзя было
# grep'нуть "что отказано сегодня". Также enqueue не логировал action_id —
# нельзя было проследить судьбу конкретного action через цепочку
# buy_action → mod poll → mod apply → ack.
log = logging.getLogger("rimlink.bannerlord")


def _refuse(action_type: str, username: str, reason: str) -> None:
    """grep-friendly: `grep '\\[bannerlord REFUSE\\]'` найдёт все отказы."""
    try:
        log.warning("[bannerlord REFUSE] action=%s user=%s reason=%s",
                    action_type, username, reason)
    except Exception:
        pass

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}


# Sprint 5.32 — class_level вычисляется из основного скилла класса (BLT-style).
# Раньше class_level хранился в bannerlord_hero_class но НЕ обновлялся (всегда 1).
# Теперь dynamic compute: для archer смотрим Bow, для cavalry — Riding, и т.д.
# Threshold:
#   skill <  50  → class_level 1 (×1.4 для rage и т.п.)
#   skill >= 50  → class_level 2 (×1.6)
#   skill >= 150 → class_level 3 (×1.9)
#
# С class-weighted XP (Sprint 5.29 #29) primary skill качается быстрее → progression
# награждает специализацию: archer'у выгодно качать Bow.
_CLASS_PRIMARY_SKILL = {
    "archer":         "Bow",
    "horse_archer":   "Bow",
    "camel_archer":   "Bow",
    "cavalry":        "Riding",
    "camel_cavalry":  "Riding",
    "knight":         "Riding",
    "infantry":       "Polearm",
    "tank":           "OneHanded",
    "berserk":        "TwoHanded",
    "psycho":         "TwoHanded",
}
_CLASS_LEVEL_THRESHOLDS = (50, 150)   # skill ≥ 50 → lvl2, ≥ 150 → lvl3


async def _compute_class_level(conn, channel_id: int, username: str,
                                class_key: str) -> int:
    """Сomputed dynamic class_level (1-3) для viewer'а на основе primary skill.

    Если класс не в map'е (legacy / unknown) — возвращает 1.
    Если skill не найден в bannerlord_skills — возвращает 1.
    """
    if not class_key:
        return 1
    primary_skill = _CLASS_PRIMARY_SKILL.get((class_key or "").lower())
    if not primary_skill:
        return 1
    cur = await conn.execute(
        "SELECT level FROM bannerlord_skills "
        "WHERE channel_id=? AND username=? AND LOWER(skill_key)=LOWER(?)",
        (channel_id, username, primary_skill))
    row = await cur.fetchone()
    if not row:
        return 1
    skill_val = int(row[0] or 0)
    t2, t3 = _CLASS_LEVEL_THRESHOLDS
    if skill_val >= t3:
        return 3
    if skill_val >= t2:
        return 2
    return 1


@router.get("/api/bannerlord/heirs")
async def bannerlord_heirs(request: Request):
    """Sprint 5.32 (BLT-parity M2) — heir queue для adopted viewer hero.

    Frontend: показать "наследники в очереди" в hero pane (под HP/skills).
    Возвращает список alive non-activated heirs у viewer'а (по убыванию came_of_age_at).
    JWT auth — viewer видит только своих наследников.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT heir_hero_id, heir_name, came_of_age_at "
            "FROM bannerlord_heirs "
            "WHERE channel_id=? AND parent_username=? "
            "AND alive=1 AND activated=0 "
            "ORDER BY came_of_age_at DESC",
            (channel_id, username))
        rows = await cur.fetchall()

    # Sprint 5.32 (LOG-3) — log если у пользователя есть наследники. Silent
    # если пусто (не спамим — большинство viewer'ов без heirs).
    if rows:
        log.info("[HEIR-API] ch=%s user=@%s heirs=%d (%s)",
                 channel_id, username, len(rows),
                 ", ".join(r[1] for r in rows[:3]) + ("..." if len(rows) > 3 else ""))

    return {
        "success": True,
        "heirs": [
            {"hero_id": r[0], "name": r[1], "came_of_age_at": r[2]}
            for r in rows
        ],
    }


@router.get("/api/bannerlord/recent-tournament-winners")
async def bannerlord_recent_tournament_winners(request: Request):
    """Sprint 5.32 (BLT-parity H8) — persistent anti-snowball winners list.

    Mod GET'ит при tournament start чтобы initialize TournamentMissionBehavior._recentWinners.
    Возвращает top-5 viewers по tournament_wins (DESC). Используется для HP-penalty
    при spawn'е в следующих турнирах.

    Раньше _recentWinners хранился как **static List в C#** — сбрасывался на reload
    save / restart игры. Топ-1 viewer переставал получать nerf после restart'а.

    Module-token auth (мод-side) ИЛИ Twitch JWT (frontend debug).
    """
    # Try module-token first.
    auth_header = request.headers.get("Authorization", "")
    channel_id = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            from routes.streamer import verify_module_token
            claims = verify_module_token(token)
            if claims and claims.get("module_id") == "bannerlord":
                channel_id = int(claims["channel_id"])
        except Exception as e:
            log.warning("[recent-tournament-winners] module-token verify failed: %s", e)
    if channel_id is None:
        auth = require_jwt_user(request)
        if not auth:
            return _AUTH_FAIL
        _, channel_id = auth

    try:
        limit = int(request.query_params.get("limit") or 5)
        limit = max(1, min(limit, 50))
    except (TypeError, ValueError):
        limit = 5

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT username, tournament_wins FROM bannerlord_heroes "
            "WHERE channel_id=? AND tournament_wins > 0 "
            "ORDER BY tournament_wins DESC, last_sync DESC LIMIT ?",
            (channel_id, limit))
        rows = await cur.fetchall()

    # Sprint 5.32 (LOG-3) — на каждом tournament start mod fetch'ит этот endpoint.
    # Log даёт visibility "сколько winners в anti-snowball list'е сейчас".
    log.info("[VET-API] ch=%s recent_winners=%d limit=%d (%s)",
             channel_id, len(rows), limit,
             ", ".join(f"@{r[0]}({r[1]})" for r in rows[:5])
             if rows else "—")

    return {
        "success": True,
        "winners": [
            {"username": r[0], "wins": r[1]} for r in rows
        ],
    }


@router.get("/api/bannerlord/class-state")
async def bannerlord_class_state(request: Request):
    """Snapshot всех heroes канала + их class + power values.

    Mod вызывает на session_start и кэширует в памяти. При AgentBuild в
    Mission смотрит cache для apply powers.

    Sprint 5.32 BUGFIX — auth поддерживает ОБА варианта:
      1. Module-token (Authorization: Bearer ...) — мод-side, основной путь
      2. Twitch JWT (X-Twitch-JWT) — frontend/streamer, fallback
    Раньше требовался ТОЛЬКО JWT → мод получал AUTH_FAIL → PowerCache
    refresh падал → viewer powers не применялись в бою.
    """
    # Try module-token first (мод-side).
    auth_header = request.headers.get("Authorization", "")
    channel_id = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            from routes.streamer import verify_module_token
            claims = verify_module_token(token)
            if claims and claims.get("module_id") == "bannerlord":
                channel_id = int(claims["channel_id"])
        except Exception as e:
            log.warning("[class-state] module-token verify failed: %s", e)
    # Fallback to JWT (frontend / streamer).
    if channel_id is None:
        auth = require_jwt_user(request)
        if not auth:
            return _AUTH_FAIL
        _, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        # All heroes + their class + level
        # Sprint 5.32 — class_level dynamically computed from primary skill.
        # DB column stays as legacy/seed (always 1); реальный level — функция
        # от Bow/Riding/etc. См. _compute_class_level выше.
        cur = await conn.execute("""
            SELECT h.username, h.hero_id, c.class_key,
                   COALESCE(h.combat_stance, 'balanced')
            FROM bannerlord_heroes h
            LEFT JOIN bannerlord_hero_class c
              ON h.channel_id = c.channel_id AND h.username = c.username
            WHERE h.channel_id=? AND h.is_alive=1
        """, (channel_id,))
        rows = await cur.fetchall()
        heroes = []
        for r in rows:
            uname, hero_id, cls_key, stance = r[0], r[1], r[2], r[3]
            class_level = await _compute_class_level(conn, channel_id, uname, cls_key)
            heroes.append({
                "username":      uname,
                "hero_id":       hero_id,
                "class_key":     cls_key,
                "class_level":   class_level,
                "combat_stance": stance,   # 2026-06-10 — мод грузит стойку на рестарте
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
        # Sprint 5.32 — class_level dynamic (по primary skill). Старая колонка
        # class_level в БД остаётся 1 forever (legacy field), реальный
        # level вычисляется через _compute_class_level.
        username = auth[0]
        cur = await conn.execute(
            "SELECT class_key FROM bannerlord_hero_class "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
        current = None
        if row:
            cls_key = row[0]
            class_level = await _compute_class_level(conn, channel_id, username, cls_key)
            # Дополнительно отдаём frontend info о primary skill + threshold —
            # для будущего UI "до lvl 2 осталось N очков скилла Bow".
            primary_skill = _CLASS_PRIMARY_SKILL.get((cls_key or "").lower())
            primary_skill_level = 0
            if primary_skill:
                cur_ps = await conn.execute(
                    "SELECT level FROM bannerlord_skills "
                    "WHERE channel_id=? AND username=? AND LOWER(skill_key)=LOWER(?)",
                    (channel_id, username, primary_skill))
                ps_row = await cur_ps.fetchone()
                if ps_row:
                    primary_skill_level = int(ps_row[0] or 0)
            current = {
                "class_key":           cls_key,
                "class_level":         class_level,
                "primary_skill":       primary_skill,
                "primary_skill_level": primary_skill_level,
                "next_threshold":      (_CLASS_LEVEL_THRESHOLDS[0] if class_level == 1
                                        else _CLASS_LEVEL_THRESHOLDS[1] if class_level == 2
                                        else None),
            }

        # Sprint 4.7: active powers для current класса viewer'а (для UI кнопок).
        # Фильтруем только active power_keys — passive (hp_multi / armor / skill
        # boosts) не покупаются runtime'ом. Heal_burst — special: доступен всем.
        ACTIVE_POWER_KEYS = (
            "shield_break_burst", "rage", "retribution_toggle",
            # 2026-05-29 BLT-parity combat powers (active variants).
            "lifesteal_burst", "ironskin_toggle",
            # 2026-05-29 взрывные стрелы (ranged AoE active).
            "explosive_arrows",
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


# Sprint 5.32 (BLT-parity #46) — daily reward presets.
# 1 раз в день (UTC reset) viewer выбирает либо gold либо XP.
DAILY_GOLD_AMOUNT = 100_000   # динаров
DAILY_XP_AMOUNT   = 50_000    # XP в random skill


@router.get("/api/bannerlord/daily-status")
async def bannerlord_daily_status(request: Request):
    """Status дейлика: можно ли клеймить сегодня + что забирал в прошлый раз.

    Returns: {can_claim: bool, last_claim_date, last_reward_type,
              today_date, reward_amounts: {gold, xp}}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        # SQLite DATE('now') возвращает UTC date (YYYY-MM-DD).
        cur = await conn.execute(
            "SELECT claim_date, reward_type FROM bannerlord_daily_claims "
            "WHERE channel_id=? AND username=? "
            "ORDER BY claim_date DESC LIMIT 1",
            (channel_id, username))
        row = await cur.fetchone()
        last_date = row[0] if row else None
        last_type = row[1] if row else None

        cur = await conn.execute("SELECT DATE('now')")
        today_row = await cur.fetchone()
        today = today_row[0] if today_row else None

    can_claim = (last_date != today)
    return {
        "success":           True,
        "can_claim":         can_claim,
        "last_claim_date":   last_date,
        "last_reward_type":  last_type,
        "today_date":        today,
        "reward_amounts":    {"gold": DAILY_GOLD_AMOUNT, "xp": DAILY_XP_AMOUNT},
    }


@router.post("/api/bannerlord/daily-claim")
async def bannerlord_daily_claim(request: Request):
    """Заклеймить дейлик. Body: {reward_type: 'gold'|'xp'}.

    Atomic: BEGIN IMMEDIATE → check not already claimed today → INSERT claim →
    enqueue action в module_actions → COMMIT. Daily reset на UTC midnight.

    Returns: {success, message, amount, reward_type, action_id}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    try:
        body = await request.json()
    except Exception:
        return {"success": False, "message": "bad JSON"}

    reward_type = (body.get("reward_type") or "").strip().lower()
    if reward_type not in ("gold", "xp"):
        return {"success": False, "message": "reward_type должен быть 'gold' или 'xp'"}

    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")

            # Уже клеймил сегодня?
            cur = await conn.execute(
                "SELECT reward_type FROM bannerlord_daily_claims "
                "WHERE channel_id=? AND username=? AND claim_date=DATE('now')",
                (channel_id, username))
            existing = await cur.fetchone()
            if existing:
                await conn.execute("ROLLBACK")
                return {
                    "success": False,
                    "message": f"Дейлик уже забран сегодня ({existing[0]}). "
                               f"Возвращайся завтра!",
                }

            # INSERT claim record.
            await conn.execute(
                "INSERT INTO bannerlord_daily_claims "
                "(channel_id, username, claim_date, reward_type) "
                "VALUES (?, ?, DATE('now'), ?)",
                (channel_id, username, reward_type))

            # Enqueue mod action.
            action_id = uuid.uuid4().hex
            if reward_type == "gold":
                payload = {
                    "initiated_by": username,
                    "target":       username,
                    "item_type":    "gold",
                    "amount":       DAILY_GOLD_AMOUNT,
                    "_daily":       True,
                }
                action_type = "player.give_item"
                amount = DAILY_GOLD_AMOUNT
                msg = f"🎁 +{DAILY_GOLD_AMOUNT:,}💰 динаров — приходи завтра за новым!"
            else:
                payload = {
                    "initiated_by": username,
                    "target":       username,
                    "skill_key":    "",   # mod random pick
                    "xp":           DAILY_XP_AMOUNT,
                    "_daily":       True,
                }
                action_type = "hero.add_skill"
                amount = DAILY_XP_AMOUNT
                msg = f"🎁 +{DAILY_XP_AMOUNT:,} XP в случайный скилл — приходи завтра!"

            await conn.execute(
                "INSERT INTO module_actions "
                "(channel_id, module_id, action_id, type, data, status) "
                "VALUES (?, 'bannerlord', ?, ?, ?, 'queued')",
                (channel_id, action_id, action_type,
                 json.dumps(payload, ensure_ascii=False)))

            await conn.commit()
            log.info("[bannerlord DAILY] ch=%s user=%s type=%s amount=%s action_id=%s",
                     channel_id, username, reward_type, amount, action_id)
            return {
                "success":     True,
                "message":     msg,
                "amount":      amount,
                "reward_type": reward_type,
                "action_id":   action_id,
            }
        except Exception as ex:
            try: await conn.execute("ROLLBACK")
            except Exception: pass
            log.exception("daily-claim failed: %s", ex)
            return {"success": False, "message": f"server error: {ex}"}


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
            "entry_fee_gold": TOURNAMENT_ENTRY_FEE_GOLD,  # legacy 0 — backward-compat
            "join_price":     TOURNAMENT_JOIN_PRICE,      # 5.28: 1000 крустиков
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


# Sprint 5.30 #41 — power activation events для overlay broadcast.
# Ring buffer per-channel, auto-prune events older than 30s. Overlay polls
# every 1s, renders big floating banner for each new event (по seq counter).
_power_events: dict[int, list[dict]] = {}
_power_events_seq: dict[int, int] = {}
_POWER_EVENTS_TTL_SEC = 30


def _push_power_event(channel_id: int, user: str, power_key: str,
                       value: float = 0.0, duration_s: float = 0.0) -> None:
    """Inline-called from buy_action когда action_type=power.activate.
    Append event в ring buffer + prune старые. Idempotent через seq."""
    import time
    now = time.time()
    seq = _power_events_seq.get(channel_id, 0) + 1
    _power_events_seq[channel_id] = seq
    lst = _power_events.setdefault(channel_id, [])
    lst.append({
        "seq":         seq,
        "ts":          now,
        "user":        (user or "").lower(),
        "power_key":   power_key,
        "value":       value,
        "duration_s":  duration_s,
    })
    # Prune expired
    cutoff = now - _POWER_EVENTS_TTL_SEC
    _power_events[channel_id] = [e for e in lst if e["ts"] >= cutoff]


@router.get("/api/overlay/bannerlord/power-events")
async def overlay_bannerlord_power_events(channel_id: int = 0, since_seq: int = 0):
    """Sprint 5.30 #41 — recent power activations для overlay big-banner display.

    Public endpoint (no JWT) для OBS browser source.
    Returns events with seq > since_seq. Overlay polls с last seq → animates
    каждое новое событие как floating banner ~3-5s.

    Returns: {success, events: [...], cursor: max_seq}
    """
    if channel_id <= 0:
        from dependencies import resolve_channel_id_or_default
        channel_id = resolve_channel_id_or_default()

    lst = _power_events.get(channel_id, [])
    fresh = [e for e in lst if e["seq"] > int(since_seq or 0)]
    max_seq = max((e["seq"] for e in fresh), default=int(since_seq or 0))
    return {
        "success":  True,
        "events":   fresh,
        "cursor":   max_seq,
    }


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
    "hero.set_combat_stance", # 2026-06-10: боевая стойка (defensive/balanced/aggressive)
    "power.activate",         # Sprint 4.3: active power burst
    "hero.upgrade_gear",      # Sprint M20: 6-tier equipment progression
    "hero.reequip_gear",      # 2026-05-29: re-roll снаряги на текущем тире (BLT ReequipInsteadOfUpgrade)
    "player.spawn",
    "player.heal",
    "player.respawn",
    "player.give_item",
    "player.equip_item",
    "player.modify_attribute",
    "world.trigger_event",
    "hero.add_skill",
    "hero.recruit_troops",
    "hero.train_troops",         # 2026-05-29 (BLT TrainingBehavior): bulk-upgrade свиты за динары
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
    "hero.set_gender",           # Sprint 5.27a: gender swap (Hero.Gold 50K)
    "hero.marry",                # Sprint 5.27b: marriage to random NPC (50K)
    "hero.divorce",              # Sprint 5.27b: free divorce
    "hero.make_baby",            # Sprint 5.27c: pregnancy (100K)
    "hero.smith_item",           # Sprint 5.29 BLT-parity #6: trophy crafting
    "hero.equip_trophy",         # Sprint 5.29 BLT-parity #6 phase A: equip into hero inventory
    # Sprint 5.32 (BLT-parity Detachment) — viewer командует своим hero-agent'ом
    # in-Mission. Detach → hold/charge/walls/gate. Возвращение через attach.
    # Pattern из Randomchair22-fork BLT (BLTHeroDetachmentBehavior, апрель 2026).
    "hero.detach",               # Вынуть из formation в собственный отряд
    "hero.attach",               # Вернуть обратно в parent formation
    "hero.detach_hold",          # Стоять на текущей позиции (sniper-mode)
    "hero.detach_charge",        # Бежать на ближайшее enemy formation
    "hero.detach_walls",         # Siege only: лезть на стены/лестницы/башни
    "hero.detach_gate",          # Siege only: к ближайшим воротам/баррикаде
    # Sprint 5.33 (BLT-parity FAM) — viewer↔viewer семейные интеракции
    # между взрослыми детьми. Proposal flow с accept/reject через 24h timeout.
    "hero.propose_marriage",     # A → B: «поженим Маше и Петю?»
    "hero.respond_marriage_proposal", # B принимает/отклоняет
    "hero.cancel_proposal",      # A отзывает proposal до response
    "hero.rename_child",         # переименовать своего взрослого ребёнка
    "hero.change_child_looks",   # body code change ребёнка
    "hero.respec_child_skills",  # re-init child skills (HeroDeveloper)
    # Sprint 5.33 (BLT-parity VAS) — vassal sub-clan management
    "hero.create_vassal_clan",   # 250K Hero.Gold — выделить heir в новый clan
    "hero.rename_vassal",        # 50K Hero.Gold — rename vassal clan
    # Sprint 5.33 (BLT-parity SIEGE) — party order strategic management
    "hero.party_order_set",      # установить siege/defend/raid/garrison/patrol
    "hero.party_order_release",  # отменить active order
    # Sprint 5.33 (BLT-parity DIPLO) — kingdom politics + ransom
    "hero.enact_policy",         # 1500⦷ king-only — propose+pass policy
    "hero.make_peace",           # 2000⦷ king-only — propose peace с врагом
    "hero.pay_ransom",           # 500⦷ — chip into ransom pool captured hero
    "kingdom.set_tax_rate",      # free king-only — set kingdom tax 0-100% (Backlog #1)
    # Sprint 5.33 (BLT-parity SHOP) — workshops passive income loop
    "hero.buy_workshop",         # 2500⦷ — viewer покупает workshop в town (чистая 💎)
    "hero.sell_workshop",        # free — engine refund 50% capital
    # Sprint 5.33 (BLT-parity FIEF) — fief tribute boost
    "hero.tribute_boost",        # 2000⦷ — +50% multiplier on 1 fief for 7 days
    # Sprint 5.33 (BLT-parity CARAVAN) — mobile passive income trilogy closer
    "hero.buy_caravan",          # 4000⦷ — create caravan party (чистая 💎)
    "hero.sell_caravan",         # free — engine transfer к MainHero
    "hero.pay_caravan_rescue",   # 500⦷ — chip into rescue pool destroyed caravan
)

# Sprint 5.27a — стоимость gender swap (BLT default: 50k).
GENDER_SWAP_COST = 50_000
# Sprint 5.27b — стоимость брака с NPC.
MARRIAGE_COST = 50_000
# Sprint 5.27c — стоимость pregnancy (трюк на дитя).
BABY_COST = 100_000

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


async def _fetch_hero_clan_name(channel_id: int, username: str) -> str:
    """Возвращает cached clan_name героя ('' если клана/героя нет).

    Гейт для действий, требующих клан (брак/дети): бесклановый замужний
    герой крашит ванильную DefaultPregnancyModel на дейли-тике — см.
    BannerlordLink PregnancyModelPatch + crash dump 2026-05-29."""
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT clan_name FROM bannerlord_heroes WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
    return (row[0] if row else "") or ""


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

# Sprint 5.3: tournament entry fee.
# 5.28a: было 0 крустиков + 5000 динаров → отказы в моде, крустики не списывались.
# 5.28b: было 1000 крустиков + 0 динаров → юзер передумал, нужно free.
# 5.28c: ПОЛНОСТЬЮ БЕСПЛАТНО. Идея: turnover в очереди важнее barrier-to-entry,
# монетизация остаётся через ставки на участников (TOURNAMENT_MIN/MAX_BET).
TOURNAMENT_ENTRY_FEE_GOLD = 0              # in-game динары (deprecated, было 5000)
TOURNAMENT_JOIN_PRICE     = 0              # крустиков (5.28c: free)
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
_BACKEND_ONLY_ACTIONS = (
    "tournament.bet", "hero.smith_item",
    # Sprint 5.33 (BLT-parity FAM) — proposal flow это backend state machine.
    # На respond accept backend САМ enqueue'ит mod-action hero.activate_marriage.
    # Сам propose/respond/cancel — backend-only.
    "hero.propose_marriage",
    "hero.respond_marriage_proposal",
    "hero.cancel_proposal",
    # Sprint 5.33 VAS — vassal create/rename — backend INSERT + enqueue mod
    "hero.create_vassal_clan",
    "hero.rename_vassal",
    # Sprint 5.33 SIEGE — party orders — backend INSERT + enqueue mod
    "hero.party_order_set",
    "hero.party_order_release",
    # Sprint 5.33 DIPLO — kingdom politics + ransom — backend INSERT + enqueue mod
    "hero.enact_policy",
    "hero.make_peace",
    "hero.pay_ransom",
    "kingdom.set_tax_rate",
    # Sprint 5.33 SHOP — workshops — backend INSERT/UPDATE + enqueue mod
    "hero.buy_workshop",
    "hero.sell_workshop",
    # Sprint 5.33 FIEF — tribute boost — backend-only state mutation
    "hero.tribute_boost",
    # Sprint 5.33 CARAVAN — caravan lifecycle — backend INSERT/UPDATE + enqueue mod
    "hero.buy_caravan",
    "hero.sell_caravan",
    "hero.pay_caravan_rescue",
)


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
        # + M38 iteration (heir succession counter, Sprint 5.29).
        cur = await conn.execute(
            "SELECT hero_id, display_name, culture, is_alive, is_prisoner, gold, "
            "       location, adopted_at, last_sync, level, clan_name, kingdom_name, "
            "       gear_tier, clan_info_json, kingdom_info_json, "
            "       is_female, family_info_json, "
            "       COALESCE(iteration, 1), "
            "       COALESCE(is_wounded, 0), "
            "       COALESCE(tournament_wins, 0), "
            "       party_info_json, "
            "       COALESCE(combat_stance, 'balanced') "
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
            "is_female":    bool(row[15]) if row[15] is not None else None,
            "family_info":  _safe_json(row[16]),
            "iteration":    int(row[17]) if row[17] is not None else 1,  # Sprint 5.29
            "is_wounded":   bool(row[18]),  # Sprint 5.32 M43 — KO state
            "tournament_wins": int(row[19]) if row[19] is not None else 0,  # Sprint 5.32 H8/FE-H8 veteran badge
            "party_info":   _safe_json(row[20]),  # 2026-06-10 — отряд на карте (size/task/target/in_army)
            "combat_stance": row[21],             # 2026-06-10 — боевая стойка зрителя
        }
        # Convenience: top-level spouse_name (для profile modal display)
        fi = hero.get("family_info") or {}
        sp = fi.get("spouse") if isinstance(fi, dict) else None
        hero["spouse_name"] = sp.get("name") if isinstance(sp, dict) else None

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
        # Sprint 5.27v: нормализуем keys к PascalCase в response, чтобы
        # frontend получал стабильный shape независимо от того, как mod
        # их сохранил (engine StringId был lowercase → frontend ожидал
        # PascalCase → 0/10 для всех). Single source of truth: response.
        cur = await conn.execute(
            "SELECT attribute, value FROM bannerlord_attributes "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        def _to_pascal(k: str) -> str:
            return (k[0].upper() + k[1:].lower()) if k else k
        attributes = {_to_pascal(r[0]): r[1] for r in await cur.fetchall()}

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

        # 2026-06-10 — retinue_cap = 5 + clan-upgrade retinue_size_bonus. Фронт
        # раньше хардкодил 5 → апгрейд «Усиленная свита» не открывал слот свиты.
        retinue_cap = 5
        cur = await conn.execute(
            "SELECT u.effects_json FROM bannerlord_clan_upgrades_owned o "
            "JOIN bannerlord_clan_upgrades_catalog u ON "
            "  u.channel_id = o.channel_id AND u.upgrade_id = o.upgrade_id "
            "WHERE o.channel_id = ? AND o.username = ?",
            (channel_id, username))
        for (eff_json,) in await cur.fetchall():
            try:
                retinue_cap += int((json.loads(eff_json or '{}')).get("retinue_size_bonus", 0) or 0)
            except Exception:
                pass
        hero["retinue_cap"] = retinue_cap

        # 2026-06-10 — недавние рефанды этого зрителя. Mod отказывает действию
        # асинхронно (после ACK) → action.failed → крустики возвращаются, НО
        # зритель не видел ПОЧЕМУ «не сработало» и кликал снова. Отдаём список
        # причин; фронт тостит (дедуп по action_id). Окно 30s покрывает 8s
        # hero-poll без пропусков. error_msg формат: "REFUNDED:{price} reason={r}"
        # (или "REFUNDED:0 (no_price) reason={r}" для бесплатных действий).
        recent_refunds = []
        cur = await conn.execute(
            "SELECT action_id, type, data, error_msg FROM module_actions "
            "WHERE channel_id=? AND module_id='bannerlord' "
            "  AND error_msg LIKE 'REFUNDED:%' "
            "  AND created_at > datetime('now','-30 seconds') "
            "ORDER BY id DESC LIMIT 20",
            (channel_id,))
        _uname = (username or "").lower()
        for _aid, _atype, _adata, _aerr in await cur.fetchall():
            try:
                if (json.loads(_adata or "{}").get("initiated_by") or "").lower() != _uname:
                    continue
            except Exception:
                continue
            _aerr = _aerr or ""
            recent_refunds.append({
                "action_id": _aid,
                "type":      _atype,
                "reason":    _aerr.split("reason=", 1)[-1].strip() or "unspecified",
                "refunded":  not _aerr.startswith("REFUNDED:0"),
            })

    return {
        "success":        True,
        "has_hero":       True,
        "hero":           hero,
        "skills":         skills,
        "attributes":     attributes,
        "equipment":      equipment,
        "retinue":        retinue,
        "recent_refunds": recent_refunds,
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

    # Sprint 5.29 BLT-parity #9: extract role для perk-tier system.
    # Twitch JWT role enum: viewer / broadcaster / moderator / external.
    # Subscriber detection via Helix — TODO (требует broadcaster OAuth scope).
    from auth import verify_twitch_jwt
    _jwt = verify_twitch_jwt(request)
    user_role = (_jwt.get("role") if _jwt.get("status") == "valid" else "viewer") or "viewer"

    body = await request.json()
    action_type = (body.get("action_type") or "").strip()
    data = body.get("data") or {}
    if not isinstance(data, dict):
        return {"success": False, "message": "data должен быть объектом"}
    # Pass role в data для mod (использует для XP/gold boost).
    data["_user_role"] = user_role

    # Sprint 5.32 VERBOSE-5 — entry log для request tracing. client_action_id
    # (H1 idempotency) + action_type + user — full chain visibility.
    _client_id = (data.get("client_action_id") or "").strip() or "?"
    log.info("[BNR-ACTION enter] ch=%s user=@%s role=%s action=%s client_id=%s",
             channel_id, username, user_role, action_type, _client_id[:12])

    # Sprint 5.29 audit fix #39 — per-user serialization (double-spend prevention).
    # Wrap entire handler в asyncio.Lock keyed (channel, username).
    # Без этого два simultaneous actions того же viewer'а оба видят кэшированный
    # gold/balance, оба validate, оба charge — refund для второго работает,
    # но это плодит ненужные actions в outbox + spam в логах.
    user_lock = await _get_user_lock(channel_id, username)
    async with user_lock:
        return await _bannerlord_buy_action_locked(
            request, username, channel_id, action_type, data)


async def _bannerlord_buy_action_locked(request, username, channel_id, action_type, data):
    """Sprint 5.29: extracted body of bannerlord_buy_action — runs под user_lock."""

    if action_type not in _PURCHASABLE_ACTIONS:
        return {"success": False, "message": f"Action '{action_type}' не разрешён"}

    # Sprint 5.1c/5.2: server-side price enforcement.
    # Random equip — БЕСПЛАТНО в крустиках (price=0), mod-side списывает
    # Hero.Gold (in-game динары) — fairness через game economy.
    # Mirror HERO_GOLD_RANDOM_PRICES в C# EquipItemHandler.
    RANDOM_EQUIP_HERO_GOLD = {
        # 5.27o: повышены до T5–T6 уровня (random equip даёт high-tier
        # items, baseline должен соответствовать ценности).
        "weapon": 1_000_000,
        "armor":    500_000,
        "horse":  1_000_000,
    }
    RANDOM_EQUIP_PRICES = RANDOM_EQUIP_HERO_GOLD  # legacy name (some refs ниже)
    SPAWN_PRICES = {
        "player": 50,     # на сторону стримера (ally) — 5.27i: ×0.5 от 100
        "enemy":  100,    # против стримера — 2× as тролл-tax — 5.27i: ×0.5 от 200
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
    if action_type in ("hero.recruit_troops", "player.spawn", "hero.create_party",
                       "hero.train_troops"):
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
                # Sprint 5.26d: retinue_size_bonus из clan upgrades суммируется
                # к базовым 5 slots. Бонус = sum effects.retinue_size_bonus по
                # owned upgrades этого юзера в этом канале.
                base_cap = 5
                bonus_cap = 0
                cur = await conn.execute(
                    "SELECT u.effects_json FROM bannerlord_clan_upgrades_owned o "
                    "JOIN bannerlord_clan_upgrades_catalog u ON "
                    "  u.channel_id = o.channel_id AND u.upgrade_id = o.upgrade_id "
                    "WHERE o.channel_id = ? AND o.username = ?",
                    (channel_id, username))
                for (eff_json,) in await cur.fetchall():
                    try:
                        eff = json.loads(eff_json or '{}')
                        bonus_cap += int(eff.get("retinue_size_bonus", 0) or 0)
                    except Exception:
                        pass
                MAX_RETINUE = base_cap + bonus_cap

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
            # 2026-05-29 currency re-map: рекрут платится ТОЛЬКО динарами героя
            # (hero_gold_cost ниже, списывается модом). Крустиковая часть убрана
            # — одно действие = одна валюта (армия = кошелёк героя 💰).
            data["price"] = 0

        if action_type == "hero.train_troops":
            # 2026-05-29 (BLT TrainingBehavior): тренировка свиты платится ТОЛЬКО
            # динарами героя — мод списывает сумму апгрейдов всех слотов. retinue
            # snapshot уже приложен выше. Крустиков 0.
            data["price"] = 0

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

    # 2026-05-29 hero.reequip_gear — «переформировать снаряжение» (BLT
    # ReequipInsteadOfUpgrade). Ре-ролл на ТЕКУЩЕМ тире (без повышения), FREE,
    # работает в т.ч. на T6 (фикс-утилита при кривой экипировке). Mod
    # переиспользует ApplyGearLoadout.
    if action_type == "hero.reequip_gear":
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
        class_key = (row[1] or "").lower()
        if not class_key:
            return {
                "success": False,
                "message": "Сначала выбери класс — он определяет slot template",
            }
        data["class_key"] = class_key
        data["gear_tier"] = row[0] or 0     # текущий тир — ре-ролл на нём
        data["price"] = 0                   # крустики: бесплатно (utility/fix)

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
            # 5.27s diagnostic: log refuse так стример видит причину в supervisor.
            print(f"[bannerlord:{channel_id}] hero.add_attribute REFUSE @{username} "
                  f"attr={attr_key or 'random'} cost={cost} hero_gold={hero_gold}")
            return {
                "success": False,
                "message": f"Нужно {cost:,}💰 динаров у героя (у тебя {hero_gold:,}💰). "
                           "Заработай в битвах или конвертируй крустики в gold.",
            }
        print(f"[bannerlord:{channel_id}] hero.add_attribute QUEUE @{username} "
              f"attr={attr_key or 'random'} amount={amount} cost={cost}")
        data["attribute_key"] = attr_key  # '' = random
        data["amount"] = amount
        data["hero_gold_cost"] = cost
        data["price"] = 0

    # Sprint 5.27a: hero.set_gender — gender swap (50k💰 Hero.Gold).
    # Body: {gender: "male"|"female"}. Mod auto-flips spouse если есть
    # (Bannerlord не любит same-sex marriages).
    if action_type == "hero.set_gender":
        gender = (data.get("gender") or "").strip().lower()
        if gender not in ("male", "female"):
            return {"success": False, "message": "gender должен быть male|female"}
        hero_gold = await _fetch_hero_gold(channel_id, username)
        if hero_gold < GENDER_SWAP_COST:
            return {
                "success": False,
                "message": f"Нужно {GENDER_SWAP_COST:,}💰 для смены пола "
                           f"(у тебя {hero_gold:,}💰).",
            }
        data["gender"] = gender
        data["hero_gold_cost"] = GENDER_SWAP_COST
        data["price"] = 0  # крустики free

    # Sprint 5.27b: hero.marry — брак с random suitable NPC (50K💰).
    # Mod выбирает подходящую NPC (opposite gender, single, 18+, не [BLink]).
    if action_type == "hero.marry":
        # 2026-05-29: брак требует клан. Бесклановый замужний герой крашит
        # ванильную DefaultPregnancyModel на дейли-тике (PregnancyModelPatch).
        # Фронт уже дизейблит кнопку, но клиент обходим — гейтим и на сервере.
        if not await _fetch_hero_clan_name(channel_id, username):
            return {
                "success": False,
                "message": "Нужен клан для брака — сначала создай или вступи в клан (🏰).",
            }
        hero_gold = await _fetch_hero_gold(channel_id, username)
        if hero_gold < MARRIAGE_COST:
            return {
                "success": False,
                "message": f"Нужно {MARRIAGE_COST:,}💰 для брака "
                           f"(у тебя {hero_gold:,}💰).",
            }
        data["hero_gold_cost"] = MARRIAGE_COST
        data["price"] = 0

    # Sprint 5.27b: hero.divorce — free (никакой gold check, мод просто
    # обнуляет Spouse). Развод emotionally free :)
    if action_type == "hero.divorce":
        data["hero_gold_cost"] = 0
        data["price"] = 0

    # Sprint 5.27c: hero.make_baby — pregnancy через MakePregnantAction (100K💰).
    # Mod проверяет spouse + age + max children (5).
    if action_type == "hero.make_baby":
        # 2026-05-29: дети рождаются в клан родителя; бесклановый родитель →
        # клейтлесс-дети → краш беременности. Требуем клан (как и брак).
        if not await _fetch_hero_clan_name(channel_id, username):
            return {
                "success": False,
                "message": "Нужен клан, чтобы заводить детей — создай или вступи в клан (🏰).",
            }
        hero_gold = await _fetch_hero_gold(channel_id, username)
        if hero_gold < BABY_COST:
            return {
                "success": False,
                "message": f"Нужно {BABY_COST:,}💰 для зачатия "
                           f"(у тебя {hero_gold:,}💰).",
            }
        data["hero_gold_cost"] = BABY_COST
        data["price"] = 0

    # 2026-05-29: hero.propose_marriage женит ДЕТЕЙ двух viewer'ов. Дети
    # наследуют клан родителя — у бесклановых детей брак даёт тот же
    # клейтлесс-краш беременности. Гейтим за клан инициатора (его дети в его
    # клане). Сам proposal обрабатывается ниже (handle_propose_marriage).
    if action_type == "hero.propose_marriage":
        if not await _fetch_hero_clan_name(channel_id, username):
            return {
                "success": False,
                "message": "Нужен клан, чтобы устраивать браки детей — создай или вступи в клан (🏰).",
            }

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

    # Sprint 5.29 BLT-parity #6 phase A: hero.equip_trophy — pre-validate
    # ownership + inject trophy details в data для mod handler.
    if action_type == "hero.equip_trophy":
        try:
            trophy_id = int(data.get("custom_item_id") or 0)
        except (TypeError, ValueError):
            trophy_id = 0
        if trophy_id <= 0:
            return {"success": False, "message": "custom_item_id required"}
        db_tmp = get_db()
        async with db_tmp._connect() as conn:
            cur = await conn.execute(
                "SELECT base_type, base_subtype, custom_name, rarity, tier, "
                "       COALESCE(damage_bonus, 0), COALESCE(armor_bonus, 0), "
                "       COALESCE(weight_factor, 1.0), COALESCE(speed_factor, 1.0), "
                "       COALESCE(claimed, 0) "
                "FROM bannerlord_custom_items "
                "WHERE id=? AND channel_id=? AND owner_username=?",
                (trophy_id, channel_id, username))
            row = await cur.fetchone()
            if not row:
                return {"success": False, "message": "Трофей не найден / не твой"}
            # Phase B — нельзя получить один предмет дважды (анти double-bonus).
            if int(row[9] or 0) == 1:
                return {"success": False, "message": "Этот предмет уже получен в игре"}
            # Optimistic claim — предмет уходит в инвентарь героя через mod.
            await conn.execute(
                "UPDATE bannerlord_custom_items SET claimed=1 WHERE id=?", (trophy_id,))
            await conn.commit()
        data["base_type"]    = row[0]
        data["base_subtype"] = row[1]
        data["custom_name"]  = row[2]
        data["rarity"]       = row[3]
        data["tier"]         = row[4]
        # Sprint 5.33 (BLT-parity ITEM) — rolled stats injection.
        # Mod-side EquipTrophyHandler читает эти поля и регистрирует в
        # ActiveTrophyState для apply через DamageHookPatch.
        data["damage_bonus"]  = row[5]
        data["armor_bonus"]   = row[6]
        data["weight_factor"] = row[7]
        data["speed_factor"]  = row[8]
        data["price"] = 0

    # Sprint 5.3 / 5.28 update: hero.join_tournament — 1000 крустиков, 0 динаров.
    # Раньше было: 0 крустиков + 5000 динаров in-game → adopted viewer'ы часто
    # без денег → отказы в моде, крустики уже потрачены (не было).
    # Теперь: 1000 крустиков списываются на backend ДО enqueue (universal
    # buy-action price path), мод гарантированно ставит в очередь.
    # mod = source-of-truth для очереди (event tournament.joined → INSERT).
    if action_type == "hero.join_tournament":
        # Sprint 5.31 #45d (audit HIGH-5) — checks перенесены ВНУТРЬ BEGIN
        # IMMEDIATE ниже (см. _tournament_join_atomic_check). Раньше SELECT
        # status + SELECT queue делались отдельной connection ВНЕ TX —
        # два одновременных POST'а могли пройти оба SELECT'а, оба
        # списывали 1000⦷, второй уходил в never-land без refund.
        # Теперь checks под одним IMMEDIATE lock'ом — serialized.
        data["hero_gold_cost"] = 0           # mod больше не списывает динары
        data["price"] = TOURNAMENT_JOIN_PRICE  # 1000 крустиков

    # 1.5 compliance (2026-06-11): tournament.bet → БЕСПЛАТНЫЙ no-loss ПРОГНОЗ
    # на победителя. Крустики НЕ списываются и НЕ сгорают; верный прогноз даёт
    # фикс-бонус из платформенного пула (см. _adapter._on_tournament_ended).
    # Убрали wager-на-исход (дух §6.2.6) — как уже сделали для дуэлей.
    if action_type == "tournament.bet":
        target = (data.get("target") or "").strip().lower()
        if not target:
            return {"success": False, "message": "Не указан участник"}
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
        # Sprint 5.31 #45e (audit MED-6) — dedup check внутри BEGIN IMMEDIATE ниже.
        data["target"] = target
        data["amount"] = 0          # no-loss: ставка не берётся
        data["round_index"] = round_index
        data["price"] = 0           # бесплатный прогноз — ничего не списываем

    # ════════════════════════════════════════════════════════════════════
    # Sprint 5.29 audit fix #32 — server-side ACTION_PRICES enforcement.
    # ════════════════════════════════════════════════════════════════════
    # SECURITY: до этого fix'а viewer мог POST `{action_type: "player.heal",
    # data: {price: 0}}` и получить бесплатное действие. Backend читал
    # data["price"] напрямую из viewer payload'а для actions БЕЗ explicit
    # per-action branch. Fix: server-side price table enforce'ит цену.
    #
    # Two categories:
    #   _ACTIONS_WITH_OWN_PRICING — already set data["price"] выше
    #     (player.spawn → SPAWN_PRICES per-side; tournament.bet → amount;
    #      все *clan/kingdom/party/marry/* → 0 потому что mod использует
    #      Hero.Gold; etc.).
    #   ACTION_PRICES_DEFAULT — fallback для actions БЕЗ branch'а.
    #     Hardcoded crustic price, viewer override игнорируется.
    #
    # Unknown action (не в одном из двух) → REFUSE (security gate, новые
    # actions требуют explicit price entry).
    # Sprint 5.32 BUGFIX — player.give_item и hero.add_skill ИМЕЮТ собственный
    # pricing валидатор (GIVE_GOLD_PRESETS / ADD_SKILL_XP_PRESETS) выше в этой
    # функции (~L1265, ~L1140). Они должны быть в _ACTIONS_WITH_OWN_PRICING,
    # иначе ACTION_PRICES_DEFAULT внизу перезаписывает их preset price на 100
    # → viewer платит 100 крустиков за 5000 динаров (вместо 1000⦷). Это
    # security/exploit гэп — sub'ы с Boosty tier3 ×0.5 платили 50 за 5K динаров.
    _ACTIONS_WITH_OWN_PRICING = {
        "player.spawn", "player.equip_item", "hero.set_class",
        "hero.upgrade_gear", "hero.reequip_gear", "hero.recruit_troops", "hero.train_troops",
        "hero.join_tournament", "tournament.bet",
        "hero.create_clan", "hero.create_kingdom", "hero.leave_clan",
        "hero.leave_kingdom", "hero.join_clan", "hero.join_kingdom",
        "hero.create_party", "hero.set_gender", "hero.marry",
        "hero.divorce", "hero.make_baby",
        "hero.add_focus", "hero.add_attribute",
        "hero.equip_trophy",  # Sprint 5.29 BLT-parity #6 phase A
        # Sprint 5.32 BUGFIX — обе currency-conversion actions имеют свои
        # presets; без этого list'а DEFAULT перезатирает их.
        "player.give_item",   # 1000/5000/20000⦷ → 5K/25K/100K динаров (M21)
        "hero.add_skill",     # 500/1000/5000⦷ → 50/100/500 XP (M21)
    }
    ACTION_PRICES_DEFAULT = {
        "hero.create":             0,    # adoption — free
        "player.heal":            50,
        "player.respawn":        500,    # heir succession (future)
        "player.modify_attribute": 50,
        "world.trigger_event":  1000,    # heavy / admin-style
        "power.activate":         50,    # standardize crustik price per power use
        "hero.smith_item":       500,    # Sprint 5.29 BLT-parity #6 — trophy crafting
        "hero.equip_trophy":      0,    # Sprint 5.29 BLT-parity #6 phase A — free (viewer уже заплатил smith)
        "hero.set_combat_stance": 0,    # 2026-06-10: боевая стойка — бесплатно, мгновенно
        # Sprint 5.32 BUGFIX — player.give_item / hero.add_skill убраны
        # отсюда (перенесены в _ACTIONS_WITH_OWN_PRICING выше).
        # Sprint 5.32 (BLT-parity Detachment) — 6 commands управления своим
        # hero-agent'ом в Mission. Цены низкие (10-30⦷) потому что spam-friendly:
        # в активной битве viewer должен мочь часто переключать команды.
        "hero.detach":            10,
        "hero.attach":            10,
        "hero.detach_hold":       30,
        "hero.detach_charge":     30,
        "hero.detach_walls":      30,
        "hero.detach_gate":       30,
        # Sprint 5.33 (BLT-parity FAM) — семейные viewer↔viewer интеракции.
        # Propose/respond — viral engagement-loop, цены символические.
        # Rename/looks/respec — cosmetic + customization.
        "hero.propose_marriage":         100,   # viewer A: «поженим Машу + Петю?»
        "hero.respond_marriage_proposal": 0,    # accept/reject — free
        "hero.cancel_proposal":           0,    # withdraw — free
        "hero.rename_child":             50,    # customize child name
        "hero.change_child_looks":      200,    # body change (BLT pattern)
        "hero.respec_child_skills":     500,    # full skill re-roll
        # Sprint 5.33 (BLT-parity VAS) — sub-clan progression. High crustic
        # entry barrier — это long-term feature, не impulse-buy.
        "hero.create_vassal_clan":        0,    # 2026-05-29 currency re-map: платится Hero.Gold (как обычный клан), мод списывает 💰
        "hero.rename_vassal":           100,    # cosmetic
        # Sprint 5.33 (BLT-parity SIEGE) — party strategic orders
        "hero.party_order_set":         500,    # significant strategic decision
        "hero.party_order_release":       0,    # free cancel
        # Sprint 5.33 (BLT-parity DIPLO) — kingdom politics + ransom
        "hero.enact_policy":           1500,    # king-only major political move
        "hero.make_peace":             2000,    # king-only diplomatic decision
        "hero.pay_ransom":              500,    # crowd-fund tier, any viewer
        "kingdom.set_tax_rate":           0,    # free — king manages own kingdom (Backlog #1)
        # Sprint 5.33 (BLT-parity SHOP) — workshops passive income
        "hero.buy_workshop":           2500,    # 2026-05-29: чистая 💎 (Hero.Gold капитал НЕ списывался — миф убран, цена поднята 1000→2500)
        "hero.sell_workshop":             0,    # free — engine handles refund
        # Sprint 5.33 (BLT-parity FIEF) — fief tribute boost
        "hero.tribute_boost":          2000,    # 7-day +50% multiplier на 1 fief
        # Sprint 5.33 (BLT-parity CARAVAN) — mobile passive income
        "hero.buy_caravan":            4000,    # 2026-05-29: чистая 💎 (15K Hero.Gold капитал НЕ списывался — миф убран, цена поднята 1500→4000)
        "hero.sell_caravan":              0,    # free — engine handles transfer
        "hero.pay_caravan_rescue":      500,    # rescue pool chip-in
    }
    if action_type not in _ACTIONS_WITH_OWN_PRICING:
        if action_type not in ACTION_PRICES_DEFAULT:
            log.warning(
                "[bannerlord SECURITY REFUSE] no server-side price for %s user=%s ch=%s",
                action_type, username, channel_id)
            return {
                "success": False,
                "message": f"Action '{action_type}' не имеет server-side цены",
            }
        # Жёсткий override — viewer не может задать price.
        data["price"] = ACTION_PRICES_DEFAULT[action_type]

    try:
        price = int(data.get("price", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверная цена"}
    if price < 0:
        return {"success": False, "message": "Цена не может быть отрицательной"}

    # Sprint 5.33 TOS-COMPLIANCE (2026-05-28) — REMOVED subscription bonuses.
    # Twitch Extension ToS / Community Guidelines:
    #   - Cannot gate gameplay rewards behind Twitch subscriptions
    #   - Cannot give sub'ам discount on in-extension currency
    #   - Cannot give sub'ам extra rewards
    # Removed:
    #   - Twitch Tier 1/2/3 multipliers (0.85/0.70/0.50× price, 1.5/2.0/3.0× rewards)
    #   - Boosty Tier 1/2/3 same multipliers (third-party paywall, same spirit)
    # Kept (role-based, NOT subscription-based — OK per ToS):
    #   - broadcaster (channel owner) → 0.5× price, 2.0× rewards
    # Removed 2026-06-06 (по просьбе стримера; Twitch против привилегий по роли):
    #   - moderator boost (был 0.75× price, 1.5× rewards) → теперь 1.0/1.0.
    #     role_label="moderator" сохранён ТОЛЬКО для admin-гейта world.trigger_event.
    #
    # Sprint 5.32 fix — `_jwt` был bound в внешнем bannerlord_buy_action,
    # но эта функция (_bannerlord_buy_action_locked) — отдельная scope.
    from auth import verify_twitch_jwt
    _jwt = verify_twitch_jwt(request)
    _user_role = (_jwt.get("role") or "viewer") if _jwt.get("status") == "valid" else "viewer"
    _user_twitch_id = (_jwt.get("user_id") or "") if _jwt.get("status") == "valid" else ""

    if _user_role == "broadcaster":
        price_mult, reward_mult, role_label = 0.5, 2.0, "broadcaster"
    elif _user_role == "moderator":
        # 2026-06-06 — boost модераторов УБРАН (Twitch против привилегий-наград
        # по роли). role_label остаётся "moderator" ТОЛЬКО для admin-гейта
        # world.trigger_event; скидки на цену и бонуса к награде больше нет.
        price_mult, reward_mult, role_label = 1.0, 1.0, "moderator"
    else:
        # Sub status (Twitch + Boosty) больше НЕ влияет на price/reward.
        # Detection функции остаются для optional cosmetic UI (badge) если
        # понадобятся в будущем — НЕ для perks.
        price_mult, reward_mult, role_label = 1.0, 1.0, "viewer"
    # Sprint 5.33 TOS-COMPLIANCE — REMOVED subscriber-only action gating.
    # Twitch ToS prohibits gating gameplay features за Twitch subscription.
    # Previously gated:
    #   hero.set_gender → "subscriber"     — теперь open для всех
    #   hero.create_kingdom → "subscriber" — теперь open для всех (цена 5M Hero.Gold
    #     остаётся естественным economic gate)
    #   world.trigger_event → "moderator"  — admin-style, OK keep (channel role)
    # Kept gating only для channel roles (broadcaster/moderator), не subscription.
    _ROLE_PRIORITY = {
        "viewer":      0,
        "moderator":   2,
        "broadcaster": 3,
    }
    _ACTIONS_MIN_ROLE = {
        "world.trigger_event":   "moderator",  # admin-style spawn, OK keep
    }
    required_role = _ACTIONS_MIN_ROLE.get(action_type)
    if required_role:
        my_priority = _ROLE_PRIORITY.get(role_label, 0)
        need_priority = _ROLE_PRIORITY.get(required_role, 0)
        if my_priority < need_priority:
            log.info(
                "[bannerlord ROLE-GATE REFUSE] action=%s required=%s user=%s "
                "role=%s priority=%d<%d",
                action_type, required_role, username, role_label,
                my_priority, need_priority)
            human_role = {
                "moderator":   "модераторов",
                "broadcaster": "стримера",
            }.get(required_role, required_role)
            return {
                "success": False,
                "message": f"Это действие доступно только для {human_role}.",
                "required_role": required_role,
                "your_role":     role_label,
            }

    if price > 0 and price_mult < 1.0:
        new_price = max(0, int(price * price_mult))
        price = new_price
        data["price"] = price   # backend uses this in TX
    data["reward_boost"] = reward_mult   # mod использует
    data["_perk_label"] = role_label    # для frontend UI (badge)
    # Sprint 5.31 #45c — UNCONDITIONAL perk-resolve log. Каждая покупка
    # оставляет запись о том, какой role/tier применился и почему. Без этого
    # нельзя дебажить "почему мне не дали скидку" / "почему BS2 не сработал".
    log.info("[bannerlord PERK RESOLVED] ch=%s user=%s action=%s role=%s "
             "price=%d×%.2f reward×%.2f",
             channel_id, username, action_type, role_label, price, price_mult, reward_mult)

    # Sprint 4.8/5.0: server-side cooldown enforcement.
    # Для power.activate ключ cooldown'а = data.power_key (per-power).
    # Для player.spawn — split per-side (Sprint 5.29: ally и enemy раздельно).
    # Sprint 5.29 audit fix #28: extended на spam-prone actions
    # (recruit / heal / equip / add_skill / add_focus / add_attribute / marry / etc.)
    # — ACTION_COOLDOWNS_SEC в _adapter.py.
    # Frontend disable — UX only; реальная защита здесь.
    cooldown_key = None
    if action_type == "power.activate":
        cooldown_key = (data.get("power_key") or "").strip().lower() or None
    elif action_type == "player.spawn":
        # split per-side — ally CD не блокирует enemy и наоборот
        side = (data.get("side") or "player").strip().lower()
        cooldown_key = f"player.spawn:{side}"
    else:
        # Sprint 5.29: fallback к action-level CD из ACTION_COOLDOWNS_SEC.
        from modules.bannerlord._adapter import ACTION_COOLDOWNS_SEC
        if action_type in ACTION_COOLDOWNS_SEC:
            cooldown_key = action_type

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

            # Sprint 5.32 (BLT-parity H1) — client_action_id idempotency.
            # Frontend генерит crypto.randomUUID() при первом отправлении
            # action'а и шлёт его в payload. При retry (network blip /
            # multi-click / proxy replay) — backend видит конфликт по
            # UNIQUE (channel_id, module_id, client_action_id) и возвращает
            # прежний result БЕЗ charge'а. Защита от двойного списания
            # крустиков. BLT использует Twitch redemption-id (natural key),
            # у нас natural key'а нет — client_action_id от frontend.
            client_action_id = (data.get("client_action_id") or "").strip() or None
            if client_action_id:
                cur_idem = await conn.execute(
                    "SELECT action_id, type, status FROM module_actions "
                    "WHERE channel_id=? AND module_id='bannerlord' "
                    "AND client_action_id=? LIMIT 1",
                    (channel_id, client_action_id))
                idem_row = await cur_idem.fetchone()
                if idem_row:
                    prev_action_id, prev_type, prev_status = idem_row
                    await conn.execute("ROLLBACK")
                    log.info(
                        "[bannerlord IDEM] retry hit ch=%s user=%s "
                        "client_id=%s → reusing action_id=%s (type=%s status=%s)",
                        channel_id, username, client_action_id,
                        prev_action_id, prev_type, prev_status)
                    return {
                        "success":          True,
                        "message":          "Действие уже принято",
                        "action_id":        prev_action_id,
                        "idempotent_replay": True,
                    }

            # Sprint 5.31 #45e (audit MED-6) — tournament.bet dedup
            # ВНУТРИ TX, защищён BEGIN IMMEDIATE lock'ом. Раньше SELECT был
            # отдельной connection — два concurrent bet'а от того же юзера
            # обходили dedup и оба charge'или.
            if action_type == "tournament.bet":
                cur = await conn.execute(
                    "SELECT 1 FROM bannerlord_tournament_bets "
                    "WHERE channel_id=? AND bettor=? AND round_index=?",
                    (channel_id, username, data.get("round_index", 0)))
                if await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    return {
                        "success": False,
                        "message": f"Ты уже ставил в раунде "
                                   f"{int(data.get('round_index', 0)) + 1}",
                    }

            # Sprint 5.31 #45d (audit HIGH-5) — для hero.join_tournament: проверка
            # status + dedup ВНУТРИ BEGIN IMMEDIATE (один lock с charge). Раньше
            # эти SELECT'ы были вне TX — race window между ними и charge.
            if action_type == "hero.join_tournament":
                cur = await conn.execute(
                    "SELECT status FROM bannerlord_tournament_state WHERE channel_id=?",
                    (channel_id,))
                _row = await cur.fetchone()
                _status = (_row[0] if _row else "idle") or "idle"
                if _status == "running":
                    await conn.execute("ROLLBACK")
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
                    await conn.execute("ROLLBACK")
                    return {
                        "success": False,
                        "message": "Ты уже в очереди на турнир",
                    }
                # Pending join action в outbox (не ACK'нут модом)? Защита от
                # double-click: ACK задержался, второй request видит queue
                # пустым но action ещё in-flight.
                cur = await conn.execute(
                    "SELECT 1 FROM module_actions "
                    "WHERE channel_id=? AND module_id='bannerlord' "
                    "AND type='hero.join_tournament' "
                    "AND json_extract(data, '$.initiated_by')=? "
                    "AND status IN ('queued','dispatched') "
                    "LIMIT 1",
                    (channel_id, username))
                if await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    log.info("[join_tournament] dedup blocked @%s ch=%s "
                             "(pending action in module_actions)",
                             username, channel_id)
                    return {
                        "success": False,
                        "message": "Заявка уже отправлена — подожди подтверждения",
                    }

            # Sprint 5.31 #45d (audit HIGH-6) — atomic single-shot UPDATE
            # вместо SELECT-then-UPDATE. Старый pattern полагался на
            # in-process asyncio.Lock (см. _user_action_locks) — бесполезен
            # под --workers > 1. UPDATE с условием `points >= ?` атомарен
            # на уровне SQLite даже без in-process lock'а; rowcount=0 =
            # недостаточно крустиков (либо row не существует — viewer
            # никогда не зарабатывал).
            if price > 0:
                cur = await conn.execute(
                    "UPDATE viewers SET points = points - ? "
                    "WHERE channel_id=? AND username=? AND points >= ?",
                    (price, channel_id, username, price))
                if cur.rowcount != 1:
                    # Re-read balance чтобы вернуть точное сообщение.
                    cur2 = await conn.execute(
                        "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                        (channel_id, username))
                    _row = await cur2.fetchone()
                    _balance = (_row[0] if _row else 0) or 0
                    await conn.execute("ROLLBACK")
                    return {
                        "success": False,
                        "message": f"Недостаточно крустиков: {_balance} < {price}",
                    }
            # price=0 → ничего не списываем (freebie actions).

            # Enqueue action в outbox (через тот же conn — atomic с charge).
            # tournament.bet — backend-only (не идёт в mod), пропускаем enqueue.
            action_id = uuid.uuid4().hex
            payload = dict(data)
            payload["initiated_by"] = username
            if action_type not in _BACKEND_ONLY_ACTIONS:
                # Sprint 5.32 (BLT-parity H1) — записываем client_action_id
                # для идемпотентности. UNIQUE partial INDEX в m46 блокирует
                # повторные INSERT'ы с тем же client_action_id (хотя мы уже
                # проверили выше — это второй слой защиты против гонки между
                # SELECT и INSERT внутри одной TX).
                await conn.execute("""
                    INSERT INTO module_actions
                        (channel_id, module_id, action_id, type, data, status,
                         client_action_id)
                    VALUES (?, 'bannerlord', ?, ?, ?, 'queued', ?)
                """, (channel_id, action_id, action_type,
                      json.dumps(payload, ensure_ascii=False),
                      client_action_id))

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

            # Sprint 5.29 BLT-parity #6: hero.smith_item — backend-only trophy.
            # Generates random custom item, inserts в bannerlord_custom_items.
            # Mod не задействуется (текущий MVP); future iteration добавит
            # in-game ItemObject creation через mod handler.
            smith_result = None
            if action_type == "hero.smith_item":
                base_type = (data.get("base_type") or "").strip().lower()
                if base_type not in ("weapon", "armor", "horse"):
                    # Этой validation должен был быть сделан до — но guard на всякий
                    await conn.execute("ROLLBACK")
                    return {
                        "success": False,
                        "message": "base_type должен быть weapon / armor / horse",
                    }

                # Sprint 5.32 (BLT-parity M15) — class requirement для weapon smith.
                # BLT pattern (SmithItem.cs:94-97): weapon без class — REFUSE.
                # Без spec'и crafted weapon будет mismatched с hero'й equipment'ом
                # (archer smith'ит two-handed → не может equip без переcasting).
                # Class lock защищает от random смитов "лишь бы потратить крустики".
                if base_type == "weapon":
                    cur_cls = await conn.execute(
                        "SELECT class_key FROM bannerlord_hero_class "
                        "WHERE channel_id=? AND username=?",
                        (channel_id, username))
                    cls_row = await cur_cls.fetchone()
                    if not cls_row or not cls_row[0]:
                        await conn.execute("ROLLBACK")
                        return {
                            "success": False,
                            "message": "Сначала выбери класс — без него виверу не "
                                       "подходит специализированное оружие.",
                        }

                # Inventory cap
                cur_inv = await conn.execute(
                    "SELECT COUNT(*) FROM bannerlord_custom_items "
                    "WHERE channel_id=? AND owner_username=?",
                    (channel_id, username))
                inv_row = await cur_inv.fetchone()
                if inv_row and inv_row[0] >= 50:
                    await conn.execute("ROLLBACK")
                    return {
                        "success": False,
                        "message": "Инвентарь полон (50). Дискарди что-то.",
                    }
                # Generate inline (reuse module logic).
                from routes.bannerlord_custom_items import _generate_item, RARITY_COLORS
                item = _generate_item(base_type)
                cur_smith = await conn.execute(
                    "INSERT INTO bannerlord_custom_items "
                    "(channel_id, owner_username, base_type, base_subtype, "
                    " custom_name, rarity, tier, icon, "
                    " damage_bonus, armor_bonus, weight_factor, speed_factor) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (channel_id, username, item["base_type"], item["base_subtype"],
                     item["custom_name"], item["rarity"], item["tier"], item["icon"],
                     item.get("damage_bonus", 0), item.get("armor_bonus", 0),
                     item.get("weight_factor", 1.0), item.get("speed_factor", 1.0)))
                smith_row = await cur_smith.fetchone()
                item_id_db = smith_row[0] if smith_row else 0
                smith_result = {**item, "id": item_id_db,
                                "color": RARITY_COLORS[item["rarity"]]}
                log.info("[bannerlord SMITH] user=%s ch=%s base=%s rarity=%s '%s'",
                         username, channel_id, base_type,
                         item["rarity"], item["custom_name"])

            # Sprint 5.33 (BLT-parity FAM) — family proposal handlers.
            # Все 3 — backend-only state machine. On accept в `respond_marriage`
            # backend enqueue'ит mod-action `hero.activate_marriage` сам.
            family_result = None
            if action_type == "hero.propose_marriage":
                from routes.bannerlord_family import handle_propose_marriage
                family_result = await handle_propose_marriage(conn, channel_id, username, data)
                if not family_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return family_result
            elif action_type == "hero.respond_marriage_proposal":
                from routes.bannerlord_family import handle_respond_marriage
                family_result = await handle_respond_marriage(conn, channel_id, username, data)
                if not family_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return family_result
            elif action_type == "hero.cancel_proposal":
                from routes.bannerlord_family import handle_cancel_proposal
                family_result = await handle_cancel_proposal(conn, channel_id, username, data)
                if not family_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return family_result

            # Sprint 5.33 (BLT-parity VAS) — vassal sub-clan handlers.
            vassal_result = None
            if action_type == "hero.create_vassal_clan":
                from routes.bannerlord_vassals import handle_create_vassal
                vassal_result = await handle_create_vassal(conn, channel_id, username, data)
                if not vassal_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return vassal_result
            elif action_type == "hero.rename_vassal":
                from routes.bannerlord_vassals import handle_rename_vassal
                vassal_result = await handle_rename_vassal(conn, channel_id, username, data)
                if not vassal_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return vassal_result

            # Sprint 5.33 (BLT-parity SIEGE) — party order handlers.
            siege_result = None
            if action_type == "hero.party_order_set":
                from routes.bannerlord_party_orders import handle_set_party_order
                siege_result = await handle_set_party_order(conn, channel_id, username, data)
                if not siege_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return siege_result
            elif action_type == "hero.party_order_release":
                from routes.bannerlord_party_orders import handle_release_party_order
                siege_result = await handle_release_party_order(conn, channel_id, username, data)
                if not siege_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return siege_result

            # Sprint 5.33 (BLT-parity DIPLO) — kingdom politics + ransom.
            diplo_result = None
            if action_type == "hero.enact_policy":
                from routes.bannerlord_diplomacy import handle_enact_policy
                diplo_result = await handle_enact_policy(conn, channel_id, username, data)
                if not diplo_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return diplo_result
            elif action_type == "hero.make_peace":
                from routes.bannerlord_diplomacy import handle_make_peace
                diplo_result = await handle_make_peace(conn, channel_id, username, data)
                if not diplo_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return diplo_result
            elif action_type == "hero.pay_ransom":
                from routes.bannerlord_diplomacy import handle_pay_ransom
                diplo_result = await handle_pay_ransom(conn, channel_id, username, data)
                if not diplo_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return diplo_result
            elif action_type == "kingdom.set_tax_rate":
                from routes.bannerlord_diplomacy import handle_set_kingdom_tax
                diplo_result = await handle_set_kingdom_tax(conn, channel_id, username, data)
                if not diplo_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return diplo_result

            # Sprint 5.33 (BLT-parity SHOP) — workshops passive income.
            shop_result = None
            if action_type == "hero.buy_workshop":
                from routes.bannerlord_workshops import handle_buy_workshop
                shop_result = await handle_buy_workshop(conn, channel_id, username, data)
                if not shop_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return shop_result
            elif action_type == "hero.sell_workshop":
                from routes.bannerlord_workshops import handle_sell_workshop
                shop_result = await handle_sell_workshop(conn, channel_id, username, data)
                if not shop_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return shop_result

            # Sprint 5.33 (BLT-parity FIEF) — tribute boost.
            fief_result = None
            if action_type == "hero.tribute_boost":
                from routes.bannerlord_fiefs import handle_tribute_boost
                fief_result = await handle_tribute_boost(conn, channel_id, username, data)
                if not fief_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return fief_result

            # Sprint 5.33 (BLT-parity CARAVAN) — caravan lifecycle.
            caravan_result = None
            if action_type == "hero.buy_caravan":
                from routes.bannerlord_caravans import handle_buy_caravan
                caravan_result = await handle_buy_caravan(conn, channel_id, username, data)
                if not caravan_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return caravan_result
            elif action_type == "hero.sell_caravan":
                from routes.bannerlord_caravans import handle_sell_caravan
                caravan_result = await handle_sell_caravan(conn, channel_id, username, data)
                if not caravan_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return caravan_result
            elif action_type == "hero.pay_caravan_rescue":
                from routes.bannerlord_caravans import handle_pay_caravan_rescue
                caravan_result = await handle_pay_caravan_rescue(conn, channel_id, username, data)
                if not caravan_result.get("success"):
                    await conn.execute("ROLLBACK")
                    return caravan_result

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
        except Exception as ex:
            # Sprint 5.29 audit fix #34: было silent — exception swallowed +
            # raised, FastAPI default handler logged opaque 500. Теперь
            # explicit logger.exception с context.
            try:
                await conn.execute("ROLLBACK")
            except Exception:
                pass
            log.exception(
                "[bannerlord buy_action] commit failed ch=%s user=%s "
                "action=%s price=%s: %s",
                channel_id, username, action_type, price, ex)
            raise

    # Sprint 4.8/5.0: запустить cooldown ПОСЛЕ commit (если упало — cooldown
    # не считается). Происходит вне TX — cooldown это in-memory state.
    # cooldown_applied_s — длительность запущенного CD; возвращаем frontend'у
    # чтобы кнопка сразу показала отсчёт (без второго клика / ожидания poll'а).
    cooldown_applied_s = 0
    if cooldown_key:
        from modules.bannerlord._adapter import (
            set_cooldown, POWER_COOLDOWNS, ACTION_COOLDOWNS_SEC,
        )
        set_cooldown(channel_id, username, cooldown_key)
        cooldown_applied_s = (
            POWER_COOLDOWNS.get(cooldown_key)
            or ACTION_COOLDOWNS_SEC.get(cooldown_key)
            or 0
        )

    # Sprint 5.30 #41 — broadcast power activation event для OBS overlay.
    # Append to ring buffer per-channel; overlay.html polls /api/overlay/bannerlord/power-events.
    if action_type == "power.activate":
        try:
            _power_key = (data.get("power_key") or "").strip().lower()
            _push_power_event(
                channel_id=channel_id,
                user=username,
                power_key=_power_key,
                value=float(data.get("value") or 0),
                duration_s=float(data.get("duration_s") or 0),
            )
        except Exception as _pex:
            log.warning("[bannerlord overlay power-event] push failed: %s", _pex)

    # Sprint 5.29 audit fix #34: log enqueued action_id для трассировки.
    # Frontend получает action_id в response — теперь и в логах есть.
    # Когда mod пушит ack — можно matched against action_id.
    if action_type not in _BACKEND_ONLY_ACTIONS:
        log.info(
            "[bannerlord ENQUEUE] action_id=%s action=%s user=%s ch=%s price=%s",
            action_id, action_type, username, channel_id, price)

    # Sprint 5.29 BLT-parity #6: smith result returned inline.
    if action_type == "hero.smith_item" and smith_result:
        return {
            "success":    True,
            "action_id":  action_id,
            "charged":    price,
            "message":    f"{smith_result['icon']} Создан: «{smith_result['custom_name']}» ({smith_result['rarity']})",
            "item":       smith_result,
            "perk":       role_label,
            "perk_price_mult": price_mult,
            "cooldown_applied_s": cooldown_applied_s,
        }

    return {
        "success":    True,
        "action_id":  action_id,
        "charged":    price,
        "message":    f"⚔️ Action {action_type} в очереди ({price}💎 списано)",
        "perk":       role_label,
        "perk_price_mult": price_mult,
        "cooldown_applied_s": cooldown_applied_s,
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


@router.get("/api/bannerlord/clan-upgrades/all-owners")
async def bannerlord_clan_upgrades_all_owners(channel_id: int = 0):
    """Возвращает MAP {username → [upgrade_id, ...]} для всех heroes канала.

    Public-ish (channel_id query — нет JWT т.к. mod вызывает с module token).
    Mod polls этот endpoint раз в N минут чтобы знать актуальные owned upgrades
    каждого hero для daily tick применения эффектов.

    Также возвращает effects для каждого upgrade чтобы mod не дёргал отдельный
    catalog endpoint.
    """
    from dependencies import resolve_channel_id_or_default
    if channel_id <= 0:
        channel_id = resolve_channel_id_or_default()

    db = get_db()
    async with db._connect() as conn:
        # Catalog (только active)
        cur = await conn.execute(
            "SELECT upgrade_id, effects_json FROM bannerlord_clan_upgrades_catalog "
            "WHERE channel_id = ? AND deprecated = 0",
            (channel_id,)
        )
        catalog = {}
        for upg_id, eff_json in await cur.fetchall():
            try:
                catalog[upg_id] = _bnr_clan_json.loads(eff_json or '{}')
            except Exception:
                catalog[upg_id] = {}

        # Owned per username
        cur = await conn.execute(
            "SELECT username, upgrade_id FROM bannerlord_clan_upgrades_owned "
            "WHERE channel_id = ?",
            (channel_id,)
        )
        owners = {}
        for username, upg_id in await cur.fetchall():
            owners.setdefault(username, []).append(upg_id)

    return {"success": True, "owners": owners, "catalog_effects": catalog}


@router.post("/api/bannerlord/clan-upgrades/buy")
async def bannerlord_clan_upgrades_buy(request: Request):
    """Купить апгрейд(ы) клана за hero.gold.

    Sprint 5.33 BULK (BLT-parity Lait fork inspiration) — теперь принимает
    либо одиночный `upgrade_id` (legacy), либо list `upgrade_ids` для bulk
    purchase. Все апгрейды покупаются **атомарно** — или все, или ни одного
    (если gold кончится).

    Body:
      {"upgrade_id": str}          — single (legacy)
      {"upgrade_ids": [str, ...]}  — bulk (NEW), max 10 за раз

    Валидации (для каждого upgrade):
      - exists и not deprecated
      - не куплен уже
      - prereq куплен (если есть)
      - сумма gold >= sum(cost'ов) — atomic check
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    # Normalize input — either bulk list или single id (backward-compat).
    bulk_ids = data.get("upgrade_ids")
    if isinstance(bulk_ids, list) and bulk_ids:
        upgrade_ids = [str(x).strip() for x in bulk_ids if str(x).strip()]
    else:
        single = (data.get("upgrade_id") or '').strip()
        upgrade_ids = [single] if single else []
    if not upgrade_ids:
        return {"success": False, "message": "upgrade_id/upgrade_ids обязателен"}
    # Cap bulk size — anti-spam + UI ergonomics
    if len(upgrade_ids) > 10:
        return {"success": False, "message": "Максимум 10 апгрейдов за раз"}
    # Dedup в payload (защита если фронт прислал дубликаты)
    upgrade_ids = list(dict.fromkeys(upgrade_ids))

    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")

            # Phase 1 — load & validate ALL upgrades. Collect total cost.
            # Bulk failure mode: на первой проблеме ROLLBACK с понятным message.
            validated = []  # list of (upgrade_id, name, cost)
            total_cost = 0
            for uid in upgrade_ids:
                cur = await conn.execute(
                    "SELECT name, required_upgrade_id, gold_cost, deprecated "
                    "FROM bannerlord_clan_upgrades_catalog "
                    "WHERE channel_id = ? AND upgrade_id = ?",
                    (channel_id, uid))
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {"success": False,
                            "message": f"Апгрейд '{uid}' не найден"}
                name, req, cost, deprecated = row
                if deprecated:
                    await conn.execute("ROLLBACK")
                    return {"success": False,
                            "message": f"'{name}' недоступен"}
                cur = await conn.execute(
                    "SELECT 1 FROM bannerlord_clan_upgrades_owned "
                    "WHERE channel_id = ? AND username = ? AND upgrade_id = ?",
                    (channel_id, username, uid))
                if await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    return {"success": False,
                            "message": f"'{name}' уже куплено"}
                # Prereq check — может быть в samem bulk batch'е выше (chain
                # purchase). Учитываем both owned-in-DB и validated-in-list.
                if req:
                    cur = await conn.execute(
                        "SELECT 1 FROM bannerlord_clan_upgrades_owned "
                        "WHERE channel_id = ? AND username = ? AND upgrade_id = ?",
                        (channel_id, username, req))
                    has_prereq = await cur.fetchone() is not None
                    if not has_prereq:
                        # Check если prereq в bulk batch'е выше — chained buy.
                        has_prereq = any(v[0] == req for v in validated)
                    if not has_prereq:
                        await conn.execute("ROLLBACK")
                        return {"success": False,
                                "message": f"Для '{name}' нужен сначала prereq '{req}'"}
                validated.append((uid, name, cost))
                total_cost += cost

            # Phase 2 — gold check (sum), atomic.
            cur = await conn.execute(
                "SELECT gold FROM bannerlord_heroes WHERE channel_id = ? AND username = ?",
                (channel_id, username))
            hero_row = await cur.fetchone()
            current_gold = (hero_row[0] if hero_row else 0) or 0
            if current_gold < total_cost:
                await conn.execute("ROLLBACK")
                return {
                    "success": False,
                    "message": f"Нужно {total_cost:,}💰 (у тебя {current_gold:,}💰) для {len(validated)} апгрейдов",
                }

            # Phase 3 — debit + INSERT × N owned records. Эффекты апгрейдов мод
            # применяет сам (ClanUpgradesBehavior опрашивает clan_upgrades_all_owners
            # на daily tick) — отдельный enqueue в module_actions НЕ нужен.
            await conn.execute(
                "UPDATE bannerlord_heroes SET gold = gold - ? "
                "WHERE channel_id = ? AND username = ?",
                (total_cost, channel_id, username))

            purchased_names = []
            for uid, name, cost in validated:
                await conn.execute(
                    "INSERT INTO bannerlord_clan_upgrades_owned "
                    "(channel_id, username, upgrade_id, gold_paid) VALUES (?, ?, ?, ?)",
                    (channel_id, username, uid, cost))
                # 2026-06-05 (AUTOTEST fix) — убран мёртвый INSERT INTO module_actions
                # 'clan.upgrade_purchased': у мода нет хендлера → плодил вечные failed
                # в очереди (поймано автотестом). Owned-запись выше — источник правды.
                purchased_names.append(name)

            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    if len(validated) == 1:
        # Backward-compat response shape.
        uid, name, cost = validated[0]
        return {
            "success":    True,
            "upgrade_id": uid,
            "message":    f"✨ {name} куплено (-{cost:,}💰)",
        }
    else:
        log.info("[BNR-BULK] ch=%s user=@%s bought %d upgrades total=%d💰",
                 channel_id, username, len(validated), total_cost)
        return {
            "success":   True,
            "bulk":      True,
            "count":     len(validated),
            "upgrade_ids": [v[0] for v in validated],
            "total_cost": total_cost,
            "message":   f"✨ Куплено {len(validated)} апгрейдов: " +
                         ", ".join(purchased_names[:3]) +
                         (f" и ещё {len(purchased_names)-3}" if len(purchased_names) > 3 else "") +
                         f" (-{total_cost:,}💰)",
        }


# ════════ Sprint 5.33 (BLT-parity HERITAGE) ════════════════════════════════════

@router.get("/api/bannerlord/inheritance-log")
async def bannerlord_inheritance_log(request: Request, limit: int = 20):
    """История наследования — assets, переданные heir'у viewer'а после death.
    Frontend "Наследие" section показывает audit entries для transparency.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    limit = max(1, min(int(limit or 20), 100))

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT id, parent_username, heir_hero_id, asset_type, asset_ref, "
            "       asset_name, total_value, inherited_at "
            "FROM bannerlord_inheritance_log "
            "WHERE channel_id=? AND parent_username=? "
            "ORDER BY inherited_at DESC LIMIT ?",
            (channel_id, username, limit))
        rows = await cur.fetchall()

    items = [{
        "id":              r[0],
        "parent_username": r[1],
        "heir_hero_id":    r[2],
        "asset_type":      r[3],
        "asset_ref":       r[4],
        "asset_name":      r[5],
        "total_value":     r[6] or 0,
        "inherited_at":    r[7],
    } for r in rows]
    return {"success": True, "items": items}
