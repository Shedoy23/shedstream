"""
routes/duel.py — дуэли с RPS, ELO и системой сезонов.
"""

import asyncio
import random
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

from config import sanitize_username
from dependencies import get_bot, get_db, require_jwt_user, require_stream_live
from models import AcceptDuelRequest, DuelRequest

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch — открой расширение и войди"}

router = APIRouter()

# Ожидающие дуэли: {duel_id: {creator, amount, move, status, created_ts}}
# Dict — быстрый доступ; параллельно персистим в БД (pending_duels), чтобы переживали рестарт.
_duels: dict = {}


async def _db_save_duel(duel_id: str, d: dict) -> None:
    """Сохранить pending-дуэль в БД."""
    db = get_db()
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO pending_duels (duel_id, creator, amount, move, created_ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (duel_id, d["creator"], d["amount"], d["move"], d["created_ts"])
        )
        await conn.commit()


async def _db_remove_duel(duel_id: str) -> None:
    """Удалить дуэль из БД (при accept/expire)."""
    db = get_db()
    async with db._connect() as conn:
        await conn.execute("DELETE FROM pending_duels WHERE duel_id = ?", (duel_id,))
        await conn.commit()


async def load_pending_duels() -> None:
    """Восстанавливаем pending-дуэли из БД при старте приложения."""
    db = get_db()
    async with db._connect() as conn:
        rows = await (await conn.execute(
            "SELECT duel_id, creator, amount, move, created_ts FROM pending_duels"
        )).fetchall()

    now = time.time()
    loaded, expired = 0, 0
    for duel_id, creator, amount, move, created_ts in rows:
        if now - created_ts > 300:
            await _db_remove_duel(duel_id)
            expired += 1
            continue
        _duels[duel_id] = {
            "creator":    creator,
            "amount":     amount,
            "move":       move,
            "status":     "pending",
            "created_ts": created_ts,
        }
        loaded += 1
    print(f"[duel] Восстановлено {loaded} pending-дуэлей из БД (отброшено просроченных: {expired})")

# RPS: атакующий → защитник → победа атакующего?
_RPS_BEATS = {
    "rock":     {"scissors": True,  "paper":    False, "rock":     False},
    "scissors": {"paper":    True,  "rock":     False, "scissors": False},
    "paper":    {"rock":     True,  "scissors": False, "paper":    False},
}
_RPS_EMOJI  = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}
_VALID_MOVES = ("rock", "scissors", "paper")

ELO_START = 1100
ELO_K     = 32
PRIZES    = {1: 1_000_000, 2: 500_000, 3: 350_000}


# ─── Helpers ────────────────────────────────────────────────────────────────

def _elo_update(rating: int, opp_rating: int, result: float) -> int:
    """result: 1=победа, 0=поражение, 0.5=ничья"""
    expected = 1 / (1 + 10 ** ((opp_rating - rating) / 400))
    return round(rating + ELO_K * (result - expected))


def _rps_outcome(attacker: str, defender: str) -> str:
    """Возвращает 'win', 'lose' или 'draw' с позиции атакующего."""
    if attacker == defender:
        return "draw"
    return "win" if _RPS_BEATS[attacker][defender] else "lose"


def _delta_str(new: int, old: int) -> str:
    d = new - old
    return f"+{d}" if d >= 0 else str(d)


def _next_sunday_midnight() -> datetime:
    now  = datetime.now(timezone.utc)
    days = (6 - now.weekday()) % 7
    if days == 0:
        days = 7
    target = now + timedelta(days=days)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)


async def _ensure_season(conn) -> int:
    """Возвращает ID активного сезона, создаёт новый если нет."""
    row = await (await conn.execute(
        "SELECT id FROM duel_seasons WHERE finished = 0 ORDER BY id DESC LIMIT 1"
    )).fetchone()
    if row:
        return row[0]

    now     = datetime.now(timezone.utc)
    ends_at = _next_sunday_midnight()
    await conn.execute(
        "INSERT INTO duel_seasons (started_at, ends_at, finished) VALUES (?, ?, 0)",
        (now.isoformat(), ends_at.isoformat())
    )
    row = await (await conn.execute("SELECT last_insert_rowid()")).fetchone()
    return row[0]


async def _get_stats(conn, username: str, season_id: int):
    """Возвращает (elo, win_streak), создаёт запись если нет."""
    row = await (await conn.execute(
        "SELECT elo, win_streak FROM duel_stats WHERE username = ?", (username,)
    )).fetchone()
    if not row:
        await conn.execute(
            "INSERT OR IGNORE INTO duel_stats (username, elo, win_streak, season_id) VALUES (?, ?, 0, ?)",
            (username, ELO_START, season_id)
        )
        return (ELO_START, 0)
    return (row[0], row[1])


async def _update_stats(conn, username: str, elo: int, streak: int):
    await conn.execute(
        "UPDATE duel_stats SET elo = ?, win_streak = ? WHERE username = ?",
        (elo, streak, username)
    )


async def check_season_end():
    """Проверяет окончание сезона; при необходимости начисляет призы и стартует новый."""
    db = get_db()
    async with db._connect() as conn:
        row = await (await conn.execute(
            "SELECT id, ends_at FROM duel_seasons WHERE finished = 0 ORDER BY id DESC LIMIT 1"
        )).fetchone()

        if not row:
            await _ensure_season(conn)
            return

        season_id, ends_at_str = row
        ends_at = datetime.fromisoformat(ends_at_str)
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) < ends_at:
            return  # Сезон ещё идёт

        # ── Сезон закончился ──────────────────────────────────────────────
        top = await (await conn.execute(
            "SELECT username, elo FROM duel_stats WHERE season_id = ? ORDER BY elo DESC LIMIT 3",
            (season_id,)
        )).fetchall()

        prize_parts = []
        for rank, (uname, elo) in enumerate(top, 1):
            prize = PRIZES.get(rank, 0)
            if prize:
                await db.add_points(uname, prize)
                prize_parts.append(f"#{rank} @{uname} ({elo} ELO) +{prize:,}💎")

        await conn.execute("UPDATE duel_seasons SET finished = 1 WHERE id = ?", (season_id,))

        now     = datetime.now(timezone.utc)
        new_end = _next_sunday_midnight()
        await conn.execute(
            "INSERT INTO duel_seasons (started_at, ends_at, finished) VALUES (?, ?, 0)",
            (now.isoformat(), new_end.isoformat())
        )
        new_row = await (await conn.execute("SELECT last_insert_rowid()")).fetchone()
        new_season_id = new_row[0]

        await conn.execute(
            "UPDATE duel_stats SET elo = ?, win_streak = 0, season_id = ?",
            (ELO_START, new_season_id)
        )
        await conn.commit()

        try:
            bot = get_bot()
            if prize_parts:
                await bot.send_message(
                    f"🏆 Сезон #{season_id} завершён! Призы: {' | '.join(prize_parts)}"
                )
            else:
                await bot.send_message(f"🏆 Сезон #{season_id} завершён! Новый сезон начался.")
        except Exception:
            pass


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/api/duel/create")
async def create_duel(body: DuelRequest, request: Request):
    """Создать дуэль и выбрать ход (ход скрыт от соперника)."""
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    creator, channel_id = auth
    db = get_db()

    if body.amount < 50:
        return {"success": False, "message": "Минимальная ставка 50💎"}

    move = body.move.lower() if body.move else ""
    if move not in _VALID_MOVES:
        return {"success": False, "message": "Выбери ход: 🪨 камень, ✂️ ножницы или 📄 бумага"}

    await get_bot().touch_viewer(creator)

    creator_points = await db.get_points(creator)
    if creator_points < body.amount:
        return {"success": False, "message": f"У тебя только {creator_points}💎"}

    for d in _duels.values():
        if d["creator"] == creator and d["status"] == "pending":
            return {"success": False, "message": "У тебя уже есть активная дуэль"}

    await check_season_end()

    duel_id = f"duel_{int(time.time())}_{random.randint(1000, 9999)}"
    _duels[duel_id] = {
        "creator":    creator,
        "amount":     body.amount,
        "move":       move,
        "status":     "pending",
        "created_ts": time.time(),
    }
    await _db_save_duel(duel_id, _duels[duel_id])
    return {
        "success":  True,
        "duel_id":  duel_id,
        "message":  f"⚔️ Дуэль на {body.amount}💎 создана! Ход сделан тайно. Ждём соперника...",
    }


@router.post("/api/duel/accept")
async def accept_duel(req: AcceptDuelRequest, request: Request):
    """Принять дуэль, выбрать ход и определить победителя."""
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    db  = get_db()
    bot = get_bot()

    duel_id  = req.duel_id
    move     = req.move.lower()
    if move not in _VALID_MOVES:
        return {"success": False, "message": "Выбери ход: 🪨 камень, ✂️ ножницы или 📄 бумага"}

    await bot.touch_viewer(username)

    if duel_id not in _duels:
        return {"success": False, "message": "Дуэль не найдена"}

    duel = _duels[duel_id]
    if duel["creator"] == username:
        return {"success": False, "message": "Нельзя принять свою дуэль!"}
    # Атомарный захват дуэли: меняем status pending→accepting, если кто-то другой
    # уже это сделал — accept провалится. Защищает от двойного accept'а.
    if duel["status"] != "pending":
        return {"success": False, "message": "Дуэль уже завершена"}
    duel["status"] = "accepting"
    if time.time() - duel["created_ts"] > 300:
        duel["status"] = "expired"
        await _db_remove_duel(duel_id)
        return {"success": False, "message": "Время дуэли истекло"}

    creator_points = await db.get_points(duel["creator"])
    if creator_points < duel["amount"]:
        duel["status"] = "expired"
        await _db_remove_duel(duel_id)
        return {"success": False, "message": "У создателя не хватает очков — дуэль отменена"}

    acceptor_points = await db.get_points(username)
    if acceptor_points < duel["amount"]:
        return {"success": False, "message": f"У тебя только {acceptor_points}💎"}

    await check_season_end()

    creator_move  = duel["move"]
    acceptor_move = move
    outcome       = _rps_outcome(creator_move, acceptor_move)
    c_emoji       = _RPS_EMOJI[creator_move]
    a_emoji       = _RPS_EMOJI[acceptor_move]

    async with db._connect() as conn:
        season_id          = await _ensure_season(conn)
        c_elo, c_streak    = await _get_stats(conn, duel["creator"], season_id)
        a_elo, a_streak    = await _get_stats(conn, username,        season_id)

        # Снимок лидера сезона ДО матча — чтобы поймать смену #1 после апдейта ELO.
        _top_before_row = await (await conn.execute(
            "SELECT username FROM duel_stats WHERE season_id = ? ORDER BY elo DESC LIMIT 1",
            (season_id,)
        )).fetchone()
        _top_before = _top_before_row[0] if _top_before_row else None

        # Списание/начисление очков через тот же conn — без вложенного _connect(),
        # иначе SQLite выдаёт "database is locked" внутри активной транзакции → 500.
        async def _transfer(conn, loser: str, winner: str, amount: int) -> bool:
            cur = await conn.execute(
                "UPDATE viewers SET points = points - ? WHERE username = ? AND points >= ?",
                (amount, loser.lower(), amount))
            if cur.rowcount == 0:
                return False
            await conn.execute("""
                INSERT INTO viewers (username, points, last_seen, join_time, is_afk)
                VALUES (?, ?, datetime('now'), datetime('now'), 0)
                ON CONFLICT(username) DO UPDATE SET
                    points = points + ?,
                    last_seen = datetime('now')
            """, (winner.lower(), amount, amount))
            return True

        if outcome == "win":
            winner, loser = duel["creator"], username
            await _transfer(conn, loser, winner, duel["amount"])
            new_c_elo    = _elo_update(c_elo, a_elo, 1.0)
            new_a_elo    = _elo_update(a_elo, c_elo, 0.0)
            new_c_streak = c_streak + 1
            new_a_streak = 0
        elif outcome == "lose":
            winner, loser = username, duel["creator"]
            await _transfer(conn, loser, winner, duel["amount"])
            new_c_elo    = _elo_update(c_elo, a_elo, 0.0)
            new_a_elo    = _elo_update(a_elo, c_elo, 1.0)
            new_c_streak = 0
            new_a_streak = a_streak + 1
        else:  # draw — очки не переводятся, ELO сближается, стрики не меняются
            winner       = None
            new_c_elo    = _elo_update(c_elo, a_elo, 0.5)
            new_a_elo    = _elo_update(a_elo, c_elo, 0.5)
            new_c_streak = c_streak
            new_a_streak = a_streak

        await _update_stats(conn, duel["creator"], new_c_elo, new_c_streak)
        await _update_stats(conn, username,         new_a_elo, new_a_streak)

        # Лидер после матча — возможно, сменился.
        _top_after_row = await (await conn.execute(
            "SELECT username FROM duel_stats WHERE season_id = ? ORDER BY elo DESC LIMIT 1",
            (season_id,)
        )).fetchone()
        _top_after = _top_after_row[0] if _top_after_row else None

        await conn.commit()

    duel["status"] = "completed"
    duel["winner"] = winner
    await _db_remove_duel(duel_id)

    c_delta = _delta_str(new_c_elo, c_elo)
    a_delta = _delta_str(new_a_elo, a_elo)

    if outcome == "draw":
        msg = (f"⚔️ @{duel['creator']} {c_emoji} vs {a_emoji} @{username} — "
               f"НИЧЬЯ! Ставки возвращены. "
               f"[ELO: {new_c_elo} ({c_delta}) vs {new_a_elo} ({a_delta})]")
    else:
        msg = (f"⚔️ @{duel['creator']} {c_emoji} vs {a_emoji} @{username} — "
               f"победил @{winner}! +{duel['amount']}💎 "
               f"[ELO: {new_c_elo} ({c_delta}) vs {new_a_elo} ({a_delta})]")

    await bot.send_message(msg)

    # Новый #1 сезона — отдельное оповещение (интрига + пиар соревнования).
    # Срабатывает на первом матче сезона и на каждой смене лидера по ELO.
    if _top_after and _top_after != _top_before:
        asyncio.create_task(bot.send_message(
            f"👑 @{_top_after} возглавил сезон дуэлей #{season_id}! Новый #1 по ELO 🏆"
        ))

    if winner:
        asyncio.create_task(bot.check_and_unlock_achievements(winner, "duel_win"))

    return {
        "success":      True,
        "winner":       winner,
        "outcome":      outcome,
        "creator_move": creator_move,
        "acceptor_move": acceptor_move,
        "message":      msg,
    }


@router.get("/api/duel/list")
async def list_duels(username: str = ""):
    """Список открытых дуэлей (без раскрытия хода создателя)."""
    global _duels
    result  = []
    now_ts  = time.time()
    expired = []

    for duel_id, d in _duels.items():
        if d["status"] != "pending":
            continue
        if now_ts - d.get("created_ts", now_ts) > 300:
            expired.append(duel_id)
            continue
        result.append({
            "duel_id":    duel_id,
            "creator":    d["creator"],
            "amount":     d["amount"],
            "is_mine":    d["creator"] == username,
            "can_accept": d["creator"] != username,
        })

    for eid in expired:
        _duels[eid]["status"] = "expired"
        await _db_remove_duel(eid)
    _duels = {k: v for k, v in _duels.items() if v["status"] == "pending"}
    return {"duels": result}


@router.get("/api/duel/leaderboard")
async def duel_leaderboard():
    """Топ-5 дуэлистов по ELO в текущем сезоне."""
    db = get_db()
    async with db._connect() as conn:
        rows = await (await conn.execute(
            "SELECT username, elo, win_streak FROM duel_stats ORDER BY elo DESC LIMIT 5"
        )).fetchall()
        season_row = await (await conn.execute(
            "SELECT id, ends_at FROM duel_seasons WHERE finished = 0 ORDER BY id DESC LIMIT 1"
        )).fetchone()

    return {
        "season_id": season_row[0] if season_row else 1,
        "ends_at":   season_row[1] if season_row else None,
        "leaderboard": [
            {"rank": i + 1, "username": r[0], "elo": r[1], "win_streak": r[2]}
            for i, r in enumerate(rows)
        ],
    }
