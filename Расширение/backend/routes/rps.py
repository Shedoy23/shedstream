"""
routes/rps.py — Дуэли RPS через matchmaking + best-of-3 (Sprint 5.24b, 2026-05-21).

До 5.24b дуэли работали только через invite-flow (routes/duel.py:
create/accept). Этот модуль добавляет matchmaking-вариант с best-of-3:
очередь → match → 3 раунда RPS, кто первый набирает 2 wins — победитель.
ELO + сезоны общие с duel.py (game_type='rps').

State JSON (для PvP rooms, game_type='rps_bo3' внутри match_rooms):
  {
    "version":      2,
    "rounds_total": 3,           # max, может закончиться раньше при 2-0
    "current_round": 1,
    "moves": {                    # 'rock'|'paper'|'scissors'|null
      "a": [null, null, null],
      "b": [null, null, null]
    },
    "round_outcomes": [None|'a'|'b'|'draw', ...],  # per round
    "wins": {"a": 0, "b": 0},
    "phase":        "moving" | "finished",
    "deadline_at":  "ISO" | null,
  }

10-секундный таймер на каждый раунд (оба должны сделать ход). Skip
на timeout = forfeit раунда (засчитывается как loss за раунд).
"""
import json
import random
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request

from dependencies import (
    get_bot, get_db, require_jwt_user,
    require_jwt_channel, resolve_channel_id_or_default,
)

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}

GAME_TYPE = "rps"  # совмещаем season/ELO с duel.py
ELO_START = 1000   # Sprint 5.25 rebalance
ELO_K = 32

ROUNDS_MAX     = 3   # best-of-3 → max 3 раунда
WINS_TO_TAKE   = 2   # достаточно 2 wins для победы (early-stop при 2-0)
TURN_TIMEOUT_S = 10

_VALID_MOVES = ("rock", "paper", "scissors")
_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
_EMOJI = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}

_rng = random.Random()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deadline_at(seconds: int = TURN_TIMEOUT_S) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _deadline_expired(iso_str) -> bool:
    if not iso_str:
        return False
    try:
        return datetime.now(timezone.utc) >= datetime.fromisoformat(iso_str)
    except Exception:
        return False


def _new_rps_state() -> dict:
    return {
        "version":      2,
        "rounds_total": ROUNDS_MAX,
        "current_round": 1,
        "moves": {
            "a": [None] * ROUNDS_MAX,
            "b": [None] * ROUNDS_MAX,
        },
        "round_outcomes": [None] * ROUNDS_MAX,
        "wins":         {"a": 0, "b": 0},
        "phase":        "moving",
        "deadline_at":  _deadline_at(),
    }


def _resolve_round(a_move, b_move) -> str:
    """'a' | 'b' | 'draw' | 'a' if только a сделал ход (b forfeit) и т.д."""
    if a_move is None and b_move is None:
        # Оба forfeit → draw (никто очко не получает)
        return "draw"
    if a_move is None:
        return "b"  # только b сделал ход → b выиграл раунд
    if b_move is None:
        return "a"
    if a_move == b_move:
        return "draw"
    return "a" if _BEATS[a_move] == b_move else "b"


def _elo_update(rating: int, opp_rating: int, result: float) -> int:
    expected = 1 / (1 + 10 ** ((opp_rating - rating) / 400))
    return round(rating + ELO_K * (result - expected))


# Reuse season / stats helpers из duel.py (DRY)
async def _ensure_season(conn, channel_id: int) -> int:
    from routes.duel import _ensure_season as _duel_ensure_season
    return await _duel_ensure_season(conn, channel_id, game_type=GAME_TYPE)


async def _get_or_init_stats(conn, channel_id, username, season_id):
    cur = await conn.execute(
        "SELECT elo, win_streak FROM duel_stats "
        "WHERE channel_id = ? AND username = ? AND game_type = ?",
        (channel_id, username, GAME_TYPE)
    )
    row = await cur.fetchone()
    if row:
        return row[0], row[1]
    await conn.execute(
        "INSERT INTO duel_stats (channel_id, username, game_type, elo, win_streak, season_id) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (channel_id, username, GAME_TYPE, ELO_START, season_id)
    )
    return ELO_START, 0


async def _update_stats(conn, channel_id, username, elo, streak):
    await conn.execute(
        "UPDATE duel_stats SET elo = ?, win_streak = ? "
        "WHERE channel_id = ? AND username = ? AND game_type = ?",
        (elo, streak, channel_id, username, GAME_TYPE)
    )


# ─── State machine helpers ────────────────────────────────────────────────────

def _check_round_complete(state, round_idx):
    """Если оба сделали ход в раунде → resolve, начисли wins, advance."""
    a_move = state["moves"]["a"][round_idx]
    b_move = state["moves"]["b"][round_idx]
    if a_move is None or b_move is None:
        return False  # ещё не оба
    outcome = _resolve_round(a_move, b_move)
    state["round_outcomes"][round_idx] = outcome
    if outcome == "a":
        state["wins"]["a"] += 1
    elif outcome == "b":
        state["wins"]["b"] += 1
    return True


def _is_game_over(state):
    """Best-of-3: достаточно WINS_TO_TAKE wins, или все раунды сыграны."""
    if state["wins"]["a"] >= WINS_TO_TAKE or state["wins"]["b"] >= WINS_TO_TAKE:
        return True
    if state["current_round"] > state["rounds_total"]:
        return True
    return False


def _resolve_winner(state):
    if state["wins"]["a"] > state["wins"]["b"]:
        return "a"
    if state["wins"]["b"] > state["wins"]["a"]:
        return "b"
    return "draw"


def _maybe_expire_phase(state):
    """Lazy expiration. Если deadline истёк и кто-то не сделал ход → forfeit."""
    if state.get("phase") == "finished":
        return False
    if not _deadline_expired(state.get("deadline_at")):
        return False

    idx = state["current_round"] - 1
    changed = False
    # Forfeit для тех кто не сходил — оставляем None (resolve_round
    # обработает как loss для того, у кого None против non-None)
    if state["moves"]["a"][idx] is None and state["moves"]["b"][idx] is None:
        # Оба silent → форсим оба None forfeit → draw, advance
        pass

    if _check_round_complete(state, idx):
        # round resolved (хотя бы один сходил, а второй forfeit'нул)
        changed = True
    else:
        # Оба None → пометим раунд как draw, advance
        state["round_outcomes"][idx] = "draw"
        changed = True

    # Advance round
    state["current_round"] += 1
    if _is_game_over(state):
        state["phase"] = "finished"
        state["deadline_at"] = None
    else:
        state["phase"] = "moving"
        state["deadline_at"] = _deadline_at()
    return changed


async def _finalize_pvp_match(conn, room_id, state, channel_id, p_a, p_b, elo_a, elo_b):
    state["phase"] = "finished"
    state["deadline_at"] = None
    winner_role = _resolve_winner(state)
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
    _, a_streak = await _get_or_init_stats(conn, channel_id, p_a, season_id)
    _, b_streak = await _get_or_init_stats(conn, channel_id, p_b, season_id)
    if outcome == "win_a":
        a_streak, b_streak = a_streak + 1, 0
    elif outcome == "win_b":
        a_streak, b_streak = 0, b_streak + 1
    await _update_stats(conn, channel_id, p_a, new_elo_a, a_streak)
    await _update_stats(conn, channel_id, p_b, new_elo_b, b_streak)
    return winner_user, outcome, new_elo_a, new_elo_b


def _broadcast_state(channel_id, room_id, state, finished=False, winner_user=None):
    try:
        from pubsub import broadcast as _pubsub_broadcast
        _pubsub_broadcast(channel_id, "match_state", {
            "room_id":  room_id,
            "game":     "rps",
            "state":    state,
            "status":   "finished" if finished else "active",
            "finished": finished,
            "winner":   winner_user,
        })
    except Exception:
        pass


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/api/rps/move")
async def rps_move(request: Request):
    """Сделать ход в RPS PvP-комнате.

    Body: {"room_id": str, "move": "rock"|"paper"|"scissors"}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    uname = username.lower()

    data = await request.json()
    room_id = data.get("room_id")
    move = data.get("move")
    if not room_id:
        return {"success": False, "message": "room_id обязателен"}
    if move not in _VALID_MOVES:
        return {"success": False, "message": "move должен быть rock|paper|scissors"}

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
                return {"success": False, "reason": "not_active"}

            state = json.loads(state_json or "{}")
            if state.get("version") != 2:
                state = _new_rps_state()

            _maybe_expire_phase(state)

            if state.get("phase") != "moving":
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_moving_phase", "state": state}

            you_are = "a" if uname == p_a else "b"
            idx = state["current_round"] - 1

            if state["moves"][you_are][idx] is not None:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "already_moved",
                        "state": state, "message": "Ход уже сделан"}

            state["moves"][you_are][idx] = move
            state["deadline_at"] = _deadline_at()  # refresh для оппа

            # Если оба сходили → resolve round + advance
            if _check_round_complete(state, idx):
                state["current_round"] += 1
                if _is_game_over(state):
                    winner_user, outcome, new_elo_a, new_elo_b = await _finalize_pvp_match(
                        conn, room_id, state, channel_id, p_a, p_b, elo_a, elo_b)
                    finished = True
                else:
                    state["phase"] = "moving"
                    state["deadline_at"] = _deadline_at()
                    await conn.execute(
                        "UPDATE match_rooms SET state = ? WHERE room_id = ?",
                        (json.dumps(state), room_id)
                    )
            else:
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
            wa = state["wins"]["a"]
            wb = state["wins"]["b"]
            if winner_user:
                await bot.send_message(
                    f"⚔️ RPS BO3: @{p_a} ({wa}) vs @{p_b} ({wb}) — победил @{winner_user}!",
                    channel_id=channel_id)
            else:
                await bot.send_message(
                    f"⚔️ RPS ничья: @{p_a} ({wa}) = @{p_b} ({wb})", channel_id=channel_id)
            if winner_user:
                await bot.check_and_unlock_achievements(
                    winner_user, "duel_win", channel_id=channel_id)
        except Exception: pass

    _broadcast_state(channel_id, room_id, state,
                     finished=finished, winner_user=winner_user)

    you_are = "a" if uname == p_a else "b"
    return {
        "success":  True,
        "you_are":  you_are,
        "state":    state,
        "finished": finished,
        "winner":   winner_user,
    }


@router.get("/api/rps/poll")
async def rps_poll(request: Request, room_id: str):
    """Lazy-expire poll endpoint для rps rooms (аналог /api/dice/poll)."""
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
                "FROM match_rooms WHERE room_id = ?", (room_id,)
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
                state = _new_rps_state()

            changed = False
            if status == "active":
                changed = _maybe_expire_phase(state)
                if state.get("phase") == "finished":
                    winner_user, outcome, _ea, _eb = await _finalize_pvp_match(
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
