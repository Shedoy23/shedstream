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
import os
import time as _time
from collections import deque
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

    # 7-бис. Одна строка на КАЖДОЕ принятое уведомление.
    #
    # Зачем: часть обработчиков молчит по делу (chat.notification без
    # watch_streak, приветствие при выключенной настройке), и такое событие
    # раньше не оставляло следа вообще. Из-за этого пропажу channel.follow
    # (5→20 августа) пришлось искать по логам nginx, а eventsub_seen живёт
    # сутки и как журнал не годится. Теперь «пришло ли оно вообще» видно
    # прямо здесь.
    logger.info("eventsub: принято type=%s ch=%s", event_type, channel_id)

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

def _is_tester_request(reward_title: str) -> bool:
    """Похоже ли название награды на «хочу в тестеры расширения».

    Регистр и лишние пробелы игнорируем: название редактируется руками в
    панели Twitch, и лишний пробел не должен стоить зрителю баллов.
    """
    from config import CHANNEL_POINTS_CONFIG

    normalized = " ".join((reward_title or "").upper().split())
    if not normalized:
        return False
    return any(
        p in normalized
        for p in CHANNEL_POINTS_CONFIG.get("tester_request_patterns", ())
    )


async def _on_tester_request(
    channel_id: int, username: str, reward_title: str, redemption_id: str,
) -> None:
    """Зритель купил за баллы заявку в тестеры расширения.

    Записываем в тот же журнал наград (0 крустиков — это не обмен, это заявка),
    дедуп по redemption_id. Пишем в чат ДВА адресата в одной строке: зрителю —
    что заявка принята и доступ не мгновенный, стримеру — ник, который надо
    добавить в консоли. Без этого заявка живёт только в логе, которого владелец
    не читает.
    """
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "INSERT OR IGNORE INTO channel_points_log "
            "(channel_id, username, twitch_redemption_id, reward_title, "
            "channel_points_spent, diamonds_given) VALUES (?,?,?,?,?,?)",
            (channel_id, username, redemption_id, reward_title, 0, 0),
        )
        if cur.rowcount == 0:
            return          # повторная доставка того же вебхука
        await conn.commit()

    logger.info(
        "🧪 tester-request ch=%s @%s ('%s') — нужен ручной доступ в консоли",
        channel_id, username, reward_title,
    )
    await _send_greet(
        channel_id,
        f"🧪 @{username}, заявка в тестеры принята! Доступ выдаётся вручную — "
        f"стример добавит тебя в настройках расширения, это не мгновенно. "
        f"Стример, ник для списка тестеров: {username}",
    )


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

    # Заявка «хочу в тестеры расширения». Крустиков не даёт: доступ выдаёт
    # владелец руками в консоли Twitch, публичного API для этого нет. Наша
    # задача — не потерять заявку и ответить зрителю, иначе он платит баллы
    # в пустоту (так и вышло 20.08 с @zerohomes).
    if _is_tester_request(reward_title):
        await _on_tester_request(channel_id, username, reward_title,
                                 event.get("id", ""))
        return

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

    # 2026-07-27 (аудит S-06): дедуп и начисление — ОДНОЙ транзакцией.
    # Было: INSERT дедуп-строки коммитился сам по себе, а крустики начислял
    # отдельный add_points() на ВТОРОМ соединении со вторым коммитом. Падение
    # в этом окне давало худший исход: Channel Points у зрителя Twitch уже
    # списал, дедуп-строка закоммичена, крустиков нет — а повторная доставка
    # вебхука видит дедуп и молча выходит. Награда терялась навсегда.
    # Это тот же класс, что ловили 7× в аудите 2026-07-02 (CLAUDE.md:
    # «списание/источник и эффект — в одной транзакции»).
    # Дедуп теперь держит UNIQUE(channel_id, twitch_redemption_id):
    # INSERT OR IGNORE + rowcount==0 значит «уже начисляли». Сбой откатывает
    # ОБА действия → повтор вебхука отработает штатно.
    # Красный тест: tests/test_channel_points_atomic.py
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "INSERT OR IGNORE INTO channel_points_log "
                "(channel_id, username, twitch_redemption_id, reward_title, "
                "channel_points_spent, diamonds_given) "
                "VALUES (?,?,?,?,?,?)",
                (
                    channel_id, username, redemption_id, reward_title,
                    reward_cfg["channel_points_cost"], diamonds,
                ),
            )
            if cur.rowcount == 0:
                await conn.execute("ROLLBACK")
                return
            await db.add_points_tx(conn, username, diamonds, channel_id)
            await conn.commit()
        except Exception:
            try:
                await conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
    logger.info(
        "💜 ch=%s @%s обменял '%s' → +%s💎",
        channel_id, username, reward_title, diamonds,
    )

    try:
        bot = get_bot()
        await bot.send_message(
            f"💜 @{username} обменял баллы канала на {diamonds}💎! "
            f"Спасибо за поддержку! monkaHmm",
            channel_id=channel_id,
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
    # Phase C (2026-05-17): broadcast stream_state — frontend мгновенно
    # снимет «доступно только во время стрима» gate без следующего polling.
    try:
        from pubsub import broadcast as _pubsub_broadcast
        _pubsub_broadcast(channel_id, "stream_state", {"live": True})
    except Exception as e:
        logger.warning("stream.online pubsub broadcast failed: %s", e)
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
    # Phase C: broadcast stream_state — frontend мгновенно перекроет
    # action endpoints с require_stream_live (без задержки следующего polling).
    try:
        from pubsub import broadcast as _pubsub_broadcast
        _pubsub_broadcast(channel_id, "stream_state", {"live": False})
    except Exception as e:
        logger.warning("stream.offline pubsub broadcast failed: %s", e)


# ─── Подписки: бот приветствует в чате (ToS §5.2 — только текст, без наград) ──


def _plural_subs(n: int) -> str:
    """Склонение слова 'подписка' по числу: 1/2/5 → подписку/подписки/подписок."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return "подписок"
    d = n % 10
    if d == 1:
        return "подписку"
    if 2 <= d <= 4:
        return "подписки"
    return "подписок"


async def _greet_enabled(channel_id: int, kind: str) -> bool:
    """Приветствие kind ('sub'|'follow') включено на канале?

    Ошибку чтения трактуем как ON (default) — приветствие важнее идеальной точности.
    """
    try:
        settings = await get_db().get_channel_greet_settings(channel_id)
        return bool(settings.get(kind, True))
    except Exception as e:
        logger.warning(
            "greet setting read ch=%s kind=%s failed: %s — default ON",
            channel_id, kind, e,
        )
        return True


# Sliding-window rate limit на фолоу-приветствия. Фолловы спамнее сабов
# (фолоу-боты массово фолловят) — без лимита бот зафлудит чат и его самого
# затаймаутят за спам. Не более N приветствий за окно на канал; превышение
# логируем и молча скипаем (НЕ копим очередь — это лишь усилит флуд).
_FOLLOW_GREET_WINDOW_SEC = 60
_FOLLOW_GREET_MAX_PER_WINDOW = 8
_follow_greet_times: dict[int, "deque"] = {}


def _follow_greet_allowed(channel_id: int) -> bool:
    now = _time.time()
    dq = _follow_greet_times.get(channel_id)
    if dq is None:
        dq = deque()
        _follow_greet_times[channel_id] = dq
    cutoff = now - _FOLLOW_GREET_WINDOW_SEC
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= _FOLLOW_GREET_MAX_PER_WINDOW:
        return False
    dq.append(now)
    return True


async def _send_greet(channel_id: int, text: str) -> None:
    """Приветствие в чат конкретного канала. Ошибку глотаем (не валим webhook)."""
    try:
        await get_bot().send_message(text, channel_id=channel_id)
    except Exception as e:
        logger.warning("sub-greet send ch=%s failed: %s", channel_id, e)


@handler("channel.subscribe")
async def _on_channel_subscribe(event: dict, channel_id: int) -> None:
    """Новая подписка → приветствие в чате.

    is_gift=true пропускаем: подарочные подписки приветствуем ОДНИМ сообщением
    дарителю в channel.subscription.gift (иначе бомба из 50 подарков = 50 спам-
    строк по получателям). Ресабы сюда НЕ приходят — они в .message.
    """
    if event.get("is_gift"):
        return
    if not await _greet_enabled(channel_id, "sub"):
        return

    raw_user = (event.get("user_login") or event.get("user_name") or "").lower()
    username = sanitize_username(raw_user)
    if not username or not validate_username(username):
        logger.warning(
            "channel.subscribe: bad user '%s' ch=%s", raw_user, channel_id
        )
        return

    await _send_greet(
        channel_id,
        f"🎉 Спасибо за подписку, @{username}! Добро пожаловать!",
    )
    logger.info("🎉 sub-greet ch=%s @%s (new)", channel_id, username)


@handler("channel.subscription.message")
async def _on_subscription_message(event: dict, channel_id: int) -> None:
    """Ресаб (зритель поделился сообщением о продлении) → приветствие с месяцами."""
    if not await _greet_enabled(channel_id, "sub"):
        return

    raw_user = (event.get("user_login") or event.get("user_name") or "").lower()
    username = sanitize_username(raw_user)
    if not username or not validate_username(username):
        logger.warning(
            "subscription.message: bad user '%s' ch=%s", raw_user, channel_id
        )
        return

    try:
        months = int(event.get("cumulative_months") or 0)
    except (TypeError, ValueError):
        months = 0

    if months >= 2:
        text = f"🔥 @{username} с нами уже {months} мес — спасибо, что остаёшься!"
    else:
        text = f"🔥 @{username} продлил подписку — спасибо!"
    await _send_greet(channel_id, text)
    logger.info("🔥 sub-greet ch=%s @%s (resub %dмес)", channel_id, username, months)


@handler("channel.subscription.gift")
async def _on_subscription_gift(event: dict, channel_id: int) -> None:
    """Подарок подписок → ОДНО приветствие дарителю (не по получателям — анти-спам).

    total = сколько подарено в этом событии. is_anonymous → без @ника
    (Twitch не отдаёт логин анонимного дарителя).
    """
    if not await _greet_enabled(channel_id, "sub"):
        return

    try:
        total = int(event.get("total") or 1)
    except (TypeError, ValueError):
        total = 1
    word = _plural_subs(total)

    if event.get("is_anonymous"):
        text = f"🎁 Кто-то подарил {total} {word} — спасибо за щедрость!"
        logger.info("🎁 sub-greet ch=%s anon gifted %d", channel_id, total)
    else:
        raw_user = (
            event.get("user_login") or event.get("user_name") or ""
        ).lower()
        username = sanitize_username(raw_user)
        if not username or not validate_username(username):
            logger.warning(
                "subscription.gift: bad gifter '%s' ch=%s", raw_user, channel_id
            )
            return
        text = f"🎁 @{username} подарил {total} {word} — спасибо за щедрость!"
        logger.info("🎁 sub-greet ch=%s @%s gifted %d", channel_id, username, total)
    await _send_greet(channel_id, text)


@handler("channel.follow")
async def _on_channel_follow(event: dict, channel_id: int) -> None:
    """Новый фолловер → приветствие в чате (если включено + не превышен лимит).

    Анти-флуд: rate-limit на канал (фолоу-боты массово фолловят). Превышение
    лимита логируем и скипаем — иначе бот зафлудит чат и его затаймаутят.
    """
    if not await _greet_enabled(channel_id, "follow"):
        return

    raw_user = (event.get("user_login") or event.get("user_name") or "").lower()
    username = sanitize_username(raw_user)
    if not username or not validate_username(username):
        logger.warning(
            "channel.follow: bad user '%s' ch=%s", raw_user, channel_id
        )
        return

    if not _follow_greet_allowed(channel_id):
        logger.info(
            "👋 follow-greet ch=%s @%s SKIPPED (rate-limit %d/%dс — возможен фолоу-бот)",
            channel_id, username,
            _FOLLOW_GREET_MAX_PER_WINDOW, _FOLLOW_GREET_WINDOW_SEC,
        )
        return

    await _send_greet(channel_id, f"👋 Спасибо за фолоу, @{username}! Рады видеть!")
    logger.info("👋 follow-greet ch=%s @%s", channel_id, username)


@handler("channel.raid")
async def _on_channel_raid(event: dict, channel_id: int) -> None:
    """Входящий рейд → приветствие рейдерам в чате.

    Условие подписки — `to_broadcaster_user_id` (мы цель рейда), его и
    резолвит общий разбор выше. Scope не требуется: рейды публичны.
    """
    raw_user = (
        event.get("from_broadcaster_user_login")
        or event.get("from_broadcaster_user_name") or ""
    ).lower()
    username = sanitize_username(raw_user)
    if not username or not validate_username(username):
        logger.warning("channel.raid: bad raider '%s' ch=%s", raw_user, channel_id)
        return
    try:
        viewers = int(event.get("viewers") or 0)
    except (TypeError, ValueError):
        viewers = 0

    # Рейд редок, лимитом не защищаем — но текст без числа, если оно нулевое:
    # «рейд на 0 зрителей» выглядит как поломка, хотя это просто пустое поле.
    if viewers > 0:
        text = f"🚀 Рейд от @{username} — {viewers} чел. на борту! Добро пожаловать!"
    else:
        text = f"🚀 Рейд от @{username}! Добро пожаловать!"
    await _send_greet(channel_id, text)
    logger.info("🚀 raid-greet ch=%s от @%s (%d зрителей)", channel_id, username, viewers)


@handler("channel.cheer")
async def _on_channel_cheer(event: dict, channel_id: int) -> None:
    """Биты → благодарность в чате. ТОЛЬКО ТЕКСТ, никакой игровой выгоды.

    Дать за биты крустики/динары/предметы нельзя: это продажа игрового
    преимущества мимо платёжной системы Twitch — тот же класс нарушения, из-за
    которого в мае вырезали казино. Здесь только «спасибо».

    Анонимный чир приходит с is_anonymous=true и БЕЗ ника — благодарим
    безымянно, а не роняем обработчик на пустом поле.
    """
    try:
        bits = int(event.get("bits") or 0)
    except (TypeError, ValueError):
        bits = 0
    if bits <= 0:
        return

    if not _follow_greet_allowed(channel_id):
        logger.info("💜 cheer-greet ch=%s SKIPPED (rate-limit)", channel_id)
        return

    if event.get("is_anonymous"):
        await _send_greet(channel_id, f"💎 Спасибо за {bits} бит(ов), аноним!")
        logger.info("💎 cheer-greet ch=%s аноним %d бит", channel_id, bits)
        return

    raw_user = (event.get("user_login") or event.get("user_name") or "").lower()
    username = sanitize_username(raw_user)
    if not username or not validate_username(username):
        await _send_greet(channel_id, f"💎 Спасибо за {bits} бит(ов)!")
        logger.warning("channel.cheer: bad user '%s' ch=%s", raw_user, channel_id)
        return
    await _send_greet(channel_id, f"💎 @{username}, спасибо за {bits} бит(ов)!")
    logger.info("💎 cheer-greet ch=%s @%s %d бит", channel_id, username, bits)


@handler("channel.chat.notification")
async def _on_chat_notification(event: dict, channel_id: int) -> None:
    """Чат-уведомления Twitch → ловим ТОЛЬКО watch_streak (серии просмотров).

    Это «общая труба» нотисов (сабы/рейды/анонсы тоже сюда летят, но их мы
    обрабатываем отдельными подписками) — фильтруем по notice_type. Стрик
    пишем молча в статистику (НЕ в чат) — лидерборд лояльности для стримера.
    """
    if event.get("notice_type") != "watch_streak":
        return

    streak = event.get("watch_streak") or {}
    try:
        streak_count = int(streak.get("streak_count") or 0)
    except (TypeError, ValueError):
        streak_count = 0
    if streak_count <= 0:
        return
    try:
        points = int(streak.get("channel_points_awarded") or 0)
    except (TypeError, ValueError):
        points = 0

    raw_user = (
        event.get("chatter_user_login") or event.get("chatter_user_name") or ""
    ).lower()
    username = sanitize_username(raw_user)
    if not username or not validate_username(username):
        logger.warning(
            "watch_streak: bad user '%s' ch=%s", raw_user, channel_id
        )
        return

    try:
        await get_db().record_watch_streak(
            channel_id, username, streak_count, points
        )
        logger.info(
            "🔥 watch-streak ch=%s @%s стрик=%d (+%d баллов)",
            channel_id, username, streak_count, points,
        )
    except Exception as e:
        logger.warning(
            "watch_streak record ch=%s @%s failed: %s",
            channel_id, username, e,
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
                    "DELETE FROM eventsub_seen WHERE seen_at < ?", (cutoff,)  # tenant-ok: hourly TTL maintenance sweep, intentionally all channels
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


async def _followers_gained_24h(channel_id: int) -> Optional[int]:
    """Сколько человек зафолловили канал за сутки ПО ДАННЫМ TWITCH.

    None — «узнать не удалось». Неизвестность НЕ приравниваем к нулю: иначе
    сломанный токен выглядел бы как «всё сходится», а это ровно тот способ
    обмануть себя, из-за которого пропажу фолловов не замечали 17 дней.
    """
    import aiohttp as _aiohttp

    try:
        row = await get_db().get_channel(channel_id)
        token = (row or {}).get("oauth_access_token") or ""
    except Exception as e:
        logger.warning("follow-watch: токен канала %s недоступен: %s", channel_id, e)
        return None
    if not token:
        return None

    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    url = "https://api.twitch.tv/helix/channels/followers"
    try:
        async with _aiohttp.ClientSession() as s:
            async with s.get(
                url,
                params={"broadcaster_id": str(channel_id), "first": "100"},
                headers={"Client-Id": client_id, "Authorization": "Bearer " + token},
                timeout=_aiohttp.ClientTimeout(total=20),
            ) as r:
                if r.status != 200:
                    logger.warning("follow-watch: Helix ответил %s", r.status)
                    return None
                data = await r.json()
    except Exception as e:
        logger.warning("follow-watch: Helix недоступен: %s: %s", type(e).__name__, e)
        return None

    cutoff = _time.time() - DEDUPE_TTL_SEC
    gained = 0
    for item in data.get("data", []):
        stamp = (item.get("followed_at") or "").replace("Z", "+00:00")
        try:
            if datetime.fromisoformat(stamp).timestamp() >= cutoff:
                gained += 1
        except (ValueError, TypeError):
            continue
    return gained


async def follow_delivery_watch_loop():
    """Раз в сутки: столько ли фолловов нам прислали, сколько их было на самом деле.

    Зачем отдельный сторож. 2026-08-05 Twitch тихо перестал слать
    `channel.follow`, продолжая слать всё остальное: подписка числилась
    `enabled`, ошибок не было, ничего не упало. Проверка «сервис жив» такое
    не ловит в принципе — ловит только сверка ФАКТА (сколько людей
    зафолловило по данным Twitch) с ОЖИДАНИЕМ (сколько событий мы приняли).

    Окно ровно сутки, потому что считаем по `eventsub_seen`, а её чистит
    TTL — на большем окне сравнение врало бы в сторону «всё пропало».

    Отчитывается в чат канала: это единственное место, куда владелец смотрит
    каждый день (его решение 2026-08-22). Не чаще раза в сутки на канал.
    """
    while True:
        try:
            await asyncio.sleep(DEDUPE_TTL_SEC)
            try:
                channels = await get_db().list_channels()
            except Exception as e:
                logger.warning("follow-watch: список каналов недоступен: %s", e)
                continue
            for ch in channels:
                channel_id = int(ch.get("channel_id") or 0)
                if channel_id <= 0:
                    continue
                gained = await _followers_gained_24h(channel_id)
                if not gained:
                    continue        # нечего сверять либо проверить не вышло
                async with get_db()._connect() as conn:
                    cur = await conn.execute(
                        "SELECT count(*) FROM eventsub_seen WHERE event_type=? "
                        "AND channel_id=? AND seen_at >= ?",
                        ("channel.follow", channel_id, _time.time() - DEDUPE_TTL_SEC),
                    )
                    seen = int((await cur.fetchone())[0])
                if seen >= gained:
                    continue
                logger.warning(
                    "follow-watch ch=%s: фолловеров %d, событий принято %d",
                    channel_id, gained, seen,
                )
                await _send_greet(
                    channel_id,
                    f"⚠️ Служебное: за сутки фолловеров {gained}, а событий от "
                    f"Twitch пришло {seen}. Приветствия могут не работать — "
                    f"нужно пересоздать подписку channel.follow.",
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("follow-watch error: %s: %s", type(e).__name__, e)


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
    # Подписки → бот приветствует в чате (только текст, без наград — ToS §5.2).
    # Требуют scope channel:read:subscriptions у broadcaster'а (config.py).
    # Старые токены без этого scope → Twitch вернёт 403 при регистрации
    # (register_subscription логирует и не валит остальные) — нужен re-auth.
    {
        "type": "channel.subscribe",
        "version": "1",
        "condition_factory": lambda bid: {"broadcaster_user_id": bid},
    },
    {
        "type": "channel.subscription.message",
        "version": "1",
        "condition_factory": lambda bid: {"broadcaster_user_id": bid},
    },
    {
        "type": "channel.subscription.gift",
        "version": "1",
        "condition_factory": lambda bid: {"broadcaster_user_id": bid},
    },
    # Фоллов → бот приветствует (только текст). v2 требует moderator_user_id
    # в условии + scope moderator:read:followers. Бродкастер — модератор своего
    # канала, потому moderator_user_id = broadcaster_user_id (его авторизация
    # покрывает оба). Старый токен без scope → 403 при регистрации → re-auth.
    {
        "type": "channel.follow",
        "version": "2",
        "condition_factory": lambda bid: {
            "broadcaster_user_id": bid,
            "moderator_user_id": bid,
        },
    },
    # Рейд → приветствие рейдерам. Условие — to_broadcaster_user_id (мы цель).
    # Scope НЕ требуется, поэтому подписка встаёт сразу, без re-OAuth.
    {
        "type": "channel.raid",
        "version": "1",
        "condition_factory": lambda bid: {"to_broadcaster_user_id": bid},
    },
    # Биты → благодарность текстом (никакой игровой выгоды, см. обработчик).
    # Требует scope bits:read у бродкастера. Старый токен без него → 403 при
    # регистрации, register_subscription залогирует и пойдёт дальше: рейды и
    # остальное от этого не пострадают.
    {
        "type": "channel.cheer",
        "version": "1",
        "condition_factory": lambda bid: {"broadcaster_user_id": bid},
    },
    # Чат-уведомления → ловим ТОЛЬКО notice_type='watch_streak' (серии
    # просмотров) для статистики лояльности. v1 требует user_id (кто читает
    # чат — бродкастер читает свой) + scope user:read:chat. Это «общая труба»
    # всех нотисов (сабы/рейды/анонсы) — хендлер фильтрует только стрики.
    {
        "type": "channel.chat.notification",
        "version": "1",
        "condition_factory": lambda bid: {
            "broadcaster_user_id": bid,
            "user_id": bid,
        },
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
