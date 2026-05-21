"""
routes/tictactoe.py — TicTacToe 4×4 best-of-3 (Sprint 5.24c, 2026-05-21).

История:
  - Phase 5.1: классическая 3×3 TTT, одна игра до win/draw
  - Sprint 5.24c: 4×4 (4-в-ряд win condition) + best-of-3 + 10s timer

State JSON v2:
  {
    "version": 2,
    "board_size": 4,
    "rounds_total": 3,
    "current_round": 1,         # 1..3
    "boards": [                 # один current board, остальные в history
      {
        "cells": [16 strings ""|"a"|"b"],
        "next_turn": "a"|"b",
        "moves": int,
        "winner": "a"|"b"|"draw"|None,
      }
    ],
    "wins": {"a": 0, "b": 0},   # round wins (BO3 → max 2)
    "phase": "playing" | "finished",
    "deadline_at": "ISO" | null,
    "starter": "a" | "b",       # кто стартует current раунд (alternates)
  }

Move endpoint логика:
  1. Lazy-expire: если deadline истёк → auto-play random valid cell
     для current player
  2. Apply move
  3. Check winner of current board
  4. If winner → increment wins, advance round (or finish if 2 wins / 3 rounds)

ELO/season общие с предыдущей TTT 3×3 (game_type='tictactoe').

Compliance: skill-based PvP без ставок, §5.x OK.
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

GAME_TYPE      = "tictactoe"
ELO_START      = 1100
ELO_K          = 32
PRIZES         = {1: 1_000_000, 2: 500_000, 3: 350_000}

BOARD_SIZE     = 4
ROUNDS_MAX     = 3
WINS_TO_TAKE   = 2
TURN_TIMEOUT_S = 10
CELLS_TOTAL    = BOARD_SIZE * BOARD_SIZE  # 16

_rng = random.Random()


# ─── Game logic helpers ───────────────────────────────────────────────────────

def _generate_win_lines(n: int):
    """4-в-ряд для NxN board. Rows + cols + 2 diagonals."""
    lines = []
    for r in range(n):
        lines.append(tuple(r * n + c for c in range(n)))        # row
    for c in range(n):
        lines.append(tuple(r * n + c for r in range(n)))        # col
    lines.append(tuple(i * n + i     for i in range(n)))        # main diag
    lines.append(tuple(i * n + (n-1-i) for i in range(n)))      # anti diag
    return tuple(lines)


WIN_LINES = _generate_win_lines(BOARD_SIZE)


def _check_winner(cells: list) -> str:
    """Returns 'a' | 'b' | '' (no winner yet)."""
    for line in WIN_LINES:
        first = cells[line[0]]
        if not first:
            continue
        if all(cells[i] == first for i in line):
            return first
    return ""


def _is_full(cells: list) -> bool:
    return all(c for c in cells)


def _new_board(starter: str) -> dict:
    return {
        "cells":     [""] * CELLS_TOTAL,
        "next_turn": starter,
        "moves":     0,
        "winner":    None,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deadline_at(seconds: int = TURN_TIMEOUT_S) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _deadline_expired(iso_str) -> bool:
    if not iso_str: return False
    try:
        return datetime.now(timezone.utc) >= datetime.fromisoformat(iso_str)
    except Exception:
        return False


def _initial_state() -> dict:
    return {
        "version":       2,
        "board_size":    BOARD_SIZE,
        "rounds_total":  ROUNDS_MAX,
        "current_round": 1,
        "boards":        [_new_board("a")],
        "wins":          {"a": 0, "b": 0},
        "phase":         "playing",
        "deadline_at":   _deadline_at(),
        "starter":       "a",
    }


def _current_board(state):
    return state["boards"][-1]


def _is_game_over(state):
    if state["wins"]["a"] >= WINS_TO_TAKE or state["wins"]["b"] >= WINS_TO_TAKE:
        return True
    if state["current_round"] > state["rounds_total"]:
        return True
    return False


def _advance_after_board(state):
    """После завершения current board: засчитать win, начать следующий или finish."""
    board = _current_board(state)
    if board["winner"] == "a":
        state["wins"]["a"] += 1
    elif board["winner"] == "b":
        state["wins"]["b"] += 1
    # Draw — никому не очко

    state["current_round"] += 1
    if _is_game_over(state):
        state["phase"] = "finished"
        state["deadline_at"] = None
        return

    # Next round — стартует второй игрок (alternates)
    new_starter = "b" if state["starter"] == "a" else "a"
    state["starter"] = new_starter
    state["boards"].append(_new_board(new_starter))
    state["phase"] = "playing"
    state["deadline_at"] = _deadline_at()


def _maybe_expire_phase(state):
    """Lazy expiration: auto-play random valid cell для current player."""
    if state.get("phase") == "finished":
        return False
    if not _deadline_expired(state.get("deadline_at")):
        return False

    board = _current_board(state)
    if board.get("winner"):
        return False  # already resolved, advance handled elsewhere

    # Auto-play random empty cell
    empty_cells = [i for i, c in enumerate(board["cells"]) if not c]
    if not empty_cells:
        # Draw
        board["winner"] = "draw"
        _advance_after_board(state)
        return True

    cell = _rng.choice(empty_cells)
    board["cells"][cell] = board["next_turn"]
    board["moves"] += 1
    winner = _check_winner(board["cells"])
    if winner:
        board["winner"] = winner
        _advance_after_board(state)
    elif _is_full(board["cells"]):
        board["winner"] = "draw"
        _advance_after_board(state)
    else:
        board["next_turn"] = "b" if board["next_turn"] == "a" else "a"
        state["deadline_at"] = _deadline_at()
    return True


def _resolve_overall_winner(state):
    if state["wins"]["a"] > state["wins"]["b"]:
        return "a"
    if state["wins"]["b"] > state["wins"]["a"]:
        return "b"
    return "draw"


def _broadcast_state(channel_id, room_id, state, finished=False, winner_user=None):
    try:
        from pubsub import broadcast as _pubsub_broadcast
        _pubsub_broadcast(channel_id, "match_state", {
            "room_id":  room_id,
            "game":     "tictactoe",
            "state":    state,
            "status":   "finished" if finished else "active",
            "finished": finished,
            "winner":   winner_user,
        })
    except Exception:
        pass


def _elo_update(rating: int, opp_rating: int, result: float) -> int:
    """result: 1.0=win, 0.5=draw, 0.0=loss"""
    expected = 1 / (1 + 10 ** ((opp_rating - rating) / 400))
    return round(rating + ELO_K * (result - expected))


# ─── Season helpers (per channel + per game) ──────────────────────────────────

def _next_sunday_midnight():
    now = datetime.now(timezone.utc)
    days_ahead = (6 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target = now + timedelta(days=days_ahead)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)


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
    """Возвращает (elo, win_streak); создаёт запись с ELO_START если новая."""
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
    """Завершает сезон tictactoe для канала если ends_at прошло, начисляет
    PRIZES top-3 и стартует новый.

    Аналогично routes/duel.py:check_season_end, но per game_type='tictactoe'.
    """
    cid = channel_id if channel_id else resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
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
            return  # sезон ещё идёт

        # Sезон закончен — выдаём PRIZES top-3 крустиками
        top = await (await conn.execute(
            "SELECT username, elo FROM duel_stats "
            "WHERE channel_id = ? AND game_type = ? AND season_id = ? "
            "ORDER BY elo DESC LIMIT 3",
            (cid, GAME_TYPE, season_id)
        )).fetchall()

        prize_parts = []
        for rank, (uname, elo) in enumerate(top, 1):
            prize = PRIZES.get(rank, 0)
            if prize:
                await db.add_points(uname, prize, channel_id=cid)
                prize_parts.append(f"#{rank} @{uname} ({elo} ELO) +{prize:,}💎")

        await conn.execute(
            "UPDATE duel_seasons SET finished = 1 WHERE id = ?",
            (season_id,)
        )

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
                    f"🏆 TicTacToe сезон #{season_id} завершён! Призы: {' | '.join(prize_parts)}",
                    channel_id=cid,
                )
            else:
                await bot.send_message(
                    f"🏆 TicTacToe сезон #{season_id} завершён! Новый сезон стартовал.",
                    channel_id=cid,
                )
        except Exception:
            pass


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/api/tictactoe/move")
async def tictactoe_move(request: Request):
    """Сделать ход в TicTacToe 4×4 BO3.

    Body: {"room_id": str, "cell": int 0..15}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    uname = username.lower()

    data = await request.json()
    room_id = data.get("room_id")
    try:
        cell = int(data.get("cell", -1))
    except (TypeError, ValueError):
        return {"success": False, "reason": "invalid_cell", "message": "Неверная клетка"}
    if not (0 <= cell < CELLS_TOTAL):
        return {"success": False, "reason": "invalid_cell", "message": "Клетка вне доски"}
    if not room_id:
        return {"success": False, "reason": "no_room_id", "message": "room_id обязателен"}

    await check_season_end(channel_id)

    db = get_db()
    finished = False
    winner_user = None
    outcome = None
    new_elo_a = None
    new_elo_b = None

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
            (room_cid, gt, p_a, p_b, elo_a, elo_b, state_json, status) = row

            if room_cid != channel_id or gt != GAME_TYPE or uname not in (p_a, p_b):
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "access_denied"}
            if status != "active":
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_active", "message": "Матч завершён"}

            state = json.loads(state_json or "{}")
            if state.get("version") != 2:
                state = _initial_state()

            _maybe_expire_phase(state)

            if state.get("phase") == "finished":
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "game_over", "state": state}

            you_are = "a" if uname == p_a else "b"
            opponent = p_b if you_are == "a" else p_a
            board = _current_board(state)

            if board["next_turn"] != you_are:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_your_turn",
                        "state": state, "message": "Сейчас не твой ход"}
            if board["cells"][cell]:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "cell_taken",
                        "state": state, "message": "Клетка занята"}

            # Apply move
            board["cells"][cell] = you_are
            board["moves"] += 1
            state["deadline_at"] = _deadline_at()  # refresh для оппа

            # Check winner of current board
            winner_role = _check_winner(board["cells"])
            if winner_role:
                board["winner"] = winner_role
                _advance_after_board(state)
            elif _is_full(board["cells"]):
                board["winner"] = "draw"
                _advance_after_board(state)
            else:
                board["next_turn"] = "b" if you_are == "a" else "a"

            # Game over → finalize
            if state.get("phase") == "finished":
                finished = True
                overall = _resolve_overall_winner(state)
                if overall == "a":
                    outcome = "win_a"; winner_user = p_a
                    new_elo_a = _elo_update(elo_a, elo_b, 1.0)
                    new_elo_b = _elo_update(elo_b, elo_a, 0.0)
                elif overall == "b":
                    outcome = "win_b"; winner_user = p_b
                    new_elo_a = _elo_update(elo_a, elo_b, 0.0)
                    new_elo_b = _elo_update(elo_b, elo_a, 1.0)
                else:
                    outcome = "draw"
                    new_elo_a = _elo_update(elo_a, elo_b, 0.5)
                    new_elo_b = _elo_update(elo_b, elo_a, 0.5)
            else:
                # Не финиш — просто сохранить state
                await conn.execute(
                    "UPDATE match_rooms SET state = ? WHERE room_id = ?",
                    (json.dumps(state), room_id)
                )

            # Save state + status
            if finished:
                await conn.execute(
                    "UPDATE match_rooms SET state = ?, status = 'finished', "
                    "winner = ?, outcome = ?, player_a_elo = ?, player_b_elo = ?, "
                    "finished_at = CURRENT_TIMESTAMP WHERE room_id = ?",
                    (json.dumps(state), winner_user, outcome, new_elo_a, new_elo_b, room_id)
                )

                # Update duel_stats per game_type
                season_id = await _ensure_season(conn, channel_id)
                a_old_elo, a_streak = await _get_or_init_stats(conn, channel_id, p_a, season_id)
                b_old_elo, b_streak = await _get_or_init_stats(conn, channel_id, p_b, season_id)

                if outcome == "win_a":
                    new_a_streak = a_streak + 1
                    new_b_streak = 0
                elif outcome == "win_b":
                    new_a_streak = 0
                    new_b_streak = b_streak + 1
                else:  # draw
                    new_a_streak = a_streak
                    new_b_streak = b_streak

                await _update_stats(conn, channel_id, p_a, new_elo_a, new_a_streak)
                await _update_stats(conn, channel_id, p_b, new_elo_b, new_b_streak)
            else:
                await conn.execute(
                    "UPDATE match_rooms SET state = ? WHERE room_id = ?",
                    (json.dumps(state), room_id)
                )

            await conn.commit()

        except Exception:
            await conn.execute("ROLLBACK")
            raise

    # Chat-notification на победу (вне БД-транзакции)
    if finished and winner_user:
        try:
            bot = get_bot()
            await bot.send_message(
                f"❌⭕ TicTacToe: @{winner_user} победил! [ELO @{p_a}: {new_elo_a}, @{p_b}: {new_elo_b}]",
                channel_id=channel_id,
            )
        except Exception:
            pass
    elif finished and outcome == "draw":
        try:
            bot = get_bot()
            await bot.send_message(
                f"❌⭕ TicTacToe ничья! @{p_a} vs @{p_b}", channel_id=channel_id,
            )
        except Exception:
            pass

    # Achievement-trigger для победителя
    if winner_user:
        try:
            await get_bot().check_and_unlock_achievements(winner_user, "duel_win", channel_id=channel_id)
        except Exception:
            pass

    your_elo = new_elo_a if you_are == "a" else new_elo_b
    opp_elo = new_elo_b if you_are == "a" else new_elo_a

    # Phase C (2026-05-17): match_state broadcast — оппонент мгновенно видит
    # обновлённый board без 3-сек polling. Frontend dedupe по seq.
    try:
        from pubsub import broadcast as _pubsub_broadcast
        _pubsub_broadcast(channel_id, "match_state", {
            "room_id":  room_id,
            "game":     GAME_TYPE,
            "state":    state,
            "status":   "finished" if finished else "active",
            "finished": finished,
            "winner":   winner_user,
        })
    except Exception as e:
        import logging
        logging.getLogger("rimlink.tictactoe").warning(
            "post-move match_state broadcast failed: %s", e
        )

    return {
        "success":   True,
        "state":     state,
        "status":    "finished" if finished else "active",
        "finished":  finished,
        "winner":    winner_user,
        "outcome":   outcome,
        "you_are":   you_are,
        "opponent":  opponent,
        "your_elo":  your_elo,
        "opponent_elo": opp_elo,
        "message":   "Ход принят" if not finished else (
            "🎉 Победа!" if winner_user == uname else
            "😢 Поражение" if winner_user else
            "🤝 Ничья"
        ),
    }


@router.get("/api/tictactoe/poll")
async def tictactoe_poll(request: Request, room_id: str):
    """Lazy-expire poll endpoint для TTT rooms (аналог /api/dice/poll).

    Sprint 5.24c: /api/match/room/{id}/state не знает про game-specific
    deadline. Этот endpoint проверяет expiration на каждый poll и
    auto-играет random cell если кто-то завис.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    uname = username.lower()

    db = get_db()
    finished_just_now = False
    winner_user = None
    new_elo_a = None
    new_elo_b = None
    outcome = None

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
            room_cid, gt, p_a, p_b, elo_a, elo_b, state_json, status, winner_db, outcome_db = row

            if room_cid != channel_id or gt != GAME_TYPE or uname not in (p_a, p_b):
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "access_denied"}

            state = json.loads(state_json or "{}")
            if state.get("version") != 2 and status == "active":
                state = _initial_state()

            changed = False
            if status == "active":
                changed = _maybe_expire_phase(state)
                if state.get("phase") == "finished":
                    finished_just_now = True
                    overall = _resolve_overall_winner(state)
                    if overall == "a":
                        outcome = "win_a"; winner_user = p_a
                        new_elo_a = _elo_update(elo_a, elo_b, 1.0)
                        new_elo_b = _elo_update(elo_b, elo_a, 0.0)
                    elif overall == "b":
                        outcome = "win_b"; winner_user = p_b
                        new_elo_a = _elo_update(elo_a, elo_b, 0.0)
                        new_elo_b = _elo_update(elo_b, elo_a, 1.0)
                    else:
                        outcome = "draw"
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
            "player_a_elo": new_elo_a if new_elo_a is not None else elo_a,
            "player_b_elo": new_elo_b if new_elo_b is not None else elo_b,
            "state":        state,
            "status":       final_status,
            "you_are":      you_are,
            "opponent":     opponent,
            "winner":       winner_user or winner_db,
            "outcome":      outcome or outcome_db,
        }
    }


@router.get("/api/tictactoe/leaderboard")
async def tictactoe_leaderboard(request: Request):
    """Топ-5 TicTacToe per channel."""
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
        "leaderboard": [
            {"rank": i + 1, "username": r[0], "elo": r[1], "win_streak": r[2]}
            for i, r in enumerate(rows)
        ],
    }
