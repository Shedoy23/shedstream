"""
backend/pubsub.py — Twitch Extensions PubSub send-side (Phase C, 2026-05-17).

Push к frontend extension'у через Twitch infrastructure. Backend публикует
event'ы → Twitch разносит через WebSocket → `Twitch.ext.listen` в frontend.

## Topics
  - `broadcast`              — все viewers канала видят
  - `whisper-<opaque_id>`    — конкретный viewer (personal update)
  - `global`                 — cross-channel (НЕ используем, лицензия не покрывает)

## Use cases (Phase C/D roadmap)
  - `vote_started` / `vote_tick` / `vote_ended` — broadcast (kill 4s voting poll)
  - `match_state`            — broadcast в матче (kill 3s ttt/dice poll)
  - `rulection_tick`         — broadcast (kill 4-8s family poll)
  - `stream_state`           — broadcast (мгновенно при start/end)
  - `balance_changed`        — **whisper** (personal — баланс зрителя, не для всех)

## Twitch limits (verified 2026-05)
  - **1 message/sec per (channel, topic)** для broadcast/whisper
  - **5 KB payload максимум** (после JSON-stringify)
  - **5 second JWT TTL минимум**, мы используем 120s
  - Helix endpoint: `POST /helix/extensions/pubsub`

## Security model

| Threat | Mitigation |
|---|---|
| Cross-channel send (T1.1) | `channel_id` строго parameter; send-JWT bind'им к нему; никогда из user input |
| PII в payload (T1.2) | `_PAYLOAD_DENY_KEYS` deny-list + recursive scrub перед enqueue |
| Spam → Twitch dropping (T1.3) | per-topic queue + 1msg/sec throttle + coalesce при backpressure |
| Public broadcast of personal data (T1.4) | API differentiation: broadcast vs whisper по semantics |
| XSS через payload (T1.5) | Frontend политика: только textContent, не innerHTML |
| Replay / out-of-order (T1.6) | Monotonic `seq` per (channel, type) + frontend dedupe |

## Failure model

PubSub НЕ гарантирует delivery. Polling-fallback остаётся в frontend как
safety net. При 429/timeout от Twitch — log warn + drop, frontend polling
covers gap. Подписки этого канала на Twitch'е не affected.

## NOT to send
  - Real Twitch user_id (используй `opaque_user_id` для whisper target)
  - Secrets/tokens (deny-list ловит, но и manually не суйте)
  - Bits-related state до confirm transaction (financial integrity)
  - Cases reveal animation state (race — может опередить animation)
"""

from __future__ import annotations

import asyncio
import base64 as _base64
import json
import logging
import os
import time as _time
from typing import Any, Optional

import aiohttp
import jwt

logger = logging.getLogger("rimlink.pubsub")

# ─── Constants ────────────────────────────────────────────────────────────────

_TWITCH_PUBSUB_URL = "https://api.twitch.tv/helix/extensions/pubsub"
_RATE_PER_TOPIC_SEC = 1.0           # 1 msg/sec per (channel, topic)
_PAYLOAD_MAX_BYTES = 5000
_JWT_TTL_SEC = 120

# Coalesce: при превышении backpressure дропаем oldest при enqueue.
# Стратегия безопасна для tick-style событий (последний tick содержит
# cumulative state, старые лишь throwaway).
_QUEUE_BACKPRESSURE = 5

# PII deny-list. Случайный `{...'email': u.email...}` payload → raise ValueError.
# Защита от forgetful programmer'а. Не логируем сам value (чтобы не leak'нуть
# в логи). lowercase comparison.
_PAYLOAD_DENY_KEYS = frozenset({
    "token", "email", "helix_token", "authorization", "jwt",
    "ip", "fingerprint", "client_secret", "access_token", "refresh_token",
    "real_user_id",   # opaque_user_id OK; real Twitch user_id — нет
    "password", "secret", "api_key", "twitch_token",
})


# ─── Payload safety ───────────────────────────────────────────────────────────

def _scrub_payload(payload: Any, path: str = "") -> None:
    """Recursive walk. Raise при denied key, never log value.

    Raises:
        ValueError: payload contains denied key. Не отправляем, не показываем
            value в exception (чтобы не дублировать leak дальше в логи).
    """
    if isinstance(payload, dict):
        for k, v in payload.items():
            key_lower = str(k).lower()
            if key_lower in _PAYLOAD_DENY_KEYS:
                # НЕ включаем value в exception — могло быть actual leak.
                raise ValueError(
                    f"PubSub payload contains denied key '{k}' at path '{path or '<root>'}'"
                )
            _scrub_payload(v, f"{path}.{k}" if path else str(k))
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            _scrub_payload(v, f"{path}[{i}]")
    # str/int/float/bool/None — leaf values, OK.


# ─── JWT signing ──────────────────────────────────────────────────────────────

def _decode_extension_secret(b64: str) -> bytes:
    """Twitch shared-secret — base64url-encoded. Восстанавливаем padding."""
    s = b64.replace('-', '+').replace('_', '/')
    pad = 4 - len(s) % 4
    if pad != 4:
        s += '=' * pad
    return _base64.b64decode(s)


def _make_send_jwt(channel_id: int, topics: list[str]) -> str:
    """HS256 send-JWT для одного POST в Helix.

    Claims per Twitch Extension PubSub spec:
      - `exp`            — Unix timestamp expiration (мы +120s)
      - `user_id`        — extension owner user_id (для self-channel = broadcaster)
      - `role`           — должно быть "external"
      - `channel_id`     — TARGET broadcaster (строго связан с этой JWT)
      - `pubsub_perms`   — `{send: [topic, ...]}` whitelisted targets

    `channel_id` строго bind'им к запросу — атакующий с этой JWT не может
    переслать broadcast в другой канал. Это часть T1.1 mitigation.
    """
    secret_b64 = os.getenv("TWITCH_EXTENSION_SECRET", "")
    if not secret_b64:
        raise RuntimeError("TWITCH_EXTENSION_SECRET не задан в .env")
    secret = _decode_extension_secret(secret_b64)

    now = int(_time.time())
    claims = {
        "exp": now + _JWT_TTL_SEC,
        "user_id": str(channel_id),
        "role": "external",
        "channel_id": str(channel_id),
        "pubsub_perms": {"send": topics},
    }
    return jwt.encode(claims, secret, algorithm="HS256")


# ─── Queue + throttle state ───────────────────────────────────────────────────

# (channel_id, topic) → asyncio.Queue[str]. Per-topic чтобы шумный topic не
# блокировал остальные. Capped через _QUEUE_BACKPRESSURE.
_send_queues: dict[tuple[int, str], asyncio.Queue] = {}

# (channel_id, topic) → last successful send timestamp (unix). Throttle gate.
_last_send_ts: dict[tuple[int, str], float] = {}

# (channel_id, event_type) → monotonic counter. Frontend дропает out-of-order.
_seq_counter: dict[tuple[int, str], int] = {}

# Singleton aiohttp session, lifetime = process. Init at drain_loop start.
_session: Optional[aiohttp.ClientSession] = None


def _next_seq(channel_id: int, event_type: str) -> int:
    key = (channel_id, event_type)
    n = _seq_counter.get(key, 0) + 1
    _seq_counter[key] = n
    return n


def _make_envelope(event_type: str, channel_id: int, data: dict) -> str:
    """JSON-сериализованный envelope готовый для message-field Helix request.

    Schema (frontend realtime.js парсит):
      {v: 1, type: "<event_type>", seq: N, ts: <unix_ms>, data: {...}}

    Raises:
        ValueError: payload > 5 KB.
    """
    envelope = {
        "v": 1,
        "type": event_type,
        "seq": _next_seq(channel_id, event_type),
        "ts": int(_time.time() * 1000),
        "data": data,
    }
    s = json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))
    if len(s.encode('utf-8')) > _PAYLOAD_MAX_BYTES:
        raise ValueError(
            f"PubSub envelope {len(s)} bytes > {_PAYLOAD_MAX_BYTES} max — "
            f"type={event_type} ch={channel_id}. Slim payload или split."
        )
    return s


def _enqueue(channel_id: int, topic: str, envelope: str) -> bool:
    """Положить envelope в per-topic очередь. Returns True всегда (мы либо
    enqueue, либо coalesce-drop oldest).

    Backpressure: если очередь >= _QUEUE_BACKPRESSURE, выкидываем oldest.
    Это semantic-safe для tick-style событий (последний tick = current state).
    Для non-coalesceable событий (vote_started, balance_changed) backpressure
    drop'ы будут редкими — это P0 events с low rate.
    """
    q = _send_queues.setdefault((channel_id, topic), asyncio.Queue())
    while q.qsize() >= _QUEUE_BACKPRESSURE:
        try:
            q.get_nowait()
            logger.warning(
                "pubsub backpressure ch=%s topic=%s — dropped oldest (qsize=%d)",
                channel_id, topic, q.qsize(),
            )
        except asyncio.QueueEmpty:
            break
    q.put_nowait(envelope)
    return True


# ─── Public API ───────────────────────────────────────────────────────────────

def broadcast(channel_id: int, event_type: str, data: dict) -> bool:
    """Шлёт всем viewers канала. Sync (только enqueue) — actual HTTP в drain loop.

    Returns:
        True если enqueued.

    Raises:
        ValueError: payload содержит denied PII key или > 5 KB.
        RuntimeError: TWITCH_EXTENSION_SECRET не задан (только при actual send).
    """
    _scrub_payload(data)
    envelope = _make_envelope(event_type, channel_id, data)
    return _enqueue(channel_id, "broadcast", envelope)


def whisper(channel_id: int, opaque_user_id: str, event_type: str,
            data: dict) -> bool:
    """Шлёт конкретному viewer'у через `whisper-<opaque>` topic.

    Использовать для personal/private updates (balance changed, personal
    notification). Frontend подписан на `Twitch.ext.listen('whisper-<own>', cb)`.

    `opaque_user_id` — Twitch opaque ID (с префиксом 'U'), НЕ реальный user_id.
    Получается через `Twitch.ext.viewer.opaqueId` на frontend.

    Returns:
        True если enqueued, False если opaque_user_id пустой.
    """
    if not opaque_user_id:
        return False
    _scrub_payload(data)
    envelope = _make_envelope(event_type, channel_id, data)
    return _enqueue(channel_id, f"whisper-{opaque_user_id}", envelope)


# ─── HTTP send ────────────────────────────────────────────────────────────────

async def _send_to_twitch(channel_id: int, topic: str, message: str) -> bool:
    """POST в Helix /extensions/pubsub. Returns True при 2xx.

    Errors logged но не raised — caller (drain loop) не должен crash на
    transient Twitch issues. Frontend polling fallback покрывает потери.

    Sprint 5.31 #45d (audit HIGH-7) — теперь shared session из http_session.
    Раньше создавали локальную ClientSession без close'a на shutdown —
    утечка connector'ов на каждом reload'е, плюс concurrency-race на init.
    """
    from http_session import get_session
    session = await get_session()

    client_id = (
        os.getenv("TWITCH_EXTENSION_CLIENT_ID")
        or os.getenv("TWITCH_CLIENT_ID")
        or ""
    )
    if not client_id:
        logger.error("pubsub: TWITCH_EXTENSION_CLIENT_ID (или TWITCH_CLIENT_ID) не задан")
        return False

    try:
        send_jwt = _make_send_jwt(channel_id, [topic])
    except Exception as e:
        logger.error("pubsub: JWT-sign failed: %s: %s", type(e).__name__, e)
        return False

    body = {
        "target": [topic],
        "broadcaster_id": str(channel_id),
        "is_global_broadcast": False,
        "message": message,
    }
    headers = {
        "Client-Id": client_id,
        "Authorization": f"Bearer {send_jwt}",
        "Content-Type": "application/json",
    }

    try:
        async with session.post(
            _TWITCH_PUBSUB_URL, json=body, headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            # Twitch shares rate-limit между Helix calls. <10 = warning.
            rl = r.headers.get("Ratelimit-Remaining", "")
            if rl.isdigit() and int(rl) < 10:
                logger.warning(
                    "pubsub: Twitch ratelimit-remaining=%s (low) — backing off recommended",
                    rl,
                )
            if r.status in (200, 204):
                return True
            body_text = await r.text()
            # Не логируем send-JWT (Authorization header) на error — он short-TTL
            # но всё равно avoid'им появление в логах.
            logger.warning(
                "pubsub: helix returned %s for ch=%s topic=%s body=%s",
                r.status, channel_id, topic, body_text[:200],
            )
            return False
    except asyncio.TimeoutError:
        logger.warning("pubsub: helix timeout ch=%s topic=%s", channel_id, topic)
        return False
    except aiohttp.ClientError as e:
        logger.warning("pubsub: helix client error ch=%s topic=%s: %s",
                        channel_id, topic, e)
        return False


# ─── Drain loop ────────────────────────────────────────────────────────────────

async def drain_loop():
    """Background task: вытаскивает messages из per-topic очередей, throttle'ит
    до 1msg/sec per (channel, topic), шлёт в Helix concurrently.

    Запускается из main.py startup. Cancellation-safe.
    """
    logger.info("pubsub drain loop started")
    while True:
        try:
            now = _time.time()
            # Snapshot keys чтобы не модифицировать dict во время iteration.
            keys = list(_send_queues.keys())
            for (channel_id, topic) in keys:
                q = _send_queues.get((channel_id, topic))
                if not q or q.empty():
                    continue
                last_ts = _last_send_ts.get((channel_id, topic), 0)
                if now - last_ts < _RATE_PER_TOPIC_SEC:
                    continue
                try:
                    message = q.get_nowait()
                except asyncio.QueueEmpty:
                    continue
                _last_send_ts[(channel_id, topic)] = now
                # Spawn task — не блокируем drain loop на 10s timeout одного
                # медленного channel'а. Concurrent sends across topics OK,
                # Twitch limits per (channel,topic) уже соблюдены throttle gate'ом.
                asyncio.create_task(_send_to_twitch(channel_id, topic, message))

            # 100ms tick granularity. Sufficient для 1msg/sec hard limit.
            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("pubsub drain loop cancelled, shutting down")
            # Sprint 5.31 #45d — shared session закрывается в on_shutdown
            # (http_session.close_session). Здесь больше ничего не делаем.
            raise
        except Exception as e:
            logger.exception("pubsub drain loop error: %s: %s",
                              type(e).__name__, e)
            await asyncio.sleep(1)  # backoff чтобы не tight-loop при storm
