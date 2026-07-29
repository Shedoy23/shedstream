"""
routes/dice.py — Dice match (Sprint 5.24a 3-round + reroll, 2026-05-21).

Два режима:
  1. Vs bot — instant single-roll match (без ELO, без раундов).
     Чисто фановый расслаб когда не хочется ждать.
  2. PvP — 3 раунда с механикой переброса:
       a) Каждый игрок бросает 2d6 (initial)
       b) Видит свой результат (не оппа), решает: переброс ОДНОГО кубика
          или оставить как есть
       c) После обоих decisions → round score; advance к следующему раунду
       d) После 3 раундов — winner = чья общая сумма больше
     Цель: добавить элемент стратегии (вероятностный расчёт) поверх рандома.

10-секундный таймер на каждую фазу (rolling / deciding). Lazy expire:
на /api/match/room/{id}/state poll проверяем deadline_at, если истёк —
auto-action (random roll / keep без reroll).

State JSON v2 (для PvP rooms):
  {
    "version": 2,
    "rounds_total": 3,
    "current_round": 1,        # 1-indexed
    "rolls": {
      "a": [{initial: [d1,d2], final: [d1,d2]|null, reroll_index: 0|1|null}, ...],
      "b": [...]
    },
    "totals": {"a": int, "b": int},  # сумма final dice по всем сыгранным раундам
    "phase": "rolling" | "deciding" | "finished",
    "deadline_at": "ISO" | null,
  }

Compliance: §6.2.4 — НЕ mystery box, никаких real-money стейков. Skill+chance
elements компетится в ELO (§5.x OK для skill-based competition).
"""
import json
import random
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request

from dependencies import (
    get_bot,
    get_db,
    require_jwt_user,
    require_jwt_channel,
    resolve_channel_id_or_default,
)

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}

GAME_TYPE = "dice"
ELO_START = 1000
ELO_K = 32
# Sprint 5.25 rebalance: prizes 300/200/100k (было 1M/500k/350k),
# 2-недельный сезон (было 1 нед), prize gate elo >= 1100 (filtering
# free-loaders которые сидят на стартовом ELO без побед).
PRIZES = {1: 300_000, 2: 200_000, 3: 100_000}
PRIZE_ELO_GATE = 1100

ROUNDS_TOTAL = 3
TURN_TIMEOUT_S = 10  # на каждую фазу (rolling / deciding) даётся 10s

# SystemRandom — НЕ нужен (без monetary stakes). Default random OK для casual.
_rng = random.Random()


# ─── Pure game logic ──────────────────────────────────────────────────────────

def _roll_2d6() -> list:
    """Бросок 2 кубиков. Returns [d1, d2] каждое 1..6."""
    return [_rng.randint(1, 6), _rng.randint(1, 6)]


def _roll_d6() -> int:
    return _rng.randint(1, 6)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deadline_at(seconds: int = TURN_TIMEOUT_S) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _deadline_expired(iso_str) -> bool:
    if not iso_str:
        return False
    try:
        dt = datetime.fromisoformat(iso_str)
        return datetime.now(timezone.utc) >= dt
    except Exception:
        return False


def _new_dice_state() -> dict:
    return {
        "version":      2,
        "rounds_total": ROUNDS_TOTAL,
        "current_round": 1,
        "rolls":        {"a": [], "b": []},
        "totals":       {"a": 0, "b": 0},
        "phase":        "rolling",
        "deadline_at":  _deadline_at(),
    }


def _player_has_initial(state, role, round_idx):
    """role='a'/'b', round_idx 0-based."""
    rolls = state["rolls"][role]
    return len(rolls) > round_idx


def _player_has_decided(state, role, round_idx):
    rolls = state["rolls"][role]
    if len(rolls) <= round_idx:
        return False
    return rolls[round_idx].get("final") is not None


def _compute_phase(state) -> str:
    """Текущая фаза на основе rolls. 'rolling' если кто-то не initial-roll'нул,
    'deciding' если оба rolled но не оба decided, 'finished' если все раунды
    сыграны."""
    if state["current_round"] > state["rounds_total"]:
        return "finished"
    idx = state["current_round"] - 1
    a_init = _player_has_initial(state, "a", idx)
    b_init = _player_has_initial(state, "b", idx)
    if not (a_init and b_init):
        return "rolling"
    a_done = _player_has_decided(state, "a", idx)
    b_done = _player_has_decided(state, "b", idx)
    if a_done and b_done:
        # Bug-safe: должно было advance в /decide. На всякий случай.
        return "advancing"
    return "deciding"


def _recompute_totals(state):
    """Сумма по final-rolls во всех завершённых раундах."""
    totals = {"a": 0, "b": 0}
    for role in ("a", "b"):
        for r in state["rolls"][role]:
            if r.get("final"):
                totals[role] += sum(r["final"])
    state["totals"] = totals


def _resolve_pvp_winner(state):
    """После 3 раундов — кто победил по сумме."""
    sa = state["totals"]["a"]
    sb = state["totals"]["b"]
    if sa > sb: return "a"
    if sb > sa: return "b"
    return "draw"


def _elo_update(rating: int, opp_rating: int, result: float) -> int:
    expected = 1 / (1 + 10 ** ((opp_rating - rating) / 400))
    return round(rating + ELO_K * (result - expected))


# ─── Season helpers ───────────────────────────────────────────────────────────

def _next_season_end():
    """Sprint 5.25: 2-week season (было 1 week). Aligns на Sunday midnight."""
    now = datetime.now(timezone.utc)
    days_ahead = (6 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 14  # сегодня Sunday → следующий через 2 недели
    else:
        days_ahead += 7  # ближайший Sunday + неделя = бай-уикли
    target = now + timedelta(days=days_ahead)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)


# Backward-compat alias (старое имя ещё используется в коде ниже)
_next_sunday_midnight = _next_season_end


async def _ensure_season(conn, channel_id: int) -> int:
    row = await (await conn.execute(
        "SELECT id FROM duel_seasons WHERE channel_id = ? AND game_type = ? AND finished = 0 "
        "ORDER BY id DESC LIMIT 1",
        (channel_id, GAME_TYPE)
    )).fetchone()
    if row:
        return row[0]
    now = datetime.now(timezone.utc)
    ends_at = _next_sunday_midnight()
    await conn.execute(
        "INSERT INTO duel_seasons (channel_id, game_type, started_at, ends_at, finished) "
        "VALUES (?, ?, ?, ?, 0)",
        (channel_id, GAME_TYPE, now.isoformat(), ends_at.isoformat())
    )
    return (await (await conn.execute("SELECT last_insert_rowid()")).fetchone())[0]


async def _get_or_init_stats(conn, channel_id: int, username: str, season_id: int):
    row = await (await conn.execute(
        "SELECT elo, win_streak FROM duel_stats "
        "WHERE channel_id = ? AND username = ? AND game_type = ?",
        (channel_id, username.lower(), GAME_TYPE)
    )).fetchone()
    if row:
        return row[0], row[1]
    await conn.execute(
        "INSERT OR IGNORE INTO duel_stats "
        "(channel_id, username, game_type, elo, win_streak, season_id) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (channel_id, username.lower(), GAME_TYPE, ELO_START, season_id)
    )
    return ELO_START, 0


async def _update_stats(conn, channel_id: int, username: str, elo: int, streak: int):
    await conn.execute(
        "UPDATE duel_stats SET elo = ?, win_streak = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE channel_id = ? AND username = ? AND game_type = ?",
        (elo, streak, channel_id, username.lower(), GAME_TYPE)
    )


async def check_season_end(channel_id: int = None):
    """Aналог TicTacToe / RPS — finalizes dice sезон когда ends_at прошёл."""
    cid = channel_id if channel_id else resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        # Атомарность: призы + finish + reset + новый сезон — одна транзакция
        # (иначе краш между add_points и finish = двойная выдача при ретрае).
        await conn.execute("BEGIN IMMEDIATE")
        row = await (await conn.execute(
            "SELECT id, ends_at FROM duel_seasons "
            "WHERE channel_id = ? AND game_type = ? AND finished = 0 "
            "ORDER BY id DESC LIMIT 1",
            (cid, GAME_TYPE)
        )).fetchone()
        if not row:
            await _ensure_season(conn, cid)
            await conn.commit()
            return
        season_id, ends_at_str = row
        ends_at = datetime.fromisoformat(ends_at_str)
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < ends_at:
            return

        # Sprint 5.25: prize gate — только игроки с ELO >= 1100 получают приз
        # (фильтр free-loaders, кто сел в очередь но никогда не побеждал).
        top = await (await conn.execute(
            "SELECT username, elo FROM duel_stats "
            "WHERE channel_id = ? AND game_type = ? AND season_id = ? AND elo >= ? "
            "ORDER BY elo DESC LIMIT 3",
            (cid, GAME_TYPE, season_id, PRIZE_ELO_GATE)
        )).fetchall()
        prize_parts = []
        for rank, (uname, elo) in enumerate(top, 1):
            prize = PRIZES.get(rank, 0)
            if prize:
                await db.add_points_tx(conn, uname, prize, cid)  # в той же транзакции, что finish+reset
                prize_parts.append(f"#{rank} @{uname} ({elo} ELO) +{prize:,}💎")

        await conn.execute("UPDATE duel_seasons SET finished = 1 WHERE id = ?", (season_id,))
        now = datetime.now(timezone.utc)
        new_end = _next_sunday_midnight()
        await conn.execute(
            "INSERT INTO duel_seasons (channel_id, game_type, started_at, ends_at, finished) "
            "VALUES (?, ?, ?, ?, 0)",
            (cid, GAME_TYPE, now.isoformat(), new_end.isoformat())
        )
        new_season_id = (await (await conn.execute("SELECT last_insert_rowid()")).fetchone())[0]
        await conn.execute(
            "UPDATE duel_stats SET elo = ?, win_streak = 0, season_id = ? "
            "WHERE channel_id = ? AND game_type = ?",
            (ELO_START, new_season_id, cid, GAME_TYPE)
        )
        await conn.commit()

        try:
            bot = get_bot()
            if prize_parts:
                await bot.send_message(
                    f"🎲 Dice сезон #{season_id} завершён! Призы: {' | '.join(prize_parts)}",
                    channel_id=cid,
                )
            else:
                await bot.send_message(
                    f"🎲 Dice сезон #{season_id} завершён! Новый старт.", channel_id=cid,
                )
        except Exception:
            pass


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/api/dice/play-vs-bot")
async def dice_play_vs_bot(request: Request):
    """Singleplayer match vs bot. Instant single-request roll.

    Без ELO updates (casual mode), без записи в match_rooms. Просто бросок.

    Body: {} (юзер identified by JWT)
    Returns: {success, your_roll, bot_roll, your_sum, bot_sum, outcome, message}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    your_roll = _roll_2d6()
    bot_roll = _roll_2d6()
    your_sum = sum(your_roll)
    bot_sum = sum(bot_roll)

    if your_sum > bot_sum:
        outcome = "win"
        msg = f"🎲 {your_sum} vs {bot_sum} — ты выиграл!"
    elif bot_sum > your_sum:
        outcome = "loss"
        msg = f"🎲 {your_sum} vs {bot_sum} — бот выиграл"
    else:
        outcome = "draw"
        msg = f"🎲 {your_sum} vs {bot_sum} — ничья"

    return {
        "success":  True,
        "mode":     "bot",
        "your_roll": your_roll,
        "bot_roll":  bot_roll,
        "your_sum":  your_sum,
        "bot_sum":   bot_sum,
        "outcome":   outcome,
        "message":   msg,
    }


async def _finalize_pvp_match(conn, room_id, state, channel_id, p_a, p_b, elo_a, elo_b):
    """Завершение после 3 раундов. Применяет ELO + duel_stats updates,
    обновляет match_rooms row. Returns (winner_user, outcome, new_elo_a, new_elo_b)."""
    state["phase"] = "finished"
    state["deadline_at"] = None
    _recompute_totals(state)
    winner_role = _resolve_pvp_winner(state)
    if winner_role == "a":
        winner_user, outcome = p_a, "win_a"
        new_elo_a = _elo_update(elo_a, elo_b, 1.0)
        new_elo_b = _elo_update(elo_b, elo_a, 0.0)
    elif winner_role == "b":
        winner_user, outcome = p_b, "win_b"
        new_elo_a = _elo_update(elo_a, elo_b, 0.0)
        new_elo_b = _elo_update(elo_b, elo_a, 1.0)
    else:
        winner_user, outcome = None, "draw"
        new_elo_a = _elo_update(elo_a, elo_b, 0.5)
        new_elo_b = _elo_update(elo_b, elo_a, 0.5)

    await conn.execute(
        "UPDATE match_rooms SET state = ?, status = 'finished', "
        "winner = ?, outcome = ?, player_a_elo = ?, player_b_elo = ?, "
        "finished_at = CURRENT_TIMESTAMP WHERE room_id = ?",
        (json.dumps(state), winner_user, outcome, new_elo_a, new_elo_b, room_id)
    )

    season_id = await _ensure_season(conn, channel_id)
    _a_old, a_streak = await _get_or_init_stats(conn, channel_id, p_a, season_id)
    _b_old, b_streak = await _get_or_init_stats(conn, channel_id, p_b, season_id)
    if outcome == "win_a":
        new_a_streak, new_b_streak = a_streak + 1, 0
    elif outcome == "win_b":
        new_a_streak, new_b_streak = 0, b_streak + 1
    else:
        new_a_streak, new_b_streak = a_streak, b_streak
    await _update_stats(conn, channel_id, p_a, new_elo_a, new_a_streak)
    await _update_stats(conn, channel_id, p_b, new_elo_b, new_b_streak)

    return winner_user, outcome, new_elo_a, new_elo_b


def _maybe_expire_phase(state):
    """Lazy expiration: вызывается перед read/write если deadline истёк.
    Auto-actions: rolling → auto-roll, deciding → auto-keep (no reroll).
    Returns True если что-то изменили (нужно записать state в БД)."""
    if state.get("phase") == "finished":
        return False
    if not _deadline_expired(state.get("deadline_at")):
        return False

    idx = state["current_round"] - 1
    changed = False
    for role in ("a", "b"):
        if not _player_has_initial(state, role, idx):
            # Auto-roll
            initial = _roll_2d6()
            state["rolls"][role].append({
                "initial": initial,
                "final":   None,
                "reroll_index": None,
            })
            changed = True

    # После auto-rolls возможно оба rolled — переход в deciding со свежим
    # deadline. Если они уже rolled и deadline прошёл в "deciding" — auto-keep.
    new_phase = _compute_phase(state)
    if new_phase == "rolling":
        # Кто-то не rolled даже после auto — не должно быть
        state["phase"] = "rolling"
        state["deadline_at"] = _deadline_at()
    elif new_phase == "deciding":
        # Если был в "rolling" и теперь "deciding" — это нормальный progress,
        # дать 10s на decide. Иначе (был в "deciding" и deadline истёк) →
        # auto-keep.
        if state.get("phase") == "deciding":
            for role in ("a", "b"):
                if not _player_has_decided(state, role, idx):
                    state["rolls"][role][idx]["final"] = state["rolls"][role][idx]["initial"]
                    state["rolls"][role][idx]["reroll_index"] = None
                    changed = True
            # После auto-keep оба decided — нужно advance
            new_phase = _compute_phase(state)
        else:
            state["phase"] = "deciding"
            state["deadline_at"] = _deadline_at()

    if new_phase == "advancing":
        # Оба решили — advance round
        state["current_round"] += 1
        _recompute_totals(state)
        if state["current_round"] > state["rounds_total"]:
            state["phase"] = "finished"
            state["deadline_at"] = None
        else:
            state["phase"] = "rolling"
            state["deadline_at"] = _deadline_at()
        changed = True

    return changed


@router.post("/api/dice/roll")
async def dice_roll(request: Request):
    """Initial-roll в PvP match для текущего раунда.

    Body: {"room_id": str}

    После roll'а игрок получает свои кубики, но не оппа. Решает re-roll
    через /api/dice/decide.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    uname = username.lower()

    data = await request.json()
    room_id = data.get("room_id")
    if not room_id:
        return {"success": False, "message": "room_id обязателен"}

    await check_season_end(channel_id)

    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")

            cur = await conn.execute(
                "SELECT channel_id, game_type, player_a, player_b, "
                "player_a_elo, player_b_elo, state, status FROM match_rooms WHERE room_id = ?",
                (room_id,)
            )
            row = await cur.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_found", "message": "Комната не найдена"}

            room_cid, gt, p_a, p_b, elo_a, elo_b, state_json, status = row

            if room_cid != channel_id:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "wrong_channel"}
            if gt != GAME_TYPE:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "wrong_game", "message": "Wrong game"}
            if uname not in (p_a, p_b):
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_player", "message": "Ты не в этой комнате"}
            if status != "active":
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_active", "message": "Матч уже завершён"}

            state = json.loads(state_json or "{}")
            # Sprint 5.24a: state v2 — multi-round. Если version<2 (старая
            # одно-roll'ная partial-finished room) — пересоздаём пустое state.
            if state.get("version") != 2:
                state = _new_dice_state()

            you_are = "a" if uname == p_a else "b"
            opponent = p_b if you_are == "a" else p_a

            # Lazy expire if deadline passed
            _maybe_expire_phase(state)

            # If already finished (e.g. after expiration cascade) — finalize
            if state.get("phase") == "finished" and status == "active":
                winner_user, outcome, new_elo_a_, new_elo_b_ = await _finalize_pvp_match(
                    conn, room_id, state, channel_id, p_a, p_b, elo_a, elo_b)
                await conn.commit()
                _broadcast_state(channel_id, room_id, state,
                                 finished=True, winner_user=winner_user)
                return {
                    "success":  True,
                    "mode":     "pvp",
                    "you_are":  you_are,
                    "opponent": opponent,
                    "state":    state,
                    "finished": True,
                    "winner":   winner_user,
                    "message":  ("🎉 Победа!" if winner_user == uname else
                                 "😢 Поражение" if winner_user else "🤝 Ничья"),
                }

            cur_idx = state["current_round"] - 1
            if state.get("phase") != "rolling":
                # Уже не в rolling-фазе — нельзя initial-rollать
                await conn.execute(
                    "UPDATE match_rooms SET state = ? WHERE room_id = ?",
                    (json.dumps(state), room_id)
                )
                await conn.commit()
                return {
                    "success": False,
                    "reason":  "not_rolling_phase",
                    "phase":   state.get("phase"),
                    "state":   state,
                    "message": "Сейчас не фаза броска",
                }

            if _player_has_initial(state, you_are, cur_idx):
                await conn.execute("ROLLBACK")
                return {
                    "success":  False,
                    "reason":   "already_rolled",
                    "state":    state,
                    "message":  "Ты уже бросил в этом раунде",
                }

            # Initial roll этого раунда
            initial = _roll_2d6()
            state["rolls"][you_are].append({
                "initial":      initial,
                "final":        None,
                "reroll_index": None,
            })

            # Sprint 5.24a fix: рефрешим deadline на КАЖДОМ action чтобы
            # оппа всегда имел свежие 10s от последнего хода. Иначе если
            # юзер тупил с opener'ом 30s — deadline уже истёк когда он рольнул.
            if _player_has_initial(state, "a", cur_idx) and _player_has_initial(state, "b", cur_idx):
                state["phase"] = "deciding"
            else:
                state["phase"] = "rolling"
            state["deadline_at"] = _deadline_at()

            await conn.execute(
                "UPDATE match_rooms SET state = ? WHERE room_id = ?",
                (json.dumps(state), room_id)
            )

            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    _broadcast_state(channel_id, room_id, state, finished=False, winner_user=None)
    return {
        "success":   True,
        "mode":      "pvp",
        "you_are":   you_are,
        "opponent":  opponent,
        "state":     state,
        "message":   "Бросок принят. Решай: переброс или оставить.",
    }


@router.post("/api/dice/decide")
async def dice_decide(request: Request):
    """После initial-roll'а игрок решает: переброс одного кубика или оставить.

    Body: {"room_id": str, "reroll_index": 0 | 1 | null}
      - reroll_index=null → keep, final = initial
      - reroll_index in [0,1] → bросаем 1 кубик заново, заменяем final[idx]
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    uname = username.lower()

    data = await request.json()
    room_id = data.get("room_id")
    reroll_index = data.get("reroll_index")
    if not room_id:
        return {"success": False, "message": "room_id обязателен"}
    if reroll_index is not None and reroll_index not in (0, 1):
        return {"success": False, "message": "reroll_index должен быть 0, 1 или null"}

    await check_season_end(channel_id)

    db = get_db()
    finished = False
    winner_user = None
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")

            cur = await conn.execute(
                "SELECT channel_id, game_type, player_a, player_b, "
                "player_a_elo, player_b_elo, state, status FROM match_rooms WHERE room_id = ?",
                (room_id,)
            )
            row = await cur.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_found"}
            room_cid, gt, p_a, p_b, elo_a, elo_b, state_json, status = row

            if room_cid != channel_id or gt != GAME_TYPE or uname not in (p_a, p_b):
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "access_denied"}
            if status != "active":
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_active",
                        "message": "Матч уже завершён"}

            state = json.loads(state_json or "{}")
            if state.get("version") != 2:
                state = _new_dice_state()

            _maybe_expire_phase(state)

            you_are = "a" if uname == p_a else "b"
            cur_idx = state["current_round"] - 1

            if state.get("phase") not in ("deciding", "finished"):
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_deciding_phase",
                        "state": state, "message": "Сейчас не фаза решения"}

            if not _player_has_initial(state, you_are, cur_idx):
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "no_initial_roll",
                        "message": "Сначала брось кубики"}
            if _player_has_decided(state, you_are, cur_idx):
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "already_decided",
                        "state": state, "message": "Решение уже принято"}

            # Apply decision
            entry = state["rolls"][you_are][cur_idx]
            initial = entry["initial"]
            if reroll_index is None:
                entry["final"] = list(initial)
                entry["reroll_index"] = None
            else:
                new_dice = list(initial)
                new_dice[reroll_index] = _roll_d6()
                entry["final"] = new_dice
                entry["reroll_index"] = reroll_index

            # Sprint 5.24a fix: deadline refresh на каждом action для fair timer
            state["deadline_at"] = _deadline_at()

            # Check if both decided this round → advance
            if _player_has_decided(state, "a", cur_idx) and _player_has_decided(state, "b", cur_idx):
                _recompute_totals(state)
                if state["current_round"] >= state["rounds_total"]:
                    # Game over
                    winner_user, outcome, new_elo_a, new_elo_b = await _finalize_pvp_match(
                        conn, room_id, state, channel_id, p_a, p_b, elo_a, elo_b)
                    finished = True
                else:
                    state["current_round"] += 1
                    state["phase"] = "rolling"
                    state["deadline_at"] = _deadline_at()
                    await conn.execute(
                        "UPDATE match_rooms SET state = ? WHERE room_id = ?",
                        (json.dumps(state), room_id)
                    )
            else:
                # Wait for opponent decision
                await conn.execute(
                    "UPDATE match_rooms SET state = ? WHERE room_id = ?",
                    (json.dumps(state), room_id)
                )

            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    if finished:
        try:
            bot = get_bot()
            a_sum = state["totals"]["a"]
            b_sum = state["totals"]["b"]
            if winner_user:
                await bot.send_message(
                    f"🎲 Dice 3-round: @{p_a} ({a_sum}) vs @{p_b} ({b_sum}) — "
                    f"победил @{winner_user}!", channel_id=channel_id)
            else:
                await bot.send_message(
                    f"🎲 Dice ничья: @{p_a} ({a_sum}) = @{p_b} ({b_sum})",
                    channel_id=channel_id)
        except Exception: pass

        if winner_user:
            try:
                await get_bot().check_and_unlock_achievements(
                    winner_user, "duel_win", channel_id=channel_id)
            except Exception: pass

    _broadcast_state(channel_id, room_id, state,
                     finished=finished, winner_user=winner_user)

    return {
        "success":   True,
        "mode":      "pvp",
        "you_are":   you_are,
        "state":     state,
        "finished":  finished,
        "winner":    winner_user,
        "message":   ("🎉 Победа!" if finished and winner_user == uname else
                      "😢 Поражение" if finished and winner_user else
                      "🤝 Ничья" if finished else
                      "Решение принято"),
    }


def _broadcast_state(channel_id, room_id, state, finished=False, winner_user=None):
    """Phase C realtime broadcast — оппа моментально видит обновлённое state."""
    try:
        from pubsub import broadcast as _pubsub_broadcast
        _pubsub_broadcast(channel_id, "match_state", {
            "room_id":  room_id,
            "game":     "dice",
            "state":    state,
            "status":   "finished" if finished else "active",
            "finished": finished,
            "winner":   winner_user,
        })
    except Exception as e:
        import logging
        logging.getLogger("rimlink.dice").warning(
            "match_state broadcast failed: %s", e)


@router.get("/api/dice/poll")
async def dice_poll(request: Request, room_id: str):
    """Lazy-expire poll endpoint для dice rooms.

    Sprint 5.24a fix (2026-05-21): generic /api/match/room/{id}/state не
    знает про game-specific timer'ы. Frontend polling должен дёргать ЭТОТ
    endpoint вместо /state для dice rooms — он на каждый запрос проверяет
    deadline_at и если истёк → auto-actions (random roll / keep no reroll).

    Returns same shape as /api/match/room/{id}/state но с авто-обработкой
    expiration'а.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    uname = username.lower()

    db = get_db()
    finished_just_now = False
    winner_user = None
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT channel_id, game_type, player_a, player_b, "
                "player_a_elo, player_b_elo, state, status, winner, outcome "
                "FROM match_rooms WHERE room_id = ?",
                (room_id,)
            )
            row = await cur.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_found"}
            room_cid, gt, p_a, p_b, elo_a, elo_b, state_json, status, winner, outcome = row

            if room_cid != channel_id or gt != GAME_TYPE or uname not in (p_a, p_b):
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "access_denied"}

            state = json.loads(state_json or "{}")
            if state.get("version") != 2 and status == "active":
                state = _new_dice_state()

            changed = False
            if status == "active":
                changed = _maybe_expire_phase(state)
                # Если после lazy-expire оба decided последний раунд → finalize
                if state.get("phase") == "finished":
                    winner_user, outcome, new_elo_a, new_elo_b = await _finalize_pvp_match(
                        conn, room_id, state, channel_id, p_a, p_b, elo_a, elo_b)
                    finished_just_now = True
                elif changed:
                    await conn.execute(
                        "UPDATE match_rooms SET state = ? WHERE room_id = ?",
                        (json.dumps(state), room_id)
                    )
            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    if finished_just_now:
        _broadcast_state(channel_id, room_id, state,
                         finished=True, winner_user=winner_user)
        try:
            bot = get_bot()
            a_sum = state["totals"]["a"]
            b_sum = state["totals"]["b"]
            if winner_user:
                await bot.send_message(
                    f"🎲 Dice 3-round: @{p_a} ({a_sum}) vs @{p_b} ({b_sum}) — "
                    f"победил @{winner_user}!", channel_id=channel_id)
            else:
                await bot.send_message(
                    f"🎲 Dice ничья: @{p_a} ({a_sum}) = @{p_b} ({b_sum})",
                    channel_id=channel_id)
        except Exception: pass

    you_are = "a" if uname == p_a else "b"
    opponent = p_b if you_are == "a" else p_a
    final_status = "finished" if (finished_just_now or status == "finished") else status

    return {
        "success":  True,
        "room": {
            "room_id":      room_id,
            "channel_id":   channel_id,
            "game_type":    GAME_TYPE,
            "player_a":     p_a,
            "player_b":     p_b,
            "player_a_elo": elo_a,
            "player_b_elo": elo_b,
            "state":        state,
            "status":       final_status,
            "you_are":      you_are,
            "opponent":     opponent,
            "winner":       winner_user or winner,
            "outcome":      outcome,
        }
    }


@router.get("/api/dice/leaderboard")
async def dice_leaderboard(request: Request):
    """Топ-5 dice ELO per channel."""
    channel_id = require_jwt_channel(request) or resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        rows = await (await conn.execute(
            "SELECT username, elo, win_streak FROM duel_stats "
            "WHERE channel_id = ? AND game_type = ? ORDER BY elo DESC LIMIT 5",
            (channel_id, GAME_TYPE)
        )).fetchall()
        season_row = await (await conn.execute(
            "SELECT id, ends_at FROM duel_seasons "
            "WHERE channel_id = ? AND game_type = ? AND finished = 0 "
            "ORDER BY id DESC LIMIT 1",
            (channel_id, GAME_TYPE)
        )).fetchone()
    return {
        "success":     True,
        "game_type":   GAME_TYPE,
        "season_id":   season_row[0] if season_row else 1,
        "ends_at":     season_row[1] if season_row else None,
        # 2026-07-29 (тонкий фронт + аудит): панель обязана СКАЗАТЬ зрителю,
        # что за сезон вообще есть награда и при каком условии. Порог
        # PRIZE_ELO_GATE до сих пор не показывался нигде — а на проде за два
        # месяца никто его не перешагнул, то есть призы не выплатились ни разу.
        # Числа отдаём с бэка: менять их во фронте = ждать нового ревью Twitch.
        "prizes":      PRIZES,
        "elo_gate":    PRIZE_ELO_GATE,
        "leaderboard": [
            {"rank": i + 1, "username": r[0], "elo": r[1], "win_streak": r[2]}
            for i, r in enumerate(rows)
        ],
    }
