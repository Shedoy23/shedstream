# bot_core.py - полная версия с поддержкой чат-сообщений для ивентов
import aiosqlite
import asyncio
import aiohttp
import logging
import random
from datetime import datetime, timedelta, date
from typing import Dict, Optional
import os

logger = logging.getLogger('rimlink.bot')

from database import Database
from event_manager import EventManager
from config import (
    ACTIVE_WINDOW,
    REDUCED_WINDOW,
    AUTO_MESSAGE_INTERVAL,
    AUTO_MESSAGES,
    AUTO_MESSAGES_ENABLED,
    CACHE_EVICTION_INTERVAL,
    CASINO_CONFIG,
    CHECK_INTERVAL,
    DROP_BLACKLIST,
    DROP_CHANCE,
    DROP_INTERVAL,
    EVENT_CONFIG,
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

# Предметы для дропа: (имя, вес, редкость)
DROP_ITEMS = [
    ('деревяшка', 70, 'common'),
    ('камень', 20, 'uncommon'),
    ('амулет', 8, 'rare'),
    ('корона', 2, 'epic')
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
        # Единый словарь: последнее действие (чат ИЛИ activity)
        self.viewers_last_active: Dict[str, datetime] = {}
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
        self.event_manager = EventManager(self, db)
        
        # Данные для казино
        self.casino_total_bets = 0
        self.casino_cooldown_until = datetime.min
        self.casino_cooldown_duration = CASINO_CONFIG['cooldown_duration']
        self.casino_threshold = CASINO_CONFIG['cooldown_threshold']

        
        # Розыгрыши
        self.last_raffle = datetime.min
        
        # Внимание (тревога)
        self.last_attention: Dict[str, datetime] = {}
        
        # Пути для RimWorld
        self.rimworld_commands_file = RIMWORLD_COMMANDS_PATH
        self.rimworld_refunds_file = RIMWORLD_REFUNDS_PATH
        
        # Статистика активности (для предотвращения спама)
        self.last_activity_update: Dict[str, datetime] = {}
        self.current_stream_id: str = ""   # устанавливается при старте стрима

        self.last_chat_update: Dict[str, datetime] = {}
        
        # Кэш проверки стрима (instance-level, не class-level)
        self._stream_live_cache: bool = False
        self._stream_live_checked: float = 0.0
        # Кэш app-токена Twitch — токен живёт ~60 дней
        self._twitch_app_token: str = ""
        self._twitch_app_token_expires: float = 0.0

        logger.info("BotCore инициализирован")
    
    # ===== АКТИВНОСТЬ ЗРИТЕЛЯ =====
    #
    # Источник правды — БД `viewers.last_seen`. In-memory словарь
    # `viewers_last_active` живёт как write-through кэш: обновляется
    # синхронно с БД, но _reward_points/_process_drop читают из БД —
    # это переживает рестарт и закрывает расхождение с admin view.
    def update_viewer_presence(self, username: str):
        """Быстрое in-memory касание для heartbeat/chat handlers.

        DB-запись в этих горячих путях делают сами роуты (INSERT … ON CONFLICT),
        мы тут только обновляем память и кэш бонусов.
        """
        self.viewers_last_active[username] = datetime.now()
        self._bonus_cache.invalidate(f"bonus_{username}")

    def update_viewer_chat(self, username: str):
        """Alias для чат-handler'ов — семантика та же что presence."""
        self.viewers_last_active[username] = datetime.now()
        self._bonus_cache.invalidate(f"bonus_{username}")

    async def touch_viewer(self, username: str):
        """Единая точка для любого действия пользователя (спин/ставка/покупка/…).

        Пишет в память И в БД (upsert last_seen, is_afk=0). Используется
        из action-эндпоинтов — там нет собственного INSERT INTO viewers.
        """
        if not username:
            return
        username = username.lower()
        now = datetime.now()
        self.viewers_last_active[username] = now
        self._bonus_cache.invalidate(f"bonus_{username}")
        try:
            async with self.db._connect() as conn:
                await conn.execute("""
                    INSERT INTO viewers (username, last_seen, is_afk, join_time)
                    VALUES (?, datetime('now'), 0, datetime('now'))
                    ON CONFLICT(username) DO UPDATE SET
                        last_seen = datetime('now'),
                        is_afk    = 0
                """, (username,))
                await conn.commit()
        except Exception as e:
            logger.debug("touch_viewer db write failed for %s: %s", username, e)

    def _twitch_bot_ready(self) -> bool:
        """IRC-бот подключён и умеет слать? Используется как гейт для send."""
        tb = self.twitch_bot
        if tb is None or not hasattr(tb, '_channel'):
            return False
        # twitchio держит канал в кэше только после event_ready.
        # До коннекта get_channel() вернёт None → message drop.
        try:
            return tb.get_channel(tb._channel) is not None
        except Exception:
            # На старых версиях twitchio get_channel может не существовать —
            # в этом случае ограничимся проверкой атрибутов.
            return True

    async def send_message(self, message: str):
        """Отправить сообщение в чат Twitch.

        Если IRC-бот ещё не подключился (ранний старт или переподключение) —
        складываем в очередь. Флашим при:
          1) TwitchChatBot.event_ready() — сразу после коннекта
          2) Следующем успешном send_message (opportunistic)
          3) Периодическом pending_chat_flush_loop (safety net каждые 15с)
        """
        try:
            if self._twitch_bot_ready():
                # Прежде чем слать текущее — добить хвост, чтобы сохранить порядок
                # событий по времени их возникновения (critical для "АУКЦИОН ЗАВЕРШЁН"
                # перед "АУКЦИОН СТАРТОВАЛ").
                if self._pending_chat_messages:
                    await self.flush_pending_chat()
                await self.twitch_bot.send_message(message)
                print(f"📢 [CHAT] {message}")
            else:
                # IRC не готов — буферим (с капом на антизатопление памяти).
                if len(self._pending_chat_messages) < self._pending_chat_limit:
                    self._pending_chat_messages.append(message)
                    print(f"📢 [CHAT QUEUED] {message}")
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
        for msg in pending:
            try:
                await self.twitch_bot.send_message(msg)
                print(f"📢 [CHAT FLUSHED] {msg}")
            except Exception as e:
                logger.warning("flush_pending_chat send fail: %s", e)
                # Не теряем сообщение — возвращаем в начало очереди.
                self._pending_chat_messages.insert(0, msg)
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
    
    # ===== НАЧИСЛЕНИЕ ОЧКОВ =====
    async def reward_points_loop(self):
        """Цикл начисления очков (каждую минуту)"""
        logger.info("Цикл начисления запущен")
        _was_live = False
        while self.running:
            await asyncio.sleep(CHECK_INTERVAL)
            is_live = await self._is_stream_live()
            if is_live:
                # Авторегистрируем сессию в трёх сценариях:
                #   1. Первый вход в live после старта сервера (_was_live=False)
                #   2. Смена даты (стрим пересёк полночь)
                #   3. Возобновление стрима в тот же день (второй стрим — после
                #      паузы; register_stream_session сбрасывает ended_at=NULL,
                #      иначе get_streak считал бы этот день "завершённым" и
                #      жёг зрителям стрик прямо во время второго стрима)
                from datetime import date
                today_id = date.today().isoformat()  # напр. "2025-01-15"
                if not _was_live or self.current_stream_id != today_id:
                    await self.handle_stream_start(today_id)
                    logger.info("Автостарт/возобновление стрима: %s (prev=%s, was_live=%s)",
                                today_id, self.current_stream_id or "none", _was_live)
                _was_live = True
                await self._reward_points()
            else:
                # Переход live→offline: закрываем сессию (ended_at=now).
                # Это маркер «стрим прошёл» — get_streak будет считать её
                # завершённой и сжигать стрик зрителям, которые её не засчитали.
                if _was_live and self.current_stream_id:
                    try:
                        await self.db.end_stream_session(self.current_stream_id)
                        logger.info("Стрим %s завершён (ended_at выставлен)",
                                    self.current_stream_id)
                    except Exception as e:
                        logger.warning("end_stream_session failed: %s", e)
                _was_live = False
                logger.debug("Стрим %s не в эфире — начисление пропущено", TWITCH_STREAM_CHANNEL)

    async def _is_stream_live(self) -> bool:
        """Проверить через Twitch Helix API, идёт ли стрим на канале TWITCH_STREAM_CHANNEL"""
        from datetime import datetime
        now = datetime.now().timestamp()
        # Используем кэш чтобы не спамить API каждую минуту
        if now - self._stream_live_checked < 120:
            return self._stream_live_cache

        client_id     = os.getenv("TWITCH_CLIENT_ID", "")
        client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
        channel       = TWITCH_STREAM_CHANNEL.lower().strip()

        if not client_id or not client_secret:
            # Если ключей нет — не блокируем начисление, просто предупреждаем
            logger.warning("TWITCH_CLIENT_ID/SECRET не заданы — проверка стрима пропущена")
            self._stream_live_cache   = True
            self._stream_live_checked = now
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
                    is_live = len(data.get("data", [])) > 0

            self._stream_live_cache   = is_live
            self._stream_live_checked = now
            logger.info("Стрим %s: %s", channel, 'В ЭФИРЕ' if is_live else 'офлайн')
            return is_live

        except Exception as e:
            logger.warning("Ошибка проверки стрима: %s — продолжаем без блокировки", e)
            self._stream_live_cache   = True   # при ошибке не блокируем
            self._stream_live_checked = now
            return True
    
    async def _reward_points(self):
        """Начислить очки зрителям по статусу активности.

        Источник правды — БД `viewers.last_seen`. По возрасту (age):
          age < ACTIVE_WINDOW                  → "active",  100% очков
          ACTIVE_WINDOW ≤ age < REDUCED_WINDOW → "reduced", 50%  очков
          age ≥ REDUCED_WINDOW                 → "offline", 0    (пропускаем)

        В конце синхронизируем колонку `viewers.is_afk` с реальностью,
        чтобы admin view и COUNT(is_afk=0) отражали текущие статусы.
        """
        now = datetime.now()

        # 1. Читаем из БД всех кто хотя бы раз отметился за REDUCED_WINDOW.
        #    Это «канон», in-memory словарь больше не гейткипит награду.
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                cursor = await conn.execute(
                    """
                    SELECT username,
                           CAST((julianday('now') - julianday(last_seen)) * 86400 AS INTEGER) AS age_sec
                    FROM   viewers
                    WHERE  last_seen >= datetime('now', ?)
                    """,
                    (f"-{REDUCED_WINDOW} seconds",),
                )
                rows = await cursor.fetchall()
        except Exception as e:
            logger.warning("Чтение активных из БД упало: %s", e)
            rows = []

        # 2. Уборка in-memory мусора (TTL 30 мин) — не влияет на решение,
        #    просто чтобы словарь не рос вечно.
        offline_cutoff = now - timedelta(seconds=REDUCED_WINDOW)
        for u in [u for u, t in self.viewers_last_active.items() if t < offline_cutoff]:
            del self.viewers_last_active[u]
            self._bonus_cache.invalidate(f"bonus_{u}")

        chat_cutoff = now - timedelta(hours=1)
        for u in [u for u, t in self.last_chat_update.items() if t < chat_cutoff]:
            del self.last_chat_update[u]
        for u in [u for u, t in self.last_activity_update.items() if t < chat_cutoff]:
            del self.last_activity_update[u]

        attention_cutoff = now - timedelta(minutes=5)
        for u in [u for u, t in self.last_attention.items() if t < attention_cutoff]:
            del self.last_attention[u]

        # 3. Классификация + начисление.
        active_count = reduced_count = 0
        for username, age_sec in rows:
            if age_sec >= REDUCED_WINDOW:
                # защита от граничного случая (должно быть отфильтровано WHERE)
                continue

            # Бонусы от инвентаря и уровня
            item_bonus = await self._get_viewer_bonus(username)
            level_data = await self.db.get_user_level(username)
            level_info = self.db.get_level_info(level_data['level'])
            level_pct  = level_info.get('bonus_pct', 0)

            base_income  = POINTS_PER_MINUTE + item_bonus
            total_points = int(base_income * (1 + level_pct / 100))

            # Статус
            if age_sec < ACTIVE_WINDOW:
                status = "active"
                active_count += 1
            else:
                status = "reduced"
                total_points //= 2
                reduced_count += 1

            await self.db.add_points(username, total_points)

            # Квесты «сколько минут посмотрено» тикаем только для активных,
            # чтобы AFK ×½ не засчитывало полноценное время (спорно, но
            # бывший код тикал всем — меняю на «только active» т.к.
            # статус reduced и так де-факто AFK).
            if status == "active":
                for quest in WATCH_TIME_QUESTS:
                    await self._update_quest_progress(username, quest, 1)

        # 4. Синхронизация is_afk в БД — чтобы admin view был честным.
        #    active/reduced → is_afk=0 (онлайн в какой-то форме);
        #    offline        → is_afk=1.
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute(
                    """
                    UPDATE viewers SET is_afk = CASE
                        WHEN last_seen >= datetime('now', ?) THEN 0
                        ELSE 1
                    END
                    """,
                    (f"-{REDUCED_WINDOW} seconds",),
                )
                await conn.commit()
        except Exception as e:
            logger.warning("Sync is_afk упал: %s", e)

        total = active_count + reduced_count
        if total > 0:
            print(
                f"💰 Награда: active={active_count} (100%), "
                f"reduced={reduced_count} (50%)"
            )
    
    async def _get_viewer_bonus(self, username: str) -> int:
        """Получить бонус от предметов"""
        cache_key = f"bonus_{username}"
        cached = self._bonus_cache.get(cache_key)
        if cached is not None:
            return cached
        
        inventory = await self.db.get_inventory(username)
        bonus = sum(item['bonus'] * item['quantity'] for item in inventory)
        
        self._bonus_cache.set(cache_key, bonus)
        return bonus
    
    # ===== ОБНОВЛЕНИЕ КВЕСТОВ (УЛУЧШЕННАЯ ВЕРСИЯ) =====
    async def _update_quest_progress(self, username: str, quest_type: str, increment: int):
        """Обновить прогресс квеста с поддержкой всех типов"""
        today = date.today().isoformat()
        username = username.lower()

        async with aiosqlite.connect(self.db.db_path) as conn:
            cursor = await conn.execute(
                "SELECT id, current_value, target_value, completed_at FROM quests WHERE username = ? AND quest_type = ? AND day_date = ?",
                (username, quest_type, today)
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

                await conn.execute("""
                    INSERT INTO quests
                    (username, quest_type, target_value, current_value, reward_points, reward_item_id, day_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (username, quest_type, target, increment, reward_points, None, today))
                await conn.commit()

                # Проверяем, не завершился ли сразу
                if increment >= target:
                    await self._complete_quest(username, quest_type, reward_points, reward_item)
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

                await conn.execute(
                    "UPDATE quests SET completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (quest_id,)
                )
                await conn.commit()
                await self._complete_quest(username, quest_type, reward_points, reward_item)
                logger.info("Квест %s завершён для @%s", quest_type, username)
            else:
                await conn.commit()
    
    async def _complete_quest(self, username: str, quest_type: str, reward_points: int, reward_item: Optional[str]):
        """Выдать награду за завершённый квест"""
        # Начисляем очки
        await self.db.add_points(username, reward_points)
        
        # Выдаём предмет, если есть
        if reward_item:
            await self.db.give_item(username, reward_item)
            logger.info("Предмет %s выдан @%s за квест %s", reward_item, username, quest_type)
    
    # ===== СПЕЦИАЛИЗИРОВАННЫЕ МЕТОДЫ ДЛЯ КВЕСТОВ =====
    async def _update_quests_by_type(self, username: str, quest_type: str, increment: int):
        """Обновить все квесты указанного типа"""
        for quest in QUEST_ORDER:
            quest_config = QUESTS_CONFIG.get(quest)
            if quest_config and quest_config.get('type') == quest_type:
                await self._update_quest_progress(username, quest, increment)

    async def update_chat_quest_progress(self, username: str, message_length: int):
        """Обновить прогресс чат-квестов"""
        # Защита от спама (не чаще раза в 2 секунды)
        now = datetime.now()
        last_update = self.last_chat_update.get(username, datetime.min)
        if (now - last_update).total_seconds() < 2:
            return
        
        self.last_chat_update[username] = now
        
        # Обновляем все чат-квесты
        await self._update_quests_by_type(username, 'chat', 1)
        
        # Для комбинированного квеста active_viewer тоже добавляем прогресс
        if 'active_viewer' in QUESTS_CONFIG:
            # Проверяем, достигнуты ли условия
            activity = await self.db.get_today_activity(username)
            chat = await self.db.get_today_chat_stats(username)
            
            config = QUESTS_CONFIG['active_viewer']
            req = config.get('requirements', {})
            
            if (activity.get('total_time', 0) >= req.get('time', 60) and
                chat.get('message_count', 0) >= req.get('messages', 10) and
                activity.get('total_clicks', 0) >= req.get('activity', 50)):
                await self._update_quest_progress(username, 'active_viewer', 1)
    
    async def update_activity_quest_progress(self, username: str, watch_time: int, clicks: int = 0):
        """Обновить прогресс квестов активности"""
        # Защита от спама (не чаще раза в 10 секунд)
        now = datetime.now()
        last_update = self.last_activity_update.get(username, datetime.min)
        if (now - last_update).total_seconds() < 10:
            return
        
        self.last_activity_update[username] = now
        
        # Обновляем квесты активности (каждые 60 секунд = +1)
        await self._update_quests_by_type(username, 'activity', watch_time // 60)
    
    # ===== ДРОПЫ =====
    async def drop_loop(self):
        """Цикл дропов"""
        logger.info("Цикл дропов запущен (каждые %d мин)", DROP_INTERVAL // 60)
        while self.running:
            await asyncio.sleep(DROP_INTERVAL)
            await self._process_drop()
    
    async def _process_drop(self):
        """Обработать дроп"""
        if not await self._is_stream_live():
            return
        if random.random() > DROP_CHANCE:
            return
        # Дроп — только среди "active" (< ACTIVE_WINDOW). Читаем из БД для
        # консистентности с _reward_points и чтобы пережить рестарт.
        cutoff = datetime.now() - timedelta(seconds=ACTIVE_WINDOW)
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                cursor = await conn.execute(
                    "SELECT username FROM viewers WHERE last_seen >= datetime('now', ?)",
                    (f"-{ACTIVE_WINDOW} seconds",),
                )
                rows = await cursor.fetchall()
            active = [r[0] for r in rows if r[0].lower() not in DROP_BLACKLIST]
        except Exception as e:
            logger.warning("Drop: чтение активных из БД упало: %s", e)
            active = [
                u for u, t in self.viewers_last_active.items()
                if t > cutoff and u.lower() not in DROP_BLACKLIST
            ]
        if not active:
            return
        
        lucky = random.choice(active)
        
        # Выбираем предмет для дропа
        item_name, rarity = random.choices(
            [(i[0], i[2]) for i in DROP_ITEMS],
            weights=[i[1] for i in DROP_ITEMS]
        )[0]
        
        await self.db.give_item(lucky, item_name)
        
        # Отправляем сообщение о дропе в чат
        await self.send_message(f"🎁 @{lucky} получил {item_name} в дропе!")
        logger.info("ДРОП: @%s получил %s", lucky, item_name)
        
        # Уведомляем оверлей
        try:
            await self.on_drop(lucky, item_name, rarity)
        except Exception as e:
            print(f"⚠️ Ошибка on_drop: {e}")
    
    async def force_drop(self):
        """Принудительный дроп (из админки)"""
        await self._process_drop()
        return {"success": True, "message": "Принудительный дроп выполнен"}
    
    # ===== КАЗИНО =====

    async def check_and_unlock_achievements(self, username: str, trigger: str, extra: dict = None) -> list:
        """
        Проверяет и выдаёт достижения по триггеру.
        trigger: 'craft', 'duel_win', 'rimworld_buy', 'casino', 'watch_hours', 'level_up', 'streak'
        """
        unlocked = []
        extra = extra or {}

        async def _try(key):
            result = await self.db.unlock_achievement(username, key)
            if result:
                unlocked.append(result)
                await self.send_message(
                    f"🏆 @{username} получил достижение «{result['emoji']} {result['name']}»! +{result['reward']}💎"
                )

        if trigger == 'craft':
            await _try('first_craft')
        elif trigger == 'duel_win':
            await _try('first_duel_win')
        elif trigger == 'rimworld_buy':
            await _try('first_rimworld_buy')
        elif trigger == 'casino':
            await _try('first_casino')
        elif trigger == 'watch_hours':
            hours = extra.get('hours', 0)
            if hours >= 10:  await _try('watch_10h')
            if hours >= 50:  await _try('watch_50h')
            if hours >= 100: await _try('watch_100h')
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
            if current >= 10: await _try('streak_10')
            if max_s >= 5:    await _try('max_streak_5')
            if max_s >= 10:   await _try('max_streak_10')

        return unlocked

    async def handle_stream_start(self, stream_id: str):
        """Вызывается при старте стрима — регистрирует сессию."""
        self.current_stream_id = stream_id
        await self.db.register_stream_session(stream_id)
        logger.info("Стрим зарегистрирован: %s", stream_id)

    async def record_viewer_attendance(self, username: str, minutes: int) -> dict:
        """
        Записывает присутствие зрителя. При 15+ мин — выдаёт стрик-бонус и проверяет достижения.
        """
        if not self.current_stream_id:
            return {"rewarded": False}

        result = await self.db.record_attendance(username, self.current_stream_id, minutes)

        if result.get("rewarded"):
            await self.check_and_unlock_achievements(username, 'streak', {
                'current_streak': result['current_streak'],
                'max_streak':     result['max_streak'],
            })
            hours = await self.db.get_total_watch_hours(username)
            await self.check_and_unlock_achievements(username, 'watch_hours', {'hours': hours})

        return result


    async def casino_bet(self, username: str, amount: int) -> dict:
        """Сделать ставку в казино"""
        now = datetime.now()
        
        # Проверка глобального кулдауна казино
        if now < self.casino_cooldown_until:
            minutes = int((self.casino_cooldown_until - now).total_seconds() / 60)
            return {
                "success": False,
                "message": f"Казино закрыто! Осталось {minutes} мин"
            }
        
        # Проверка минимальной ставки
        if amount < CASINO_CONFIG['min_bet']:
            return {
                "success": False,
                "message": f"Минимальная ставка {CASINO_CONFIG['min_bet']}💎"
            }
        
        # Проверяем баланс
        points = await self.db.get_points(username)
        if points < amount:
            return {
                "success": False,
                "message": f"Недостаточно очков! У тебя {points}💎"
            }
        
        # Списываем ставку — проверяем результат (атомарность в БД)
        success = await self.db.remove_points(username, amount)
        if not success:
            return {
                "success": False,
                "message": f"Ошибка списания очков! Попробуйте позже."
            }
        
        self.casino_total_bets += amount
        if self.casino_total_bets >= self.casino_threshold and now >= self.casino_cooldown_until:
            self.casino_cooldown_until = now + timedelta(seconds=self.casino_cooldown_duration)
            self.casino_total_bets = 0
            logger.info("Казино уходит в кулдаун на %d мин", self.casino_cooldown_duration // 60)
        
        # Генерируем результат через конфиг
        chances = CASINO_CONFIG['win_chances']
        roll = random.random()

        loss_threshold   = chances['loss']
        double_threshold = loss_threshold + chances['double']
        # остаток — джекпот

        if roll < loss_threshold:
            win_amount = 0
            message = f"😢 @{username} проиграл {amount}💎"
        elif roll < double_threshold:
            win_amount = amount * 2
            message = f"🍀 @{username} выиграл {win_amount}💎!"
        else:
            win_amount = amount * 5
            message = f"🎰 @{username} СОРВАЛ ДЖЕКПОТ! {win_amount}💎!!!"
        
        if win_amount > 0:
            await self.db.add_points(username, win_amount)
        
        # Пишем в чат только джекпот, обычная победа — молча
        if win_amount == amount * 5:
            await self.send_message(message)
        
        return {
            "success": True,
            "win": win_amount,
            "loss": amount if win_amount == 0 else 0,
            "result": "jackpot" if win_amount == amount * 5 else ("win" if win_amount > 0 else "loss"),
            "message": message
        }
    
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
            "active_event": self.event_manager.active_event is not None
        }
    
    # ===== МЕТОДЫ ДЛЯ ИВЕНТОВ (ОБНОВЛЕНЫ) =====
    async def on_event_start(self, event_type: str, prize_name: str):
        """Вызывается при старте ивента"""
        type_name = "🎲 Рулетка" if event_type == 'roulette' else "⚖️ Аукцион"
        duration_min = EVENT_CONFIG.get('event_duration', 180) // 60
        message = f"🎡 РУЛЕКЦИОН АКТИВИРОВАН! Запускается {type_name}! Приз: {prize_name}! У вас {duration_min} мин чтобы сделать ставки!"
        await self.send_message(message)
    
    async def on_event_end(
        self,
        winner: str,
        event_type: str,
        prize_name: str,
        winner_bid: int = 0,
        total_pool: int = 0,
        participants: int = 0,
    ):
        """Оповещение о победителе рулекциона в чат.

        Разный текст для рулетки (шанс + ставка) и аукциона (только ставка).
        """
        if event_type == "roulette":
            chance = (winner_bid / total_pool * 100) if total_pool > 0 else 0.0
            text = (
                f"🎲✨ РУЛЕТКА ЗАВЕРШЕНА! ✨🎲 "
                f"🏆 Победитель — @{winner}! "
                f"Ставка: {winner_bid:,}💎 | Шанс: {chance:.1f}% | "
                f"Участников: {participants} | Банк: {total_pool:,}💎 "
                f"🎁 Приз: {prize_name}!"
            )
        else:
            text = (
                f"⚖️💥 АУКЦИОН ЗАВЕРШЁН! 💥⚖️ "
                f"🏆 Победитель — @{winner}! "
                f"Победная ставка: {winner_bid:,}💎 | Соперников: {max(0, participants-1)} "
                f"🎁 Приз: {prize_name}!"
            )
        await self.send_message(text)
    
    async def on_drop(self, username: str, item_name: str, rarity: str):
        """Вызывается при дропе предмета — переопределяется в main.py"""
        pass

    # ===== ОСТАНОВ =====
    async def auto_message_loop(self):
        """Цикл автосообщений в чат (каждые AUTO_MESSAGE_INTERVAL секунд).
        Отправляет только во время стрима, перебирает сообщения по очереди.
        """
        if not AUTO_MESSAGES_ENABLED or not AUTO_MESSAGES:
            print("ℹ️ Автосообщения отключены или список пуст")
            return

        print(f"💬 Цикл автосообщений запущен (каждые {AUTO_MESSAGE_INTERVAL//60} мин)")
        index = 0
        while self.running:
            await asyncio.sleep(AUTO_MESSAGE_INTERVAL)
            if not self.running:
                break
            if not await self._is_stream_live():
                continue
            try:
                msg = AUTO_MESSAGES[index % len(AUTO_MESSAGES)]
                await self.send_message(msg)
                index += 1
            except Exception as e:
                print(f"⚠️ auto_message_loop: {e}")

    async def shutdown(self):
        """Остановка бота"""
        self.running = False
        logger.info("BotCore остановлен")
