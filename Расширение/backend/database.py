# database.py - работа с твоей БД
import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Optional, List, Dict

from db_pool import DBPool
from dependencies import resolve_channel_id

class Database:
    def __init__(self, db_path="viewers.db"):
        self.db_path = db_path
        self._pool = DBPool(db_path=db_path, min_size=2, max_size=10, timeout=10.0)

    async def init_pool(self) -> None:
        """Инициализирует пул соединений. Вызывать один раз при старте приложения."""
        await self._pool.initialize()

    @asynccontextmanager
    async def _connect(self):
        """
        Контекстный менеджер: берёт соединение из пула, возвращает после использования.
        При успехе — commit (как делал aiosqlite.connect), при ошибке — rollback.
        Использование: async with self._connect() as db: ...
        """
        conn = await self._pool.acquire()
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await self._pool.release(conn)
    
    # ===== ИНИЦИАЛИЗАЦИЯ БД =====
    async def init_tables(self):
        """Создание всех необходимых таблиц. WAL и busy_timeout выставляются пулом."""
        async with self._connect() as db:
            # M4: реестр стримеров (multi-tenant). См. migrations/m4_channels.py.
            # Полная схема (с OAuth/EventSub полями) поднимается миграцией M4 —
            # здесь только базовая для свежих установок без существующих миграций.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER PRIMARY KEY,
                    login TEXT NOT NULL,
                    display_name TEXT,
                    tier TEXT NOT NULL DEFAULT 'free',
                    active_module TEXT DEFAULT NULL,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    oauth_access_token TEXT,
                    oauth_refresh_token TEXT,
                    oauth_expires_at TIMESTAMP,
                    eventsub_subscription_id TEXT
                )
            """)

            # Основная таблица зрителей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS viewers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    points INTEGER DEFAULT 0,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    join_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_afk INTEGER DEFAULT 0
                )
            """)

            # Счётчики прогрессивных покупок (черты и гены)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS purchase_counters (
                    username TEXT NOT NULL,
                    category TEXT NOT NULL,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (username, category)
                )
            """)

            # Предметы (справочник)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    value INTEGER DEFAULT 0,
                    rarity TEXT DEFAULT 'common',
                    craft_level INTEGER DEFAULT 1,
                    description TEXT,
                    emoji TEXT DEFAULT '📦'
                )
            """)

            # Инвентарь зрителей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    item_id INTEGER NOT NULL,
                    quantity INTEGER DEFAULT 1,
                    UNIQUE(username, item_id),
                    FOREIGN KEY (item_id) REFERENCES items(id)
                )
            """)

            # Квесты зрителей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS quests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    quest_type TEXT NOT NULL,
                    current_value INTEGER DEFAULT 0,
                    target_value INTEGER NOT NULL,
                    reward_points INTEGER DEFAULT 0,
                    reward_item_id INTEGER,
                    completed_at DATETIME,
                    day_date TEXT NOT NULL,
                    UNIQUE(username, quest_type, day_date)
                )
            """)

            # Дропы
            await db.execute("""
                CREATE TABLE IF NOT EXISTS drops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Браки
            await db.execute("""
                CREATE TABLE IF NOT EXISTS marriages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user1 TEXT NOT NULL,
                    user2 TEXT NOT NULL,
                    family_balance INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    divorced_at DATETIME
                )
            """)

            # Соответствие twitch_id → username
            await db.execute("""
                CREATE TABLE IF NOT EXISTS twitch_ids (
                    twitch_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Пешки RimWorld
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    pawn_name TEXT NOT NULL,
                    is_alive INTEGER DEFAULT 1,
                    health REAL DEFAULT 1.0,
                    world_id TEXT DEFAULT '',
                    world_name TEXT DEFAULT '',
                    last_sync DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Экипировка пешек (meta: JSON с weapon_traits, psi, quality, stuff, max_hp и т.д.)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_equipment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER NOT NULL,
                    slot TEXT,
                    item_def TEXT,
                    item_name TEXT,
                    hp INTEGER DEFAULT 100,
                    meta TEXT,
                    FOREIGN KEY (pawn_id) REFERENCES rimworld_pawns(id)
                )
            """)
            # Миграция для существующих БД
            try:
                await db.execute("ALTER TABLE rimworld_pawn_equipment ADD COLUMN meta TEXT")
            except Exception:
                pass

            # Навыки пешек
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER NOT NULL,
                    skill_name TEXT,
                    skill_level INTEGER DEFAULT 0,
                    passion INTEGER DEFAULT 0,
                    xp REAL DEFAULT 0,
                    is_disabled INTEGER DEFAULT 0,
                    FOREIGN KEY (pawn_id) REFERENCES rimworld_pawns(id)
                )
            """)

            # Состояния здоровья пешек
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_hediffs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER NOT NULL,
                    body_part TEXT,
                    hediff_label TEXT,
                    hediff_type TEXT DEFAULT 'injury',
                    severity REAL DEFAULT 0.0,
                    icon TEXT DEFAULT '🩸',
                    is_permanent INTEGER DEFAULT 0,
                    age_ticks INTEGER DEFAULT 0,
                    description TEXT DEFAULT '',
                    FOREIGN KEY (pawn_id) REFERENCES rimworld_pawns(id)
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_traits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER NOT NULL,
                    trait_def TEXT NOT NULL,
                    degree INTEGER DEFAULT 0,
                    label TEXT,
                    trait_desc TEXT,
                    FOREIGN KEY (pawn_id) REFERENCES rimworld_pawns(id)
                )
            """)

            # Гены (Biotech DLC)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_genes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER NOT NULL,
                    def_name TEXT NOT NULL,
                    label TEXT,
                    is_active INTEGER DEFAULT 1,
                    xenogene INTEGER DEFAULT 1,
                    gene_class TEXT DEFAULT '',
                    FOREIGN KEY (pawn_id) REFERENCES rimworld_pawns(id)
                )
            """)

            # Каталог предметов RimWorld
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_def TEXT UNIQUE NOT NULL,
                    item_name TEXT NOT NULL,
                    item_type TEXT,
                    slot TEXT,
                    base_cost INTEGER DEFAULT 0,
                    description TEXT,
                    is_available INTEGER DEFAULT 1
                )
            """)

            # Статистика активности (только watch_time — clicks/moves удалены
            # в M7 как никогда не использовавшиеся)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS activity_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    watch_time INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Статистика чата
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    message_length INTEGER DEFAULT 0,
                    message_text TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""                CREATE TABLE IF NOT EXISTS market_listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seller TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    item_emoji TEXT DEFAULT '📦',
                    price INTEGER NOT NULL,
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            
            # craft_stats — удалён 2026-05-10 (Phase 1.B compliance rework, 3/3 gambling).
            # DROP TABLE будет в M8. См. COMPLIANCE_REWORK_PLAN.md §4 Phase 1.

            # Заполняем справочник предметов если пустой
            await db.execute("""
                INSERT OR IGNORE INTO items (name, display_name, value, rarity, craft_level, description, emoji)
                VALUES
                    ('деревяшка', 'Деревяшка', 1,   'common',   1, 'Простая палка. +1 очко/мин',      '🪵'),
                    ('камень',    'Камень',    6,   'uncommon', 2, 'Тяжёлый камень. +6 очков/мин',    '🪨'),
                    ('амулет',    'Амулет',    32,  'rare',     3, 'Магический амулет. +32 очка/мин',  '🔮'),
                    ('корона',    'Корона',    200, 'epic',     4, 'Золотая корона. +200 очков/мин!', '👑')
            """)

            # Индексы
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_activity_stats_username_date 
                ON activity_stats(username, date(created_at))
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_stats_username_date 
                ON chat_stats(username, date(created_at))
            """)

            # Таблицы колонистов (устаревшие, для обратной совместимости)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_colonists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    owner_username TEXT NOT NULL,
                    is_alive INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_skills (
                    colonist_id INTEGER NOT NULL,
                    skill_name TEXT NOT NULL,
                    level INTEGER DEFAULT 0,
                    FOREIGN KEY (colonist_id) REFERENCES rimworld_colonists(id)
                )
            """)
            
            
                        # ═══════════════════════════════════════════════════════════
            # Таблицы для ачивок, стриков и посещаемости (отсутствовали)
            # ═══════════════════════════════════════════════════════════
            await db.execute("""
                CREATE TABLE IF NOT EXISTS achievements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL, description TEXT, emoji TEXT DEFAULT '🏆', reward INTEGER DEFAULT 0
                )
            """)
            # Все 4 таблицы post-M1: PK включает channel_id для multi-tenant.
            # На существующих БД с примененным M1 эти CREATE'ы не сработают
            # (IF NOT EXISTS). Для свежих установок (новый dev VPS) — даёт
            # сразу корректную схему без нужды в M1 миграции.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_achievements (
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL, achievement_key TEXT NOT NULL,
                    unlocked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (channel_id, username, achievement_key)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stream_streaks (
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    current_streak INTEGER DEFAULT 0,
                    max_streak INTEGER DEFAULT 0,
                    last_stream_id TEXT DEFAULT '',
                    PRIMARY KEY (channel_id, username)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stream_attendance (
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    stream_id TEXT NOT NULL,
                    minutes INTEGER DEFAULT 0,
                    claimed INTEGER DEFAULT 0,
                    PRIMARY KEY (channel_id, username, stream_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stream_sessions (
                    channel_id INTEGER NOT NULL,
                    id TEXT NOT NULL,
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ended_at   DATETIME DEFAULT NULL,
                    PRIMARY KEY (channel_id, id)
                )
            """)
            # ended_at миграция для legacy БД (single-tenant до M1) —
            # если M1 ещё не применён, защищает от поломки.
            try:
                await db.execute("ALTER TABLE stream_sessions ADD COLUMN ended_at DATETIME DEFAULT NULL")
            except Exception:
                pass  # колонка уже есть

            # casino_settings + free_spins_daily — удалены 2026-05-10 (Phase 1.A,
            # gambling по §6.2.3 Twitch Extension Guidelines). DROP TABLE будет в M8.
            # См. COMPLIANCE_REWORK_PLAN.md §4 Phase 1.

            # Дуэли — ELO и стрики
            await db.execute("""
                CREATE TABLE IF NOT EXISTS duel_stats (
                    username TEXT PRIMARY KEY,
                    elo INTEGER DEFAULT 1100,
                    win_streak INTEGER DEFAULT 0,
                    season_id INTEGER DEFAULT 1
                )
            """)
            # Сезоны дуэлей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS duel_seasons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    finished INTEGER DEFAULT 0
                )
            """)
            # Ожидающие дуэли (переживают рестарт)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_duels (
                    duel_id TEXT PRIMARY KEY,
                    creator TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    move TEXT NOT NULL,
                    created_ts REAL NOT NULL
                )
            """)

            # ── Seed достижений (INSERT OR IGNORE — не перезапишет существующие) ──
            achievements_seed = [
                # key,               name,                        description,                                emoji,  reward
                # 'first_craft' achievement удалён 2026-05-10 (Phase 1.B compliance rework — crafting вырезан)
                ('first_duel_win',   'Первая победа в дуэли',     'Выиграл первую дуэль',                     '⚔️',   500),
                ('first_rimworld_buy','Покупатель RimWorld',      'Купил первый предмет в RimWorld',          '🛒',   500),
                # 'first_casino' achievement удалён в Phase 1.A (2026-05-10) — casino вырезан
                ('watch_10h',        '10 часов просмотра',        'Смотрел стримы суммарно 10 часов',         '⏱️',  2000),
                ('watch_50h',        '50 часов просмотра',        'Смотрел стримы суммарно 50 часов',         '⌛',   8000),
                ('watch_100h',       '100 часов просмотра',       'Смотрел стримы суммарно 100 часов',        '🏆',  20000),
                ('level_5',          'Уровень 5',                 'Достиг 5-го уровня',                       '⭐',   1000),
                ('level_10',         'Уровень 10',                'Достиг 10-го уровня',                      '🌟',   3000),
                ('level_20',         'Уровень 20',                'Достиг 20-го уровня',                      '💫',  10000),
                ('streak_3',         'Стрик 3 стрима',            'Смотрел 3 стрима подряд',                  '🔥',   1000),
                ('streak_5',         'Стрик 5 стримов',           'Смотрел 5 стримов подряд',                 '🔥',   2000),
                ('streak_10',        'Стрик 10 стримов',          'Смотрел 10 стримов подряд',                '🔥',   5000),
                ('max_streak_5',     'Рекорд стрика: 5',          'Максимальный стрик достиг 5 стримов',      '🏅',   2000),
                ('max_streak_10',    'Рекорд стрика: 10',         'Максимальный стрик достиг 10 стримов',     '🥇',   7000),
            ]
            await db.executemany(
                "INSERT OR IGNORE INTO achievements (key, name, description, emoji, reward) VALUES (?, ?, ?, ?, ?)",
                achievements_seed
            )

            await db.commit()
    
    # ===== ОЧКИ =====
    async def get_points(self, username: str, channel_id: int = None) -> int:
        """Получить очки пользователя. channel_id с fallback DEFAULT_CHANNEL_ID до M3.1."""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT points FROM viewers WHERE channel_id = ? AND username = ?",
                (channel_id, username.lower())
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def add_points(self, username: str, amount: int, channel_id: int = None):
        """Начислить очки. channel_id опционален пока M3 не протолкнёт его везде."""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk)
                VALUES (?, ?, ?, datetime('now'), datetime('now'), 0)
                ON CONFLICT(channel_id, username) DO UPDATE SET
                    points = points + ?,
                    last_seen = datetime('now')
            """, (channel_id, username.lower(), amount, amount))
            await db.commit()
    
    async def remove_points(self, username: str, amount: int, channel_id: int = None) -> bool:
        """Списать очки. Atomic — защита от race condition при одновременных списаниях."""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            # Одним UPDATE: списываем только если points достаточно
            cursor = await db.execute(
                "UPDATE viewers SET points = points - ? WHERE channel_id = ? AND username = ? AND points >= ?",
                (amount, channel_id, username.lower(), amount)
            )
            await db.commit()
            return cursor.rowcount > 0
    
    # ===== ПРОГРЕССИВНЫЕ СЧЁТЧИКИ (черты и гены) =====

    async def get_purchase_count(self, username: str, category: str) -> int:
        """Сколько раз зритель купил предметы данной категории (trait/gene)."""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT count FROM purchase_counters WHERE username = ? AND category = ?",
                (username.lower(), category)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def increment_purchase_count(self, username: str, category: str) -> int:
        """Увеличить счётчик покупок на 1. Возвращает НОВОЕ значение (после инкремента)."""
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO purchase_counters (username, category, count)
                VALUES (?, ?, 1)
                ON CONFLICT(username, category) DO UPDATE SET count = count + 1
            """, (username.lower(), category))
            await db.commit()
            cursor = await db.execute(
                "SELECT count FROM purchase_counters WHERE username = ? AND category = ?",
                (username.lower(), category)
            )
            row = await cursor.fetchone()
            return row[0] if row else 1

    def calc_progressive_price(self, base_price: int, count: int) -> int:
        """
        Прогрессивная цена: каждая следующая покупка дороже на base_price.
        1-я: base_price * 1, 2-я: base_price * 2, 3-я: base_price * 3, ...
        Пример при base_price=1000: 1000 → 2000 → 3000 → ...
        """
        return base_price * (count + 1)

    # ===== ИНВЕНТАРЬ =====
    async def get_inventory(self, username: str, channel_id: int = None):
        """Получить инвентарь"""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cursor = await db.execute("""
                SELECT i.emoji, i.display_name, i.value, i.rarity, inv.quantity
                FROM inventory inv
                JOIN items i ON inv.item_id = i.id
                WHERE inv.channel_id = ? AND inv.username = ?
                ORDER BY i.craft_level DESC
            """, (channel_id, username.lower()))
            
            items = await cursor.fetchall()
            return [
                {
                    "emoji": item[0],
                    "name": item[1],
                    "bonus": item[2],
                    "rarity": item[3],
                    "quantity": item[4]
                }
                for item in items
            ]
    
    async def give_item(self, username: str, item_name: str, quantity: int = 1, channel_id: int = None):
        """Выдать предмет. channel_id опционален пока M3 не протолкнёт его везде."""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT id FROM items WHERE name = ?",
                (item_name,)
            )
            item_row = await cursor.fetchone()
            if not item_row:
                return False

            item_id = item_row[0]

            # Atomic upsert — без SELECT+UPDATE race condition
            await db.execute("""
                INSERT INTO inventory (channel_id, username, item_id, quantity) VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id, username, item_id) DO UPDATE SET quantity = quantity + ?
            """, (channel_id, username.lower(), item_id, quantity, quantity))
            
            await db.commit()
            return True
        
        
        
        
    async def get_user_level(self, username: str, channel_id: int = None) -> dict:
        """Расчёт уровня: 1 минута = 1 EXP. Порог растёт каждые 5 уровней."""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT COALESCE(SUM(watch_time), 0) FROM activity_stats WHERE channel_id = ? AND username = ?",
                (channel_id, username.lower())
            )
            row = await cur.fetchone()
            total_exp = int(row[0] / 60) if row else 0

        level = 1
        exp_current = total_exp

        # Проходим по уровням до 100, пока хватает EXP
        while level < 100:
            # Формула: 1-5 → 100, 5-10 → 200, 10-15 → 300 ...
            needed = ((level + 4) // 5) * 100
            if exp_current < needed:
                break
            exp_current -= needed
            level += 1

        return {
            "level": level,
            "exp": exp_current,
            "total_exp": total_exp
        }

    def get_level_info(self, level: int) -> dict:
        """Сколько нужно до следующего уровня + пассивный бонус"""
        titles = {
            1: "Новенький", 2: "Зритель", 3: "Активный", 4: "Постоянный",
            5: "Фанат", 6: "Ветеран", 7: "Легенда", 8: "Элита", 
            9: "Мастер", 10: "Бог"
        }
        
        # Пассивный бонус: +1% к доходу за каждый уровень (кап 100%)
        bonus_pct = min(100, (level - 1) * 1.0)
        
        # Порог для текущего уровня (та же формула)
        exp_needed = ((level + 4) // 5) * 100

        return {
            "exp_needed": exp_needed,
            "title": titles.get(level, f"Ур. {level}"),
            "bonus_pct": round(bonus_pct, 1)
        }
        
        
        
        
    # get_craft_count + calc_craft_chance удалены 2026-05-10 (Phase 1.B compliance
    # rework — 3/3 gambling: §6.2.4 + §5.3 Twitch Extension Guidelines).

    # ===== КВЕСТЫ =====
    async def get_quests(self, username: str, channel_id: int = None):
        """Получить квесты с поддержкой новых типов"""
        channel_id = resolve_channel_id(channel_id)
        today = date.today().isoformat()

        async with self._connect() as db:
            cursor = await db.execute("""
                SELECT quest_type, current_value, target_value, reward_points, completed_at
                FROM quests
                WHERE channel_id = ? AND username = ? AND day_date = ?
                ORDER BY
                    CASE quest_type
                        WHEN 'watch_time_30' THEN 1
                        WHEN 'watch_time_60' THEN 2
                        WHEN 'watch_time_120' THEN 3
                        WHEN 'watch_time_180' THEN 4
                        WHEN 'watch_time_240' THEN 5
                        WHEN 'watch_time_300' THEN 6
                        WHEN 'chat_messages_10' THEN 7
                        WHEN 'chat_messages_25' THEN 8
                        WHEN 'chat_messages_50' THEN 9
                        WHEN 'chat_messages_100' THEN 10
                        WHEN 'activity_points_100' THEN 11
                        WHEN 'activity_points_500' THEN 12
                        WHEN 'active_viewer' THEN 13
                    END
            """, (channel_id, username.lower(), today))
            
            quests = await cursor.fetchall()
            
            # Расширенная конфигурация квестов
            quest_config = {
                # Временные квесты
                'watch_time_30': {'name': '30 минут просмотра', 'emoji': '⏱️'},
                'watch_time_60': {'name': '1 час просмотра', 'emoji': '⌛'},
                'watch_time_120': {'name': '2 часа просмотра', 'emoji': '⏳'},
                'watch_time_180': {'name': '3 часа просмотра', 'emoji': '⌚'},
                'watch_time_240': {'name': '4 часа просмотра', 'emoji': '⏰'},
                'watch_time_300': {'name': '5 ЧАСОВ ПРОСМОТРА!', 'emoji': '🏆'},
                
                # Чат-квесты
                'chat_messages_10': {'name': '10 сообщений в чате', 'emoji': '💬'},
                'chat_messages_25': {'name': '25 сообщений в чате', 'emoji': '🗣️'},
                'chat_messages_50': {'name': '50 сообщений в чате', 'emoji': '💎'},
                'chat_messages_100': {'name': '100 сообщений в чате', 'emoji': '👑'},
                
                # Квесты активности
                'activity_points_100': {'name': '100 очков активности', 'emoji': '🎮'},
                'activity_points_500': {'name': '500 очков активности', 'emoji': '🎯'},
                
                # Особые квесты
                'active_viewer': {'name': 'Активный зритель', 'emoji': '🌟'}
            }
            
            result = []
            for qtype, current, target, reward, completed in quests:
                config = quest_config.get(qtype, {'name': qtype, 'emoji': '📜'})
                result.append({
                    "type": qtype,
                    "name": config['name'],
                    "emoji": config['emoji'],
                    "current": current,
                    "target": target,
                    "reward": reward,
                    "completed": completed is not None
                })
            
            return result
    
    # ===== СТАТИСТИКА АКТИВНОСТИ =====
    async def add_activity(self, username: str, watch_time: int, channel_id: int = None):
        """Добавить запись об активности (только watch_time после M7)."""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO activity_stats (channel_id, username, watch_time)
                VALUES (?, ?, ?)
            """, (channel_id, username.lower(), watch_time))
            await db.commit()

    async def get_today_activity(self, username: str, channel_id: int = None) -> dict:
        """Получить активность за сегодня"""
        channel_id = resolve_channel_id(channel_id)
        today = date.today().isoformat()

        async with self._connect() as db:
            cursor = await db.execute("""
                SELECT
                    SUM(watch_time) as total_time,
                    COUNT(*) as sessions
                FROM activity_stats
                WHERE channel_id = ? AND username = ? AND date(created_at) = ?
            """, (channel_id, username.lower(), today))

            row = await cursor.fetchone()

            if row and row[0]:
                return {
                    "total_time": row[0] or 0,
                    "sessions": row[1] or 0
                }
            return {
                "total_time": 0,
                "sessions": 0
            }

    async def get_activity_stats(self, username: str, days: int = 7, channel_id: int = None) -> List[dict]:
        """Получить статистику активности за последние N дней"""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cursor = await db.execute("""
                SELECT
                    date(created_at) as day,
                    SUM(watch_time) as total_time
                FROM activity_stats
                WHERE channel_id = ? AND username = ?
                AND created_at >= datetime('now', ?)
                GROUP BY date(created_at)
                ORDER BY day DESC
            """, (channel_id, username.lower(), f'-{days} days'))
            
            rows = await cursor.fetchall()
            return [
                {
                    "day": row[0],
                    "total_time": row[1] or 0,
                }
                for row in rows
            ]
    
    # ===== СТАТИСТИКА ЧАТА =====
    async def add_chat_message(self, username: str, length: int, text: Optional[str] = None, channel_id: int = None):
        """Добавить запись о сообщении в чате. Текст не сохраняем — только длину."""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO chat_stats (channel_id, username, message_length, message_text)
                VALUES (?, ?, ?, ?)
            """, (channel_id, username.lower(), length, None))  # text намеренно не сохраняем — рост БД
            await db.commit()

    async def get_today_chat_stats(self, username: str, channel_id: int = None) -> dict:
        """Получить статистику чата за сегодня"""
        channel_id = resolve_channel_id(channel_id)
        today = date.today().isoformat()

        async with self._connect() as db:
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as message_count,
                    SUM(message_length) as total_length,
                    MAX(message_length) as max_length
                FROM chat_stats
                WHERE channel_id = ? AND username = ? AND date(created_at) = ?
            """, (channel_id, username.lower(), today))
            
            row = await cursor.fetchone()
            
            if row and row[0]:
                return {
                    "message_count": row[0] or 0,
                    "total_length": row[1] or 0,
                    "max_length": row[2] or 0,
                    "average_length": (row[1] or 0) // (row[0] or 1)
                }
            return {
                "message_count": 0,
                "total_length": 0,
                "max_length": 0,
                "average_length": 0
            }
    
    async def get_chat_stats(self, username: str, days: int = 7, channel_id: int = None) -> List[dict]:
        """Получить статистику чата за последние N дней"""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cursor = await db.execute("""
                SELECT
                    date(created_at) as day,
                    COUNT(*) as message_count,
                    SUM(message_length) as total_length
                FROM chat_stats
                WHERE channel_id = ? AND username = ?
                AND created_at >= datetime('now', ?)
                GROUP BY date(created_at)
                ORDER BY day DESC
            """, (channel_id, username.lower(), f'-{days} days'))
            
            rows = await cursor.fetchall()
            return [
                {
                    "day": row[0],
                    "message_count": row[1] or 0,
                    "total_length": row[2] or 0
                }
                for row in rows
            ]
    
    # ===== КОМБИНИРОВАННАЯ СТАТИСТИКА =====
    async def get_daily_summary(self, username: str, channel_id: int = None) -> dict:
        """Получить сводку за сегодня"""
        channel_id = resolve_channel_id(channel_id)
        activity = await self.get_today_activity(username, channel_id=channel_id)
        chat = await self.get_today_chat_stats(username, channel_id=channel_id)

        return {
            "date": date.today().isoformat(),
            "activity": activity,
            "chat": chat,
            "total_points": await self.get_points(username, channel_id=channel_id)
        }

    async def get_leaderboard(self, metric: str = "points", limit: int = 10, channel_id: int = None) -> List[dict]:
        """Получить таблицу лидеров по разным метрикам"""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            if metric == "points":
                cursor = await db.execute("""
                    SELECT username, points FROM viewers
                    WHERE channel_id = ?
                    ORDER BY points DESC LIMIT ?
                """, (channel_id, limit))

            elif metric == "chat_today":
                cursor = await db.execute("""
                    SELECT c.username, COUNT(*) as count
                    FROM chat_stats c
                    WHERE c.channel_id = ? AND date(c.created_at) = date('now')
                    GROUP BY c.username
                    ORDER BY count DESC LIMIT ?
                """, (channel_id, limit))

            elif metric == "activity_today":
                cursor = await db.execute("""
                    SELECT a.username, SUM(a.watch_time) as total
                    FROM activity_stats a
                    WHERE a.channel_id = ? AND date(a.created_at) = date('now')
                    GROUP BY a.username
                    ORDER BY total DESC LIMIT ?
                """, (channel_id, limit))

            else:
                return []

            rows = await cursor.fetchall()
            return [{"username": r[0], "value": r[1]} for r in rows]
    
    # ===== КОЛОНИСТЫ =====
    async def get_colonists(self, username: str, channel_id: int = None):
        """Получить колонистов"""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cursor = await db.execute("""
                SELECT name, is_alive,
                       (SELECT COUNT(*) FROM rimworld_skills WHERE colonist_id = c.id) as skill_count
                FROM rimworld_colonists c
                WHERE c.channel_id = ? AND c.owner_username = ?
                ORDER BY is_alive DESC, name
            """, (channel_id, username.lower()))
            
            colonists = await cursor.fetchall()
            return [
                {
                    "name": c[0],
                    "alive": bool(c[1]),
                    "skills_count": c[2]
                }
                for c in colonists
            ]
    

    # ===== ДОСТИЖЕНИЯ =====

    async def get_achievements(self) -> list:
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT key, name, description, emoji, reward FROM achievements ORDER BY id")
            rows = await cur.fetchall()
            return [{"key": r[0], "name": r[1], "description": r[2],
                     "emoji": r[3], "reward": r[4]} for r in rows]

    async def get_user_achievements(self, username: str, channel_id: int = None) -> list:
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT achievement_key, unlocked_at FROM user_achievements WHERE channel_id = ? AND username = ?",
                (channel_id, username.lower()))
            rows = await cur.fetchall()
            return [{"key": r[0], "unlocked_at": r[1]} for r in rows]

    async def unlock_achievement(self, username: str, key: str, channel_id: int = None):
        channel_id = resolve_channel_id(channel_id)
        username = username.lower()
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT 1 FROM user_achievements WHERE channel_id = ? AND username = ? AND achievement_key = ?",
                (channel_id, username, key))
            if await cur.fetchone():
                return None
            cur = await db.execute(
                "SELECT name, description, emoji, reward FROM achievements WHERE key = ?", (key,))
            row = await cur.fetchone()
            if not row:
                return None
            name, description, emoji, reward = row
            await db.execute(
                "INSERT OR IGNORE INTO user_achievements (channel_id, username, achievement_key) VALUES (?, ?, ?)",
                (channel_id, username, key))
            if reward > 0:
                await db.execute(
                    "UPDATE viewers SET points = points + ? WHERE channel_id = ? AND username = ?",
                    (reward, channel_id, username))
            await db.commit()
            return {"key": key, "name": name, "description": description,
                    "emoji": emoji, "reward": reward}

    # ===== СТРИКИ =====

    async def get_streak(self, username: str, channel_id: int = None) -> dict:
        """Вернуть стрик с «честным» учётом пропусков.

        Правило (как заявил стример):
          * был стрим и зритель был  → стрик растёт (делается в record_attendance)
          * не было стрима            → стрик не меняется
          * был стрим и зрителя не было → стрик = 0

        Хранимый `current_streak` сбрасывается только в момент визита
        (в record_attendance). Но если зритель не возвращается — БД будет
        показывать старое значение. Здесь мы динамически учитываем количество
        ЗАВЕРШЁННЫХ стримов после `last_stream_id` без зачёта → если хотя бы
        один есть, отдаём 0.

        Текущий (незавершённый) стрим не считается пропуском — зритель ещё
        может его засчитать, набрав 15 мин просмотра.
        """
        channel_id = resolve_channel_id(channel_id)
        username = username.lower()
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT current_streak, max_streak, last_stream_id FROM stream_streaks WHERE channel_id = ? AND username = ?",
                (channel_id, username))
            row = await cur.fetchone()
            if not row:
                return {"current_streak": 0, "max_streak": 0, "last_stream_id": ""}
            current, maximum, last_sid = row

            # Считаем завершённые (ended_at IS NOT NULL) стримы после last_sid.
            # Если last_sid пуст или его нет в таблице — начинаем с начала времён.
            cur2 = await db.execute("""
                SELECT COUNT(*) FROM stream_sessions
                WHERE channel_id = ?
                  AND ended_at IS NOT NULL
                  AND id != ?
                  AND started_at > COALESCE(
                      (SELECT started_at FROM stream_sessions WHERE channel_id = ? AND id = ? LIMIT 1),
                      '1970-01-01'
                  )
            """, (channel_id, last_sid, channel_id, last_sid))
            missed_row = await cur2.fetchone()
            missed = missed_row[0] if missed_row else 0

            effective = 0 if missed > 0 else current
            return {"current_streak": effective, "max_streak": maximum,
                    "last_stream_id": last_sid}

    async def record_attendance(self, username: str, stream_id: str, minutes: int, channel_id: int = None) -> dict:
        channel_id = resolve_channel_id(channel_id)
        username = username.lower()
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO stream_attendance (channel_id, username, stream_id, minutes, claimed)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(channel_id, username, stream_id) DO UPDATE SET minutes = MAX(minutes, excluded.minutes)
            """, (channel_id, username, stream_id, minutes))

            # Атомарно выставляем claimed=1 только если ещё не выдавали и порог достигнут
            # WHERE claimed=0 защищает от race condition двойной выдачи
            cur = await db.execute(
                "UPDATE stream_attendance SET claimed = 1 WHERE channel_id = ? AND username = ? AND stream_id = ? AND claimed = 0 AND minutes >= 15",
                (channel_id, username, stream_id))
            await db.commit()

            if cur.rowcount == 0:
                # Либо уже выдавали, либо минут недостаточно
                return {"rewarded": False}

            cur = await db.execute(
                "SELECT current_streak, max_streak, last_stream_id FROM stream_streaks WHERE channel_id = ? AND username = ?",
                (channel_id, username))
            srow = await cur.fetchone()

            if not srow:
                new_streak, max_streak = 1, 1
                await db.execute(
                    "INSERT INTO stream_streaks (channel_id, username, current_streak, max_streak, last_stream_id) VALUES (?,?,?,?,?)",
                    (channel_id, username, 1, 1, stream_id))
            else:
                prev_current, prev_max, last_sid = srow
                cur2 = await db.execute(
                    """SELECT COUNT(*) FROM stream_sessions s
                       WHERE s.channel_id = ? AND s.id != ? AND s.id != ?
                       AND s.started_at > (SELECT started_at FROM stream_sessions WHERE channel_id = ? AND id = ? LIMIT 1)
                       AND s.started_at < (SELECT started_at FROM stream_sessions WHERE channel_id = ? AND id = ? LIMIT 1)""",
                    (channel_id, last_sid, stream_id, channel_id, last_sid, channel_id, stream_id))
                gap_row = await cur2.fetchone()
                missed = gap_row[0] if gap_row else 0

                if last_sid == stream_id:
                    # Повторный claim в тот же стрим (не должно случиться при
                    # claimed=0 WHERE-гейте выше, но на всякий — сохраняем текущее).
                    new_streak = prev_current
                elif last_sid == "":
                    # Строка stream_streaks существует, но юзер ещё ни разу
                    # не получал награду за стрим (legacy/импорт). Это первый
                    # засчитанный стрим — стрик начинается с 1.
                    # Раньше здесь было new_streak = prev_current = 0, и юзер
                    # никогда не мог сдвинуть стрик вперёд (reward = 0).
                    new_streak = 1
                elif missed == 0:
                    new_streak = prev_current + 1
                else:
                    new_streak = 1

                max_streak = max(prev_max, new_streak)
                await db.execute(
                    """INSERT INTO stream_streaks (channel_id, username, current_streak, max_streak, last_stream_id)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(channel_id, username) DO UPDATE SET
                           current_streak = excluded.current_streak,
                           max_streak = excluded.max_streak,
                           last_stream_id = excluded.last_stream_id""",
                    (channel_id, username, new_streak, max_streak, stream_id))

            reward = 1000 * new_streak
            await db.execute(
                "UPDATE viewers SET points = points + ? WHERE channel_id = ? AND username = ?",
                (reward, channel_id, username))
            await db.commit()
            return {"rewarded": True, "reward": reward,
                    "current_streak": new_streak, "max_streak": max_streak}

    async def register_stream_session(self, stream_id: str, channel_id: int = None):
        """Зарегистрировать стрим (старт или возобновление).

        - Закрывает любые висящие другие сессии (ended_at=NULL) — страховка
          на случай рестарта сервера между стримами.
        - Если запись stream_id уже есть (второй стрим в тот же день после
          перерыва), сбрасывает ended_at=NULL — стрим снова «идёт», зрители
          могут его засчитать, get_streak не считает его пропуском.
        """
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            await db.execute(
                "UPDATE stream_sessions SET ended_at = datetime('now') "
                "WHERE channel_id = ? AND id != ? AND ended_at IS NULL",
                (channel_id, stream_id))
            # UPSERT: новая запись ИЛИ сброс ended_at у существующей.
            await db.execute(
                "INSERT INTO stream_sessions (channel_id, id, ended_at) VALUES (?, ?, NULL) "
                "ON CONFLICT(channel_id, id) DO UPDATE SET ended_at = NULL",
                (channel_id, stream_id))
            await db.commit()

    async def end_stream_session(self, stream_id: str, channel_id: int = None):
        """Пометить стрим как завершённый. Вызывается из reward_points_loop
        при переходе is_live: True→False. Без этого «пропущенный» стрим
        выглядит как «ещё идущий» и не сжигает стрик зрителей."""
        if not stream_id:
            return
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            await db.execute(
                "UPDATE stream_sessions SET ended_at = datetime('now') "
                "WHERE channel_id = ? AND id = ? AND ended_at IS NULL",
                (channel_id, stream_id))
            await db.commit()

    async def get_total_watch_hours(self, username: str, channel_id: int = None) -> float:
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT SUM(minutes) FROM stream_attendance WHERE channel_id = ? AND username = ?",
                (channel_id, username.lower()))
            row = await cur.fetchone()
            return (row[0] or 0) / 60.0


    # ===== СТАТИСТИКА (общая) =====
    async def get_stats(self, channel_id: int = None):
        """Общая статистика для одного канала."""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM viewers WHERE channel_id = ? AND is_afk = 0",
                (channel_id,))
            active = (await cursor.fetchone())[0]

            cursor = await db.execute(
                "SELECT SUM(points) FROM viewers WHERE channel_id = ?",
                (channel_id,))
            total_points = (await cursor.fetchone())[0] or 0

            today = date.today().isoformat()
            cursor = await db.execute("""
                SELECT COUNT(*) FROM quests
                WHERE channel_id = ? AND day_date = ? AND completed_at IS NULL
            """, (channel_id, today))
            active_quests = (await cursor.fetchone())[0]

            cursor = await db.execute("""
                SELECT COUNT(*) FROM drops
                WHERE channel_id = ? AND date(created_at) = date('now')
            """, (channel_id,))
            today_drops = (await cursor.fetchone())[0]

            # Добавляем статистику чата за сегодня
            cursor = await db.execute("""
                SELECT COUNT(*) FROM chat_stats
                WHERE channel_id = ? AND date(created_at) = date('now')
            """, (channel_id,))
            today_chat = (await cursor.fetchone())[0]

            # Добавляем статистику активности за сегодня
            cursor = await db.execute("""
                SELECT COUNT(DISTINCT username) FROM activity_stats
                WHERE channel_id = ? AND date(created_at) = date('now')
            """, (channel_id,))
            active_today = (await cursor.fetchone())[0]
            
            return {
                "active_viewers": active,
                "total_points": total_points,
                "active_quests": active_quests,
                "today_drops": today_drops,
                "today_chat_messages": today_chat,
                "active_users_today": active_today
            }

    # ===== M4: CHANNELS REGISTRY =====

    async def get_channel(self, channel_id: int) -> Optional[Dict]:
        """Вернуть запись стримера или None если канал не зарегистрирован.

        Используется в M4.1 для eager-registration check (require_jwt_user → 403
        если канал отсутствует) и в admin-UI lite для отображения tier/настроек.
        """
        async with self._connect() as db:
            cur = await db.execute(
                """
                SELECT channel_id, login, display_name, tier, active_module,
                       registered_at, last_seen_at,
                       oauth_access_token, oauth_refresh_token, oauth_expires_at,
                       eventsub_subscription_id
                FROM channels WHERE channel_id = ?
                """,
                (channel_id,),
            )
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "channel_id":               row[0],
                "login":                    row[1],
                "display_name":             row[2],
                "tier":                     row[3],
                "active_module":            row[4],
                "registered_at":            row[5],
                "last_seen_at":             row[6],
                "oauth_access_token":       row[7],
                "oauth_refresh_token":      row[8],
                "oauth_expires_at":         row[9],
                "eventsub_subscription_id": row[10],
            }

    async def list_channels(self) -> list:
        """Список всех зарегистрированных стримеров (для admin / cross-channel ops)."""
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT channel_id, login, tier, active_module, registered_at "
                "FROM channels ORDER BY registered_at DESC"
            )
            rows = await cur.fetchall()
            return [
                {"channel_id": r[0], "login": r[1], "tier": r[2],
                 "active_module": r[3], "registered_at": r[4]}
                for r in rows
            ]

    async def upsert_channel(
        self,
        channel_id: int,
        login: str,
        display_name: Optional[str] = None,
        tier: str = "free",
        oauth_access_token: Optional[str] = None,
        oauth_refresh_token: Optional[str] = None,
        oauth_expires_at: Optional[str] = None,
    ) -> None:
        """Создать/обновить запись стримера. Используется M4.3 OAuth callback'ом.

        OAuth-поля опциональны — initial registration через .env backfill их не
        ставит, OAuth-callback ставит их через тот же метод.

        ON CONFLICT обновляет login/display_name/last_seen всегда, OAuth-поля
        только если переданы (COALESCE с excluded — None НЕ затирает существующие).
        """
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO channels (channel_id, login, display_name, tier,
                                      oauth_access_token, oauth_refresh_token, oauth_expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    login                = excluded.login,
                    display_name         = excluded.display_name,
                    last_seen_at         = CURRENT_TIMESTAMP,
                    oauth_access_token   = COALESCE(excluded.oauth_access_token, oauth_access_token),
                    oauth_refresh_token  = COALESCE(excluded.oauth_refresh_token, oauth_refresh_token),
                    oauth_expires_at     = COALESCE(excluded.oauth_expires_at, oauth_expires_at)
                """,
                (channel_id, login.lower(), display_name or login, tier,
                 oauth_access_token, oauth_refresh_token, oauth_expires_at),
            )
            await db.commit()

    async def update_channel_oauth(
        self,
        channel_id: int,
        access_token: str,
        refresh_token: str,
        expires_at: str,
    ) -> bool:
        """Атомарное обновление только OAuth-полей канала.

        Используется M4 follow-up (б) refresh-loop'ом — по сравнению с
        `upsert_channel` не трогает login/display_name/tier/module чтобы
        случайно не затереть админ-настройки. Вернёт False если канала нет
        в реестре (race с удалением, например).
        """
        async with self._connect() as db:
            cur = await db.execute(
                """
                UPDATE channels SET
                    oauth_access_token  = ?,
                    oauth_refresh_token = ?,
                    oauth_expires_at    = ?,
                    last_seen_at        = CURRENT_TIMESTAMP
                WHERE channel_id = ?
                """,
                (access_token, refresh_token, expires_at, channel_id),
            )
            await db.commit()
            return cur.rowcount > 0

    # ===== ЭТАП 3 STEP 3: MODULE ACTIONS QUEUE =====
    #
    # Outbox-pattern: core enqueue'ит actions, connector long-poll'ит и ACK'ает.
    # Lifecycle: queued → dispatched → acked|failed. См. migrations/m5_module_actions.py.

    async def enqueue_action(
        self,
        channel_id: int,
        module_id: str,
        action_id: str,
        action_type: str,
        data: Optional[Dict] = None,
    ) -> int:
        """INSERT в module_actions со status=queued. Возвращает int PK.

        action_id — envelope id, выданный caller'ом (UUID или подобное). НЕ
        путать с PK таблицы (который служит cursor'ом для long-poll).
        """
        import json as _json
        async with self._connect() as db:
            cur = await db.execute(
                """
                INSERT INTO module_actions
                    (channel_id, module_id, action_id, type, data, status)
                VALUES (?, ?, ?, ?, ?, 'queued')
                """,
                (channel_id, module_id, action_id, action_type,
                 _json.dumps(data or {}, ensure_ascii=False)),
            )
            await db.commit()
            return cur.lastrowid

    async def fetch_pending_actions(
        self,
        channel_id: int,
        module_id: str,
        since_id: int = 0,
        limit: int = 50,
    ) -> List[Dict]:
        """Достаёт queued actions с PK > since_id. Атомарно помечает их
        status=dispatched перед возвратом — защита от двойной выдачи если
        connector long-poll переподключился и снова вызывает с тем же cursor.

        Returns list of dicts: {id, action_id, type, data (JSON-парсенный),
        created_at}. Пустой список = нет новых actions (long-poll waits).
        """
        import json as _json
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                """
                SELECT id, action_id, type, data, created_at
                FROM module_actions
                WHERE channel_id = ? AND module_id = ?
                  AND status = 'queued' AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (channel_id, module_id, int(since_id), int(limit)),
            )
            rows = await cur.fetchall()
            if not rows:
                await db.commit()
                return []
            ids = [r[0] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            await db.execute(
                f"UPDATE module_actions SET status='dispatched', dispatched_at=CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders})",
                ids,
            )
            await db.commit()

        result: List[Dict] = []
        for r in rows:
            try:
                data = _json.loads(r[3]) if r[3] else {}
            except (TypeError, ValueError):
                data = {}
            result.append({
                "id":         r[0],
                "action_id":  r[1],
                "type":       r[2],
                "data":       data,
                "created_at": r[4],
            })
        return result

    async def ack_action(
        self,
        channel_id: int,
        module_id: str,
        action_id: str,
        success: bool,
        error_msg: Optional[str] = None,
    ) -> bool:
        """Connector подтвердил исполнение action. Status → acked|failed.

        Возвращает False если запись не найдена (повторный ACK или action_id
        от чужого канала). Идемпотентно: повторный ACK для уже acked записи
        — no-op (rowcount=0 → False).
        """
        target_status = "acked" if success else "failed"
        async with self._connect() as db:
            cur = await db.execute(
                """
                UPDATE module_actions
                SET status     = ?,
                    acked_at   = CURRENT_TIMESTAMP,
                    error_msg  = ?
                WHERE channel_id = ? AND module_id = ? AND action_id = ?
                  AND status IN ('queued', 'dispatched')
                """,
                (target_status, error_msg, channel_id, module_id, action_id),
            )
            await db.commit()
            return cur.rowcount > 0

    # ===== ЭТАП 3 STEP 4: MODULE CATALOGS =====
    #
    # Catalog publish/consume через Module API (см. docs/MODULE_API.md §9).
    # Per-channel-per-module-per-type. Replace-семантика: новый catalog_update
    # event полностью заменяет существующий каталог (DELETE + INSERT в
    # одной транзакции).

    async def replace_module_catalog(
        self,
        channel_id: int,
        module_id: str,
        catalog_type: str,
        entries: List[Dict],
    ) -> int:
        """Полностью заменить каталог. Атомарно через BEGIN IMMEDIATE.

        entries — list of dicts. Каждый должен содержать `id` (или `entry_id`)
        — opaque ID, уникальный в рамках (channel, module, catalog_type).
        Полный entry serialised в payload как JSON.

        Returns count of inserted entries.
        """
        import json as _json
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "DELETE FROM module_catalogs WHERE channel_id=? AND module_id=? AND catalog_type=?",
                (channel_id, module_id, catalog_type),
            )
            inserted = 0
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                entry_id = str(entry.get("id") or entry.get("entry_id") or "")
                if not entry_id:
                    continue  # без id невозможно дедуплицировать
                payload = _json.dumps(entry, ensure_ascii=False)
                await db.execute(
                    """
                    INSERT INTO module_catalogs
                        (channel_id, module_id, catalog_type, entry_id, payload, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (channel_id, module_id, catalog_type, entry_id, payload),
                )
                inserted += 1
            await db.commit()
            return inserted

    async def get_module_catalog(
        self,
        channel_id: int,
        module_id: str,
        catalog_type: str,
    ) -> List[Dict]:
        """SELECT all entries для канала+модуля+типа. Возвращает list payloads
        (отпарсеных). Пустой list если каталог пуст / не публиковался."""
        import json as _json
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT payload FROM module_catalogs "
                "WHERE channel_id=? AND module_id=? AND catalog_type=? "
                "ORDER BY id ASC",
                (channel_id, module_id, catalog_type),
            )
            rows = await cur.fetchall()
        result: List[Dict] = []
        for r in rows:
            try:
                result.append(_json.loads(r[0]) if r[0] else {})
            except (TypeError, ValueError):
                continue
        return result

    async def clear_module_catalogs(
        self,
        channel_id: int,
        module_id: str,
    ) -> int:
        """Очистить все каталоги канала+модуля (всех типов). Вызывается на
        module.session_start per MULTITENANT_PLAN.md §H — каталоги
        session-scoped."""
        async with self._connect() as db:
            cur = await db.execute(
                "DELETE FROM module_catalogs WHERE channel_id=? AND module_id=?",
                (channel_id, module_id),
            )
            await db.commit()
            return cur.rowcount

    # ===== ЭТАП 3 STEP 5: MODULE API PLAYER EVENTS HELPERS =====
    #
    # Тонкие helpers под `RimWorldAdapter.handle_event` — пишут в rimworld_pawns
    # (текущая схема, разделяемая с легаси /api/rimworld/* эндпоинтами). Под
    # feature-flag MODULE_API_PLAYER_EVENTS_ENABLED — если false, adapter
    # пропускает вызовы (log only).

    async def upsert_player_pawn(
        self,
        channel_id: int,
        viewer_id: str,
        character_ref: str,
        is_alive: bool = True,
        health: float = 1.0,
    ) -> bool:
        """player.linked / player.state_update → UPSERT в rimworld_pawns.

        viewer_id здесь — Twitch login зрителя (то же что в legacy /api/
        rimworld/link). character_ref — pawn_name (либо ThingID).
        is_alive/health опциональны (state_update передаёт; linked нет).
        """
        viewer_id = (viewer_id or "").strip().lower()
        if not viewer_id or not character_ref:
            return False
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO rimworld_pawns
                    (channel_id, username, pawn_name, is_alive, health, last_sync)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id, username) DO UPDATE SET
                    pawn_name = excluded.pawn_name,
                    is_alive  = excluded.is_alive,
                    health    = excluded.health,
                    last_sync = CURRENT_TIMESTAMP
                """,
                (channel_id, viewer_id, character_ref,
                 1 if is_alive else 0, max(0.0, min(1.0, float(health)))),
            )
            await db.commit()
            return True

    async def mark_player_alive(
        self,
        channel_id: int,
        viewer_id: str,
        alive: bool,
    ) -> bool:
        """player.died (alive=False) / player.respawned (alive=True). UPDATE
        is_alive у существующей записи. Returns False если pawn'а не было
        (надо сначала player.linked прислать)."""
        viewer_id = (viewer_id or "").strip().lower()
        if not viewer_id:
            return False
        async with self._connect() as db:
            cur = await db.execute(
                """
                UPDATE rimworld_pawns
                SET is_alive  = ?,
                    health    = CASE WHEN ?=1 THEN MAX(health, 0.1) ELSE 0 END,
                    last_sync = CURRENT_TIMESTAMP
                WHERE channel_id = ? AND username = ?
                """,
                (1 if alive else 0, 1 if alive else 0, channel_id, viewer_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def remove_player_pawn(
        self,
        channel_id: int,
        viewer_id: str,
    ) -> bool:
        """player.unlinked → DELETE pawn (со всеми зависимыми по FK CASCADE
        — equipment, skills, hediffs, traits, genes, purchase_counters)."""
        viewer_id = (viewer_id or "").strip().lower()
        if not viewer_id:
            return False
        async with self._connect() as db:
            cur = await db.execute(
                "DELETE FROM rimworld_pawns WHERE channel_id = ? AND username = ?",
                (channel_id, viewer_id),
            )
            await db.commit()
            return cur.rowcount > 0

    # ===== ЭТАП 3 STEP 6.a: PAWN EXTENSION EVENTS HELPERS =====
    #
    # Под feature flag MODULE_API_PLAYER_EVENTS_ENABLED. RimWorld-specific
    # extension events (pawn.trait_changed / _gene_changed / _implant_installed
    # / _xenotype_changed) → INSERT/DELETE в rimworld_pawn_{traits,genes,
    # hediffs}. Все таблицы имеют FK на rimworld_pawns(id) — нужен сначала
    # resolve pawn_id из (channel_id, username).

    async def _get_pawn_id(self, channel_id: int, viewer_id: str) -> Optional[int]:
        """Резолв (channel_id, username) → rimworld_pawns.id. Возвращает None
        если pawn не linked."""
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT id FROM rimworld_pawns WHERE channel_id = ? AND username = ?",
                (channel_id, viewer_id),
            )
            row = await cur.fetchone()
            return int(row[0]) if row else None

    async def add_pawn_trait(
        self,
        channel_id: int,
        viewer_id: str,
        trait_def: str,
        degree: int = 0,
        label: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """pawn.trait_changed (added). INSERT в rimworld_pawn_traits.
        Возвращает False если pawn не найден."""
        viewer_id = (viewer_id or "").strip().lower()
        if not viewer_id or not trait_def:
            return False
        pawn_id = await self._get_pawn_id(channel_id, viewer_id)
        if pawn_id is None:
            return False
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO rimworld_pawn_traits (pawn_id, trait_def, degree, label, trait_desc)
                VALUES (?, ?, ?, ?, ?)
                """,
                (pawn_id, trait_def, int(degree), label or trait_def, description or ""),
            )
            await db.commit()
            return True

    async def remove_pawn_trait(
        self,
        channel_id: int,
        viewer_id: str,
        trait_def: str,
    ) -> bool:
        """pawn.trait_changed (removed). DELETE по trait_def."""
        viewer_id = (viewer_id or "").strip().lower()
        if not viewer_id or not trait_def:
            return False
        pawn_id = await self._get_pawn_id(channel_id, viewer_id)
        if pawn_id is None:
            return False
        async with self._connect() as db:
            cur = await db.execute(
                "DELETE FROM rimworld_pawn_traits WHERE pawn_id = ? AND trait_def = ?",
                (pawn_id, trait_def),
            )
            await db.commit()
            return cur.rowcount > 0

    async def add_pawn_gene(
        self,
        channel_id: int,
        viewer_id: str,
        def_name: str,
        label: Optional[str] = None,
        is_active: bool = True,
        xenogene: bool = True,
        gene_class: Optional[str] = None,
    ) -> bool:
        """pawn.gene_changed (added). INSERT в rimworld_pawn_genes."""
        viewer_id = (viewer_id or "").strip().lower()
        if not viewer_id or not def_name:
            return False
        pawn_id = await self._get_pawn_id(channel_id, viewer_id)
        if pawn_id is None:
            return False
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO rimworld_pawn_genes (pawn_id, def_name, label, is_active, xenogene, gene_class)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pawn_id, def_name, label or def_name,
                 1 if is_active else 0, 1 if xenogene else 0, gene_class or ""),
            )
            await db.commit()
            return True

    async def remove_pawn_gene(
        self,
        channel_id: int,
        viewer_id: str,
        def_name: str,
    ) -> bool:
        """pawn.gene_changed (removed). DELETE по def_name."""
        viewer_id = (viewer_id or "").strip().lower()
        if not viewer_id or not def_name:
            return False
        pawn_id = await self._get_pawn_id(channel_id, viewer_id)
        if pawn_id is None:
            return False
        async with self._connect() as db:
            cur = await db.execute(
                "DELETE FROM rimworld_pawn_genes WHERE pawn_id = ? AND def_name = ?",
                (pawn_id, def_name),
            )
            await db.commit()
            return cur.rowcount > 0

    async def add_pawn_implant(
        self,
        channel_id: int,
        viewer_id: str,
        body_part: str,
        hediff_label: str,
        severity: float = 0.0,
        icon: str = "🦾",
        is_permanent: bool = True,
        description: Optional[str] = None,
    ) -> bool:
        """pawn.implant_installed → INSERT в rimworld_pawn_hediffs с
        hediff_type='implant'."""
        viewer_id = (viewer_id or "").strip().lower()
        if not viewer_id or not hediff_label:
            return False
        pawn_id = await self._get_pawn_id(channel_id, viewer_id)
        if pawn_id is None:
            return False
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO rimworld_pawn_hediffs
                    (pawn_id, body_part, hediff_label, hediff_type, severity, icon, is_permanent, description)
                VALUES (?, ?, ?, 'implant', ?, ?, ?, ?)
                """,
                (pawn_id, body_part or "", hediff_label, float(severity), icon,
                 1 if is_permanent else 0, description or ""),
            )
            await db.commit()
            return True

    # ===== БЛОК 1 АРХИТЕКТУРНОЙ ПРОКАЧКИ: DB HEALTH & VISIBILITY =====
    #
    # Endpoint /api/admin/db/health дёргает эти методы. Цель: видеть БД
    # before-it-burns. Размер per-table, top-каналы по записям, WAL-стат.

    async def get_db_size_bytes(self) -> int:
        """Размер основного БД-файла в байтах (без WAL/SHM)."""
        import os as _os
        try:
            return _os.path.getsize(self.db_path)
        except OSError:
            return 0

    async def get_wal_size_bytes(self) -> int:
        """Размер WAL-файла в байтах. Большой WAL → checkpoint застрял."""
        import os as _os
        try:
            return _os.path.getsize(self.db_path + "-wal")
        except OSError:
            return 0

    async def get_table_sizes(self) -> List[Dict]:
        """Per-table page count + примерный размер. SQLite-specific через
        `dbstat` virtual table если включён, или через PRAGMA fallback.
        """
        async with self._connect() as db:
            # Через PRAGMA для каждой таблицы — page_count.
            cur = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            tables = [r[0] for r in await cur.fetchall()]
            cur = await db.execute("PRAGMA page_size")
            page_size_row = await cur.fetchone()
            page_size = int(page_size_row[0]) if page_size_row else 4096

            result: List[Dict] = []
            for tbl in tables:
                try:
                    cur = await db.execute(f"SELECT COUNT(*) FROM {tbl}")
                    row_count_row = await cur.fetchone()
                    row_count = int(row_count_row[0]) if row_count_row else 0
                except Exception:
                    row_count = -1
                result.append({
                    "table": tbl,
                    "row_count": row_count,
                    "approx_bytes": row_count * page_size if row_count > 0 else 0,
                })
        # Sort by row count desc — top-таблицы видны сразу
        result.sort(key=lambda x: x["row_count"], reverse=True)
        return result

    async def get_per_channel_record_counts(self, top: int = 10) -> List[Dict]:
        """Top-N каналов по числу строк viewers (proxy на размер канала).

        После M1 многие таблицы имеют channel_id, но viewers — самая
        репрезентативная. Дальше можно добавить inventory/chat_stats.
        """
        async with self._connect() as db:
            cur = await db.execute(
                """
                SELECT v.channel_id,
                       c.login,
                       c.tier,
                       COUNT(*) AS viewer_count
                FROM viewers v
                LEFT JOIN channels c ON c.channel_id = v.channel_id
                GROUP BY v.channel_id
                ORDER BY viewer_count DESC
                LIMIT ?
                """,
                (int(top),),
            )
            rows = await cur.fetchall()
        return [
            {
                "channel_id": r[0],
                "login": r[1] or "(unknown)",
                "tier": r[2] or "(unknown)",
                "viewers": r[3],
            }
            for r in rows
        ]

    async def wal_checkpoint(self, mode: str = "PASSIVE") -> Optional[Dict]:
        """Принудительный WAL checkpoint. Возвращает stats или None при ошибке.

        Modes (SQLite docs):
          PASSIVE  — не блокирует writers, чекпоинтит сколько может
          FULL     — ждёт writer'ов, чекпоинтит до конца
          RESTART  — после FULL ждёт readers
          TRUNCATE — после RESTART усекает WAL до нуля

        Для periodic loop достаточно PASSIVE. RESTART/TRUNCATE — раз в сутки
        чтобы WAL не рос indefinitely.
        """
        mode = (mode or "PASSIVE").upper()
        if mode not in ("PASSIVE", "FULL", "RESTART", "TRUNCATE"):
            mode = "PASSIVE"
        async with self._connect() as db:
            try:
                cur = await db.execute(f"PRAGMA wal_checkpoint({mode})")
                row = await cur.fetchone()
                # Returns (busy, log, checkpointed): busy=0 OK, log=pages в WAL,
                # checkpointed=сколько перенесено в основной файл.
                if row:
                    return {"mode": mode, "busy": row[0], "log_pages": row[1], "checkpointed_pages": row[2]}
            except Exception as e:
                print(f"⚠️  wal_checkpoint failed: {e}")
        return None