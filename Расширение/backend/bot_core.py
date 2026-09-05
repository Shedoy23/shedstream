# bot_core.py - полная версия с поддержкой чат-сообщений для ивентов
import aiosqlite
import asyncio
import aiohttp
import hashlib
import logging
import random
import time
from collections import deque
from datetime import datetime, timedelta, date
from typing import Dict, Optional, Tuple
import os

logger = logging.getLogger('rimlink.bot')

from database import Database
from dependencies import resolve_channel_id
from config import (
    ACTIVE_WINDOW,
    ENGAGED_WINDOW,
    REDUCED_WINDOW,
    AUTO_MESSAGE_TICK_SEC,
    AUTO_MESSAGES_ENABLED,
    CACHE_EVICTION_INTERVAL,
    CHAT_BONUS_COOLDOWN_SEC,
    CHAT_BONUS_DEDUP_WINDOW,
    CHAT_BONUS_BASE,
    CHAT_BONUS_MAX,
    CHAT_BONUS_MIN_CHARS,
    CHAT_BONUS_PER_CHARS,
    CHECK_INTERVAL,
    DROP_BLACKLIST,
    DROP_CHANCE,
    DROP_INTERVAL,
    CASE_TIER_REWARDS,
    HOURLY_CASE_INTERVAL,
    HOURLY_CASE_LURKER_TIER,
    HOURLY_CASE_TIERS,
    DROP_LURKER_WEIGHT,
    PERFORMANCE_CONFIG,
    POINTS_PER_MINUTE,
    QUEST_ORDER,
    QUESTS_CONFIG,
    RIMWORLD_COMMANDS_PATH,
    RIMWORLD_REFUNDS_PATH,
    TWITCH_STREAM_CHANNEL,
)

# Константы для квестов
WATCH_TIME_QUESTS = ['watch_time_30', 'watch_time_60', 'watch_time_120',
                     'watch_time_180', 'watch_time_240', 'watch_time_300']

# Phase 6 (2026-05-11): дропы выдают КЕЙСЫ (а не items как раньше).
# Старая DROP_ITEMS = [(имя, вес, редкость)] удалена — items больше нет в
# системе (Phase 1.B/1.C: crafting и рынок вырезаны).
#
# Tier weights для drop'ов: 70/25/4/1 (compliance §5.3 — free RNG-loot box,
# содержимое без monetary value т.к. крустики non-tradable).
DROP_CASE_TIERS = [
    ('common',    70),
    ('rare',      25),
    ('epic',      4),
    ('legendary', 1),
]

# DROP_BLACKLIST импортируется из config.py (настраивается через .env)

class Cache:
    """Простой кэш с TTL (из твоего бота)"""
    def __init__(self, ttl=300):
        self.cache = {}
        self.ttl = ttl
        self._last_eviction = datetime.now()

    def get(self, key):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if (datetime.now() - timestamp).total_seconds() < self.ttl:
                return value
            # Запись устарела — удаляем сразу
            del self.cache[key]
        # Периодическая чистка всего кэша (раз в 10 минут)
        if (datetime.now() - self._last_eviction).total_seconds() > CACHE_EVICTION_INTERVAL:
            now = datetime.now()
            expired = [k for k, (_, ts) in self.cache.items()
                       if (now - ts).total_seconds() >= self.ttl]
            for k in expired:
                del self.cache[k]
            self._last_eviction = now
        return None
    
    def set(self, key, value):
        self.cache[key] = (value, datetime.now())
    
    def invalidate(self, key):
        if key in self.cache:
            del self.cache[key]

class BotCore:
    def __init__(self, db: Database):
        self.db = db
        # In-memory presence trace: (channel_id, username) → datetime.
        # Multi-tenant invariant: один и тот же ник на двух каналах должен
        # быть РАЗНЫМИ записями. Раньше ключом был только username — alice
        # из канала А перезаписывала alice из канала Б. После M5 (per-channel
        # rate limits + блок 1/2 архитектурной прокачки) — обязательно tuple.
        self.viewers_last_active: Dict[Tuple[int, str], datetime] = {}
        self.running = True
        self.twitch_bot = None  # Будет установлен из main.py
        # Очередь сообщений в чат, накопленных до подключения IRC.
        # Если event_watcher_loop завершит ивент раньше чем start_twitch_bot
        # вызовет event_ready(), send_message раньше молча писал только в лог —
        # сообщение до Twitch не доходило. Теперь буферим и флашим при connect.
        self._pending_chat_messages: list = []
        self._pending_chat_limit = 50

        # Кэш для бонусов
        self._bonus_cache = Cache(ttl=PERFORMANCE_CONFIG['cache_ttl'])

        # Ивент менеджер

        # Розыгрыши
        self.last_raffle = datetime.min

        # Пути для RimWorld
        self.rimworld_commands_file = RIMWORLD_COMMANDS_PATH
        self.rimworld_refunds_file = RIMWORLD_REFUNDS_PATH

        # Текущий stream_id per-channel (Bug 4 fix, 2026-05-10).
        # Раньше было `current_stream_id: str = ""` — единое глобальное состояние,
        # которое после регистрации 2-го стримера ломало и stream_session, и
        # streak'и (все каналы делили один stream_id). Теперь это
        # Dict[channel_id, stream_id] — каждый канал крутит свой день.
        # Доступ через self.get_current_stream_id(channel_id) /
        # self.set_current_stream_id(channel_id, stream_id).
        self.current_stream_id: Dict[int, str] = {}

        # Per-channel кэш проверки стрима через Helix API.
        # Раньше было два скалярных поля _stream_live_cache/_stream_live_checked
        # — это означало, что проверка одного канала "пробивала" кэш всем.
        # Теперь key = channel_id, value = (is_live: bool, checked_ts: float).
        self._stream_live_cache: Dict[int, Tuple[bool, float]] = {}
        # Настоящий id стрима из Helix, по каналам. Нужен, чтобы опросчик и
        # EventSub заводили ОДНУ сессию, а не две (см. _session_id_for).
        self._stream_ext_id: Dict[int, str] = {}

        # ── Chat-bonus антифрод (M7) ─────────────────────────────────────────
        # State per (channel_id, username):
        #   - last_bonus_at: datetime последнего начисленного бонуса
        #   - recent_hashes: deque последних N хешей сообщений (для dedup)
        # Триггеры which прерывают bonus:
        #   1. Cooldown < CHAT_BONUS_COOLDOWN_SEC от последнего бонуса
        #   2. len(text) < CHAT_BONUS_MIN_CHARS — слишком короткое
        #   3. hash(text) уже в recent_hashes — повтор/спам
        self._chat_bonus_last_at: Dict[Tuple[int, str], datetime] = {}
        self._chat_bonus_recent_hashes: Dict[Tuple[int, str], deque] = {}

        # Кэш app-токена Twitch — токен живёт ~60 дней (shared всеми каналами)
        self._twitch_app_token: str = ""
        self._twitch_app_token_expires: float = 0.0

        logger.info("BotCore инициализирован")
    
    # ===== АКТИВНОСТЬ ЗРИТЕЛЯ =====
    #
    # Источник правды — БД `viewers.last_seen`. In-memory словарь
    # `viewers_last_active` (ключ: (channel_id, username)) живёт как
    # write-through кэш: обновляется синхронно с БД, но _reward_points/
    # _process_drop читают из БД — это переживает рестарт и закрывает
    # расхождение с admin view.
    #
    # Multi-tenant: ключ — tuple (channel_id, username), не просто username.
    # Один ник на двух каналах = ДВЕ независимые записи.
    def update_viewer_presence(self, username: str, channel_id: int):
        """Быстрое in-memory касание для heartbeat handlers.

        DB-запись в этих горячих путях делают сами роуты (INSERT … ON CONFLICT),
        мы тут только обновляем память и кэш бонусов.
        """
        if not username or not channel_id:
            return
        self.viewers_last_active[(int(channel_id), username.lower())] = datetime.now()
        self._bonus_cache.invalidate(f"bonus_{int(channel_id)}_{username.lower()}")

    def update_viewer_chat(self, username: str, channel_id: int):
        """Alias для чат-handler'ов — семантика та же что presence."""
        if not username or not channel_id:
            return
        self.viewers_last_active[(int(channel_id), username.lower())] = datetime.now()
        self._bonus_cache.invalidate(f"bonus_{int(channel_id)}_{username.lower()}")

    async def touch_viewer(self, username: str, channel_id: int = None):
        """Единая точка для любого действия пользователя (спин/ставка/покупка/…).

        Пишет в память И в БД (upsert last_seen, is_afk=0). Используется
        из action-эндпоинтов — там нет собственного INSERT INTO viewers.

        channel_id может быть None — fallback через resolve_channel_id (strict).
        """
        if not username:
            return
        channel_id = resolve_channel_id(channel_id)
        username = username.lower()
        now = datetime.now()
        self.viewers_last_active[(int(channel_id), username)] = now
        self._bonus_cache.invalidate(f"bonus_{int(channel_id)}_{username}")
        try:
            async with self.db._connect() as conn:
                await conn.execute("""
                    INSERT INTO viewers (channel_id, username, last_seen, is_afk, join_time)
                    VALUES (?, ?, datetime('now'), 0, datetime('now'))
                    ON CONFLICT(channel_id, username) DO UPDATE SET
                        last_seen = datetime('now'),
                        is_afk    = 0
                """, (channel_id, username))
                await conn.commit()
        except Exception as e:
            logger.debug("touch_viewer db write failed for %s: %s", username, e)

    # ===== CHAT-BONUS АНТИФРОД (M7) =====
    def compute_chat_bonus(self, channel_id: int, username: str, text: str) -> int:
        """Сколько поинтов начислить за чат-сообщение, с антифрод-проверками.

        Возвращает 0 если:
          - len(text) < CHAT_BONUS_MIN_CHARS (10) — слишком короткое
          - cooldown < CHAT_BONUS_COOLDOWN_SEC (10s) от последнего бонуса этому
            (channel, user) — анти-флуд
          - hash(text) уже видели в последних CHAT_BONUS_DEDUP_WINDOW (10) сообщениях
            этого user'а на этом канале — анти copy-paste

        Иначе: min(CHAT_BONUS_BASE + len(text) // CHAT_BONUS_PER_CHARS, CHAT_BONUS_MAX)
        и обновляет state. State per (channel_id, username), in-memory.
        """
        if not text or not username or not channel_id:
            return 0
        if len(text) < CHAT_BONUS_MIN_CHARS:
            return 0

        key = (int(channel_id), username.lower())
        now = datetime.now()

        # Cooldown
        last_at = self._chat_bonus_last_at.get(key)
        if last_at and (now - last_at).total_seconds() < CHAT_BONUS_COOLDOWN_SEC:
            return 0

        # Dedup. Нормализуем текст: lower + collapse whitespace, чтобы
        # "Привет" и "приВЕТ   " были одним хешем.
        normalized = " ".join(text.lower().split())
        msg_hash = hashlib.md5(normalized.encode("utf-8", errors="replace")).hexdigest()
        recent = self._chat_bonus_recent_hashes.get(key)
        if recent is None:
            recent = deque(maxlen=CHAT_BONUS_DEDUP_WINDOW)
            self._chat_bonus_recent_hashes[key] = recent
        if msg_hash in recent:
            return 0

        # Bonus eligible — записываем state и возвращаем сумму.
        recent.append(msg_hash)
        self._chat_bonus_last_at[key] = now
        # База за сам факт реплики + плата за длину, с общим потолком.
        # База нужна потому, что живой разговор состоит и из коротких реплик:
        # без неё «ага» и «жёстко» стоили почти ничего, и экономика поощряла
        # писать длинно, а не говорить.
        return min(CHAT_BONUS_BASE + len(text) // CHAT_BONUS_PER_CHARS,
                   CHAT_BONUS_MAX)

    def _twitch_bot_ready(self) -> bool:
        """IRC-бот подключён и умеет слать? Используется как гейт для send."""
        tb = self.twitch_bot
        if tb is None:
            return False
        # M4 follow-up (в): default_channel — первый из join'нутых каналов.
        # До event_ready() get_channel() возвращает None → message drop.
        default_ch = getattr(tb, '_default_channel', None) or getattr(tb, '_channel', None)
        if not default_ch:
            return False
        try:
            return tb.get_channel(default_ch) is not None
        except Exception:
            # На старых версиях twitchio get_channel может не существовать —
            # в этом случае ограничимся проверкой атрибутов.
            return True

    def _resolve_send_target(self, channel_id: Optional[int]) -> Optional[str]:
        """M4 follow-up (в): channel_id → channel_login для twitchio bot.

        Приоритет:
          1. Явный channel_id параметр
          2. ContextVar (`resolve_channel_id_or_default` идёт в DEFAULT — но мы
             хотим именно ContextVar здесь, а DEFAULT уже резолвится в default_channel
             на уровне TwitchChatBot.send_message → нет смысла дублировать).
        Возвращает None если каналу нет login-mapping → caller передаст None
        в TwitchChatBot.send_message и тот отдаст в default_channel (legacy
        single-tenant поведение).
        """
        from dependencies import (
            get_channel_login_by_id,
            _current_channel_id,
        )
        cid = channel_id
        if cid is None or cid <= 0:
            cid = _current_channel_id.get()
        if cid is None or cid <= 0:
            return None
        return get_channel_login_by_id(int(cid))

    async def send_message(self, message: str, channel_id: Optional[int] = None):
        """Отправить сообщение в чат Twitch.

        M4 follow-up (в): channel_id опциональный. Если задан или есть в
        ContextVar — sлать в соответствующий канал; иначе legacy default
        (= TwitchChatBot._default_channel = первый из реестра).

        Если IRC-бот ещё не подключился (ранний старт или переподключение) —
        складываем в очередь с привязанным target_login. Флашим при:
          1) TwitchChatBot.event_ready() — сразу после коннекта
          2) Следующем успешном send_message (opportunistic)
          3) Периодическом pending_chat_flush_loop (safety net каждые 15с)
        """
        target_login = self._resolve_send_target(channel_id)
        try:
            if self._twitch_bot_ready():
                # Прежде чем слать текущее — добить хвост, чтобы сохранить порядок
                # событий по времени их возникновения (critical для "АУКЦИОН ЗАВЕРШЁН"
                # перед "АУКЦИОН СТАРТОВАЛ").
                if self._pending_chat_messages:
                    await self.flush_pending_chat()
                await self.twitch_bot.send_message(message, channel_login=target_login)
            else:
                # IRC не готов — буферим (с капом на антизатопление памяти).
                if len(self._pending_chat_messages) < self._pending_chat_limit:
                    self._pending_chat_messages.append((message, target_login))
                    print(f"📢 [CHAT QUEUED #{target_login or 'default'}] {message}")
                else:
                    print(f"📢 [CHAT DROPPED] очередь полна ({self._pending_chat_limit}): {message}")
        except Exception as e:
            logger.warning("Ошибка отправки сообщения: %s", e)

    async def flush_pending_chat(self):
        """Отправляет всё что накопилось пока IRC был не готов.

        Вызывается из:
          * TwitchChatBot.event_ready() — сразу после коннекта
          * send_message() — opportunistic при следующем успешном send
          * pending_chat_flush_loop() — фоновая safety net
        """
        if not self._pending_chat_messages:
            return
        if not self._twitch_bot_ready():
            return
        pending = self._pending_chat_messages[:]
        self._pending_chat_messages.clear()
        logger.info("Flushing %d pending chat messages", len(pending))
        for entry in pending:
            # M4 follow-up (в): backward-compat — старые str-записи (если что-то
            # положилось до апгрейда) трактуем как target=None (= default).
            if isinstance(entry, tuple):
                msg, target_login = entry
            else:
                msg, target_login = entry, None
            try:
                await self.twitch_bot.send_message(msg, channel_login=target_login)
                print(f"📢 [CHAT FLUSHED #{target_login or 'default'}] {msg}")
            except Exception as e:
                logger.warning("flush_pending_chat send fail: %s", e)
                # Не теряем сообщение — возвращаем в начало очереди.
                self._pending_chat_messages.insert(0, (msg, target_login))
                break

    async def pending_chat_flush_loop(self):
        """Фоновая safety net: раз в 15с добиваем очередь если IRC готов.

        Нужна потому что event_ready() запускается ровно один раз при первом
        коннекте; если сообщение поставилось в очередь позже (гонка / повторный
        коннект / transient IRC-глитч) — без этого цикла оно бы висело.
        """
        logger.info("pending_chat_flush_loop запущен (interval=15s)")
        while self.running:
            await asyncio.sleep(15)
            try:
                if self._pending_chat_messages and self._twitch_bot_ready():
                    await self.flush_pending_chat()
            except Exception as e:
                logger.debug("pending_chat_flush_loop iteration failed: %s", e)
    
    # ===== STREAM_ID HELPERS (Bug 4 fix, multi-tenant) =====
    def get_current_stream_id(self, channel_id: Optional[int] = None) -> str:
        """Текущий stream_id для канала. Пустая строка если канал не в live.

        channel_id=None → resolve через ContextVar (single-channel легаси-вызовы
        и HTTP-роуты, которые вытаскивают канал из JWT).
        """
        cid = resolve_channel_id(channel_id)
        return self.current_stream_id.get(cid, "")

    def set_current_stream_id(self, channel_id: int, stream_id: str) -> None:
        if not channel_id:
            return
        if stream_id:
            self.current_stream_id[int(channel_id)] = stream_id
        else:
            self.current_stream_id.pop(int(channel_id), None)

    # ===== MATCHMAKING LOOP (Phase 5.0, 2026-05-11) =====
    async def matchmaking_loop(self):
        """Цикл matchmaking: каждые 5 сек по всем каналам и game_types
        ищет пары игроков в очереди по близкому ELO.

        Generic — обслуживает все game_types зарегистрированные в очереди.
        Game-specific game-state initialization после match (если нужна) —
        делается game-specific endpoint'ами при первом submit_move.
        """
        from config import MATCHMAKING_INTERVAL, MATCHMAKING_GAME_TYPES
        logger.info("Matchmaking loop запущен (interval=%ds, games=%s)",
                    MATCHMAKING_INTERVAL, MATCHMAKING_GAME_TYPES)
        while self.running:
            await asyncio.sleep(MATCHMAKING_INTERVAL)
            try:
                channels = await self.db.list_channels()
            except Exception as e:
                logger.warning("matchmaking_loop: list_channels failed: %s", e)
                continue

            for ch in channels:
                cid = ch["channel_id"]
                for game_type in MATCHMAKING_GAME_TYPES:
                    try:
                        pairs = await self.db.find_match_pairs(cid, game_type)
                        if pairs > 0:
                            logger.info("[ch=%s/%s] matched %d pair(s)",
                                        cid, game_type, pairs)
                    except Exception as e:
                        logger.warning("[ch=%s/%s] find_match_pairs failed: %s",
                                       cid, game_type, e)

    # ===== VOTING LOOP (Phase 4, 2026-05-11) =====
    async def voting_loop(self):
        """Voting background loop:
          1. Finalize expired active events (ends_at прошёл)
          2. Auto-start event на каналах с pool >= threshold + default template
          3. Broadcast vote_tick для всех active events (Phase C, 2026-05-17)

        Применяя async-python-patterns:
          - structured error handling (per-iteration try/except не валит loop)
          - cooperative cancellation: sleep между tick'ами
          - generic loop interval VOTING_LOOP_INTERVAL (10s default)
        """
        from config import VOTING_LOOP_INTERVAL, VOTING_POOL_THRESHOLD
        from pubsub import broadcast as _pubsub_broadcast
        logger.info("Voting loop запущен (interval=%ds, threshold=%d)",
                    VOTING_LOOP_INTERVAL, VOTING_POOL_THRESHOLD)
        while self.running:
            await asyncio.sleep(VOTING_LOOP_INTERVAL)

            # 1. Finalize expired
            try:
                expired = await self.db.find_expired_voting_events()
                for evt in expired:
                    event_id = evt["event_id"]
                    cid = evt["channel_id"]
                    try:
                        result = await self.db.finalize_voting_event(event_id, channel_id=cid)
                        if result.get("finalized"):
                            winner = result.get("winner_option")
                            outcome = result.get("outcome")
                            if winner:
                                msg = (f"🏆 Голосование завершено! Победил «{winner['label']}» "
                                       f"({winner['pool']:,}💎)")
                            else:
                                msg = "🗳️ Голосование завершено: никто не голосовал"
                            try:
                                await self.send_message(msg, channel_id=cid)
                            except Exception as e:
                                logger.warning("voting_loop chat-notify failed: %s", e)
                            # Phase C: broadcast vote_ended — frontend мгновенно покажет
                            # winner modal без следующего polling.
                            try:
                                _pubsub_broadcast(cid, "vote_ended", {
                                    "event_id": event_id,
                                    "outcome": outcome,
                                    "winner": winner,  # {id, key, label, pool} | None
                                })
                            except Exception as e:
                                logger.warning("voting_loop pubsub vote_ended failed: %s", e)
                            logger.info("[ch=%s] voting event %s finalized: %s",
                                        cid, event_id, outcome)
                    except Exception as e:
                        logger.warning("[ch=%s] voting finalize failed (event %s): %s",
                                       cid, event_id, e)
            except Exception as e:
                logger.warning("voting_loop expired-events tick failed: %s", e)

            # 2. Auto-start на каналах с готовностью
            try:
                ready = await self.db.find_channels_ready_for_voting(VOTING_POOL_THRESHOLD)
                for ch in ready:
                    cid = ch["channel_id"]
                    tpl_id = ch["default_template_id"]
                    try:
                        result = await self.db.start_voting_event(tpl_id, channel_id=cid)
                        if result.get("started"):
                            try:
                                await self.send_message(
                                    f"🗳️ Стартовало голосование «{result['template_name']}»! "
                                    f"Кидайте крустики на свой вариант — у тебя 5 минут.",
                                    channel_id=cid,
                                )
                            except Exception:
                                pass
                            # Phase C: broadcast vote_started — frontend сразу
                            # рендерит UI без ожидания poll-tick'а.
                            try:
                                # Fetch full state с options (frontend применит сразу).
                                state = await self.db.get_active_voting_event(channel_id=cid)
                                if state:
                                    _pubsub_broadcast(cid, "vote_started", {
                                        "event_id":      state["event_id"],
                                        "template_name": state["template_name"],
                                        "ends_at":       state["ends_at"],
                                        "total_pool":    state["total_pool"],
                                        "options":       state["options"],
                                    })
                            except Exception as e:
                                logger.warning("voting_loop pubsub vote_started failed: %s", e)
                            logger.info("[ch=%s] voting event auto-started: template=%s",
                                        cid, tpl_id)
                    except Exception as e:
                        logger.warning("[ch=%s] voting auto-start failed: %s", cid, e)
            except Exception as e:
                logger.warning("voting_loop auto-start tick failed: %s", e)

            # 3. Phase C: broadcast vote_tick для всех active events (1 раз/10s).
            # Дополнительно immediate vote_tick fire'ится после каждого bid
            # в routes/voting.py — это даёт <1s latency при активном торге.
            try:
                active_channels = await self.db.list_channels()
                for ch in active_channels:
                    cid = int(ch["channel_id"])
                    state = await self.db.get_active_voting_event(channel_id=cid)
                    if not state:
                        continue
                    try:
                        _pubsub_broadcast(cid, "vote_tick", {
                            "event_id":   state["event_id"],
                            "total_pool": state["total_pool"],
                            "options": [
                                {"id": o["id"], "pool": o["pool"]}
                                for o in state["options"]
                            ],
                        })
                    except Exception as e:
                        logger.warning("voting_loop pubsub vote_tick failed: %s", e)
            except Exception as e:
                logger.warning("voting_loop vote_tick fanout failed: %s", e)

    # ===== НАЧИСЛЕНИЕ ОЧКОВ =====
    async def reward_points_loop(self):
        """Цикл начисления очков (каждую минуту), multi-tenant.

        Bug 4 fix (2026-05-10): раньше цикл обслуживал один глобальный канал
        (TWITCH_STREAM_CHANNEL) и один глобальный current_stream_id. После
        регистрации 2-го стримера это ломало streak/attendance/session.

        Теперь: на каждом тике берём db.list_channels() и обрабатываем
        каждый зарегистрированный канал независимо — свой is_live, своя
        сессия, свой stream_id, своё начисление.
        """
        logger.info("Цикл начисления запущен (multi-tenant)")
        was_live: Dict[int, bool] = {}
        while self.running:
            await asyncio.sleep(CHECK_INTERVAL)
            try:
                channels = await self.db.list_channels()
            except Exception as e:
                logger.warning("reward_points_loop: list_channels упал: %s", e)
                continue

            today_id = date.today().isoformat()
            for ch in channels:
                channel_id = ch["channel_id"]
                login = (ch.get("login") or "").lower().strip()
                try:
                    is_live = await self._is_stream_live(channel_id=channel_id, login=login)
                except Exception as e:
                    logger.warning("is_stream_live(%s) упал: %s", login or channel_id, e)
                    continue

                # 2026-07-30 (аудит спеки §6). Раньше под try стоял ТОЛЬКО
                # _is_stream_live, а начисление — нет. Одно исключение из
                # _reward_points / handle_stream_start / _refresh_presence
                # вылетало из for, из while и убивало задачу НАВСЕГДА: зрители
                # переставали получать крустики за просмотр до рестарта бэка, и
                # ни одного сигнала об этом не появлялось. Ровно так уже
                # умирали награды за очки Twitch (мертвы с 8 июля, заметили 27-го).
                # Плохой тик обязан стоить одного тика, а не всей механики.
                try:
                    prev_live = was_live.get(channel_id, False)
                    prev_sid  = self.current_stream_id.get(channel_id, "")
                    # 2026-08-06: id сессии — НАСТОЯЩИЙ id стрима, если Helix
                    # его дал. Дата остаётся запасным вариантом. Почему это
                    # важно — см. _session_id_for.
                    session_id = self._session_id_for(channel_id, today_id)
                    if is_live:
                        # Сценарии регистрации сессии:
                        #   1. Первый вход в live после старта сервера
                        #   2. Смена даты (стрим пересёк полночь)
                        #   3. Возобновление стрима в тот же день (второй стрим)
                        if not prev_live or prev_sid != session_id:
                            await self.handle_stream_start(session_id, channel_id=channel_id)
                            logger.info(
                                "[ch=%s/%s] Автостарт/возобновление: %s (prev=%s, was_live=%s)",
                                channel_id, login or "?", session_id, prev_sid or "none", prev_live)
                        was_live[channel_id] = True
                        # 2026-06-06 PRESENCE-WATCHTIME (за флагом) — пометить
                        # present-зрителей по списку чата Twitch ДО начисления, чтобы
                        # серверный _reward_points выдал им очки + watch_time (мобайл).
                        await self._refresh_presence_from_chat(channel_id, login)
                        await self._reward_points(channel_id)
                    else:
                        # Переход live→offline: закрываем сессию.
                        if prev_live and prev_sid:
                            try:
                                await self.db.end_stream_session(prev_sid, channel_id=channel_id)
                                logger.info("[ch=%s] Стрим %s завершён (ended_at выставлен)",
                                            channel_id, prev_sid)
                            except Exception as e:
                                logger.warning("end_stream_session(%s,%s) failed: %s",
                                               channel_id, prev_sid, e)
                        was_live[channel_id] = False
                        logger.debug("[ch=%s/%s] не в эфире — пропускаем",
                                     channel_id, login or "?")
                except Exception:
                    # exception() — со стеком: молчаливая смерть этого цикла
                    # стоила бы всей экономики канала, причину надо видеть сразу.
                    logger.exception(
                        "[ch=%s/%s] тик начисления упал — цикл продолжает работу",
                        channel_id, login or "?")

    async def _is_stream_live(
        self,
        channel_id: Optional[int] = None,
        login: Optional[str] = None,
    ) -> bool:
        """Проверить через Twitch Helix API, идёт ли стрим на канале.

        channel_id=None → resolve через ContextVar (HTTP-роуты, single-channel
        легаси-вызовы). login можно передать явно — экономит lookup в БД,
        пригождается reward_points_loop'у который и так из list_channels()
        тащит и login и channel_id.

        Кэш per-channel (TTL=300с): раньше было два скалярных поля и проверка
        одного канала пробивала кэш всему миру.

        Phase A (2026-05-16): EventSub `stream.online`/`stream.offline` пишут
        cache мгновенно. Polling остался как fallback на случай потерянного
        EventSub event'а — TTL поднят с 120с до 300с (Helix calls -2.5×).
        """
        cid = resolve_channel_id(channel_id)
        now = datetime.now().timestamp()

        cached = self._stream_live_cache.get(cid)
        if cached is not None and now - cached[1] < 300:
            return cached[0]

        # Резолвим login: явно передан → используем; иначе db.get_channel; иначе fallback
        if not login:
            try:
                ch = await self.db.get_channel(cid)
                if ch:
                    login = (ch.get("login") or "").lower().strip()
            except Exception:
                login = None
        channel = (login or TWITCH_STREAM_CHANNEL).lower().strip()

        client_id     = os.getenv("TWITCH_CLIENT_ID", "")
        client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            # Если ключей нет — не блокируем начисление, просто предупреждаем
            logger.warning("TWITCH_CLIENT_ID/SECRET не заданы — проверка стрима пропущена")
            self._stream_live_cache[cid] = (True, now)
            return True

        try:
            async with aiohttp.ClientSession() as session:
                if not self._twitch_app_token or now > self._twitch_app_token_expires:
                    async with session.post("https://id.twitch.tv/oauth2/token", params={
                        "client_id":     client_id,
                        "client_secret": client_secret,
                        "grant_type":    "client_credentials",
                    }) as r:
                        token_data = await r.json()
                        self._twitch_app_token = token_data.get("access_token", "")
                        self._twitch_app_token_expires = now + min(
                            token_data.get("expires_in", 86400), 86400
                        )
                app_token = self._twitch_app_token
                if not app_token:
                    raise ValueError("Не удалось получить app-токен")

                # Запрашиваем статус стрима
                async with session.get(
                    f"https://api.twitch.tv/helix/streams?user_login={channel}",
                    headers={"Client-ID": client_id, "Authorization": f"Bearer {app_token}"}
                ) as r:
                    data = await r.json()
                    streams = data.get("data", [])
                    is_live = len(streams) > 0
                    stream_info = streams[0] if is_live else None

            # Transition detect для нотификаций: ранее (cached[0]) был False,
            # сейчас стал True → fire TG notify (Phase 8.G).
            was_live = cached[0] if cached is not None else None
            self._stream_live_cache[cid] = (is_live, now)
            # Запоминаем настоящий id стрима: под ним же сессию заводит
            # EventSub, и только совпадение id не даёт появиться второй.
            if is_live and stream_info and stream_info.get("id"):
                self._stream_ext_id[cid] = str(stream_info["id"])
            elif not is_live:
                self._stream_ext_id.pop(cid, None)
            logger.info("Стрим [ch=%s] %s: %s", cid, channel,
                        'В ЭФИРЕ' if is_live else 'офлайн')

            if is_live and was_live is False and stream_info:
                # Стрим только что стартовал. Шлём TG нотификацию (no-op
                # если TELEGRAM_* не настроены в .env).
                try:
                    from notifications import notify_stream_online
                    asyncio.create_task(notify_stream_online(
                        channel_id=cid,
                        login=channel,
                        title=stream_info.get("title"),
                        game=stream_info.get("game_name"),
                    ))
                except Exception as e:
                    logger.warning("TG hook upstream error: %s", e)

            return is_live

        except Exception as e:
            logger.warning("Ошибка проверки стрима [ch=%s]: %s — продолжаем без блокировки",
                           cid, e)
            self._stream_live_cache[cid] = (True, now)   # при ошибке не блокируем
            return True
    
    async def _refresh_presence_from_chat(self, channel_id: int, login: str):
        """2026-06-06 PRESENCE-WATCHTIME (за флагом PRESENCE_WATCHTIME_ENABLED).

        Лечит мобайл-перекос: на мобайле Twitch душит heartbeat расширения, и
        зрители-лёркеры выпадали из last_seen → теряли очки/уровень. Здесь по
        списку реально присутствующих в чате (channel.chatters от twitchio
        membership) обновляем last_seen (→ _reward_points даёт очки) + кредитуем
        watch_time (→ уровень). Кредитуем ТОЛЬКО существующих юзеров расширения
        (UPDATE по viewers — 0 строк если записи нет). Полностью изолировано:
        любая ошибка логируется и НЕ роняет reward_points_loop.
        """
        try:
            from config import PRESENCE_WATCHTIME_ENABLED
        except Exception:
            return
        if not PRESENCE_WATCHTIME_ENABLED:
            return
        tb = getattr(self, "twitch_bot", None)
        if tb is None or not login:
            return
        try:
            ch = tb.get_channel(login)
            if ch is None:
                return
            raw = getattr(ch, "chatters", None) or []
            bot_nick = (getattr(tb, "nick", "") or "").lower()
            names = set()
            for c in raw:
                n = getattr(c, "name", None)
                if n is None and isinstance(c, str):
                    n = c
                if not n:
                    continue
                n = str(n).lower().strip()
                if n and n != bot_nick:
                    names.add(n)
            if not names:
                return
            credited = 0
            async with self.db._connect() as conn:
                for n in names:
                    cur = await conn.execute(
                        "UPDATE viewers SET last_seen=datetime('now'), is_afk=0 "
                        "WHERE channel_id=? AND username=?",
                        (channel_id, n))
                    if getattr(cur, "rowcount", 0) and cur.rowcount > 0:
                        await conn.execute(
                            "INSERT INTO activity_stats (channel_id, username, watch_time) "
                            "VALUES (?, ?, ?)",
                            (channel_id, n, CHECK_INTERVAL))
                        credited += 1
                await conn.commit()
            if credited:
                logger.info("[ch=%s] presence-watchtime: credited %d/%d chatters",
                            channel_id, credited, len(names))
        except Exception as e:
            logger.warning("[ch=%s] presence-watchtime refresh failed: %s", channel_id, e)

    async def _reward_points(self, channel_id: Optional[int] = None):
        """Начислить очки зрителям по статусу активности (per-channel).

        Bug 4 fix (2026-05-10): теперь принимает channel_id и фильтрует
        viewers WHERE channel_id = ?. Раньше шёл по всему viewers без
        фильтра — на одиночном канале ОК, после регистрации 2-го стримера
        начислял всем сразу даже если только один канал в эфире.

        Источник правды — БД `viewers.last_seen`. По возрасту (age):
          age < ACTIVE_WINDOW                  → "active",  100% очков
          ACTIVE_WINDOW ≤ age < REDUCED_WINDOW → "reduced", 50%  очков
          age ≥ REDUCED_WINDOW                 → "offline", 0    (пропускаем)

        is_afk synchronization тоже per-channel — чтобы офлайн-канал не
        перетирал статусы в эфирном.
        """
        cid = resolve_channel_id(channel_id)
        now = datetime.now()

        # 1. Читаем активных с last_seen в пределах REDUCED_WINDOW для ЭТОГО канала.
        try:
            async with self.db._connect() as conn:
                cursor = await conn.execute(
                    """
                    SELECT username,
                           CAST((julianday('now') - julianday(last_seen)) * 86400 AS INTEGER) AS age_sec,
                           CASE WHEN last_interaction_at IS NULL THEN NULL
                                ELSE CAST((julianday('now') - julianday(last_interaction_at)) * 86400 AS INTEGER)
                           END AS interact_age_sec
                    FROM   viewers
                    WHERE  channel_id = ?
                       AND last_seen >= datetime('now', ?)
                    """,
                    (cid, f"-{REDUCED_WINDOW} seconds"),
                )
                rows = await cursor.fetchall()
        except Exception as e:
            logger.warning("[ch=%s] Чтение активных из БД упало: %s", cid, e)
            rows = []

        # 2. Уборка in-memory мусора (TTL 30 мин) для записей этого канала.
        offline_cutoff = now - timedelta(seconds=REDUCED_WINDOW)
        for k in [k for k, t in self.viewers_last_active.items()
                  if t < offline_cutoff and k[0] == cid]:
            del self.viewers_last_active[k]
            _, uname = k
            self._bonus_cache.invalidate(f"bonus_{cid}_{uname}")

        # 3. Классификация + начисление. Phase 4: incrementим voting pool
        # = active_count units per minute (1 unit/min/active viewer).
        from config import VOTING_POOL_PER_WATCH_MIN
        active_count = reduced_count = 0
        for username, age_sec, interact_age_sec in rows:
            if age_sec >= REDUCED_WINDOW:
                continue

            # item_bonus убран 2026-05-13 (Phase 8.C): items больше не дают
            # passive income (§5.3 cosmetic-only). Только level-bonus остаётся.
            level_data = await self.db.get_user_level(username, channel_id=cid)
            level_info = self.db.get_level_info(level_data['level'])
            level_pct  = level_info.get('bonus_pct', 0)

            total_points = int(POINTS_PER_MINUTE * (1 + level_pct / 100))

            # 2026-08-23. Полная ставка требует ДВУХ вещей: панель на связи
            # (свежий last_seen) И недавнее действие зрителя — клик/движение в
            # панели либо сообщение в чат. Раньше хватало первого, то есть
            # открытая вкладка приносила столько же, сколько просмотр.
            #
            # Половина, а НЕ ноль, — намеренно: на мобильном мышью не двигают,
            # и честный лёркер не должен быть наказан за устройство. Ровно из-за
            # этого перекоса в июне заводили PRESENCE_WATCHTIME_ENABLED.
            engaged = interact_age_sec is not None and interact_age_sec < ENGAGED_WINDOW
            if age_sec < ACTIVE_WINDOW and engaged:
                status = "active"
                active_count += 1
            else:
                status = "reduced"
                total_points //= 2
                reduced_count += 1

            await self.db.add_points(username, total_points, channel_id=cid)
            # Учёт источника (m117): на триаже видно, сколько дал просмотр
            # «со вниманием», а сколько — открытая вкладка.
            await self.db.record_income(
                cid, username,
                "watch_full" if status == "active" else "watch_half",
                total_points)

            # Квесты watch_time идут по ПРИСУТСТВИЮ, а не по вовлечённости.
            #
            # 2026-08-23. Раньше здесь стояло `status == "active"`, и это
            # было верно, пока «активный» значило просто «панель на связи».
            # В тот день я поменял смысл слова — полная ставка стала требовать
            # взаимодействия — и эта строка молча превратилась во второе
            # наказание: зритель с открытой вкладкой терял не половину ставки,
            # а ещё и все квесты на просмотр. За 5-часовой эфир это 3 600💎
            # вместо 45 000, то есть падение в 12 раз вместо обещанного вдвое.
            #
            # Класс ошибки: поменял значение флага, а читателя в другом месте
            # не проверил. Ставка зависит от вовлечённости, цели дня — от того,
            # что человек всё-таки был на эфире.
            for quest in WATCH_TIME_QUESTS:
                await self._update_quest_progress(username, quest, 1, channel_id=cid)

        # 4. Voting pool increment: active viewers × VOTING_POOL_PER_WATCH_MIN
        #    (1 unit/min/viewer). Auto-start подхватит voting_loop когда threshold.
        if active_count > 0:
            try:
                await self.db.increment_voting_pool(
                    cid, active_count * VOTING_POOL_PER_WATCH_MIN
                )
            except Exception as e:
                logger.debug("voting pool increment failed: %s", e)

        # 5. is_afk sync — per-channel (раньше было WHERE без фильтра, что
        #    при offline-канале ставило is_afk=1 ВСЕМ зрителям всех каналов).
        try:
            async with self.db._connect() as conn:
                await conn.execute(
                    """
                    UPDATE viewers SET is_afk = CASE
                        WHEN last_seen >= datetime('now', ?) THEN 0
                        ELSE 1
                    END
                    WHERE channel_id = ?
                    """,
                    (f"-{REDUCED_WINDOW} seconds", cid),
                )
                await conn.commit()
        except Exception as e:
            logger.warning("[ch=%s] Sync is_afk упал: %s", cid, e)

        total = active_count + reduced_count
        if total > 0:
            print(
                f"💰 [ch={cid}] Награда: active={active_count} (100%), "
                f"reduced={reduced_count} (50%)"
            )
    
    async def _get_viewer_bonus(self, username: str, channel_id: int = None) -> int:
        """Получить бонус от предметов"""
        channel_id = resolve_channel_id(channel_id)
        cache_key = f"bonus_{channel_id}_{username}"
        cached = self._bonus_cache.get(cache_key)
        if cached is not None:
            return cached

        inventory = await self.db.get_inventory(username, channel_id=channel_id)
        bonus = sum(item['bonus'] * item['quantity'] for item in inventory)

        self._bonus_cache.set(cache_key, bonus)
        return bonus

    # ===== ОБНОВЛЕНИЕ КВЕСТОВ (УЛУЧШЕННАЯ ВЕРСИЯ) =====
    async def _update_quest_progress(self, username: str, quest_type: str, increment: int, channel_id: int = None):
        """Обновить прогресс квеста с поддержкой всех типов"""
        channel_id = resolve_channel_id(channel_id)
        today = date.today().isoformat()
        username = username.lower()

        async with self.db._connect() as conn:
            cursor = await conn.execute(
                "SELECT id, current_value, target_value, completed_at FROM quests WHERE channel_id = ? AND username = ? AND quest_type = ? AND day_date = ?",
                (channel_id, username, quest_type, today)
            )
            row = await cursor.fetchone()

            if not row:
                # Создаём новый квест, если его нет
                if quest_type not in QUESTS_CONFIG:
                    return

                config = QUESTS_CONFIG[quest_type]
                target = config['target']
                reward_points = config['reward_points']
                reward_item = config.get('reward_item')

                # Квест может закрыться первым же событием. Отметка «завершён» и
                # награда обязаны лечь ОДНИМ коммитом (S-18): раньше строка
                # вставлялась и коммитилась без completed_at, а награда шла
                # отдельным соединением — сбой в окне съедал награду, а
                # незаполненный completed_at, наоборот, платил за тот же квест
                # повторно на следующем событии.
                done_now = increment >= target
                cur = await conn.execute("""
                    INSERT OR IGNORE INTO quests
                    (channel_id, username, quest_type, target_value, current_value, reward_points, reward_item_id, day_date, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
                """, (channel_id, username, quest_type, target, increment, reward_points, None, today, done_now))
                if cur.rowcount == 0:
                    # Параллельное событие успело создать строку — его прогресс
                    # уже учтён там, платить второй раз нельзя.
                    await conn.commit()
                    return
                if done_now and reward_points:
                    await self.db.add_points_tx(conn, username, reward_points, channel_id)
                await conn.commit()

                if done_now:
                    await self._grant_quest_extras(username, quest_type, reward_item, channel_id=channel_id)
                return

            quest_id, current, target, completed = row
            if completed:
                return

            new_value = min(current + increment, target)
            await conn.execute(
                "UPDATE quests SET current_value = ? WHERE id = ?",
                (new_value, quest_id)
            )

            if new_value >= target:
                config = QUESTS_CONFIG.get(quest_type, {})
                reward_points = config.get('reward_points', 0)
                reward_item = config.get('reward_item')

                # Отметка «завершён» и начисление — одной транзакцией (S-18).
                # `completed_at IS NULL` работает замком от гонки: второй
                # одновременный обработчик получит rowcount=0 и не заплатит
                # второй раз (воспроизведено тестом: 8 гонщиков платили дважды).
                cur = await conn.execute(
                    "UPDATE quests SET completed_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND completed_at IS NULL",
                    (quest_id,)
                )
                if cur.rowcount == 0:
                    await conn.commit()
                    return
                if reward_points:
                    await self.db.add_points_tx(conn, username, reward_points, channel_id)
                await conn.commit()

                # Учёт источника (m117) — ПОСЛЕ коммита: статистика не должна
                # ни держать замок кассы, ни отменять уже выданную награду.
                if reward_points:
                    await self.db.record_income(
                        channel_id, username, "quest", reward_points)

                await self._grant_quest_extras(username, quest_type, reward_item, channel_id=channel_id)
                logger.info("Квест %s завершён для @%s", quest_type, username)
            else:
                await conn.commit()

    async def _grant_quest_extras(self, username: str, quest_type: str, reward_item: Optional[str], channel_id: int = None):
        """Неденежные хвосты награды за квест: предмет и кейс.

        Крустики начисляются НЕ здесь, а в одной транзакции с отметкой
        `completed_at` (S-18) — иначе награда терялась при сбое в окне.
        """
        channel_id = resolve_channel_id(channel_id)

        # Выдаём предмет, если есть
        if reward_item:
            await self.db.give_item(username, reward_item, channel_id=channel_id)
            logger.info("Предмет %s выдан @%s за квест %s", reward_item, username, quest_type)

        # Phase 2 (2026-05-11): за завершённый квест выдаём обычный кейс.
        # Идемпотентность через quests.day_date — один квест в день =>
        # один кейс в день per quest_type. Re-grant защищён через DB UNIQUE
        # пары (quest, day_date) в quests table.
        try:
            case_result = await self.db.grant_case(
                username, tier='common', source='quest', channel_id=channel_id
            )
            if case_result.get('granted'):
                logger.info("Common case granted to @%s за quest %s", username, quest_type)
        except Exception as e:
            # Не критично — quest награда уже выдана. Логируем для диагностики.
            logger.warning("grant_case (quest %s, @%s) failed: %s", quest_type, username, e)

    # ===== СПЕЦИАЛИЗИРОВАННЫЕ МЕТОДЫ ДЛЯ КВЕСТОВ =====
    # Раньше здесь были `_update_quests_by_type`, `update_chat_quest_progress`,
    # `update_activity_quest_progress` — удалены в M7 как dead code:
    #   - никем не вызывались (chat-tick'и идут напрямую из IRC `event_message`,
    #     watch_time-tick'и идут из `_reward_points`)
    #   - reference на несуществующий quest 'active_viewer' (никогда не был в
    #     QUESTS_CONFIG)
    #   - update_activity_quest_progress использовал quest_type='activity' который
    #     отсутствовал в config (только 'time' и 'chat' существуют)
    # Если потребуется bulk-tick по типу — лучше создать pure helper иммутабельно.

    # ===== ДРОПЫ =====
    async def hourly_case_loop(self):
        """Раз в час каждому активному зрителю — кейс (решение владельца 05.09).

        Отдельно от drop_loop: тот выдаёт ОДНОМУ случайному и умеет легендарку,
        этот выдаёт ВСЕМ и легендарку не выдаёт (иначе она перестала бы быть
        событием — расчёт в config.HOURLY_CASE_TIERS).
        """
        logger.info("Цикл часовых кейсов запущен (каждые %d мин)",
                    HOURLY_CASE_INTERVAL // 60)
        while self.running:
            await asyncio.sleep(HOURLY_CASE_INTERVAL)
            try:
                channels = await self.db.list_channels()
            except Exception as e:
                logger.warning("hourly_case_loop: list_channels упал: %s", e)
                continue
            for ch in channels:
                try:
                    await self._process_hourly_cases(channel_id=ch["channel_id"])
                except Exception as e:
                    logger.warning("hourly cases [ch=%s] failed: %s",
                                   ch.get("channel_id"), e)

    async def _process_hourly_cases(self, channel_id: Optional[int] = None):
        """Выдать всем активным по кейсу и отчитаться в чат одной строкой.

        Идемпотентность через trigger_key `hourly_<ГГГГММДДЧЧ>`: перезапуск
        сервиса или второй проход в тот же час НЕ выдаст кейс повторно —
        кейс это деньги, а не уведомление.
        """
        cid = resolve_channel_id(channel_id)
        if not await self._is_stream_live(channel_id=cid):
            return

        # Те же два признака, что и у дропа: свежий last_seen — «панель на
        # связи», взаимодействие — отдельная колонка. Смешивать их нельзя,
        # иначе брошенная вкладка фармит редкие кейсы (28.08).
        try:
            async with self.db._connect() as conn:
                cursor = await conn.execute(
                    "SELECT username, "
                    "CASE WHEN last_interaction_at IS NULL THEN NULL "
                    "     ELSE CAST((julianday('now') - julianday(last_interaction_at)) * 86400 AS INTEGER) "
                    "END AS interact_age_sec "
                    "FROM viewers "
                    "WHERE channel_id = ? AND last_seen >= datetime('now', ?)",
                    (cid, f"-{ACTIVE_WINDOW} seconds"),
                )
                rows = await cursor.fetchall()
        except Exception as e:
            logger.warning("[ch=%s] Часовые кейсы: чтение активных упало: %s", cid, e)
            return

        stamp = datetime.now().strftime("%Y%m%d%H")
        tiers = [t[0] for t in HOURLY_CASE_TIERS]
        weights = [t[1] for t in HOURLY_CASE_TIERS]
        granted: dict = {}
        lucky: list = []

        for uname, interact_age_sec in rows:
            if uname.lower() in DROP_BLACKLIST:
                continue
            engaged = (interact_age_sec is not None
                       and interact_age_sec < ENGAGED_WINDOW)
            tier = (random.choices(tiers, weights=weights)[0]
                    if engaged else HOURLY_CASE_LURKER_TIER)
            try:
                result = await self.db.grant_case(
                    uname, tier=tier, source='drop', channel_id=cid,
                    trigger_key=f"hourly_{stamp}")
            except Exception as e:
                logger.warning("[ch=%s] Часовой кейс @%s не выдан: %s", cid, uname, e)
                continue
            if result.get('granted'):
                granted[tier] = granted.get(tier, 0) + 1
                if tier == 'legendary':
                    lucky.append(uname)

        if not granted:
            return

        # Легендарка — отдельной строкой и с ником: она выпадает примерно раз в
        # месяц, и потеряться в общей сводке ей нельзя (владелец: «тому, кому
        # выпала, — прям праздник»).
        for uname in lucky:
            await self.send_message(
                f"👑 @{uname} ЛЕГЕНДАРНЫЙ кейс! "
                f"{CASE_TIER_REWARDS['legendary']:,}💎 внутри — такое выпадает раз в месяц!"
                .replace(",", " "), channel_id=cid)

        labels = (('common', 'обычных'), ('rare', 'редких'),
                  ('epic', 'эпических'), ('legendary', 'ЛЕГЕНДАРНЫХ'))
        parts = [f"{name} {granted[key]}" for key, name in labels if granted.get(key)]
        await self.send_message(
            "🎁 Часовые кейсы: выдано " + ", ".join(parts)
            + ". Открывай в расширении!", channel_id=cid)
        logger.info("[ch=%s] Часовые кейсы: %s (всего %d)",
                    cid, granted, sum(granted.values()))

    async def drop_loop(self):
        """Цикл дропов (multi-tenant): каждый канал в эфире — свой dice-roll."""
        logger.info("Цикл дропов запущен (каждые %d мин, multi-tenant)",
                    DROP_INTERVAL // 60)
        while self.running:
            await asyncio.sleep(DROP_INTERVAL)
            try:
                channels = await self.db.list_channels()
            except Exception as e:
                logger.warning("drop_loop: list_channels упал: %s", e)
                continue
            for ch in channels:
                try:
                    await self._process_drop(channel_id=ch["channel_id"])
                except Exception as e:
                    logger.warning("drop iteration [ch=%s] failed: %s",
                                   ch.get("channel_id"), e)

    async def _process_drop(self, channel_id: Optional[int] = None):
        """Обработать дроп для одного канала.

        Phase 6 (2026-05-11): вместо item'а выдаёт КЕЙС случайного тира
        (DROP_CASE_TIERS weights 70/25/4/1). Юзер потом открывает кейс
        в UI → получает фиксированные крустики per tier.

        Compliance §5.3: free RNG-loot box, content без monetary value
        (наша валюта non-tradable).

        Bug 4 fix (2026-05-10): принимает channel_id явно — раньше тащил
        активных из ВСЕХ каналов и send_message шёл в "default" канал.
        """
        cid = resolve_channel_id(channel_id)
        if not await self._is_stream_live(channel_id=cid):
            return
        if random.random() > DROP_CHANCE:
            return

        cutoff = datetime.now() - timedelta(seconds=ACTIVE_WINDOW)
        # Свежий last_seen = «панель на связи», и только. Взаимодействие —
        # отдельный признак, иначе брошенная вкладка тянет кейсы у зрителя
        # (замер 28.08 — комментарий к DROP_LURKER_WEIGHT в config.py).
        weights: list = []
        try:
            async with self.db._connect() as conn:
                cursor = await conn.execute(
                    "SELECT username, "
                    "CASE WHEN last_interaction_at IS NULL THEN NULL "
                    "     ELSE CAST((julianday('now') - julianday(last_interaction_at)) * 86400 AS INTEGER) "
                    "END AS interact_age_sec "
                    "FROM viewers "
                    "WHERE channel_id = ? AND last_seen >= datetime('now', ?)",
                    (cid, f"-{ACTIVE_WINDOW} seconds"),
                )
                rows = await cursor.fetchall()
            active = []
            for uname, interact_age_sec in rows:
                if uname.lower() in DROP_BLACKLIST:
                    continue
                active.append(uname)
                engaged = (interact_age_sec is not None
                           and interact_age_sec < ENGAGED_WINDOW)
                weights.append(1.0 if engaged else DROP_LURKER_WEIGHT)
        except Exception as e:
            logger.warning("[ch=%s] Drop: чтение активных из БД упало: %s", cid, e)
            # Память не хранит взаимодействие — на запасном пути все равны.
            active = [
                u for (k_cid, u), t in self.viewers_last_active.items()
                if k_cid == cid and t > cutoff and u.lower() not in DROP_BLACKLIST
            ]
            weights = [1.0] * len(active)
        if not active:
            return

        # rename из 'lucky' 2026-05-12 (Phase 8.A.2 lexicon hygiene)
        recipient = random.choices(active, weights=weights)[0]
        engaged_n = sum(1 for w in weights if w == 1.0)
        logger.info("[ch=%s] Drop pool: %d на связи, из них %d взаимодействовали",
                    cid, len(active), engaged_n)

        # Выбор тира кейса по весам 70/25/4/1
        tier = random.choices(
            [t[0] for t in DROP_CASE_TIERS],
            weights=[t[1] for t in DROP_CASE_TIERS],
        )[0]

        result = await self.db.grant_case(
            recipient, tier=tier, source='drop', channel_id=cid
        )
        if not result.get('granted'):
            logger.warning("[ch=%s] Drop case grant failed for @%s: %s",
                           cid, recipient, result.get('reason'))
            return

        tier_emoji = {'common': '🎁', 'rare': '💎', 'epic': '💠', 'legendary': '👑'}.get(tier, '🎁')
        tier_label = {'common': 'обычный', 'rare': 'редкий', 'epic': 'эпический', 'legendary': 'легендарный'}.get(tier, tier)
        await self.send_message(
            f"{tier_emoji} @{recipient} получает {tier_label} кейс! "
            f"Открой через расширение!", channel_id=cid)
        logger.info("[ch=%s] DROP: @%s получил %s кейс (case_id=%s)",
                    cid, recipient, tier, result.get('case_id'))

        # on_drop overlay-hook сохранён для backward-compat с overlay.html.
        # Передаём tier как rarity для overlay-card; item_name больше нет —
        # передаём emoji+label чтобы overlay мог отрисовать что-то осмысленное.
        try:
            await self.on_drop(recipient, f"{tier_label} кейс", tier)
        except Exception as e:
            print(f"⚠️ Ошибка on_drop: {e}")

    # force_drop() удалён 2026-06-14 (audit) — админка read-only, ручной дроп убран.
    # Автоматический дроп идёт через _process_drop (drop-loop), он остаётся.

    # ===== КАЗИНО =====

    async def check_and_unlock_achievements(
        self,
        username: str,
        trigger: str,
        extra: dict = None,
        channel_id: Optional[int] = None,
    ) -> list:
        """Проверяет и выдаёт достижения по триггеру (per-channel).

        trigger: 'duel_win', 'rimworld_buy', 'watch_hours', 'level_up', 'streak'

        Note: 'casino' trigger удалён в Phase 1.A (2026-05-10) — casino-механика
        вырезана как gambling по §6.2.3 Twitch Extension Guidelines.
        Note: 'craft' trigger удалён в Phase 1.B (2026-05-10) — crafting механика
        вырезана как 3/3 gambling по §6.2.4 + §5.3.

        Bug 4 fix (2026-05-10): channel_id прокидывается в unlock_achievement
        и send_message. Раньше unlock_achievement брал канал через
        resolve_channel_id() (= ContextVar или fallback) — для HTTP-роутов
        это работало, но из reward_points_loop, где каналы итерируются
        вручную, нужен явный аргумент.
        """
        unlocked = []
        extra = extra or {}
        cid = resolve_channel_id(channel_id)

        async def _try(key):
            result = await self.db.unlock_achievement(username, key, channel_id=cid)
            if result:
                unlocked.append(result)
                await self.send_message(
                    f"🏆 @{username} получил достижение «{result['emoji']} {result['name']}»! +{result['reward']}💎",
                    channel_id=cid,
                )

        # Phase 2 (2026-05-11): helper для one-time case grants с
        # идемпотентным trigger_key — кейс не выдастся повторно за тот же
        # milestone (через case_triggers_fired table).
        async def _grant_milestone_case(tier: str, trigger_key: str):
            try:
                r = await self.db.grant_case(
                    username, tier=tier, source='watch_milestone' if tier == 'epic' else 'streak',
                    channel_id=cid, trigger_key=trigger_key,
                )
                if r.get('granted'):
                    tier_emoji = {'common': '🎁', 'rare': '💎', 'epic': '💠', 'legendary': '👑'}.get(tier, '🎁')
                    await self.send_message(
                        f"{tier_emoji} @{username} получил {tier} кейс за milestone «{trigger_key}»!",
                        channel_id=cid,
                    )
                    logger.info("%s case granted to @%s (trigger=%s)", tier, username, trigger_key)
            except Exception as e:
                logger.warning("milestone case grant failed (%s, %s, %s): %s",
                               username, tier, trigger_key, e)

        if trigger == 'duel_win':
            await _try('first_duel_win')
        elif trigger == 'rimworld_buy':
            await _try('first_rimworld_buy')
        elif trigger == 'watch_hours':
            hours = extra.get('hours', 0)
            if hours >= 10:  await _try('watch_10h')
            if hours >= 50:  await _try('watch_50h')
            if hours >= 100:
                await _try('watch_100h')
                # Phase 2: epic кейс единоразово за 100h просмотра
                await _grant_milestone_case('epic', 'watch_100h')
        elif trigger == 'level_up':
            level = extra.get('level', 0)
            if level >= 5:  await _try('level_5')
            if level >= 10: await _try('level_10')
            if level >= 20: await _try('level_20')
        elif trigger == 'streak':
            current = extra.get('current_streak', 0)
            max_s   = extra.get('max_streak', 0)
            if current >= 3:  await _try('streak_3')
            if current >= 5:  await _try('streak_5')
            if current >= 10:
                await _try('streak_10')
                # Phase 2: rare кейс единоразово за 10-стрик
                await _grant_milestone_case('rare', 'streak_10')
            if max_s >= 5:    await _try('max_streak_5')
            if max_s >= 10:   await _try('max_streak_10')

        return unlocked

    def _session_id_for(self, channel_id: int, today_id: str) -> str:
        """Под каким id заводить сессию стрима.

        ЗАЧЕМ (2026-08-06, жалоба владельца «стрики сбрасываются»).

        Сессию писали ДВА независимых места, и каждое своим способом:
        EventSub по `stream.online` — настоящим id стрима от Twitch, а этот
        опросчик — СЕГОДНЯШНЕЙ ДАТОЙ. Получалось две сессии на один эфир:
        короткий огрызок на секунды с нулём зрителей и рядом настоящая
        многочасовая.

        Цена ошибки — не косметика. Серия «N стримов подряд» считается как
        «сколько сессий началось между прошлой посещённой и этой»
        (`record_attendance`). Фантомная сессия попадала в этот счёт как
        ПРОПУЩЕННЫЙ стрим, поэтому серия обнулялась после каждого эфира.
        В базе на 06.08 это выглядело так: у всех `current_streak = 1` при
        5–15 посещённых стримах, и ни одного достижения за серию за всю
        историю (для первого нужно всего три подряд).

        Поэтому берём тот же id, что и EventSub: `register_stream_session`
        идемпотентен по (channel_id, id), и на один эфир остаётся одна строка.
        Дата — запасной вариант на случай, когда Helix id не отдал (тогда
        поведение прежнее, не хуже).
        """
        # Читаем через getattr намеренно. Цикл начислений ловит исключение
        # каждого тика и идёт дальше — значит `AttributeError` здесь не упал бы
        # громко, а тихо отменял бы НАЧИСЛЕНИЕ КРУСТИКОВ на каждом тике, и
        # заметили бы это по жалобам зрителей через недели. Ровно этот класс
        # ловит `tests/test_background_loops_survive.py`, и он поймал: первая
        # версия правки обращалась к полю напрямую и уронила все три сценария.
        ext = getattr(self, "_stream_ext_id", None) or {}
        return ext.get(int(channel_id)) or today_id

    async def handle_stream_start(self, stream_id: str, channel_id: Optional[int] = None):
        """Вызывается при старте стрима — регистрирует сессию для канала.

        channel_id=None → resolve_channel_id() (для совместимости с легаси-вызовами).
        """
        cid = resolve_channel_id(channel_id)
        self.set_current_stream_id(cid, stream_id)
        await self.db.register_stream_session(stream_id, channel_id=cid)
        logger.info("[ch=%s] Стрим зарегистрирован: %s", cid, stream_id)

    async def record_viewer_attendance(
        self,
        username: str,
        minutes: int,
        channel_id: Optional[int] = None,
    ) -> dict:
        """Записывает присутствие зрителя на канале. При 15+ мин выдаёт
        стрик-бонус и проверяет достижения.

        Bug 4 fix (2026-05-10): теперь принимает channel_id и берёт
        stream_id из per-channel dict. Раньше брал из глобального
        self.current_stream_id, что ломалось при 2+ каналах.
        """
        cid = resolve_channel_id(channel_id)
        stream_id = self.current_stream_id.get(cid, "")
        if not stream_id:
            # Память пуста (напр. бэк рестартанул посреди стрима). Если стрим реально
            # live — восстановим текущий stream_id из активной сессии в БД; иначе
            # минуты посещаемости/стрик молча терялись бы до следующего тика reward-loop.
            if await self._is_stream_live(cid):
                stream_id = await self.db.get_active_stream_id(cid)
                if stream_id:
                    self.set_current_stream_id(cid, stream_id)
        if not stream_id:
            return {"rewarded": False}

        result = await self.db.record_attendance(username, stream_id, minutes, channel_id=cid)

        if result.get("rewarded"):
            await self.check_and_unlock_achievements(username, 'streak', {
                'current_streak': result['current_streak'],
                'max_streak':     result['max_streak'],
            }, channel_id=cid)
            hours = await self.db.get_total_watch_hours(username, channel_id=cid)
            await self.check_and_unlock_achievements(
                username, 'watch_hours', {'hours': hours}, channel_id=cid)

        return result


    # casino_bet удалён в Phase 1.A (2026-05-10) — gambling по §6.2.3 Twitch Extension Guidelines.
    # См. COMPLIANCE_REWORK_PLAN.md §4 Phase 1 Removal pass.

    # ===== СТАТИСТИКА =====
    async def get_viewer_detailed_stats(self, username: str) -> dict:
        """Получить расширенную статистику зрителя"""
        points = await self.db.get_points(username)
        inventory = await self.db.get_inventory(username)
        quests = await self.db.get_quests(username)
        activity = await self.db.get_today_activity(username)
        chat = await self.db.get_today_chat_stats(username)
        
        return {
            "points": points,
            "inventory": inventory,
            "quests": quests,
            "activity": activity,
            "chat": chat,
        }
    
    # Оповещения об аукционе-ивенте («рулекцион») удалены 2026-07-29
    # вместе с самой механикой: она переписана в голосование за игру.

    async def on_drop(self, username: str, item_name: str, rarity: str):
        """Вызывается при дропе предмета — переопределяется в main.py"""
        pass

    # ===== ОСТАНОВ =====
    async def _get_bot_client_id(self) -> str:
        """Bot-токен может быть выпущен под сторонним client_id (напр.
        twitchtokengenerator) ≠ TWITCH_CLIENT_ID. Helix требует, чтобы Client-Id
        совпадал с токеном — берём «родной» client_id через /validate и кэшируем."""
        cached = getattr(self, "_bot_client_id", None)
        if cached:
            return cached
        token = os.getenv("TWITCH_OAUTH_TOKEN", "")
        if token.startswith("oauth:"):
            token = token[6:]
        if not token:
            return ""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://id.twitch.tv/oauth2/validate",
                                 headers={"Authorization": "OAuth " + token}) as r:
                    d = await r.json()
                    self._bot_client_id = d.get("client_id", "") or ""
        except Exception as e:
            logger.warning("[announce] validate (client_id) failed: %s", e)
            self._bot_client_id = ""
        return getattr(self, "_bot_client_id", "") or ""

    async def send_announcement(self, channel_id: int, message: str,
                                color: str = "purple") -> bool:
        """Отправить announce (по умолчанию фиолетовый) через Helix
        POST /chat/announcements. Бот должен быть МОДЕРОМ канала + токен иметь
        scope moderator:manage:announcements (проверено для shedoyrobot). IRC-
        команда /announce у Twitch deprecated (дропается) — поэтому только так.
        Fire-and-forget; ошибки логируются."""
        token = os.getenv("TWITCH_OAUTH_TOKEN", "")
        if token.startswith("oauth:"):
            token = token[6:]
        bot_id = os.getenv("TWITCH_BOT_ID", "")
        client_id = await self._get_bot_client_id()
        if not (token and bot_id and client_id):
            logger.warning("[announce] ch=%s skip — нет token/bot_id/client_id", channel_id)
            return False
        url = ("https://api.twitch.tv/helix/chat/announcements"
               f"?broadcaster_id={channel_id}&moderator_id={bot_id}")
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, headers={
                    "Authorization": "Bearer " + token,
                    "Client-Id": client_id,
                    "Content-Type": "application/json",
                }, json={"message": str(message)[:500], "color": color}) as r:
                    if r.status in (200, 204):
                        return True
                    body = await r.text()
                    logger.warning("[announce] ch=%s failed %s: %s",
                                   channel_id, r.status, body[:200])
                    return False
        except Exception as e:
            logger.warning("[announce] ch=%s error: %s", channel_id, e)
            return False

    async def auto_message_loop(self):
        """Цикл автосообщений (multi-tenant): на каждом тике обходим каналы
        и шлём auto-message в те, что в эфире.

        Bug 4 fix (2026-05-10): раньше шёл один _is_stream_live() и один
        send_message() в default — после регистрации 2-го стримера он либо
        слал ему чужие сообщения, либо игнорировал его эфир. Теперь индекс
        автосообщений тоже per-channel (разные каналы — разные «места»
        в плейлисте).
        """
        if not AUTO_MESSAGES_ENABLED:
            print("ℹ️ Автосообщения отключены")
            return

        print(f"💬 Цикл автосообщений запущен (тик {AUTO_MESSAGE_TICK_SEC}с, таймер у каждого сообщения свой)")
        while self.running:
            await asyncio.sleep(AUTO_MESSAGE_TICK_SEC)
            if not self.running:
                break
            try:
                channels = await self.db.list_channels()
            except Exception as e:
                print(f"⚠️ auto_message_loop list_channels: {e}")
                continue
            for ch in channels:
                cid = ch["channel_id"]
                login = (ch.get("login") or "").lower().strip()
                try:
                    if not await self._is_stream_live(channel_id=cid, login=login):
                        continue
                    due = await self._due_auto_message(cid)
                    if due is None:
                        continue
                    msg = due["text"]
                    # 2026-06-06 — /announcepurple ... → Helix announce (фиолетовый).
                    # IRC /announce у Twitch deprecated (молча дропается), поэтому
                    # шлём через POST /chat/announcements. Обычные сообщения — как раньше.
                    if msg.startswith("/announcepurple "):
                        await self.send_announcement(cid, msg[len("/announcepurple "):], color="purple")
                    elif msg.startswith("/announce "):
                        await self.send_announcement(cid, msg[len("/announce "):], color="primary")
                    else:
                        await self.send_message(msg, channel_id=cid)
                    await self.db.mark_auto_message_sent(cid, due["position"], time.time())
                except Exception as e:
                    print(f"⚠️ auto_message_loop [ch={cid}]: {e}")

    async def _due_auto_message(self, channel_id: int) -> Optional[dict]:
        """Какое автосообщение канала пора отправить прямо сейчас (или None).

        У каждого сообщения свой интервал, поэтому «очередь» — не круговой
        список, а «кто дольше всех просрочен».

        ВАЖНО про первый тик. У нового сообщения `last_sent_at` пуст, и если
        считать пустоту «просрочено давно», то на старте эфира разом станут
        готовы все сообщения и канал получит их пачкой — выглядит как спам, за
        это таймаутят бота. Поэтому пустое время мы не шлём, а ЗАВОДИМ: строка
        начинает отсчёт от текущего момента и прозвучит через свой интервал.

        За один тик уходит максимум ОДНО сообщение на канал — тот же запрет
        на пачку, но уже для случая, когда просрочено несколько.
        """
        try:
            rows = await self.db.get_channel_auto_messages(channel_id)
        except Exception as e:
            logger.warning("автосообщения ch=%s недоступны: %s", channel_id, e)
            return None

        now = time.time()
        best = None
        for row in rows:
            if not row["enabled"]:
                continue
            if row["last_sent_at"] is None:
                await self.db.mark_auto_message_sent(channel_id, row["position"], now)
                continue
            overdue = now - float(row["last_sent_at"]) - int(row["interval_min"]) * 60
            if overdue < 0:
                continue
            if best is None or overdue > best[0]:
                best = (overdue, row)
        return best[1] if best else None

    async def shutdown(self):
        """Остановка бота"""
        self.running = False
        logger.info("BotCore остановлен")
