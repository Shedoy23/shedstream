"""
Sprint 5.29 / BLT-parity #6 Phase B — Auction system.

Viewer выставляет custom item на аукцион с reserve + countdown. Другие
viewers бидят крустиками; outbid → автоматический refund. Истёк timer:
  - Был bid ≥ reserve → highest wins, item transfers, seller crustic'и.
  - Не было bids reaching reserve → cancel, item стает обратно seller'у.

Background loop в main.py (`_auctions_resolve_loop`) каждые 30s scan'ит
active auctions с ends_at < now → resolve.

Endpoints:
  GET  /api/bannerlord/auctions — list active в channel
  POST /api/bannerlord/auctions/create — выставить item (seller)
  POST /api/bannerlord/auctions/bid — bid (bidder, crustiks)
  POST /api/bannerlord/auctions/cancel — cancel (seller, если no bids)

Pricing:
  - Auction creation FREE (никакой комиссии за выставление)
  - На resolve seller получает 90% от winning bid, 10% — channel "house cut"
    (TODO: куда деть house cut — на счёт стримера? burn?). Пока burn.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List

from fastapi import APIRouter, Request

from dependencies import get_db, require_jwt_user

router = APIRouter()
log = logging.getLogger("rimlink.bannerlord.auctions")


MIN_RESERVE_PRICE = 100      # 100💎 — anti-spam, нельзя выставлять за бесценок
MAX_RESERVE_PRICE = 100_000  # 100K💎 — sanity cap
DEFAULT_DURATION_SEC = 300   # 5 min — стандартная длительность auction
MAX_DURATION_SEC = 1800      # 30 min — cap
BID_MIN_INCREMENT_PCT = 5    # next bid должен быть ≥ current × 1.05
HOUSE_CUT_PCT = 10           # 10% commission seller'у вычитается


@router.get("/api/bannerlord/auctions")
async def list_auctions(request: Request):
    """Список активных аукционов в channel + детали items."""
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "auth required"}
    username, channel_id = auth

    now_ts = int(time.time())
    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT a.id, a.seller_username, a.custom_item_id, "
            "       a.reserve_price, a.current_bid, a.current_bidder, "
            "       a.started_at, a.ends_at, a.status, "
            "       ci.custom_name, ci.icon, ci.rarity, ci.base_type, ci.tier "
            "FROM bannerlord_auctions a "
            "LEFT JOIN bannerlord_custom_items ci ON a.custom_item_id = ci.id "
            "WHERE a.channel_id=? AND a.status='active' "
            "ORDER BY a.ends_at ASC LIMIT 50",
            (channel_id,))
        rows = await cur.fetchall()

    from routes.bannerlord_custom_items import RARITY_COLORS
    auctions = []
    for r in rows:
        # parse ends_at — SQLite stored as ISO string
        ends_at_str = r[7]
        try:
            from datetime import datetime
            ends_at_dt = datetime.fromisoformat(ends_at_str.replace(" ", "T"))
            ends_at_unix = int(ends_at_dt.timestamp())
        except Exception:
            ends_at_unix = now_ts
        remaining = max(0, ends_at_unix - now_ts)
        auctions.append({
            "id":              r[0],
            "seller":          r[1],
            "custom_item_id":  r[2],
            "reserve_price":   r[3],
            "current_bid":     r[4],
            "current_bidder":  r[5],
            "started_at":      r[6],
            "ends_at":         r[7],
            "remaining_s":     remaining,
            "status":          r[8],
            "item_name":       r[9],
            "item_icon":       r[10],
            "item_rarity":     r[11],
            "item_color":      RARITY_COLORS.get(r[11] or "common", "#adadb8"),
            "item_base_type":  r[12],
            "item_tier":       r[13],
            "is_mine":         (r[1] == username),
        })
    return {"success": True, "auctions": auctions, "my_username": username}


@router.post("/api/bannerlord/auctions/create")
async def create_auction(request: Request):
    """Выставить custom item на аукцион. Item должен быть owned by seller.

    Body: {custom_item_id, reserve_price, duration_sec (optional, default 300)}
    """
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "auth required"}
    username, channel_id = auth

    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        item_id = int(body.get("custom_item_id") or 0)
        reserve = int(body.get("reserve_price") or 0)
        duration = int(body.get("duration_sec") or DEFAULT_DURATION_SEC)
    except (TypeError, ValueError):
        return {"success": False, "message": "invalid input"}

    if item_id <= 0:
        return {"success": False, "message": "custom_item_id required"}
    if reserve < MIN_RESERVE_PRICE or reserve > MAX_RESERVE_PRICE:
        return {
            "success": False,
            "message": f"Резерв от {MIN_RESERVE_PRICE} до {MAX_RESERVE_PRICE}💎",
        }
    duration = max(60, min(MAX_DURATION_SEC, duration))

    async with get_db()._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            # Verify ownership
            cur = await conn.execute(
                "SELECT 1 FROM bannerlord_custom_items "
                "WHERE id=? AND channel_id=? AND owner_username=?",
                (item_id, channel_id, username))
            if not await cur.fetchone():
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Item не найден или не твой"}

            # Check item is not already in active auction
            cur = await conn.execute(
                "SELECT 1 FROM bannerlord_auctions "
                "WHERE custom_item_id=? AND status='active'",
                (item_id,))
            if await cur.fetchone():
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Item уже на аукционе"}

            # Insert auction. SQLite datetime для ends_at — relative arithmetic.
            cur = await conn.execute(
                "INSERT INTO bannerlord_auctions "
                "(channel_id, seller_username, custom_item_id, reserve_price, "
                " ends_at) "
                "VALUES (?, ?, ?, ?, datetime('now', ?)) RETURNING id",
                (channel_id, username, item_id, reserve, f"+{duration} seconds"))
            row = await cur.fetchone()
            await conn.commit()
            auction_id = row[0] if row else 0
        except Exception as ex:
            await conn.execute("ROLLBACK")
            log.exception("create_auction failed: %s", ex)
            return {"success": False, "message": f"server error: {ex}"}

    log.info("[bannerlord AUCTION CREATE] ch=%s seller=%s item=%s reserve=%s dur=%ss → id=%s",
             channel_id, username, item_id, reserve, duration, auction_id)
    return {
        "success": True,
        "message": f"⚖ Аукцион создан — резерв {reserve}💎, {duration//60} мин",
        "auction_id": auction_id,
    }


@router.post("/api/bannerlord/auctions/bid")
async def bid_auction(request: Request):
    """Place bid on auction. Amount списывается immediately; outbid → refund.

    Body: {auction_id, amount}
    """
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "auth required"}
    username, channel_id = auth

    try:
        body = await request.json()
        auction_id = int(body.get("auction_id") or 0)
        amount = int(body.get("amount") or 0)
    except (TypeError, ValueError):
        return {"success": False, "message": "invalid input"}
    if auction_id <= 0 or amount <= 0:
        return {"success": False, "message": "auction_id + amount required"}

    async with get_db()._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            # Load auction (must be active, not seller's own)
            cur = await conn.execute(
                "SELECT seller_username, reserve_price, current_bid, current_bidder, "
                "       ends_at, status "
                "FROM bannerlord_auctions "
                "WHERE id=? AND channel_id=?",
                (auction_id, channel_id))
            row = await cur.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Аукцион не найден"}
            seller, reserve, current_bid, current_bidder, ends_at, status = row

            if status != "active":
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Аукцион уже закрыт"}
            if seller == username:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Нельзя бидить на собственный лот"}
            # Check timer expired (resolver loop catches это позже, но guard здесь)
            cur = await conn.execute("SELECT datetime('now') < ?", (ends_at,))
            r = await cur.fetchone()
            if not r or not r[0]:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Аукцион истёк"}

            # Validate bid amount
            min_bid = max(reserve, int(current_bid * (100 + BID_MIN_INCREMENT_PCT) / 100))
            if current_bid == 0:
                min_bid = reserve   # первый bid должен достичь reserve
            if amount < min_bid:
                await conn.execute("ROLLBACK")
                return {
                    "success": False,
                    "message": f"Минимальный bid: {min_bid}💎",
                }

            # Check bidder has enough crustics
            cur = await conn.execute(
                "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                (channel_id, username))
            r = await cur.fetchone()
            balance = r[0] if r else 0
            if balance < amount:
                await conn.execute("ROLLBACK")
                return {
                    "success": False,
                    "message": f"Не хватает крустиков ({balance} < {amount})",
                }

            # Atomic: refund previous highest bidder, charge new bidder.
            if current_bidder and current_bid > 0:
                # Refund previous bidder
                await conn.execute(
                    # currency-ok: возврат ставки предыдущему лидеру. Файл ОТКЛЮЧЁН 29.07 (роутер не подключён, эндпоинты 404).
                    "UPDATE viewers SET points = points + ? "
                    "WHERE channel_id=? AND username=?",
                    (current_bid, channel_id, current_bidder))
                # Mark prev bid as refunded
                await conn.execute(
                    "UPDATE bannerlord_auction_bids SET refunded=1 "
                    "WHERE auction_id=? AND bidder_username=? AND amount=? AND refunded=0",
                    (auction_id, current_bidder, current_bid))

            # Charge new bidder
            await conn.execute(
                "UPDATE viewers SET points = points - ? "
                "WHERE channel_id=? AND username=?",
                (amount, channel_id, username))
            # Insert new bid record
            await conn.execute(
                "INSERT INTO bannerlord_auction_bids "
                "(auction_id, bidder_username, amount) VALUES (?, ?, ?)",
                (auction_id, username, amount))
            # Update auction state
            await conn.execute(
                "UPDATE bannerlord_auctions SET current_bid=?, current_bidder=? "
                "WHERE id=?",
                (amount, username, auction_id))

            # Sprint 5.32 (BLT-parity M10) — anti-snipe extension.
            # Если bid пришёл в окне последних 10 секунд до ends_at — продлеваем
            # таймер на +30s. Защита от "last-second sniping" — бот / late
            # bidder который ждёт чтобы поставить ставку за 1s до конца и
            # отбить лот у нормальных bidder'ов которые не успеют ответить.
            # Eternal extend защищён внутри resolver loop'а: если bidder перестал
            # пушить, через 30s ends_at пройдёт и обычный auction-resolve сработает.
            cur_ext = await conn.execute(
                "SELECT (julianday(ends_at) - julianday('now')) * 86400 "
                "FROM bannerlord_auctions WHERE id=?",
                (auction_id,))
            ext_row = await cur_ext.fetchone()
            seconds_left = (ext_row[0] if ext_row else None) or 0
            extended = False
            if 0 < seconds_left < 10:
                await conn.execute(
                    "UPDATE bannerlord_auctions "
                    "SET ends_at = datetime('now', '+30 seconds') "
                    "WHERE id=?",
                    (auction_id,))
                extended = True
                log.info("[bannerlord AUCTION ANTI-SNIPE] auction=%s ch=%s "
                         "ends_at extended +30s (was %.1fs left, bid by @%s)",
                         auction_id, channel_id, seconds_left, username)

            await conn.commit()
        except Exception as ex:
            try: await conn.execute("ROLLBACK")
            except Exception: pass
            log.exception("bid_auction failed: %s", ex)
            return {"success": False, "message": f"server error: {ex}"}

    log.info("[bannerlord AUCTION BID] ch=%s auction=%s bidder=%s amount=%s "
             "(prev=%s by @%s)",
             channel_id, auction_id, username, amount, current_bid, current_bidder)
    return {
        "success": True,
        "message": f"⚖ Bid принят: {amount}💎",
        "your_bid": amount,
    }


@router.post("/api/bannerlord/auctions/cancel")
async def cancel_auction(request: Request):
    """Seller cancels auction. Allowed только если no bids ещё (бы то нечестно
    кэнсельнуть после бидов)."""
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "auth required"}
    username, channel_id = auth

    try:
        body = await request.json()
        auction_id = int(body.get("auction_id") or 0)
    except (TypeError, ValueError):
        return {"success": False, "message": "invalid"}
    if auction_id <= 0:
        return {"success": False, "message": "auction_id required"}

    async with get_db()._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await conn.execute(
                "SELECT seller_username, current_bid, status, reserve_price "
                "FROM bannerlord_auctions WHERE id=? AND channel_id=?",
                (auction_id, channel_id))
            row = await cur.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Не найден"}
            seller, current_bid, status, reserve_price = row
            current_bid = current_bid or 0
            reserve_price = reserve_price or 0
            if seller != username:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Не твой аукцион"}
            if status != "active":
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Уже закрыт"}

            # Sprint 5.32 (BLT-parity M11) — раньше cancel блокировался при
            # ЛЮБОМ bid (current_bid > 0). Теперь: блокируем только если bid
            # достиг reserve_price — тогда аукцион «состоялся», отменять
            # нечестно. Если ни одна ставка не достигла reserve → seller
            # может cancel + всем bidder'ам refund'им их points.
            if current_bid >= reserve_price and reserve_price > 0:
                await conn.execute("ROLLBACK")
                return {
                    "success": False,
                    "message": "Ставка уже достигла резерва — отменить нельзя",
                }

            # Refund всем outstanding bidder'ам (refunded=0). Их points
            # были вычтены при bid'е. Возвращаем.
            cur_refund = await conn.execute(
                "SELECT bidder, amount FROM bannerlord_auction_bids "
                "WHERE auction_id=? AND refunded=0",
                (auction_id,))
            refund_rows = await cur_refund.fetchall()
            refunded_count = 0
            for bidder, amount in refund_rows:
                if amount and amount > 0:
                    await conn.execute(
                        # currency-ok: возврат ставки при отмене лота. Файл ОТКЛЮЧЁН 29.07.
                        "UPDATE viewers SET points = points + ? "
                        "WHERE channel_id=? AND username=?",
                        (amount, channel_id, bidder))
                    refunded_count += 1
            if refund_rows:
                await conn.execute(
                    "UPDATE bannerlord_auction_bids SET refunded=1 "
                    "WHERE auction_id=? AND refunded=0",
                    (auction_id,))

            await conn.execute(
                "UPDATE bannerlord_auctions SET status='cancelled', "
                "resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                (auction_id,))
            await conn.commit()
            if refunded_count > 0:
                log.info("[bannerlord AUCTION CANCEL] auction=%s ch=%s "
                         "refunded %s bidders (below reserve)",
                         auction_id, channel_id, refunded_count)
        except Exception as ex:
            try: await conn.execute("ROLLBACK")
            except Exception: pass
            log.exception("cancel_auction failed: %s", ex)
            return {"success": False, "message": "server error"}

    log.info("[bannerlord AUCTION CANCEL] ch=%s auction=%s seller=%s",
             channel_id, auction_id, username)
    return {"success": True, "message": "Аукцион отменён"}


# ── Background resolver ────────────────────────────────────────────────────

async def _resolve_one_auction(conn, auction_id: int) -> str:
    """Resolve единичный auction. Returns status string для логирования.
    Не делает commit — caller (loop) делает batch commit."""
    cur = await conn.execute(
        "SELECT channel_id, seller_username, custom_item_id, "
        "       reserve_price, current_bid, current_bidder "
        "FROM bannerlord_auctions WHERE id=? AND status='active'",
        (auction_id,))
    row = await cur.fetchone()
    if not row:
        return "not_found_or_not_active"
    channel_id, seller, item_id, reserve, current_bid, current_bidder = row

    if not current_bidder or current_bid < reserve:
        # No qualifying bids — refund last bid (if any below reserve)
        if current_bidder and current_bid > 0:
            await conn.execute(
                # currency-ok: возврат ставки при закрытии лота без победителя. Файл ОТКЛЮЧЁН 29.07.
                "UPDATE viewers SET points = points + ? "
                "WHERE channel_id=? AND username=?",
                (current_bid, channel_id, current_bidder))
            await conn.execute(
                "UPDATE bannerlord_auction_bids SET refunded=1 "
                "WHERE auction_id=? AND bidder_username=? AND amount=? AND refunded=0",
                (auction_id, current_bidder, current_bid))
        await conn.execute(
            "UPDATE bannerlord_auctions SET status='expired_no_bids', "
            "resolved_at=CURRENT_TIMESTAMP WHERE id=?",
            (auction_id,))
        return "expired_no_bids"

    # Successful sale — transfer item ownership + seller получает 90% bid.
    seller_payout = int(current_bid * (100 - HOUSE_CUT_PCT) / 100)
    await conn.execute(
        # currency-ok: ВЫПЛАТА ПРОДАВЦУ — это НЕ возврат, а перевод крустиков между зрителями. Нарушает границу валют. Файл отключён 29.07; если механику вернут, правило пересмотреть ЯВНО (DEFERRED §C0-sexdecies).
        "UPDATE viewers SET points = points + ? "
        "WHERE channel_id=? AND username=?",
        (seller_payout, channel_id, seller))
    await conn.execute(
        "UPDATE bannerlord_custom_items SET owner_username=? "
        "WHERE id=? AND channel_id=?",
        (current_bidder, item_id, channel_id))
    await conn.execute(
        "UPDATE bannerlord_auctions SET status='sold', "
        "resolved_at=CURRENT_TIMESTAMP WHERE id=?",
        (auction_id,))
    log.info("[bannerlord AUCTION RESOLVED] ch=%s auction=%s SOLD item=%s "
             "@%s → @%s for %s💎 (seller payout %s, house cut %s)",
             channel_id, auction_id, item_id, seller, current_bidder, current_bid,
             seller_payout, current_bid - seller_payout)
    return f"sold:{current_bid}"


async def auctions_resolve_loop():
    """Background task — caller'ом main.py при startup. Каждые 30 сек scan'ит
    active auctions с истёкшим timer и resolve'ит."""
    import asyncio
    print("⚖ Auctions resolve loop started (interval=30s)")
    while True:
        try:
            await asyncio.sleep(30)
            async with get_db()._connect() as conn:
                cur = await conn.execute(
                    "SELECT id FROM bannerlord_auctions "
                    "WHERE status='active' AND datetime('now') >= ends_at"  # tenant-ok: background resolve loop scans all channels; _resolve_one_auction re-scopes by row channel_id
                )
                rows = await cur.fetchall()
                if not rows:
                    continue
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    for r in rows:
                        result = await _resolve_one_auction(conn, r[0])
                        print(f"⚖ Auction {r[0]}: {result}")
                    await conn.commit()
                except Exception as ex:
                    try: await conn.execute("ROLLBACK")
                    except Exception: pass
                    log.exception("auctions resolve batch failed: %s", ex)
        except Exception as ex:
            print(f"❌ Auctions resolve loop error: {type(ex).__name__}: {ex}")
