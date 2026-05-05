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

            # Статистика активности
            await db.execute("""
                CREATE TABLE IF NOT EXISTS activity_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    watch_time INTEGER DEFAULT 0,
                    active_clicks INTEGER DEFAULT 0,
                    active_moves INTEGER DEFAULT 0,
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
            
            
                        # Статистика крафта (для прогрессии шанса)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS craft_stats (
                    username TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    crafted_count INTEGER DEFAULT 0,
                    PRIMARY KEY (username, item_type)
                )
            """)

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
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_achievements (
                    username TEXT NOT NULL, achievement_key TEXT NOT NULL,
                    unlocked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (username, achievement_key)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stream_streaks (
                    username TEXT PRIMARY KEY, current_streak INTEGER DEFAULT 0,
                    max_streak INTEGER DEFAULT 0, last_stream_id TEXT DEFAULT ''
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stream_attendance (
                    username TEXT NOT NULL, stream_id TEXT NOT NULL,
                    minutes INTEGER DEFAULT 0, claimed INTEGER DEFAULT 0,
                    PRIMARY KEY (username, stream_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stream_sessions (
                    id TEXT PRIMARY KEY,
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ended_at   DATETIME DEFAULT NULL
                )
            """)
            # Миграция: добавить колонку в существующие БД.
            # ended_at нужен чтобы отличать «стрим ещё идёт» (нельзя засчитать
            # как пропуск) от «стрим закончился» (можно считать сгоревшим стриком).
            try:
                await db.execute("ALTER TABLE stream_sessions ADD COLUMN ended_at DATETIME DEFAULT NULL")
            except Exception:
                pass  # колонка уже есть

            # Казино — настройки (джекпот и т.д.)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS casino_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            await db.execute(
                "INSERT OR IGNORE INTO casino_settings (key, value) VALUES ('jackpot', '10000')"
            )
            # Ежедневные фриспины
            await db.execute("""
                CREATE TABLE IF NOT EXISTS free_spins_daily (
                    username TEXT PRIMARY KEY,
                    last_claim TEXT NOT NULL,
                    spins_used INTEGER DEFAULT 0
                )
            """)

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
                ('first_craft',      'Первый крафт',              'Скрафтил первый предмет',                  '🔨',   500),
                ('first_duel_win',   'Первая победа в дуэли',     'Выиграл первую дуэль',                     '⚔️',   500),
                ('first_rimworld_buy','Покупатель RimWorld',      'Купил первый предмет в RimWorld',          '🛒',   500),
                ('first_casino',     'Удача новичка',             'Первый раз сыграл в казино',               '🎰',   300),
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
        
        
        
        
    async def get_craft_count(self, username: str, item_type: str, channel_id: int = None) -> int:
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            c = await db.execute("SELECT crafted_count FROM craft_stats WHERE channel_id = ? AND username=? AND item_type=?",
                                 (channel_id, username.lower(), item_type))
            row = await c.fetchone()
            return row[0] if row else 0

    def calc_craft_chance(self, owned_count: int) -> int:
        """Шанс крафта: 100% - (кол-во предмета в инвентаре * 5%), минимум 50%"""
        return max(50, 100 - owned_count * 5)
    
    
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
    async def add_activity(self, username: str, watch_time: int, clicks: int = 0, moves: int = 0, channel_id: int = None):
        """Добавить запись об активности"""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO activity_stats (channel_id, username, watch_time, active_clicks, active_moves)
                VALUES (?, ?, ?, ?, ?)
            """, (channel_id, username.lower(), watch_time, clicks, moves))
            await db.commit()

    async def get_today_activity(self, username: str, channel_id: int = None) -> dict:
        """Получить активность за сегодня"""
        channel_id = resolve_channel_id(channel_id)
        today = date.today().isoformat()

        async with self._connect() as db:
            cursor = await db.execute("""
                SELECT
                    SUM(watch_time) as total_time,
                    SUM(active_clicks) as total_clicks,
                    SUM(active_moves) as total_moves,
                    COUNT(*) as sessions
                FROM activity_stats
                WHERE channel_id = ? AND username = ? AND date(created_at) = ?
            """, (channel_id, username.lower(), today))
            
            row = await cursor.fetchone()
            
            if row and row[0]:
                return {
                    "total_time": row[0] or 0,
                    "total_clicks": row[1] or 0,
                    "total_moves": row[2] or 0,
                    "sessions": row[3] or 0
                }
            return {
                "total_time": 0,
                "total_clicks": 0,
                "total_moves": 0,
                "sessions": 0
            }
    
    async def get_activity_stats(self, username: str, days: int = 7, channel_id: int = None) -> List[dict]:
        """Получить статистику активности за последние N дней"""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cursor = await db.execute("""
                SELECT
                    date(created_at) as day,
                    SUM(watch_time) as total_time,
                    SUM(active_clicks) as total_clicks
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
                    "total_clicks": row[2] or 0
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