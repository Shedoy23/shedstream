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

# Ожидающие дуэли: {duel_id: {creator, move, status, created_ts}}.
# In-memory only (5-минутный TTL короче рестартов, persistence не нужна).
# Persistence в `pending_duels` table удалена 2026-05-17 (T2 plan) — таблица
# была дропнута миграцией M10, но writer-функции остались и кидали
# OperationalError на каждое создание дуэли.
_duels: dict = {}

# RPS: атакующий → защитник → победа атакующего?
_RPS_BEATS = {
    "rock":     {"scissors": True,  "paper":    False, "rock":     False},
    "scissors": {"paper":    True,  "rock":     False, "scissors": False},
    "paper":    {"rock":     True,  "scissors": False, "paper":    False},
}
_RPS_EMOJI  = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}
_VALID_MOVES = ("rock", "scissors", "paper")

ELO_START = 1000
ELO_K     = 32
# Sprint 5.25 rebalance — см. dice.py
PRIZES         = {1: 300_000, 2: 200_000, 3: 100_000}
PRIZE_ELO_GATE = 1100


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
    """Sprint 5.25: 2-week season aligned на Sunday midnight."""
    now  = datetime.now(timezone.utc)
    days = (6 - now.weekday()) % 7
    if days == 0:
        days = 14
    else:
        days += 7
    target = now + timedelta(days=days)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)


async def _ensure_season(conn, channel_id: int, game_type: str = 'rps') -> int:
    """Возвращает ID активного сезона КАНАЛА per game_type, создаёт новый если нет.

    Phase 5.0 (M10): game_type добавлен — sезоны per (channel, game_type).
    Default 'rps' для backward-compat существующих RPS-дуэлей.
    """
    row = await (await conn.execute(
        "SELECT id FROM duel_seasons WHERE channel_id = ? AND game_type = ? AND finished = 0 "
        "ORDER BY id DESC LIMIT 1",
        (channel_id, game_type)
    )).fetchone()
    if row:
        return row[0]

    now     = datetime.now(timezone.utc)
    ends_at = _next_sunday_midnight()
    await conn.execute(
        "INSERT INTO duel_seasons (channel_id, game_type, started_at, ends_at, finished) "
        "VALUES (?, ?, ?, ?, 0)",
        (channel_id, game_type, now.isoformat(), ends_at.isoformat())
    )
    row = await (await conn.execute("SELECT last_insert_rowid()")).fetchone()
    return row[0]


async def _get_stats(conn, username: str, season_id: int,
                     channel_id: int, game_type: str = 'rps'):
    """Возвращает (elo, win_streak) per (channel, user, game_type),
    создаёт запись если нет.

    Phase 5.0 (M10): channel_id + game_type теперь обязательные параметры.
    """
    row = await (await conn.execute(
        "SELECT elo, win_streak FROM duel_stats "
        "WHERE channel_id = ? AND username = ? AND game_type = ?",
        (channel_id, username.lower(), game_type)
    )).fetchone()
    if not row:
        await conn.execute(
            "INSERT OR IGNORE INTO duel_stats "
            "(channel_id, username, game_type, elo, win_streak, season_id) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (channel_id, username.lower(), game_type, ELO_START, season_id)
        )
        return (ELO_START, 0)
    return (row[0], row[1])


async def _update_stats(conn, username: str, elo: int, streak: int,
                        channel_id: int, game_type: str = 'rps'):
    await conn.execute(
        "UPDATE duel_stats SET elo = ?, win_streak = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE channel_id = ? AND username = ? AND game_type = ?",
        (elo, streak, channel_id, username.lower(), game_type)
    )


# Человеческие названия мини-игр для сообщений в чат (багрепорт #41).
# Держим здесь, а не во фронте: сообщение уходит ботом в чат Twitch.
_GAME_LABELS = {
    'rps':       'Камень-ножницы-бумага',
    'dice':      'Кости',
    'tictactoe': 'Крестики-нолики',
}


async def check_season_end(channel_id: int = None, game_type: str = 'rps'):
    """Проверяет окончание сезона КАНАЛА; начисляет призы и стартует новый.

    M4 follow-up (а): channel_id теперь обязательная семантическая величина
    (резолвится через resolve_channel_id_or_default). При None — соответствует
    текущему ContextVar (если функция вызвана из request handler) или
    DEFAULT_CHANNEL_ID. На startup на_startup'е итерирует по всем каналам в
    реестре отдельно.
    """
    from dependencies import resolve_channel_id_or_default
    cid = channel_id if channel_id else resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        # Атомарность: призы + finish + reset + новый сезон — одна транзакция
        # (иначе краш между add_points и finish = двойная выдача при ретрае).
        await conn.execute("BEGIN IMMEDIATE")
        # 2026-07-29. Раньше здесь стояло `ORDER BY id DESC LIMIT 1` — то есть
        # рассматривался ТОЛЬКО самый свежий незакрытый сезон. Если рядом висел
        # незакрытый старый, он не попадал сюда никогда: ни призов, ни закрытия.
        # На проде так накопилось три сезона rps (истекли 24.05 и 21.06) и один
        # tictactoe. Берём ВСЕ незакрытые и разбираем каждый.
        rows = await (await conn.execute(
            "SELECT id, ends_at FROM duel_seasons "
            "WHERE channel_id = ? AND game_type = ? AND finished = 0 "
            "ORDER BY id ASC",
            (cid, game_type)
        )).fetchall()

        if not rows:
            await _ensure_season(conn, cid, game_type)
            return

        now_utc = datetime.now(timezone.utc)
        expired = []
        for r_id, r_ends in rows:
            r_end = datetime.fromisoformat(r_ends)
            if r_end.tzinfo is None:
                r_end = r_end.replace(tzinfo=timezone.utc)
            if now_utc >= r_end:
                expired.append(r_id)

        if not expired:
            return  # Все незакрытые сезоны ещё идут

        # Просроченные, кроме последнего, закрываем БЕЗ призов и молча.
        # Не жадность: их таблица результатов физически стёрта — ротация
        # сезона сбрасывает `duel_stats` целиком по (каналу, игре), и строк с
        # их season_id в базе не осталось. Платить не по чему.
        for stale_id in expired[:-1]:
            await conn.execute(
                "UPDATE duel_seasons SET finished = 1 WHERE channel_id = ? AND id = ?",
                (cid, stale_id))
            print(f"[DUEL-SEASON] ch={cid} {game_type}: сезон #{stale_id} закрыт "
                  f"без призов — результаты не сохранились")

        season_id = expired[-1]

        # ── Сезон закончился (Sprint 5.25: prize gate elo >= 1100) ────────
        top = await (await conn.execute(
            "SELECT username, elo FROM duel_stats "
            "WHERE channel_id = ? AND season_id = ? AND elo >= ? "
            "ORDER BY elo DESC LIMIT 3",
            (cid, season_id, PRIZE_ELO_GATE)
        )).fetchall()

        prize_parts = []
        for rank, (uname, elo) in enumerate(top, 1):
            prize = PRIZES.get(rank, 0)
            if prize:
                await db.add_points_tx(conn, uname, prize, cid)  # в той же транзакции, что finish+reset
                # M105 (2026-07-29): запись о выплате — ТОЙ ЖЕ транзакцией.
                # Без неё выплата не оставляла следа: `duel_stats` обнуляется
                # этой же ротацией, и через месяц вопрос «кому и сколько
                # заплатили» становился неразрешим. На этом я и ошибся в
                # аудите, заявив «не платили никогда» по обнулённой таблице.
                await conn.execute(
                    "INSERT INTO duel_season_payouts "
                    "(channel_id, season_id, game_type, username, rank, elo, amount) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (cid, season_id, game_type, uname, rank, elo, prize))
                prize_parts.append(f"#{rank} @{uname} ({elo} ELO) +{prize:,}💎")

        await conn.execute(
            "UPDATE duel_seasons SET finished = 1 WHERE channel_id = ? AND id = ?",
            (cid, season_id)
        )

        now     = datetime.now(timezone.utc)
        new_end = _next_sunday_midnight()
        await conn.execute(
            "INSERT INTO duel_seasons (channel_id, game_type, started_at, ends_at, finished) VALUES (?, ?, ?, ?, 0)",
            (cid, game_type, now.isoformat(), new_end.isoformat())
        )
        new_row = await (await conn.execute("SELECT last_insert_rowid()")).fetchone()
        new_season_id = new_row[0]

        await conn.execute(
            "UPDATE duel_stats SET elo = ?, win_streak = 0, season_id = ? WHERE channel_id = ? AND game_type = ?",
            (ELO_START, new_season_id, cid, game_type)
        )
        await conn.commit()

        try:
            bot = get_bot()
            # 2026-07-29 (багрепорт #41): раньше в чат уходило просто «Сезон #10
            # завершён» — зритель не понимал, о каком сезоне речь. Соседние
            # мини-игры (dice.py, tictactoe.py) игру называют, эта — нет.
            game_label = _GAME_LABELS.get(game_type, game_type)
            if prize_parts:
                await bot.send_message(
                    f"🏆 Мини-игры: сезон «{game_label}» #{season_id} завершён! "
                    f"Призы: {' | '.join(prize_parts)}"
                )
            else:
                await bot.send_message(
                    f"🏆 Мини-игры: сезон «{game_label}» #{season_id} завершён! "
                    f"Новый сезон начался."
                )
        except Exception:
            pass


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/api/duel/create")
async def create_duel(body: DuelRequest, request: Request):
    """Создать дуэль и выбрать ход (ход скрыт от соперника).

    Phase 1.F (2026-05-10): ставка крустиков убрана (§6.2.6 wagering on
    outcomes). Дуэль теперь — чистый ELO-матч. Phase 5 переделает в
    matchmaking-очередь (поиск противника со схожим ELO).
    """
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    creator, channel_id = auth

    move = body.move.lower() if body.move else ""
    if move not in _VALID_MOVES:
        return {"success": False, "message": "Выбери ход: 🪨 камень, ✂️ ножницы или 📄 бумага"}

    await get_bot().touch_viewer(creator)

    for d in _duels.values():
        if (d["creator"] == creator and d["status"] == "pending"
                and d.get("channel_id") == channel_id):
            return {"success": False, "message": "У тебя уже есть активная дуэль"}

    await check_season_end()

    duel_id = f"duel_{int(time.time())}_{random.randint(1000, 9999)}"
    _duels[duel_id] = {
        "creator":    creator,
        "move":       move,
        "status":     "pending",
        "created_ts": time.time(),
        "channel_id": channel_id,   # A4 (2026-07-02): скоуп по каналу
    }
    return {
        "success":  True,
        "duel_id":  duel_id,
        "message":  f"⚔️ Дуэль создана! Ход сделан тайно. Ждём соперника...",
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
    if duel.get("channel_id") != channel_id:
        # A4: нельзя принять дуэль другого канала (ELO-загрязнение между тенантами).
        return {"success": False, "message": "Дуэль не найдена"}
    if duel["creator"] == username:
        return {"success": False, "message": "Нельзя принять свою дуэль!"}
    # Атомарный захват дуэли: меняем status pending→accepting, если кто-то другой
    # уже это сделал — accept провалится. Защищает от двойного accept'а.
    if duel["status"] != "pending":
        return {"success": False, "message": "Дуэль уже завершена"}
    duel["status"] = "accepting"
    if time.time() - duel["created_ts"] > 300:
        duel["status"] = "expired"
        return {"success": False, "message": "Время дуэли истекло"}

    # Phase 1.F (2026-05-10): проверки баланса крустиков удалены —
    # дуэли больше не на ставку (§6.2.6 wagering removal).

    await check_season_end()

    creator_move  = duel["move"]
    acceptor_move = move
    outcome       = _rps_outcome(creator_move, acceptor_move)
    c_emoji       = _RPS_EMOJI[creator_move]
    a_emoji       = _RPS_EMOJI[acceptor_move]

    async with db._connect() as conn:
        # Phase 5.0 (M10): _ensure_season / _get_stats / _update_stats теперь
        # принимают channel_id + game_type. RPS = 'rps' (default game_type).
        season_id          = await _ensure_season(conn, channel_id, game_type='rps')
        c_elo, c_streak    = await _get_stats(conn, duel["creator"], season_id, channel_id, 'rps')
        a_elo, a_streak    = await _get_stats(conn, username,        season_id, channel_id, 'rps')

        # Снимок лидера сезона ДО матча per (channel, game_type).
        _top_before_row = await (await conn.execute(
            "SELECT username FROM duel_stats WHERE channel_id = ? AND game_type = ? "
            "AND season_id = ? ORDER BY elo DESC LIMIT 1",
            (channel_id, 'rps', season_id)
        )).fetchone()
        _top_before = _top_before_row[0] if _top_before_row else None

        # Phase 1.F (2026-05-10): _transfer + списание/начисление крустиков
        # удалены — дуэли только за ELO. Sезонные награды (PRIZES) compliant
        # как награда за skill в сезоне, не gambling.

        if outcome == "win":
            winner       = duel["creator"]
            new_c_elo    = _elo_update(c_elo, a_elo, 1.0)
            new_a_elo    = _elo_update(a_elo, c_elo, 0.0)
            new_c_streak = c_streak + 1
            new_a_streak = 0
        elif outcome == "lose":
            winner       = username
            new_c_elo    = _elo_update(c_elo, a_elo, 0.0)
            new_a_elo    = _elo_update(a_elo, c_elo, 1.0)
            new_c_streak = 0
            new_a_streak = a_streak + 1
        else:  # draw — ELO сближается, стрики не меняются
            winner       = None
            new_c_elo    = _elo_update(c_elo, a_elo, 0.5)
            new_a_elo    = _elo_update(a_elo, c_elo, 0.5)
            new_c_streak = c_streak
            new_a_streak = a_streak

        await _update_stats(conn, duel["creator"], new_c_elo, new_c_streak, channel_id, 'rps')
        await _update_stats(conn, username,         new_a_elo, new_a_streak, channel_id, 'rps')

        # Лидер после матча — возможно, сменился (per channel + game).
        _top_after_row = await (await conn.execute(
            "SELECT username FROM duel_stats WHERE channel_id = ? AND game_type = ? "
            "AND season_id = ? ORDER BY elo DESC LIMIT 1",
            (channel_id, 'rps', season_id)
        )).fetchone()
        _top_after = _top_after_row[0] if _top_after_row else None

        await conn.commit()

    duel["status"] = "completed"
    duel["winner"] = winner

    c_delta = _delta_str(new_c_elo, c_elo)
    a_delta = _delta_str(new_a_elo, a_elo)

    if outcome == "draw":
        msg = (f"⚔️ @{duel['creator']} {c_emoji} vs {a_emoji} @{username} — "
               f"НИЧЬЯ! "
               f"[ELO: {new_c_elo} ({c_delta}) vs {new_a_elo} ({a_delta})]")
    else:
        msg = (f"⚔️ @{duel['creator']} {c_emoji} vs {a_emoji} @{username} — "
               f"победил @{winner}! "
               f"[ELO: {new_c_elo} ({c_delta}) vs {new_a_elo} ({a_delta})]")

    await bot.send_message(msg)

    # Новый #1 сезона — отдельное оповещение (интрига + пиар соревнования).
    # Срабатывает на первом матче сезона и на каждой смене лидера по ELO.
    if _top_after and _top_after != _top_before:
        asyncio.create_task(bot.send_message(
            f"👑 @{_top_after} возглавил сезон дуэлей #{season_id}! Новый #1 по ELO 🏆"
        ))

    if winner:
        asyncio.create_task(bot.check_and_unlock_achievements(winner, "duel_win", channel_id=channel_id))

    return {
        "success":      True,
        "winner":       winner,
        "outcome":      outcome,
        "creator_move": creator_move,
        "acceptor_move": acceptor_move,
        "message":      msg,
    }


@router.get("/api/duel/list")
async def list_duels(request: Request):
    """Список открытых дуэлей ТЕКУЩЕГО канала (без раскрытия хода создателя).
    A4 (2026-07-02): scoped по channel_id из JWT + identity из JWT (раньше был
    публичный ?username= и листались дуэли всех каналов → cross-channel accept)."""
    global _duels
    auth = require_jwt_user(request)
    if not auth:
        return {"duels": []}
    username, channel_id = auth
    result  = []
    now_ts  = time.time()
    expired = []

    for duel_id, d in _duels.items():
        if d["status"] != "pending":
            continue
        if now_ts - d.get("created_ts", now_ts) > 300:
            expired.append(duel_id)
            continue
        if d.get("channel_id") != channel_id:
            continue   # A4: только свой канал
        result.append({
            "duel_id":    duel_id,
            "creator":    d["creator"],
            "is_mine":    d["creator"] == username,
            "can_accept": d["creator"] != username,
        })

    for eid in expired:
        _duels[eid]["status"] = "expired"
    _duels = {k: v for k, v in _duels.items() if v["status"] == "pending"}
    return {"duels": result}


@router.get("/api/duel/leaderboard")
async def duel_leaderboard(request: Request, game_type: str = "rps"):
    """Топ-5 дуэлистов по ELO в текущем сезоне per (channel, game_type).

    Query: ?game_type=rps|tictactoe|dice (default 'rps' для backward compat)
    """
    from dependencies import require_jwt_channel
    cid = require_jwt_channel(request)
    if cid is None:
        # B2 (2026-07-02): без JWT не отдаём default-канал (multi-tenant leak);
        # фронт (duels.js) шлёт JWT. Пустой борд той же формы — UI не ломается.
        return {"season_id": 1, "ends_at": None, "game_type": game_type,
                "prizes": PRIZES, "elo_gate": PRIZE_ELO_GATE, "leaderboard": []}

    db = get_db()
    async with db._connect() as conn:
        rows = await (await conn.execute(
            "SELECT username, elo, win_streak FROM duel_stats "
            "WHERE channel_id = ? AND game_type = ? ORDER BY elo DESC LIMIT 5",
            (cid, game_type)
        )).fetchall()
        season_row = await (await conn.execute(
            "SELECT id, ends_at FROM duel_seasons "
            "WHERE channel_id = ? AND game_type = ? AND finished = 0 "
            "ORDER BY id DESC LIMIT 1",
            (cid, game_type)
        )).fetchone()

    return {
        "season_id": season_row[0] if season_row else 1,
        "ends_at":   season_row[1] if season_row else None,
        "game_type": game_type,
        # 2026-07-29 (тонкий фронт): суммы призов были захардкожены в тексте
        # duels.js. Отдаём те же PRIZES, по которым сезон реально платит —
        # иначе смена наград требует новой подачи расширения на ревью.
        "prizes":    PRIZES,
        # Порог приза — то же требование: зритель должен знать, при каком ELO
        # награда вообще начинает светить (аудит 29.07).
        "elo_gate":  PRIZE_ELO_GATE,
        "leaderboard": [
            {"rank": i + 1, "username": r[0], "elo": r[1], "win_streak": r[2]}
            for i, r in enumerate(rows)
        ],
    }
