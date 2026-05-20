"""
routes/tictactoe.py — TicTacToe MVP (Phase 5.1 of COMPLIANCE_REWORK_PLAN.md).

Первая полная game-state machine поверх matchmaking-инфры из Phase 5.0.
Multi-tenant + per-game ELO + sезонные награды.

Game shape:
  - 3x3 grid, 2 player TURN-based
  - player_a начинает (X), player_b — O
  - Win conditions: 8 lines (3 rows + 3 cols + 2 diags)
  - 9 заполненных клеток без winner → draw

State JSON (в match_rooms.state):
  {
    "board": ["", "", "", "", "", "", "", "", ""],   # 9 ячеек
    "next_turn": "a" | "b",                          # whose turn
    "moves": int                                     # счётчик ходов 0-9
  }

Endpoints:
  POST /api/tictactoe/move    — сделать ход (body: room_id, cell)
  GET  /api/tictactoe/leaderboard  — топ ELO per channel

Compliance: чистый skill-based PvP без ставок (Phase 1.F убрала wager).
ELO updates per match, sезонные награды top-3 крустиками (compliant).
"""
import json
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

GAME_TYPE = "tictactoe"
ELO_START = 1100
ELO_K = 32
PRIZES = {1: 1_000_000, 2: 500_000, 3: 350_000}  # топ-3 в конце сезона


# ─── Game logic helpers ───────────────────────────────────────────────────────

WIN_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),   # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),   # cols
    (0, 4, 8), (2, 4, 6),              # diags
)


def _check_winner(board: list) -> str:
    """Returns 'a' | 'b' | '' (no winner yet)."""
    for line in WIN_LINES:
        a, b, c = line
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return ""


def _is_full(board: list) -> bool:
    return all(cell for cell in board)


def _initial_state() -> dict:
    return {
        "board":     ["", "", "", "", "", "", "", "", ""],
        "next_turn": "a",
        "moves":     0,
    }


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
    """Сделать ход в TicTacToe.

    Body: {"room_id": str, "cell": int 0..8}

    Returns:
        success: {state, status, winner?, you_are, opponent, elo_change?, finished, message}
        failure: {success: False, reason, message}
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
    if not (0 <= cell <= 8):
        return {"success": False, "reason": "invalid_cell", "message": "Клетка вне доски"}
    if not room_id:
        return {"success": False, "reason": "no_room_id", "message": "room_id обязателен"}

    await check_season_end(channel_id)

    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")

            # Загружаем room
            cur = await conn.execute(
                "SELECT channel_id, game_type, player_a, player_b, "
                "player_a_elo, player_b_elo, state, status FROM match_rooms WHERE room_id = ?",
                (room_id,)
            )
            row = await cur.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_found", "message": "Комната не найдена"}

            (room_cid, gt, p_a, p_b, elo_a, elo_b, state_json, status) = row

            # Access control
            if room_cid != channel_id:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "wrong_channel", "message": "Wrong channel"}
            if gt != GAME_TYPE:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "wrong_game", "message": "Wrong game type"}
            if uname not in (p_a, p_b):
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_player", "message": "Ты не в этой комнате"}
            if status != "active":
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_active", "message": "Матч уже завершён"}

            # Lazy-init state если первый ход
            state = json.loads(state_json or "{}")
            if not state:
                state = _initial_state()

            you_are = "a" if uname == p_a else "b"
            opponent = p_b if you_are == "a" else p_a

            # Whose turn?
            if state.get("next_turn") != you_are:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "not_your_turn", "message": "Сейчас не твой ход"}

            # Cell free?
            board = state["board"]
            if board[cell]:
                await conn.execute("ROLLBACK")
                return {"success": False, "reason": "cell_taken", "message": "Клетка занята"}

            # Apply move
            board[cell] = you_are
            state["moves"] = state.get("moves", 0) + 1

            # Check win / draw
            winner_role = _check_winner(board)
            outcome = None
            winner_user = None
            new_elo_a, new_elo_b = elo_a, elo_b
            finished = False

            if winner_role:
                finished = True
                if winner_role == "a":
                    outcome = "win_a"
                    winner_user = p_a
                    new_elo_a = _elo_update(elo_a, elo_b, 1.0)
                    new_elo_b = _elo_update(elo_b, elo_a, 0.0)
                else:
                    outcome = "win_b"
                    winner_user = p_b
                    new_elo_a = _elo_update(elo_a, elo_b, 0.0)
                    new_elo_b = _elo_update(elo_b, elo_a, 1.0)
            elif _is_full(board):
                finished = True
                outcome = "draw"
                new_elo_a = _elo_update(elo_a, elo_b, 0.5)
                new_elo_b = _elo_update(elo_b, elo_a, 0.5)
            else:
                # Continue: next turn flip
                state["next_turn"] = "b" if you_are == "a" else "a"

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
