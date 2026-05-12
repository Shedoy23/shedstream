"""
routes/dice.py — Dice match MVP (Phase 5.2 of COMPLIANCE_REWORK_PLAN.md).

Простая high-roll механика для расслабона. Два режима:
  1. Vs bot — instant single-request match (без ELO, без сезонных наград).
     Чисто фановый расслаб когда не хочется ждать.
  2. PvP — через matchmaking очередь (Phase 5.0 infra), с ELO + sезонами.

Game logic:
  Каждый игрок броsает 2d6, суммирует. Выше сумма = победа. Ничья = draw.
  - 2 кубика per player: каждый 1-6 → сумма 2-12
  - Expected value: 7
  - Range diff: 0..10

Compliance:
  - Никаких ставок крустиков (Phase 1.F убрала)
  - Vs bot: rating не считается, чисто casual
  - PvP: ELO + sезонные награды top-3 (compliant как skill-based competition)
  - Лексика UI: "Roll", "Бросок", "Match" — НЕТ "casino dice", "lucky",
    "jackpot", "high stakes"
  - Animation: dice rolling 0.8s, no roulette-style spin (см. lessons §13.12)

State JSON (для PvP rooms):
  {
    "rolls": {"a": [d1, d2] | null, "b": [d1, d2] | null},
    "phase": "rolling" | "finished"
  }
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
ELO_START = 1100
ELO_K = 32
PRIZES = {1: 1_000_000, 2: 500_000, 3: 350_000}

# SystemRandom — НЕ нужен (без monetary stakes). Default random OK для casual.
_rng = random.Random()


# ─── Pure game logic ──────────────────────────────────────────────────────────

def _roll_2d6() -> list:
    """Бросок 2 кубиков. Returns [d1, d2] каждое 1..6."""
    return [_rng.randint(1, 6), _rng.randint(1, 6)]


def _resolve_winner(roll_a: list, roll_b: list) -> str:
    """Compare 2d6 vs 2d6 sums. Returns 'a' | 'b' | 'draw'."""
    s_a = sum(roll_a)
    s_b = sum(roll_b)
    if s_a > s_b:
        return "a"
    if s_b > s_a:
        return "b"
    return "draw"


def _elo_update(rating: int, opp_rating: int, result: float) -> int:
    expected = 1 / (1 + 10 ** ((opp_rating - rating) / 400))
    return round(rating + ELO_K * (result - expected))


# ─── Season helpers ───────────────────────────────────────────────────────────

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


@router.post("/api/dice/roll")
async def dice_roll(request: Request):
    """Roll в PvP match (после matchmaking).

    Body: {"room_id": str}

    Логика:
      - Загружаем room, проверяем access + status='active'
      - Если ты ещё не roll'ил → бросаем твои 2d6, записываем в state.rolls[you_are]
      - Если оппонент уже roll'ил → определяем winner + finalize match + ELO update
      - Если оппонент ещё нет → возвращаем wait
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
            if "rolls" not in state:
                state["rolls"] = {"a": None, "b": None}
                state["phase"] = "rolling"

            you_are = "a" if uname == p_a else "b"
            opponent = p_b if you_are == "a" else p_a

            # Already rolled?
            if state["rolls"].get(you_are):
                await conn.execute("ROLLBACK")
                return {
                    "success":  False,
                    "reason":   "already_rolled",
                    "your_roll": state["rolls"][you_are],
                    "message":  "Ты уже бросил",
                }

            # Бросаем
            your_roll = _roll_2d6()
            state["rolls"][you_are] = your_roll

            opponent_roll = state["rolls"].get("b" if you_are == "a" else "a")

            finished = False
            outcome = None
            winner_user = None
            new_elo_a, new_elo_b = elo_a, elo_b

            if opponent_roll:
                # Оба roll'ed → finalize
                winner_role = _resolve_winner(
                    your_roll if you_are == "a" else opponent_roll,
                    opponent_roll if you_are == "a" else your_roll
                )
                finished = True
                state["phase"] = "finished"

                if winner_role == "a":
                    outcome = "win_a"
                    winner_user = p_a
                    new_elo_a = _elo_update(elo_a, elo_b, 1.0)
                    new_elo_b = _elo_update(elo_b, elo_a, 0.0)
                elif winner_role == "b":
                    outcome = "win_b"
                    winner_user = p_b
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

                # Update duel_stats
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
            else:
                # Только мы roll'ed, оппонент ещё нет
                await conn.execute(
                    "UPDATE match_rooms SET state = ? WHERE room_id = ?",
                    (json.dumps(state), room_id)
                )

            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    # Chat-notification на финал (вне БД)
    if finished:
        try:
            bot = get_bot()
            a_sum = sum(state["rolls"]["a"])
            b_sum = sum(state["rolls"]["b"])
            if winner_user:
                await bot.send_message(
                    f"🎲 Dice match: @{p_a} ({a_sum}) vs @{p_b} ({b_sum}) — победил @{winner_user}! "
                    f"[ELO: {new_elo_a} / {new_elo_b}]",
                    channel_id=channel_id,
                )
            else:
                await bot.send_message(
                    f"🎲 Dice ничья: @{p_a} ({a_sum}) = @{p_b} ({b_sum})",
                    channel_id=channel_id,
                )
        except Exception:
            pass

    if winner_user:
        try:
            await get_bot().check_and_unlock_achievements(winner_user, "duel_win", channel_id=channel_id)
        except Exception:
            pass

    return {
        "success":      True,
        "mode":         "pvp",
        "your_roll":    your_roll,
        "opponent_roll": opponent_roll,
        "you_are":      you_are,
        "opponent":     opponent,
        "finished":     finished,
        "winner":       winner_user,
        "outcome":      outcome,
        "your_elo":     new_elo_a if you_are == "a" else new_elo_b,
        "opponent_elo": new_elo_b if you_are == "a" else new_elo_a,
        "state":        state,
        "message":      ("⏳ Ждём оппонента..." if not finished else
                         "🎉 Победа!" if winner_user == uname else
                         "😢 Поражение" if winner_user else
                         "🤝 Ничья"),
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
        "leaderboard": [
            {"rank": i + 1, "username": r[0], "elo": r[1], "win_streak": r[2]}
            for i, r in enumerate(rows)
        ],
    }
