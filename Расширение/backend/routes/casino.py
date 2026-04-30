"""
routes/casino.py — казино: ставки, слоты, джекпот, near-miss, фриспины, риск-игра.
"""

import asyncio
import time
from datetime import datetime, date
from secrets import SystemRandom

from fastapi import APIRouter

# CSPRNG вместо random.* — Mersenne Twister предсказуем после ~624 наблюдений.
# Для денежной экономики это критично; разница в производительности нерелевантна.
_rng = SystemRandom()

from config import sanitize_username, validate_username
from dependencies import (
    check_rate_limit,
    get_bot,
    get_db,
    require_stream_live,
    set_overlay_jackpot,
)
from models import BetRequest, SpinSlotsRequest

router = APIRouter()

SLOT_SYMBOLS = [
    {"id": "wood",   "emoji": "🪵", "mult": 0, "weight": 55},
    {"id": "stone",  "emoji": "🪨", "mult": 1, "weight": 25},
    {"id": "amulet", "emoji": "🔮", "mult": 2, "weight": 15},
    {"id": "crown",  "emoji": "👑", "mult": 5, "weight": 5},
]

JACKPOT_CONTRIBUTION = 0.02   # 2% каждой ставки идёт в джекпот
JACKPOT_START        = 10_000 # значение после сброса
FREE_SPINS_COUNT     = 5      # бесплатных вращений в день
FREE_SPINS_BET       = 1_000  # виртуальная ставка фриспина

# Ожидающие риск-игры: {username: {"amount": int, "expires": float}}
_pending_doubles: dict = {}


# ─── Джекпот ─────────────────────────────────────────────────────────────────

async def _get_jackpot(db) -> int:
    async with db._connect() as conn:
        row = await (await conn.execute(
            "SELECT value FROM casino_settings WHERE key = 'jackpot'"
        )).fetchone()
    return int(row[0]) if row else JACKPOT_START


async def _add_to_jackpot(db, delta: int) -> int:
    """Прибавить delta к джекпоту, вернуть новое значение."""
    async with db._connect() as conn:
        row = await (await conn.execute(
            "SELECT value FROM casino_settings WHERE key = 'jackpot'"
        )).fetchone()
        new_val = (int(row[0]) if row else JACKPOT_START) + delta
        await conn.execute(
            "INSERT OR REPLACE INTO casino_settings (key, value) VALUES ('jackpot', ?)",
            (str(new_val),)
        )
    return new_val


async def _reset_jackpot(db):
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO casino_settings (key, value) VALUES ('jackpot', ?)",
            (str(JACKPOT_START),)
        )


# ─── Логика спина ─────────────────────────────────────────────────────────────

def _pick():
    total = sum(s["weight"] for s in SLOT_SYMBOLS)
    r = _rng.randint(1, total)
    cum = 0
    for s in SLOT_SYMBOLS:
        cum += s["weight"]
        if r <= cum:
            return s
    return SLOT_SYMBOLS[0]


def _calc_spin(bet: int, jackpot: int) -> dict:
    """Вычислить результат спина (без побочных эффектов).

    Таблица выплат (целевой RTP ≈ 92%):
      тройки:  wood=x0, stone=x25, amulet=x75, crown=jackpot
      пары:    crown=x4, amulet=x3, stone=x0.1 (near-miss), wood=x0.1 (near-miss)
      прочее:  0
    """
    r1, r2, r3 = _pick(), _pick(), _pick()
    ids = [r1["id"], r2["id"], r3["id"]]

    jackpot_won   = False
    near_miss_amt = 0
    mult          = 0
    win_amount    = 0

    if ids[0] == ids[1] == ids[2]:              # тройка
        if ids[0] == "crown":
            win_amount  = jackpot
            jackpot_won = True
        else:
            mult       = {"amulet": 75, "stone": 25, "wood": 0}.get(ids[0], 0)
            win_amount = int(bet * mult)
    else:                                        # не тройка — ищем пару
        if   ids[0] == ids[1]: pair = ids[0]
        elif ids[1] == ids[2]: pair = ids[1]
        elif ids[0] == ids[2]: pair = ids[0]
        else:                  pair = None

        if pair == "crown":
            mult, win_amount = 4, bet * 4
        elif pair == "amulet":
            mult, win_amount = 3, bet * 3
        elif pair == "stone":
            near_miss_amt = int(bet * 0.1)
        elif pair == "wood":
            near_miss_amt = int(bet * 0.1)

    return {
        "ids":           ids,
        "win_amount":    win_amount,
        "mult":          mult,
        "jackpot_won":   jackpot_won,
        "near_miss_amt": near_miss_amt,
    }


# ─── Эндпоинты ───────────────────────────────────────────────────────────────

@router.post("/api/casino/bet")
async def casino_bet(request: BetRequest):
    """Ставка в казино (старый эндпоинт)."""
    if err := await require_stream_live():
        return err
    db  = get_db()
    bot = get_bot()
    username = sanitize_username(str(request.username))
    if not username or not validate_username(username):
        return {"success": False, "message": "❌ Неверный username"}
    if not check_rate_limit(username, 60):
        return {"success": False, "message": "⏱ Слишком много запросов"}
    balance = await db.get_points(username)
    result = await bot.casino_bet(username, request.amount)
    if result.get("result") == "jackpot":
        set_overlay_jackpot({
            "id":       f"{request.username}-{time.time():.0f}",
            "username": request.username,
            "win":      result["win"],
            "bet":      request.amount,
            "ts":       datetime.now().isoformat(),
        })
    asyncio.create_task(bot.check_and_unlock_achievements(request.username, "casino"))
    return result


@router.post("/api/casino/slots")
async def play_slots(req: SpinSlotsRequest):
    """Слоты с джекпотом, near-miss и риск-игрой."""
    db    = get_db()
    uname = req.username.lower()

    if not check_rate_limit(uname, 20):
        return {"success": False, "message": "⏱ Подожди немного перед следующим спином"}

    # touch активности — действие в расширении == зритель не AFK
    await get_bot().touch_viewer(uname)

    balance = await db.get_points(uname)
    if balance < req.bet:
        return {"success": False, "message": "Недостаточно очков"}

    removed = await db.remove_points(uname, req.bet)
    if not removed:
        return {"success": False, "message": "Ошибка списания"}

    try:
        jackpot = await _get_jackpot(db)
        spin    = _calc_spin(req.bet, jackpot)

        total_win = spin["win_amount"] + spin["near_miss_amt"]

        if spin["jackpot_won"]:
            await _reset_jackpot(db)
            jackpot = JACKPOT_START
            set_overlay_jackpot({
                "id":       f"{uname}-{time.time():.0f}",
                "username": uname,
                "win":      spin["win_amount"],
                "bet":      req.bet,
                "ts":       datetime.now().isoformat(),
            })
            bot = get_bot()
            asyncio.create_task(bot.send_message(
                f"🎰👑 ДЖЕКПОТ! @{uname} сорвал куш {spin['win_amount']:,}💎!"
            ))
        else:
            jackpot = await _add_to_jackpot(db, int(req.bet * JACKPOT_CONTRIBUTION))
            # Тройка амулета (×75, p≈0.34%) — редкий крупный win, заслуживает оповещения
            if spin["mult"] == 75:
                asyncio.create_task(get_bot().send_message(
                    f"🔮🔮🔮 @{uname} собрал три амулета и унёс {spin['win_amount']:,}💎! (×75)"
                ))

        if total_win > 0:
            await db.add_points(uname, total_win)
    except Exception:
        # Если что-то пошло не так после списания — возвращаем ставку
        await db.add_points(uname, req.bet)
        return {"success": False, "message": "Ошибка обработки спина, ставка возвращена"}

    # Чистим истёкшие ожидания
    now_ts = time.time()
    expired_keys = [k for k, v in _pending_doubles.items() if v["expires"] < now_ts]
    for k in expired_keys:
        _pending_doubles.pop(k, None)

    # Регистрируем риск-игру только для чистого выигрыша (не near-miss, не джекпот)
    can_double = spin["win_amount"] > 0 and not spin["jackpot_won"]
    if can_double:
        _pending_doubles[uname] = {
            "amount":  spin["win_amount"],
            "expires": now_ts + 120,
        }

    asyncio.create_task(
        get_bot().check_and_unlock_achievements(uname, "casino")
    )

    return {
        "success":     True,
        "symbols":     spin["ids"],
        "win":         spin["win_amount"],
        "near_miss":   spin["near_miss_amt"],
        "mult":        spin["mult"],
        "jackpot_won": spin["jackpot_won"],
        "jackpot":     jackpot,
        "can_double":  can_double,
        "balance":     balance - req.bet + total_win,
    }


@router.get("/api/casino/jackpot")
async def get_jackpot_amount():
    """Текущий размер джекпота."""
    db = get_db()
    return {"jackpot": await _get_jackpot(db)}


@router.post("/api/casino/slots/double")
async def risk_double(username: str, choice: str):
    """Риск-игра: удвоить или потерять последний выигрыш. choice: red | black"""
    uname = sanitize_username(username)
    if not uname or not validate_username(uname):
        return {"success": False, "message": "❌ Неверный username"}
    await get_bot().touch_viewer(uname)
    pending = _pending_doubles.get(uname)

    if not pending:
        return {"success": False, "message": "Нет активного выигрыша для удвоения"}
    if time.time() > pending["expires"]:
        _pending_doubles.pop(uname, None)
        return {"success": False, "message": "Время вышло — выигрыш уже твой, рисковать нельзя"}
    if choice not in ("red", "black"):
        return {"success": False, "message": "Выбери red или black"}

    db     = get_db()
    amount = pending["amount"]
    _pending_doubles.pop(uname, None)

    actual = _rng.choice(("red", "black"))
    won    = actual == choice

    if won:
        await db.add_points(uname, amount)
        msg = f"🎯 Верно ({actual})! Выигрыш удвоен: +{amount * 2:,}💎"
    else:
        bal        = await db.get_points(uname)
        to_remove  = min(amount, bal)
        await db.remove_points(uname, to_remove)
        msg = f"💸 Не угадал, выпало {actual}. Выигрыш потерян"

    return {"success": True, "won": won, "actual": actual, "message": msg}


@router.post("/api/casino/slots/freespin")
async def use_free_spin(username: str):
    """Использовать одно бесплатное вращение (5 в день)."""
    uname = sanitize_username(username)
    if not uname or not validate_username(uname):
        return {"success": False, "message": "❌ Неверный username"}
    if not check_rate_limit(uname, 5):
        return {"success": False, "message": "⏱ Подожди немного"}
    await get_bot().touch_viewer(uname)
    db    = get_db()
    today = date.today().isoformat()

    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        row = await (await conn.execute(
            "SELECT last_claim, spins_used FROM free_spins_daily WHERE username = ?",
            (uname,)
        )).fetchone()

        if row:
            last_claim, spins_used = row
            if last_claim != today:
                spins_used = 0          # новый день — сброс
        else:
            spins_used = 0

        if spins_used >= FREE_SPINS_COUNT:
            await conn.execute("ROLLBACK")
            return {
                "success": False,
                "message": f"Бесплатные вращения закончились. Следующие — завтра!",
                "remaining": 0,
            }

        new_used = spins_used + 1
        await conn.execute("""
            INSERT OR REPLACE INTO free_spins_daily (username, last_claim, spins_used)
            VALUES (?, ?, ?)
        """, (uname, today, new_used))
        await conn.execute("COMMIT")

    jackpot   = await _get_jackpot(db)
    spin      = _calc_spin(FREE_SPINS_BET, jackpot)
    total_win = spin["win_amount"] + spin["near_miss_amt"]
    remaining = FREE_SPINS_COUNT - new_used

    if spin["jackpot_won"]:
        await _reset_jackpot(db)
        bot = get_bot()
        asyncio.create_task(bot.send_message(
            f"🎰👑 ДЖЕКПОТ на фриспине! @{uname} сорвал куш {spin['win_amount']:,}💎!"
        ))
    elif spin["mult"] == 75:
        # Тройка амулета — редкий win и на фриспине
        asyncio.create_task(get_bot().send_message(
            f"🔮🔮🔮 @{uname} собрал три амулета на фриспине — {spin['win_amount']:,}💎! (×75)"
        ))

    if total_win > 0:
        await db.add_points(uname, total_win)

    win_str = f"+{total_win:,}💎" if total_win > 0 else "Не повезло"
    return {
        "success":   True,
        "symbols":   spin["ids"],
        "win":       total_win,
        "near_miss": spin["near_miss_amt"],
        "mult":      spin["mult"],
        "remaining": remaining,
        "message":   f"🎰 Фриспин! {win_str} (осталось: {remaining})",
    }


@router.get("/api/casino/slots/freespin/status")
async def freespin_status(username: str):
    """Сколько фриспинов осталось сегодня."""
    db    = get_db()
    uname = username.lower()
    today = date.today().isoformat()

    async with db._connect() as conn:
        row = await (await conn.execute(
            "SELECT last_claim, spins_used FROM free_spins_daily WHERE username = ?",
            (uname,)
        )).fetchone()

    if not row or row[0] != today:
        remaining = FREE_SPINS_COUNT
    else:
        remaining = max(0, FREE_SPINS_COUNT - row[1])

    return {"remaining": remaining, "total": FREE_SPINS_COUNT}
