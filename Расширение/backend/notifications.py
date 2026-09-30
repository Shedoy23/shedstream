"""
notifications.py — внешние нотификации (Telegram-канал на старте стрима).

Triggered:
  - transition False→True в bot_core._is_stream_live polling loop
    (2026-05-14, Phase 8.G)

Configuration через .env:
  TELEGRAM_BOT_TOKEN=123456:ABC-DEF...     # от @BotFather
  TELEGRAM_CHAT_ID=@channelname            # public channel: @-handle
                                          # или numerical -1001234567 для private
  TELEGRAM_NOTIFICATIONS_ENABLED=true      # feature flag (default false)

Anti-spam:
  - in-memory cache last-notified timestamp per channel
  - повторное «стрим начался» в течение TG_RENOTIFY_COOLDOWN секунд — skip
    (защита от flap-network / API hiccup)

Если TELEGRAM_BOT_TOKEN пуст — функция no-op, не ломает основной flow.
"""
import logging
import os
from typing import Optional

import aiohttp

from config import DEFAULT_CHANNEL_ID

logger = logging.getLogger("rimlink.notifications")

# Cooldown между «стрим начался» нотификациями (сек). Если стрим flap'нул —
# мы не спамим. 30 минут достаточно: реальный stream restart обычно дольше.
TG_RENOTIFY_COOLDOWN = 1800  # 30 мин

# In-memory state: last_notified[channel_id] = unix_ts
_last_notified: dict = {}


def _enabled() -> bool:
    """Возвращает True если notifications сконфигурированы и enabled."""
    if os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").lower() != "true":
        return False
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


async def notify_stream_online(
    channel_id: int,
    login: str,
    title: Optional[str] = None,
    game: Optional[str] = None,
) -> None:
    """Telegram-нотификация что стрим начался.

    Args:
        channel_id: для anti-spam state-key
        login: Twitch login (для https://twitch.tv/{login} ссылки)
        title: title стрима (опц)
        game: название игры (опц)

    Возвращает None всегда. Любые ошибки — logged, не пробрасываются.
    """
    import time

    if not _enabled():
        return

    # Telegram-канал в конфиге ОДИН на всю платформу, а функция зовётся для
    # любого канала, вышедшего в эфир. Значит без этой проверки эфир чужого
    # стримера анонсировался бы в Telegram владельца — его же аудитории.
    # Это тот же класс, что личные автосообщения в общем списке (m114).
    # Пока настройки TG не стали per-channel, оповещаем ровно один канал:
    # тот, кому этот Telegram принадлежит.
    owner_channel = os.getenv("TELEGRAM_NOTIFY_CHANNEL_ID", "").strip()
    try:
        owner_channel_id = int(owner_channel) if owner_channel else DEFAULT_CHANNEL_ID
    except ValueError:
        owner_channel_id = DEFAULT_CHANNEL_ID
    if int(channel_id) != int(owner_channel_id):
        logger.info(
            "TG notify skip: канал %s — не владелец этого Telegram (%s)",
            channel_id, owner_channel_id,
        )
        return

    # Anti-spam: ещё в cooldown?
    now = time.time()
    last = _last_notified.get(channel_id, 0)
    if now - last < TG_RENOTIFY_COOLDOWN:
        logger.debug("TG notify skip (cooldown): channel_id=%s", channel_id)
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return

    # Собираем сообщение
    lines = [f"🔴 <b>Стрим начался!</b>"]
    if title:
        lines.append(f"<i>{_escape_html(title)}</i>")
    if game:
        lines.append(f"🎮 {_escape_html(game)}")
    lines.append(f'🔗 <a href="https://twitch.tv/{login}">twitch.tv/{login}</a>')
    text = "\n\n".join(lines)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    _last_notified[channel_id] = now
                    logger.info("TG notify sent: channel=%s login=%s", channel_id, login)
                else:
                    body = await r.text()
                    logger.warning("TG notify failed [%s]: %s", r.status, body[:200])
    except Exception as e:
        logger.warning("TG notify error: %s: %s", type(e).__name__, e)


# ---------- личка владельцу платформы: новый стример ждёт одобрения (30.09.2026) ----------
# Повод: проверяющий Twitch (qa_moderation) зарегистрировал свой канал на ревью и
# упёрся в ворота одобрения, а узнать об этом можно было только из строки в логе.
# Кому писать — TELEGRAM_OWNER_CHAT_ID (числовой id лички; бот не может написать по
# @нику, пока человек сам не нажал /start у бота). Это НЕ канал анонсов стримов.
_owner_notified: set = set()


def owner_message(login: str, channel_id: int, approve_url: Optional[str]) -> str:
    lines = [
        "🆕 <b>Новый стример ждёт одобрения</b>",
        f'<a href="https://twitch.tv/{_escape_html(login)}">{_escape_html(login)}</a> · канал {int(channel_id)}',
    ]
    if login.lower().startswith("qa_"):
        lines.append("Похоже на проверяющего Twitch — лучше одобрить сразу.")
    if approve_url:
        lines.append(f'<a href="{_escape_html(approve_url)}">✅ Одобрить</a>')
    return "\n".join(lines)


async def _post_telegram(token: str, chat_id: str, text: str) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status != 200:
                logger.warning("TG owner notify failed [%s]: %s", r.status, (await r.text())[:200])
            return r.status == 200


async def notify_owner_new_streamer(login: str, channel_id: int, approve_url: Optional[str]) -> bool:
    """Личка владельцу о заявке. Один раз на канал за жизнь процесса: стример,
    повторно проходящий вход, не должен слать по сообщению на каждый заход."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_OWNER_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning("TG owner notify skip: нет TELEGRAM_OWNER_CHAT_ID — заявка %s видна только в логе", login)
        return False
    if int(channel_id) in _owner_notified:
        return False
    try:
        ok = await _post_telegram(token, chat_id, owner_message(login, channel_id, approve_url))
    except Exception as e:
        logger.warning("TG owner notify error: %s: %s", type(e).__name__, e)
        return False
    if ok:
        _owner_notified.add(int(channel_id))
        logger.info("TG owner notified: new streamer %s (%s)", login, channel_id)
    return ok


def _escape_html(s: str) -> str:
    """Минимальный HTML-escape для Telegram parse_mode=HTML."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
