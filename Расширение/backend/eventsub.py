"""
backend/eventsub.py — Twitch EventSub webhook handler (Phase A).

Заменяет inline-обработчик в main.py:eventsub_channel_points. Generic dispatch
по `subscription.type`, общая dedupe-гарантия через таблицу eventsub_seen.

Поддерживаемые типы (Phase A):
  - channel.channel_points_custom_reward_redemption.add — обмен баллов канала
  - stream.online                                       — старт стрима
  - stream.offline                                      — конец стрима

Future (Phase B):
  - channel.cheer        — bits (для PETS_BITS_REQUIRED=true)
  - channel.subscribe    — подписки
  - channel.raid         — raid-нотификации

Security model (см. SECURITY_AUDIT_2026-04-30.md + threat model в чате):
  1. HMAC-SHA256 signature verify через compare_digest (constant-time)
  2. Timestamp replay-window 10 мин (Twitch retry-окно — 1 час, оставляем margin)
  3. Per-message dedupe через eventsub_seen (24h TTL)
  4. broadcaster_user_id ДОЛЖЕН быть зарегистрированным каналом (иначе 200
     ignored — не 4xx чтобы Twitch не убил подписку)
  5. Handler exceptions caught — никогда не пробрасываем (иначе 5xx → Twitch
     retry бесконечный)
  6. Username sanitize+validate перед использованием (defense in depth)

Идемпотентность: двойная защита для денежных handler'ов (channel_points):
  - eventsub_seen ловит retry того же webhook (message_id)
  - channel_points_log UNIQUE по (channel_id, twitch_redemption_id) — защита
    при переносе БД или ре-подписке (msg_id меняется, redemption_id остаётся)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json
import logging
import time as _time
from datetime import datetime
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from config import sanitize_username, validate_username
from dependencies import (
    get_bot,
    get_db,
    is_channel_registered,
    set_request_channel_id,
)

logger = logging.getLogger("rimlink.eventsub")

# Twitch retry-окно ~1 час (5 попыток с back-off). 10 мин — достаточный
# margin для clock-skew и legitimate latency, отсекает старые replay'и.
REPLAY_WINDOW_SEC = 600

# TTL для eventsub_seen. После TTL запись чистится cleanup_seen_loop'ом.
# Twitch не повторяет события старше своего retry-окна, так что после
# DEDUPE_TTL_SEC duplicate уже невозможен.
DEDUPE_TTL_SEC = 24 * 3600

router = APIRouter()


# ─── Handler registry ────────────────────────────────────────────────────────

HandlerFn = Callable[[dict, int], Awaitable[None]]
_handlers: dict[str, HandlerFn] = {}


def handler(event_type: str):
    """Регистрирует функцию как handler для конкретного EventSub-типа.

    Signature: `async def f(event: dict, channel_id: int) -> None`

    Errors внутри handler'а ловятся внешним try/except в eventsub_webhook —
    не пробрасываем наружу, иначе Twitch получит 5xx и запустит retry-цикл.
    Идемпотентность гарантируется eventsub_seen ДО вызова handler'а.
    """
    def deco(fn: HandlerFn) -> HandlerFn:
        _handlers[event_type] = fn
        return fn
    return deco


# ─── Verify + dedupe helpers ─────────────────────────────────────────────────

def _verify_signature(
    body: bytes, msg_id: str, msg_ts: str, msg_sig: str, secret: bytes
) -> bool:
    """HMAC-SHA256 verify по Twitch EventSub spec.

    Канон: hmac_sha256(secret, msg_id + msg_ts + body), prefix 'sha256='.
    Constant-time compare через hmac.compare_digest.
    """
    if not msg_sig or not msg_id or not msg_ts or not secret:
        return False
    expected = "sha256=" + _hmac.new(
        secret, (msg_id + msg_ts).encode() + body, hashlib.sha256
    ).hexdigest()
    return _hmac.compare_digest(expected, msg_sig)


def _check_replay_window(msg_ts: str) -> Optional[str]:
    """Replay-window check. None если OK, error-string иначе."""
    if not msg_ts:
        return "missing timestamp"
    try:
        msg_dt = datetime.fromisoformat(msg_ts.replace("Z", "+00:00"))
        age = abs(_time.time() - msg_dt.timestamp())
        if age > REPLAY_WINDOW_SEC:
            return f"timestamp out of window ({int(age)}s)"
    except (ValueError, TypeError) as e:
        return f"bad timestamp: {type(e).__name__}"
    return None


async def _check_and_record_dedupe(
    message_id: str, channel_id: int, event_type: str
) -> bool:
    """Atomic dedupe gate через INSERT OR IGNORE.

    Returns:
        True  — новое сообщение, обрабатываем
        False — duplicate, отвечаем 200 без побочных эффектов

    Edge: пустой message_id → пускаем (defensive — Twitch не должен слать
    notification без header, но если случилось, лучше обработать чем drop'нуть).
    """
    if not message_id:
        logger.warning(
            "eventsub: empty message_id for type=%s ch=%s",
            event_type, channel_id,
        )
        return True
    db = get_db()
    async with db._connect() as conn:
        cursor = await conn.execute(
            "INSERT OR IGNORE INTO eventsub_seen "
            "(message_id, channel_id, event_type, seen_at) "
            "VALUES (?, ?, ?, ?)",
            (message_id, channel_id, event_type, _time.time()),
        )
        await conn.commit()
        return cursor.rowcount == 1


# ─── Main webhook endpoint ───────────────────────────────────────────────────


async def _process_eventsub_request(request: Request):
    """Общая логика для всех URL-aliases (см. router definitions ниже)."""
    body_bytes = await request.body()
    headers = request.headers
    msg_id = headers.get("Twitch-Eventsub-Message-Id", "")
    msg_ts = headers.get("Twitch-Eventsub-Message-Timestamp", "")
    msg_sig = headers.get("Twitch-Eventsub-Message-Signature", "")
    msg_type = headers.get("Twitch-Eventsub-Message-Type", "")

    from config import CHANNEL_POINTS_CONFIG
    secret = CHANNEL_POINTS_CONFIG.get("eventsub_secret", "").encode()
    if not secret:
        logger.error("eventsub: EVENTSUB_SECRET не задан в .env")
        return JSONResponse({"error": "server misconfigured"}, status_code=500)

    # 1. Signature verify
    if not _verify_signature(body_bytes, msg_id, msg_ts, msg_sig, secret):
        logger.warning(
            "eventsub: invalid signature msg_id=%s",
            (msg_id[:16] + "…") if msg_id else "?",
        )
        return JSONResponse({"error": "invalid signature"}, status_code=403)

    # 2. Replay-window
    err = _check_replay_window(msg_ts)
    if err:
        logger.warning("eventsub: %s msg_id=%s", err, msg_id[:16])
        return JSONResponse({"error": err}, status_code=403)

    # Parse body
    try:
        data = json.loads(body_bytes)
    except json.JSONDecodeError as e:
        logger.warning("eventsub: bad JSON: %s", e)
        return JSONResponse({"error": "bad json"}, status_code=400)

    # 3a. Webhook verification challenge
    if msg_type == "webhook_callback_verification":
        challenge = data.get("challenge", "")
        sub_type = data.get("subscription", {}).get("type", "?")
        logger.info("eventsub: callback verification accepted (type=%s)", sub_type)
        return PlainTextResponse(content=challenge)

    # 3b. Subscription revocation — Twitch удалил подписку
    if msg_type == "revocation":
        sub = data.get("subscription", {})
        logger.warning(
            "eventsub: subscription revoked type=%s status=%s",
            sub.get("type"), sub.get("status"),
        )
        return JSONResponse({"status": "ok"})

    # 3c. Notification (основной случай)
    if msg_type != "notification":
        logger.warning("eventsub: unknown message type '%s'", msg_type)
        return JSONResponse({"status": "ignored"})

    event = data.get("event", {})
    subscription = data.get("subscription", {})
    event_type = subscription.get("type", "")

    # 4. Resolve broadcaster_user_id из event. Для raid типа поле называется
    # to_broadcaster_user_id (мы — таргет рейда), для остальных — обычное
    # broadcaster_user_id.
    raw_bid = (
        event.get("broadcaster_user_id")
        or event.get("to_broadcaster_user_id")
    )
    try:
        channel_id = int(raw_bid) if raw_bid else 0
    except (TypeError, ValueError):
        channel_id = 0
    if channel_id <= 0:
        logger.warning(
            "eventsub: bad broadcaster_user_id '%s' type=%s",
            raw_bid, event_type,
        )
        return JSONResponse({"status": "ignored"})

    # 5. Multi-tenant gate: канал должен быть зарегистрирован. Незарегистрированный
    # = либо leak от чужого webhook (атака), либо канал отписался но Twitch ещё
    # не успел revoke. В обоих случаях 200 ignored (не 4xx — Twitch не должен
    # рассматривать как fail и убивать подписку).
    if not is_channel_registered(channel_id):
        logger.info(
            "eventsub: channel %s not registered, ignoring type=%s",
            channel_id, event_type,
        )
        return JSONResponse({"status": "ignored"})

    # 6. Multi-tenant context — downstream db-helpers увидят channel_id
    # через ContextVar.
    set_request_channel_id(channel_id)

    # 7. Dedupe gate (ПОСЛЕ всех validations — не засоряем таблицу мусором).
    is_new = await _check_and_record_dedupe(msg_id, channel_id, event_type)
    if not is_new:
        logger.debug(
            "eventsub: duplicate msg_id=%s type=%s ch=%s",
            msg_id[:16], event_type, channel_id,
        )
        return JSONResponse({"status": "duplicate"})

    # 8. Dispatch
    fn = _handlers.get(event_type)
    if fn is None:
        logger.info(
            "eventsub: no handler for type=%s ch=%s ignored",
            event_type, channel_id,
        )
        return JSONResponse({"status": "ignored"})

    try:
        await fn(event, channel_id)
    except Exception as e:
        # CRITICAL: НЕ пробрасываем — Twitch при 5xx запускает retry-цикл
        # (до 5 раз). Логируем для observability.
        logger.exception(
            "eventsub: handler %s failed for ch=%s: %s: %s",
            event_type, channel_id, type(e).__name__, e,
        )

    return JSONResponse({"status": "ok"})


@router.post("/eventsub")
async def eventsub_webhook(request: Request):
    """Универсальный Twitch EventSub callback (Phase A — generic)."""
    return await _process_eventsub_request(request)


@router.post("/eventsub/channel-points")
async def eventsub_channel_points_alias(request: Request):
    """Backward-compat URL.

    До Phase A подписки регались на этот URL. После Phase A регистрация
    идёт на /eventsub. Старые подписки на стороне Twitch продолжат бить сюда
    — до тех пор пока rotate_eventsub.py + restart не перерегистрируют их.
    Оба URL делегируют в одну функцию — поведение идентично.
    """
    return await _process_eventsub_request(request)


# ─── Handler implementations ─────────────────────────────────────────────────

@handler("channel.channel_points_custom_reward_redemption.add")
async def _on_channel_points(event: dict, channel_id: int) -> None:
    """Channel point redemption → начисление крустиков.

    Перенесено из main.py:eventsub_channel_points. Двойная дедупа:
      - eventsub_seen (msg_id) — внешний gate выше
      - channel_points_log UNIQUE (channel_id, twitch_redemption_id) —
        защита при переносе БД / re-subscribe (msg_id меняется,
        redemption_id остаётся стабильным от Twitch).
    """
    from config import CHANNEL_POINTS_CONFIG

    raw_user = (event.get("user_login") or "").lower()
    username = sanitize_username(raw_user)
    if not username or not validate_username(username):
        logger.warning(
            "channel_points: bad user_login '%s' ch=%s", raw_user, channel_id
        )
        return

    reward_title = event.get("reward", {}).get("title", "")
    redemption_id = event.get("id", "")

    rewards_cfg = CHANNEL_POINTS_CONFIG.get("rewards", {})
    reward_cfg = rewards_cfg.get(reward_title)
    if not reward_cfg:
        # title не в конфиге — log + ignore (раньше silently dropped, чинит
        # отладку: видно incoming title чтобы понять mismatch с config).
        logger.warning(
            "channel_points: unknown reward title '%s' ch=%s user=@%s "
            "(known titles: %s)",
            reward_title, channel_id, username,
            list(rewards_cfg.keys()),
        )
        return

    diamonds = reward_cfg["diamonds"]
    db = get_db()

    async with db._connect() as conn:
        cursor = await conn.execute(
            "SELECT id FROM channel_points_log "
            "WHERE channel_id=? AND twitch_redemption_id=?",
            (channel_id, redemption_id),
        )
        if await cursor.fetchone():
            return
        await conn.execute(
            "INSERT INTO channel_points_log "
            "(channel_id, username, twitch_redemption_id, reward_title, "
            "channel_points_spent, diamonds_given) "
            "VALUES (?,?,?,?,?,?)",
            (
                channel_id, username, redemption_id, reward_title,
                reward_cfg["channel_points_cost"], diamonds,
            ),
        )
        await conn.commit()

    await db.add_points(username, diamonds, channel_id=channel_id)
    logger.info(
        "💜 ch=%s @%s обменял '%s' → +%s💎",
        channel_id, username, reward_title, diamonds,
    )

    try:
        bot = get_bot()
        await bot.send_message(
            f"💜 @{username} обменял баллы канала на {diamonds}💎! "
            f"Спасибо за поддержку! monkaHmm"
        )
    except Exception as e:
        logger.warning("channel_points chat-notify failed: %s", e)


@handler("stream.online")
async def _on_stream_online(event: dict, channel_id: int) -> None:
    """Стрим стартовал.

    Side effects:
      1. bot._stream_live_cache[channel_id] = (True, now) — мгновенно открывает
         action endpoints с require_stream_live(). До этого зрители получали
         «доступно только во время стрима» до следующего polling-tick.
      2. db.register_stream_session(event.id, channel_id) — открыть/возобновить
         stream-session. event.id — это stream_id (UUID) от Twitch.
      3. notify_stream_online() — Telegram-канал. Внутри anti-spam cooldown
         30 мин на случай flap.

    Игнорируем `type != 'live'` (playlist/watch_party/premiere/rerun) — это
    не настоящие live-стримы, наши compliance-gates они открывать не должны.
    """
    from notifications import notify_stream_online

    stream_kind = event.get("type", "live")
    if stream_kind != "live":
        logger.info(
            "stream.online ch=%s type=%s — игнорируем (не live)",
            channel_id, stream_kind,
        )
        return

    login = (
        event.get("broadcaster_user_login")
        or event.get("broadcaster_user_name")
        or ""
    ).lower()
    stream_id = event.get("id", "")

    now = _time.time()
    try:
        bot = get_bot()
        bot._stream_live_cache[channel_id] = (True, now)
    except RuntimeError:
        # Bot ещё не инициализирован (startup race). TG-notify всё равно пошлём.
        pass

    db = get_db()
    if stream_id:
        try:
            await db.register_stream_session(stream_id, channel_id=channel_id)
        except Exception as e:
            logger.warning(
                "stream.online register_session ch=%s sid=%s failed: %s",
                channel_id, stream_id, e,
            )

    # TG-notify в фоне — не блокируем response Twitch'у.
    asyncio.create_task(notify_stream_online(
        channel_id=channel_id, login=login,
    ))
    logger.info(
        "🔴 stream.online ch=%s login=%s sid=%s",
        channel_id, login, stream_id[:12] if stream_id else "?",
    )


@handler("stream.offline")
async def _on_stream_offline(event: dict, channel_id: int) -> None:
    """Стрим завершён.

    Side effects:
      1. bot._stream_live_cache[channel_id] = (False, now) — мгновенно блокирует
         action endpoints с require_stream_live(). До этого зрители могли ещё
         кликать до следующего polling-tick (~2 мин TTL).
      2. db.end_active_stream_sessions(channel_id) — закрыть незакрытую
         сессию. Twitch не шлёт stream_id в offline, потому helper закрывает
         ВСЕ активные сессии канала (обычно их одна, защита от висящих).
    """
    now = _time.time()
    try:
        bot = get_bot()
        bot._stream_live_cache[channel_id] = (False, now)
    except RuntimeError:
        pass

    db = get_db()
    try:
        closed = await db.end_active_stream_sessions(channel_id=channel_id)
        logger.info(
            "⚫ stream.offline ch=%s — %d session(s) closed", channel_id, closed
        )
    except Exception as e:
        logger.warning(
            "stream.offline end_session ch=%s failed: %s", channel_id, e
        )


# ─── TTL cleanup ─────────────────────────────────────────────────────────────


async def cleanup_seen_loop():
    """Удаляет записи из eventsub_seen старше DEDUPE_TTL_SEC.

    Запускается из main.py startup как background task. Раз в час чистит
    expired. Twitch не повторяет события старше своего retry-окна, так что
    expired записи дедупа уже бесполезны.
    """
    while True:
        try:
            await asyncio.sleep(3600)
            cutoff = _time.time() - DEDUPE_TTL_SEC
            db = get_db()
            async with db._connect() as conn:
                cursor = await conn.execute(
                    "DELETE FROM eventsub_seen WHERE seen_at < ?", (cutoff,)
                )
                await conn.commit()
                if cursor.rowcount:
                    logger.info(
                        "eventsub_seen cleanup: %d expired rows",
                        cursor.rowcount,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "eventsub_seen cleanup error: %s: %s",
                type(e).__name__, e,
            )


# ─── Subscription registration helpers ───────────────────────────────────────

# Phase A типы подписок которые регистрируем для каждого зарегистрированного
# канала при startup. version + condition_factory для каждого type.
#
# condition_factory(broadcaster_id) → dict — некоторые типы (raid, custom-reward)
# требуют доп. условия (to_broadcaster_user_id и т.п.). Для Phase A все три
# типа берут просто broadcaster_user_id.
PHASE_A_SUBSCRIPTIONS = [
    {
        "type": "channel.channel_points_custom_reward_redemption.add",
        "version": "1",
        "condition_factory": lambda bid: {"broadcaster_user_id": bid},
    },
    {
        "type": "stream.online",
        "version": "1",
        "condition_factory": lambda bid: {"broadcaster_user_id": bid},
    },
    {
        "type": "stream.offline",
        "version": "1",
        "condition_factory": lambda bid: {"broadcaster_user_id": bid},
    },
]


async def register_subscription(
    session, headers: dict, broadcaster_id: str, sub_type: str,
    version: str, condition: dict, callback_url: str, secret: str,
) -> None:
    """Зарегистрировать ОДНУ подписку конкретного типа для broadcaster.

    Идемпотентно: проверяет существующие enabled-подписки этого типа и
    пропускает если уже есть. На fail — log, не пробрасываем (один тип не
    должен ломать регистрацию остальных).
    """
    import aiohttp as _aiohttp  # local import — only on registration path

    try:
        # Запрашиваем все наши подписки. Список не огромный (3 типа × N каналов).
        async with session.get(
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            headers=headers,
        ) as r:
            existing = await r.json()
            if r.status not in (200, 202):
                logger.warning(
                    "eventsub: list subs failed for bid=%s status=%s: %s",
                    broadcaster_id, r.status, existing,
                )
                return
            for sub in existing.get("data", []):
                if (
                    sub.get("type") == sub_type
                    and sub.get("status") == "enabled"
                    and sub.get("condition", {}).get("broadcaster_user_id")
                    == broadcaster_id
                ):
                    logger.info(
                        "eventsub: %s already active for bid=%s",
                        sub_type, broadcaster_id,
                    )
                    return

        async with session.post(
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "type": sub_type,
                "version": version,
                "condition": condition,
                "transport": {
                    "method": "webhook",
                    "callback": callback_url,
                    "secret": secret,
                },
            },
        ) as r:
            resp = await r.json()
            if r.status in (200, 202):
                logger.info(
                    "✅ eventsub: %s registered for bid=%s",
                    sub_type, broadcaster_id,
                )
            else:
                logger.warning(
                    "eventsub: %s register failed for bid=%s: %s",
                    sub_type, broadcaster_id, resp,
                )
    except _aiohttp.ClientError as e:
        logger.warning(
            "eventsub: network error registering %s for bid=%s: %s",
            sub_type, broadcaster_id, e,
        )
    except Exception as e:
        logger.exception(
            "eventsub: unexpected error registering %s for bid=%s: %s",
            sub_type, broadcaster_id, e,
        )


async def register_all_for_broadcaster(
    session, headers: dict, broadcaster_id: str,
    callback_url: str, secret: str,
) -> None:
    """Зарегистрировать ВСЕ Phase A типы для одного broadcaster."""
    for sub in PHASE_A_SUBSCRIPTIONS:
        await register_subscription(
            session, headers, broadcaster_id,
            sub["type"], sub["version"],
            sub["condition_factory"](broadcaster_id),
            callback_url, secret,
        )
