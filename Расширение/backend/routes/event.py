"""
routes/event.py — рулекцион (копилка + рулетка/аукцион) и админ-управление ивентами.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from config import ECONOMY_CONFIG, EVENT_CONFIG, sanitize_username
from dependencies import (
    get_bot,
    get_db,
    get_last_event_winner,
    require_admin,
    require_jwt_user,
    require_stream_live,
    set_last_event_winner,
)

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch — открой расширение и войди"}

router = APIRouter()


@router.get("/api/event/status")
async def event_status():
    """Полный статус рулекциона — копилка, активный ивент, условия, последний победитель"""
    bot = get_bot()
    em  = bot.event_manager
    try:
        if em.active_event and em.get_time_left() <= 0:
            try:
                winner, message, prize = await em.end_event()
                if winner:
                    set_last_event_winner({
                        "has_winner": True,
                        "winner":     winner,
                        "message":    message,
                        "prize":      prize,
                        "ended_at":   datetime.now().isoformat(),
                    })
            except Exception as e:
                print(f"Ошибка при завершении ивента: {e}")

        can_start, reason = em.can_start_event()
        pool          = em.event_pool or 0
        # Источник правды — EVENT_CONFIG (тот же, что читает event_manager.can_start_event).
        # Раньше здесь был хардкод 100000 и ECONOMY_CONFIG["min_event_donations"] — фронт
        # показывал один прогресс, а сервер проверял по другому ключу.
        min_points    = EVENT_CONFIG["min_points_for_event"]
        min_donations = EVENT_CONFIG["min_donations_for_event"]

        result = {
            "pool":               pool,
            "pool_pct_points":    min(100, round(pool / min_points * 100, 1)),
            "pool_pct_donations": min(100, round((em.donation_total or 0) / min_donations * 100, 1)),
            "min_points":         min_points,
            "min_donations":      min_donations,
            "donation_total":     em.donation_total or 0,
            "can_start":          can_start,
            "can_start_reason":   reason,
            "top_contributors":   em.get_top_contributors(5) or [],
            "active_event":       None,
            "last_winner":        get_last_event_winner(),
        }

        if em.active_event:
            ev        = em.active_event
            bids_map  = ev.get("bids", {}) or {}
            time_left = max(0, (ev["end_time"] - datetime.now()).total_seconds())
            top_bids  = em.get_top_bidders(10) or []
            total_bids = sum(bids_map.values()) if bids_map else 0
            bids_with_chance = []
            for bid in top_bids:
                user   = bid["username"]
                amount = bid["amount"]
                chance = round(amount / total_bids * 100, 1) if total_bids > 0 else 0
                bids_with_chance.append({"username": user, "amount": amount, "chance": chance})

            result["active_event"] = {
                "id":        ev["id"],
                "type":      ev["type"],
                "type_name": "🎲 Рулетка" if ev["type"] == "roulette" else "⚖️ Аукцион",
                "type_desc": ("Чем больше очков вкинул — тем выше шанс!"
                               if ev["type"] == "roulette"
                               else "Побеждает тот, кто вкинул больше всех!"),
                "prize":        ev.get("prize", {"name": "Приз", "value": 0}),
                "time_left":    round(time_left),
                "time_left_fmt": f"{int(time_left//60)}:{int(time_left%60):02d}",
                "total_pool":   total_bids,
                "bids":         bids_with_chance,
                "participants": len(bids_map),
            }

        return result
    except Exception as e:
        print(f"event_status error: {e}")
        return {
            "pool":               0,
            "pool_pct_points":    0,
            "pool_pct_donations": 0,
            "min_points":         EVENT_CONFIG["min_points_for_event"],
            "min_donations":      EVENT_CONFIG["min_donations_for_event"],
            "donation_total":     0,
            "can_start":          False,
            "can_start_reason":   "event_status_error",
            "top_contributors":   [],
            "active_event":       None,
            "last_winner":        get_last_event_winner(),
            "error":              "event_status_failed",
        }


@router.post("/api/event/ack-winner")
async def ack_winner():
    """Клиент подтверждает получение информации о победителе"""
    set_last_event_winner(None)
    return {"success": True}


@router.post("/api/event/contribute")
async def event_contribute(request: Request):
    """Закинуть очки в копилку рулекциона"""
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    data   = await request.json()
    amount = int(data.get("amount", 0))

    if amount < ECONOMY_CONFIG["min_event_contribute"]:
        return {"success": False, "message": f"Минимум {ECONOMY_CONFIG['min_event_contribute']}💎"}

    db     = get_db()
    bot    = get_bot()
    await bot.touch_viewer(username)
    points = await db.get_points(username)
    if points < amount:
        return {"success": False, "message": f"Недостаточно очков! У тебя {points}💎"}

    removed = await db.remove_points(username, amount)
    if not removed:
        return {"success": False, "message": "Не удалось списать очки, попробуй ещё раз"}

    pool, msg    = await bot.event_manager.add_to_pool(username, amount)
    auto_started = bot.event_manager.active_event is not None
    left_points  = max(0, 100000 - pool)

    # Большой взнос — мотивирует других скидываться (пиар копилки в чате).
    # Порог 5000💎 — редко, но стабильно.
    if amount >= 5000:
        import asyncio as _asyncio
        min_points = EVENT_CONFIG["min_points_for_event"]
        pct = min(100, round(pool / min_points * 100))
        _asyncio.create_task(bot.send_message(
            f"💰🔥 @{username} закинул {amount:,}💎 в копилку рулекциона! "
            f"Копилка: {pool:,}/{min_points:,}💎 ({pct}%)"
        ))

    return {
        "success":       True,
        "message":       f"✅ +{amount}💎 в копилку! Итого: {pool:,}💎",
        "pool":          pool,
        "left_points":   left_points,
        "event_started": auto_started,
    }


@router.post("/api/event/bid")
async def event_bid(request: Request):
    """Сделать ставку в активном рулекционе"""
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    data   = await request.json()
    amount = int(data.get("amount", 0))
    bot = get_bot()
    await bot.touch_viewer(username)
    success, message = await bot.event_manager.place_bid(username, amount)
    return {"success": success, "message": message}


# ── Admin event endpoints ─────────────────────────────────────────────────────

@router.post("/api/admin/event/start")
async def admin_event_start(_admin: str = Depends(require_admin)):
    bot = get_bot()
    if bot.event_manager.active_event:
        return {"success": False, "message": "Ивент уже активен"}
    ev        = await bot.event_manager.start_event()
    type_name = "🎲 Рулетку" if ev["type"] == "roulette" else "⚖️ Аукцион"
    return {"success": True, "message": f"Ивент запущен! Тип: {type_name}, Приз: {ev['prize']['name']}"}


@router.post("/api/admin/event/stop")
async def admin_event_stop(_admin: str = Depends(require_admin)):
    bot = get_bot()
    if not bot.event_manager.active_event:
        return {"success": False, "message": "Нет активного ивента"}
    winner, message, prize = await bot.event_manager.end_event()
    if winner:
        set_last_event_winner({
            "has_winner": True,
            "winner":     winner,
            "message":    message,
            "prize":      prize,
            "ended_at":   datetime.now().isoformat(),
        })
        return {"success": True, "message": f"Ивент остановлен. Победитель: {winner}"}
    return {"success": True, "message": "Ивент остановлен. Участников не было"}


@router.post("/api/admin/event/force-start")
async def admin_force_start(_admin: str = Depends(require_admin)):
    """Принудительный запуск ивента"""
    bot = get_bot()
    if bot.event_manager.active_event:
        return {"success": False, "message": "Ивент уже активен"}
    ev         = await bot.event_manager.start_event()
    type_name  = "🎲 Рулетку" if ev["type"] == "roulette" else "⚖️ Аукцион"
    prize_name = ev["prize"]["name"]
    try:
        await bot.send_message(f"🎡 АДМИН ЗАПУСТИЛ РУЛЕКЦИОН! {type_name}! Приз: {prize_name}!")
    except Exception:
        pass
    return {"success": True, "message": f"Ивент запущен! Тип: {type_name}, Приз: {prize_name}"}


@router.post("/api/admin/event/force-end")
async def admin_force_end(_admin: str = Depends(require_admin)):
    """Принудительное завершение ивента"""
    bot = get_bot()
    if not bot.event_manager.active_event:
        return {"success": False, "message": "Нет активного ивента"}
    winner, message, prize = await bot.event_manager.end_event()
    if winner:
        set_last_event_winner({
            "has_winner": True,
            "winner":     winner,
            "message":    message,
            "prize":      prize,
            "ended_at":   datetime.now().isoformat(),
        })
        try:
            await bot.send_message(f"🎉 АДМИН ЗАВЕРШИЛ ИВЕНТ! {message} Приз: {prize['name']}!")
        except Exception:
            pass
        return {"success": True, "message": f"Ивент завершен! Победитель: {winner}"}
    return {"success": False, "message": "Никто не участвовал в ивенте"}
