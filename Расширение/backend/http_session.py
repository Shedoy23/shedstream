"""
http_session.py — shared aiohttp.ClientSession для всех outbound HTTP вызовов.

Sprint 5.31 #45d (audit HIGH-7,8) — раньше каждый запрос (twitch_subs sub-check,
Helix users-by-id, streamer OAuth refresh, pubsub send) создавал собственный
ClientSession через `async with aiohttp.ClientSession()`. Под нагрузкой (sub-poll
каждые 5 мин × N viewers × M channels) это давало connection churn factory:
TCP/TLS handshake + DNS lookup на каждый запрос, удерживая TIME_WAIT сокеты.

Module-level singleton с lazy init:
  - `get_session()` — async, idempotent, возвращает shared session
  - `close_session()` — async, вызывается из shutdown hook
  - thread-safety: asyncio.Lock на init

Использование в callsite:
  from http_session import get_session
  sess = await get_session()
  async with sess.get(url) as r:  # НЕ async with sess — иначе закроется!
      ...
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

log = logging.getLogger("rimlink.http_session")

_session: Optional[aiohttp.ClientSession] = None
_init_lock = asyncio.Lock()


async def get_session() -> aiohttp.ClientSession:
    """Return shared ClientSession, create on first call."""
    global _session
    if _session is not None and not _session.closed:
        return _session
    async with _init_lock:
        # Double-check после await — другой coroutine мог уже создать.
        if _session is not None and not _session.closed:
            return _session
        # Connector с разумными лимитами + keep-alive.
        connector = aiohttp.TCPConnector(
            limit=100,             # max total connections
            limit_per_host=20,     # avoid hammering Twitch/Boosty
            ttl_dns_cache=300,     # 5min DNS cache
            enable_cleanup_closed=True,
        )
        _session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30),
            # NB: per-call timeout всё ещё можно override'ить.
        )
        log.info("[http_session] shared ClientSession created "
                 "(limit=100, per_host=20)")
        return _session


async def close_session() -> None:
    """Close shared session — call from app shutdown hook."""
    global _session
    if _session is not None and not _session.closed:
        try:
            await _session.close()
            log.info("[http_session] shared ClientSession closed")
        except Exception as e:
            log.warning("[http_session] close failed: %s", e)
    _session = None
