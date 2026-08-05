"""
twitch_subs.py — Twitch Helix subscription detection.

Sprint 5.29 BLT-parity #9 real implementation.
Sprint 5.33 TOS-COMPLIANCE (2026-05-28): subscription-based bonuses NEUTRALIZED.
  Twitch Extension Developer Agreement / Community Guidelines prohibit:
    - Gating gameplay rewards / features behind subscriptions
    - Discounts or reward multipliers based on sub status
  Detection function `get_subscription_tier` остаётся (может пригодиться
  для cosmetic-only badges в будущем), но `get_sub_boost` возвращает
  (1.0, 1.0) для ВСЕХ tiers. Sub-status больше НЕ влияет на цены/награды.

Использует broadcaster's OAuth token (scope: channel:read:subscriptions) для
проверки sub-status зрителей через Helix /subscriptions endpoint.

API:
    GET https://api.twitch.tv/helix/subscriptions?broadcaster_id=X&user_id=Y
    Headers: Authorization: Bearer <access_token>, Client-Id: <client_id>

    Response 200 + data[]:
        [{tier: "1000"|"2000"|"3000", is_gift, plan_name, user_id, ...}]
    Response 200 + data=[] → не subscribed
    Response 401 → invalid scope (streamer не сделал re-OAuth)
    Response 403 → forbidden (broadcaster_id mismatch)

Кэш: in-memory dict `(channel_id, user_id) → (tier_int, expires_at)`.
TTL 5 мин — sub-status меняется редко.

Public API:
    get_subscription_tier(channel_id: int, user_id: str) → int | None
        - 0    = not subscribed
        - 1/2/3 = tier (Helix's "1000"/"2000"/"3000")
        - None = unknown (Helix error / no OAuth)
        NOTE: returned value сейчас не используется для gameplay perks —
        только для optional cosmetic UI (e.g. badge), if ever needed.

    get_sub_boost(channel_id: int, user_id: str) → (price_mult, reward_mult)
        ALWAYS RETURNS (1.0, 1.0) — Twitch ToS compliance.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional, Tuple

import aiohttp

log = logging.getLogger("rimlink.twitch_subs")

_TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID") or ""

# Cache: (channel_id, user_id) → (tier, expires_at)
# tier: 0/1/2/3 (int). expires_at — unix ts когда entry stale.
_SUB_CACHE: dict[tuple[int, str], tuple[int, float]] = {}
_CACHE_TTL_SEC = 300   # 5 min

# Sprint 5.33 TOS-COMPLIANCE: все tier multipliers → (1.0, 1.0).
# Twitch ToS prohibits sub-based discounts/rewards в Extensions.
# Dict kept для structural compatibility (existing imports), но эффект 0.
SUB_BOOSTS = {
    0: (1.0, 1.0),
    1: (1.0, 1.0),      # was (0.85, 1.5) — removed for ToS compliance
    2: (1.0, 1.0),      # was (0.70, 2.0) — removed for ToS compliance
    3: (1.0, 1.0),      # was (0.50, 3.0) — removed for ToS compliance
    -1: (1.0, 1.0),
}


def _now() -> float:
    return time.time()


async def get_subscription_tier(channel_id: int, user_id: str) -> Optional[int]:
    """Returns subscription tier int (0/1/2/3) или None при unknown.

    Кэширует на 5 мин. None означает «не удалось проверить» — fallback на
    no-perk (защита от accidental fake-sub если Helix лажает).
    """
    if not user_id or not channel_id:
        return None
    key = (channel_id, str(user_id))
    cached = _SUB_CACHE.get(key)
    if cached and cached[1] > _now():
        # -1 is an internal negative-cache sentinel for "Helix unavailable",
        # never a public subscription tier.
        return None if cached[0] == -1 else cached[0]

    # Lazy import чтобы избежать circular
    from routes.streamer import get_fresh_oauth_token
    token = await get_fresh_oauth_token(channel_id)
    if not token:
        log.debug("[twitch_subs] no OAuth token для channel=%s — cache as unknown",
                  channel_id)
        _SUB_CACHE[key] = (-1, _now() + 60)   # короткий TTL для retry
        return None
    if not _TWITCH_CLIENT_ID:
        log.warning("[twitch_subs] TWITCH_CLIENT_ID not set — cannot check subs")
        return None

    url = (f"https://api.twitch.tv/helix/subscriptions"
           f"?broadcaster_id={channel_id}&user_id={user_id}")
    headers = {
        "Authorization": f"Bearer {token}",
        "Client-Id": _TWITCH_CLIENT_ID,
    }
    try:
        # Sprint 5.31 #45d (audit HIGH-8) — shared session вместо new-per-call.
        # Endpoint вызывается раз в 5 мин на каждого активного viewer'а ×
        # N каналов; новая сессия каждый раз = TCP/TLS handshake spam.
        from http_session import get_session
        session = await get_session()
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=5)) as r:
            if r.status == 401:
                body = await r.text()
                log.warning("[twitch_subs] 401 channel=%s user=%s — scope missing? "
                            "Streamer must re-OAuth. body=%s",
                            channel_id, user_id, body[:200])
                _SUB_CACHE[key] = (-1, _now() + 600)  # don't retry for 10 min
                return None
            if r.status == 403:
                log.warning("[twitch_subs] 403 channel=%s user=%s",
                            channel_id, user_id)
                _SUB_CACHE[key] = (0, _now() + _CACHE_TTL_SEC)
                return 0
            if r.status == 429:
                # Sprint 5.31 #45c — explicit rate-limit branch.
                # Back off 2 минуты вместо обычного TTL, тогда логи не
                # завалятся попытками retry.
                body = await r.text()
                log.warning("[twitch_subs] 429 RATE LIMITED ch=%s user=%s — "
                            "backing off 120s. body=%s",
                            channel_id, user_id, body[:200])
                _SUB_CACHE[key] = (-1, _now() + 120)
                return None
            if r.status != 200:
                body = await r.text()
                log.warning("[twitch_subs] HTTP %s ch=%s user=%s body=%s",
                            r.status, channel_id, user_id, body[:200])
                return None
            payload = await r.json()
            data = (payload or {}).get("data") or []
            if not data:
                # Not subscribed (200 + empty array)
                _SUB_CACHE[key] = (0, _now() + _CACHE_TTL_SEC)
                return 0
            # data[0].tier = "1000" | "2000" | "3000"
            tier_str = str(data[0].get("tier") or "1000")
            tier = {"1000": 1, "2000": 2, "3000": 3}.get(tier_str, 1)
            _SUB_CACHE[key] = (tier, _now() + _CACHE_TTL_SEC)
            log.info("[twitch_subs] ch=%s user=%s = tier %s (sub'd)",
                     channel_id, user_id, tier)
            return tier
    except Exception as ex:
        log.warning("[twitch_subs] network error ch=%s user=%s: %s",
                    channel_id, user_id, ex)
        return None


async def get_sub_boost(channel_id: int, user_id: str) -> Tuple[float, float]:
    """Returns (price_mult, reward_mult) для perk-tier system.

    Lookup'ит sub tier и mapped к multipliers. На unknown — no-perk fallback.
    """
    tier = await get_subscription_tier(channel_id, user_id)
    if tier is None:
        return SUB_BOOSTS[-1]
    return SUB_BOOSTS.get(tier, SUB_BOOSTS[0])


def invalidate_cache(channel_id: int = None, user_id: str = None) -> None:
    """Debug/admin: invalidate cache entries. Без args — clear all."""
    if channel_id is None:
        _SUB_CACHE.clear()
        return
    if user_id:
        _SUB_CACHE.pop((channel_id, str(user_id)), None)
        return
    # Clear all entries для channel
    to_drop = [k for k in _SUB_CACHE if k[0] == channel_id]
    for k in to_drop:
        _SUB_CACHE.pop(k, None)


def get_cache_stats() -> dict:
    """Telemetry: cache size + recent entries."""
    now = _now()
    fresh = sum(1 for _, exp in _SUB_CACHE.values() if exp > now)
    stale = len(_SUB_CACHE) - fresh
    return {"total": len(_SUB_CACHE), "fresh": fresh, "stale": stale}
