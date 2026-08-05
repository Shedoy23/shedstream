# database.py - работа с твоей БД
import re as _re_db
import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Optional, List, Dict

from db_pool import DBPool
from dependencies import resolve_channel_id

import os as _os_db


# ── At-rest encryption for stored OAuth tokens (channels table) ───────────────
# Streamer OAuth access/refresh tokens are HIGH-value secrets (leak = channel
# takeover). Encrypted at rest with Fernet keyed by DB_ENCRYPTION_KEY (.env).
# Transition-safe: ciphertext carries an "enc:" prefix, so legacy plaintext rows
# decrypt as-is and become encrypted on their next write. If the key is unset/
# invalid, storage falls back to plaintext (current behaviour) with a loud
# one-time warning — set DB_ENCRYPTION_KEY in prod to actually encrypt.
_ENC_PREFIX = "enc:"
_fernet_cached = None
_fernet_init = False


def _get_fernet():
    global _fernet_cached, _fernet_init
    if not _fernet_init:
        _fernet_init = True
        key = (_os_db.getenv("DB_ENCRYPTION_KEY") or "").strip()
        if key:
            try:
                from cryptography.fernet import Fernet
                _fernet_cached = Fernet(key.encode())
            except Exception as e:
                print(f"⚠️  DB_ENCRYPTION_KEY невалиден — OAuth-токены хранятся БЕЗ шифрования: {e}")
        else:
            print("⚠️  DB_ENCRYPTION_KEY не задан — OAuth-токены стримеров хранятся БЕЗ шифрования. "
                  "Сгенерируй Fernet-ключ и пропиши в .env как DB_ENCRYPTION_KEY=...")
    return _fernet_cached


def _encrypt_secret(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a secret for at-rest storage. None/empty/already-encrypted pass through."""
    if not plaintext or plaintext.startswith(_ENC_PREFIX):
        return plaintext
    f = _get_fernet()
    if not f:
        return plaintext
    return _ENC_PREFIX + f.encrypt(plaintext.encode()).decode()


def _decrypt_secret(stored: Optional[str]) -> Optional[str]:
    """Decrypt a stored secret. Legacy plaintext (no prefix) is returned unchanged."""
    if not stored or not stored.startswith(_ENC_PREFIX):
        return stored
    f = _get_fernet()
    if not f:
        return stored
    try:
        return f.decrypt(stored[len(_ENC_PREFIX):].encode()).decode()
    except Exception:
        return stored


# 2026-05-17: Guard helper — детектит Twitch opaque user IDs.
# `u_xxx` / 15+ base64url chars — это значит viewer НЕ нажал Share Identity.
_OPAQUE_RX = _re_db.compile(r"^u[a-z0-9_-]{15,}$")


def _is_opaque_login(name: str) -> bool:
    """True если имя похоже на Twitch opaque_user_id (не real login)."""
    if not name:
        return False
    n = name.strip().lower()
    return bool(_OPAQUE_RX.match(n)) or len(n) > 25

def _utc_for_client(ts) -> Optional[str]:
    """Пометить сохранённое время как UTC, прежде чем отдать его в браузер.

    2026-08-05 (владелец: «не работает таймер автоокончания»). Время окончания
    голосования пишется как `datetime.utcnow().isoformat()` — без пометки часового
    пояса. Браузер по стандарту читает такую строку как МЕСТНОЕ время, поэтому
    зритель из Москвы получал срок на три часа раньше настоящего, и обратный
    отсчёт показывал 00:00 с первой же секунды.

    Чиним на бэкенде намеренно, а не во фронте: фронт замерзает на CDN до
    следующего ревью Twitch, а бэкенд доезжает до зрителей за минуты — значит
    уже опубликованный клиент 0.0.1 получает исправный отсчёт сразу.

    Значения, у которых пояс уже указан, не трогаем.
    """
    if not ts:
        return ts
    s = str(ts).strip().replace(" ", "T")
    if s.endswith("Z") or "+" in s[10:] or "-" in s[10:]:
        return s
    return s + "Z"


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
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    category TEXT NOT NULL,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (channel_id, username, category)
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

            # twitch_ids больше не создаётся (2026-07-29): к таблице не
            # обращался ни один запрос, на проде она пустая. Сопоставление
            # twitch_id → username живёт в `viewers`.

            # Пешки RimWorld
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    pawn_name TEXT NOT NULL,
                    is_alive INTEGER DEFAULT 1,
                    health REAL DEFAULT 1.0,
                    world_id TEXT DEFAULT '',
                    world_name TEXT DEFAULT '',
                    last_sync DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, username)
                )
            """)

            # Экипировка пешек (meta: JSON с weapon_traits, psi, quality, stuff, max_hp и т.д.)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_equipment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
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
                    channel_id INTEGER NOT NULL,
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
                    channel_id INTEGER NOT NULL,
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
                    channel_id INTEGER NOT NULL,
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
                    channel_id INTEGER NOT NULL,
                    pawn_id INTEGER NOT NULL,
                    def_name TEXT NOT NULL,
                    label TEXT,
                    is_active INTEGER DEFAULT 1,
                    xenogene INTEGER DEFAULT 1,
                    gene_class TEXT DEFAULT '',
                    FOREIGN KEY (pawn_id) REFERENCES rimworld_pawns(id)
                )
            """)

            # rimworld_catalog больше не создаётся (2026-07-29): это
            # предшественник нынешнего каталога (`shop_catalog`), к нему не
            # обращался ни один запрос, на проде он пустой.

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

            # market_listings — удалён 2026-05-10 (Phase 1.C compliance rework — P2P
            # trade items, §6.2.8 + 2026-Bits-tightening). DROP TABLE в M8.

            # craft_stats — удалён 2026-05-10 (Phase 1.B compliance rework, 3/3 gambling).
            # DROP TABLE будет в M8. См. COMPLIANCE_REWORK_PLAN.md §4 Phase 1.

            # Items seed убран 2026-05-13 (Phase 8.C lexicon/compliance):
            # items с value>0 = passive-income utility = §5.3 advantage violation.
            # items.value колонка остаётся для legacy data, но больше не используется
            # (см. bot_core._get_viewer_bonus / viewer.py income calc — закомменчены).
            # Inventory таблица остаётся для UI cosmetic, но quests/events больше
            # НЕ выдают items.

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

            # Дуэли — ELO и стрики (post-M10 schema: per-channel + per-game)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS duel_stats (
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    game_type TEXT NOT NULL DEFAULT 'rps',
                    elo INTEGER NOT NULL DEFAULT 1100,
                    win_streak INTEGER NOT NULL DEFAULT 0,
                    season_id INTEGER NOT NULL DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (channel_id, username, game_type)
                )
            """)
            # Сезоны дуэлей (post-M10: per-channel + per-game)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS duel_seasons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    game_type TEXT NOT NULL DEFAULT 'rps',
                    started_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    finished INTEGER NOT NULL DEFAULT 0
                )
            """)
            # pending_duels (legacy) — DROP в M10 (Phase 5.0). Заменён на
            # match_queue + match_rooms (см. m10_matchmaking.py).

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
        """Начислить очки. channel_id опционален пока M3 не протолкнёт его везде.

        2026-05-17: Guard против opaque Twitch IDs (u_xxx / длинные base64url
        строки). Если такая запись попала в `viewers` через старый JWT-баг —
        НЕ накручивать ей points, иначе reward_points_loop'у не выйдет из
        неё (add_points refreshes last_seen → record never times out).
        """
        if username and _is_opaque_login(username):
            return  # silently skip opaque entries (don't enable infinite loop)
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

    # ── Атомарные варианты на СУЩЕСТВУЮЩЕМ conn ────────────────────────────────
    # add_points/remove_points открывают своё соединение и коммитят сами → не
    # атомарны с окружающей логикой (краш в окне = деньги списаны без эффекта /
    # награда выдана дважды). Эти _tx-версии работают на переданном conn: вызывающий
    # сам делает BEGIN IMMEDIATE + commit, начисление/списание входит в ту же
    # транзакцию, что и изменение состояния. channel_id ОБЯЗАТЕЛЕН (не резолвим —
    # атомарные пути не должны зависеть от ContextVar).
    async def add_points_tx(self, conn, username: str, amount: int, channel_id: int):
        """Начислить очки на существующем conn (без commit — на вызывающем)."""
        if username and _is_opaque_login(username):
            return
        await conn.execute("""
            INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk)
            VALUES (?, ?, ?, datetime('now'), datetime('now'), 0)
            ON CONFLICT(channel_id, username) DO UPDATE SET
                points = points + ?, last_seen = datetime('now')
        """, (channel_id, username.lower(), amount, amount))

    async def remove_points_tx(self, conn, username: str, amount: int, channel_id: int) -> bool:
        """Списать очки на существующем conn (без commit). True если хватило."""
        cur = await conn.execute(
            "UPDATE viewers SET points = points - ? "
            "WHERE channel_id = ? AND username = ? AND points >= ?",
            (amount, channel_id, username.lower(), amount))
        return cur.rowcount > 0

    # ===== ПРОГРЕССИВНЫЕ СЧЁТЧИКИ (черты и гены) =====

    async def get_purchase_count(self, username: str, category: str,
                                 channel_id: int) -> int:
        """Сколько раз зритель купил предметы данной категории (trait/gene)."""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT count FROM purchase_counters "
                "WHERE channel_id = ? AND username = ? AND category = ?",
                (channel_id, username.lower(), category)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def increment_purchase_count(self, username: str, category: str,
                                       channel_id: int) -> int:
        """Увеличить счётчик покупок на 1. Возвращает НОВОЕ значение (после инкремента)."""
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO purchase_counters (channel_id, username, category, count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(channel_id, username, category) DO UPDATE SET count = count + 1
            """, (channel_id, username.lower(), category))
            await db.commit()
            cursor = await db.execute(
                "SELECT count FROM purchase_counters "
                "WHERE channel_id = ? AND username = ? AND category = ?",
                (channel_id, username.lower(), category)
            )
            row = await cursor.fetchone()
            return row[0] if row else 1

    async def decrement_purchase_count_tx(self, conn, username: str, category: str,
                                          channel_id: int) -> None:
        """Откатить счётчик покупок на 1 — на conn ВЫЗЫВАЮЩЕГО, без commit.

        Нужен рефанду: цены на гены/черты прогрессивные, счётчик растёт при
        покупке. Если команду не выполнили и вернули крустики, а счётчик оставили
        поднятым — зритель наказан ценой за покупку, которой не было (следующий
        ген дороже навсегда). Возврат денег и откат счётчика обязаны быть в ОДНОЙ
        транзакции: иначе падение между ними даёт либо вечную переплату, либо
        бесплатное удешевление.

        MAX(0, ...) — счётчик не должен уходить в минус даже при повторном ack.
        """
        await conn.execute(
            "UPDATE purchase_counters SET count = MAX(0, count - 1) "
            "WHERE channel_id = ? AND username = ? AND category = ?",
            (channel_id, username.lower(), category),
        )

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
        
        
        
        
    @staticmethod
    def level_from_total_exp(total_exp: int) -> tuple:
        """EXP → (уровень, остаток EXP внутри уровня).

        ЕДИНСТВЕННОЕ место, где живёт эта формула. 2026-07-27 понадобился
        уровень ещё и в overlay (подпись над питомцем) — вторая копия цикла
        разъехалась бы с этой при первой же правке баланса, а зритель увидел
        бы в расширении один уровень, на стриме другой. Это ровно класс
        «одно число в двух местах» из CLAUDE.md.

        Порог: 1-5 → 100 EXP за уровень, 6-10 → 200, 11-15 → 300 …
        """
        level = 1
        exp_current = int(total_exp)
        while level < 100:
            needed = ((level + 4) // 5) * 100
            if exp_current < needed:
                break
            exp_current -= needed
            level += 1
        return level, exp_current

    async def get_user_level(self, username: str, channel_id: int = None) -> dict:
        """Расчёт уровня: 1 минута просмотра = 1 EXP."""
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT COALESCE(SUM(watch_time), 0) FROM activity_stats WHERE channel_id = ? AND username = ?",
                (channel_id, username.lower())
            )
            row = await cur.fetchone()
            total_exp = int(row[0] / 60) if row else 0

        level, exp_current = self.level_from_total_exp(total_exp)

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
                       (SELECT COUNT(*) FROM rimworld_skills s
                        WHERE s.channel_id=c.channel_id AND s.colonist_id=c.id) as skill_count
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
            # BEGIN IMMEDIATE: serialize concurrent unlocks of the same achievement so the dedup
            # SELECT + the reward credit are atomic. Without it both callers pass the SELECT (no row
            # yet) and both run the points UPDATE → the reward is credited twice.
            await db.execute("BEGIN IMMEDIATE")
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
            await db.execute("BEGIN IMMEDIATE")
            # M89: first_seen_at = время ПЕРВОГО пинга (не обновляется на MAX-конфликте;
            # backfill COALESCE'ом для legacy-строк, у которых оно ещё NULL).
            await db.execute("""
                INSERT INTO stream_attendance (channel_id, username, stream_id, minutes, claimed, first_seen_at)
                VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id, username, stream_id) DO UPDATE SET
                    minutes = MAX(minutes, excluded.minutes),
                    first_seen_at = COALESCE(first_seen_at, CURRENT_TIMESTAMP)
            """, (channel_id, username, stream_id, minutes))

            # Атомарно выставляем claimed=1 только если ещё не выдавали и порог достигнут.
            # WHERE claimed=0 защищает от race condition двойной выдачи.
            # SECURITY (аудит 2026-07-02): `minutes` приходит от клиента — по нему одному
            # выдавать нельзя (crafted-запрос с minutes=15 забирал бы стрик без просмотра).
            # Гейт по СЕРВЕРНОМУ времени: >= 15 реальных минут с первого пинга (first_seen_at).
            # first_seen_at IS NULL — legacy-строка до M89, grandfathered.
            cur = await db.execute(
                "UPDATE stream_attendance SET claimed = 1 "
                "WHERE channel_id = ? AND username = ? AND stream_id = ? AND claimed = 0 AND minutes >= 15 "
                "AND (first_seen_at IS NULL OR (strftime('%s','now') - strftime('%s', first_seen_at)) >= 900)",
                (channel_id, username, stream_id))

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

    async def get_active_stream_id(self, channel_id: int) -> str:
        """ID текущей незакрытой стрим-сессии канала ('' если нет). Нужен чтобы
        восстановить in-memory current_stream_id после рестарта бэка посреди
        стрима — иначе минуты посещаемости/стрик молча теряются до след. тика."""
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT id FROM stream_sessions "
                "WHERE channel_id = ? AND ended_at IS NULL "
                "ORDER BY started_at DESC LIMIT 1",
                (channel_id,))
            row = await cur.fetchone()
        return (row[0] if row and row[0] else "") or ""

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

    async def end_active_stream_sessions(self, channel_id: int = None) -> int:
        """Закрыть все активные стрим-сессии канала (ended_at=NULL → NOW).

        Используется EventSub `stream.offline` handler'ом — Twitch не присылает
        stream_id в offline-payload, только broadcaster_user_id. Возвращает
        число закрытых сессий (обычно 0 или 1).
        """
        channel_id = resolve_channel_id(channel_id)
        async with self._connect() as db:
            cur = await db.execute(
                "UPDATE stream_sessions SET ended_at = datetime('now') "
                "WHERE channel_id = ? AND ended_at IS NULL",
                (channel_id,))
            await db.commit()
            return cur.rowcount or 0

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

    # ===== КЕЙСЫ (Phase 2, 2026-05-11) =====
    # Compliance: фиксированная награда крустиков per tier, без RNG в содержимом.
    # Кейсы выдаются за активность бесплатно (§5.3 Twitch — loot boxes OK
    # если contents без monetary value; наша валюта non-tradable).

    async def grant_case(
        self,
        username: str,
        tier: str,
        source: str,
        channel_id: Optional[int] = None,
        trigger_key: Optional[str] = None,
    ) -> Dict:
        """Выдать кейс юзеру.

        Args:
            username: имя юзера (lowered внутри)
            tier: 'common' | 'rare' | 'epic' | 'legendary'
            source: одна из CASE_SOURCES (audit откуда)
            channel_id: канал (None → ContextVar)
            trigger_key: если не None — идемпотентность через
                case_triggers_fired. Тот же trigger_key для (channel, user)
                → кейс НЕ выдаётся повторно. Пример: 'watch_100h',
                'streak_10', 'season_2026_Q1_top1'.

        Returns:
            {'granted': True, 'case_id': N, 'tier': X, 'source': Y}
            если выдан;
            {'granted': False, 'reason': 'already_fired'}
            если trigger_key уже сработал;
            {'granted': False, 'reason': 'invalid_tier' | 'invalid_source'}
            при ошибке валидации.
        """
        from config import CASE_TIER_REWARDS, CASE_SOURCES
        if tier not in CASE_TIER_REWARDS:
            return {'granted': False, 'reason': 'invalid_tier', 'tier': tier}
        if source not in CASE_SOURCES:
            return {'granted': False, 'reason': 'invalid_source', 'source': source}

        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                # Идемпотентность через trigger_key
                if trigger_key:
                    cur = await conn.execute(
                        "SELECT case_id FROM case_triggers_fired "
                        "WHERE channel_id = ? AND username = ? AND trigger_key = ?",
                        (cid, uname, trigger_key)
                    )
                    existing = await cur.fetchone()
                    if existing:
                        await conn.execute("ROLLBACK")
                        return {
                            'granted': False, 'reason': 'already_fired',
                            'trigger_key': trigger_key, 'case_id': existing[0]
                        }

                # Insert case
                cur = await conn.execute(
                    "INSERT INTO cases (channel_id, username, tier, source) "
                    "VALUES (?, ?, ?, ?)",
                    (cid, uname, tier, source)
                )
                case_id = cur.lastrowid

                # Запись в case_triggers_fired если trigger_key передан
                if trigger_key:
                    await conn.execute(
                        "INSERT INTO case_triggers_fired "
                        "(channel_id, username, trigger_key, case_id) "
                        "VALUES (?, ?, ?, ?)",
                        (cid, uname, trigger_key, case_id)
                    )

                await conn.commit()
                return {
                    'granted': True, 'case_id': case_id,
                    'tier': tier, 'source': source
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def open_case(
        self,
        case_id: int,
        username: str,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Открыть кейс. Атомарно списать ownership + добавить reward в points.

        Args:
            case_id: id кейса (из cases.id)
            username: должен быть владельцем (защита от cross-user open)
            channel_id: канал (None → ContextVar; используется в JWT-роутах)

        Returns:
            {'opened': True, 'tier': X, 'reward_points': N, 'new_balance': M}
            если открыт впервые;
            {'opened': False, 'reason': 'already_opened' | 'not_found' |
             'not_owner'} в остальных случаях.
        """
        from config import CASE_TIER_REWARDS
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                # Lock case row + validate ownership and unopened state
                cur = await conn.execute(
                    "SELECT channel_id, username, tier, opened_at FROM cases WHERE id = ?",
                    (case_id,)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'opened': False, 'reason': 'not_found'}

                row_cid, row_user, row_tier, row_opened = row
                if row_cid != cid or row_user != uname:
                    await conn.execute("ROLLBACK")
                    return {'opened': False, 'reason': 'not_owner'}
                if row_opened is not None:
                    await conn.execute("ROLLBACK")
                    return {'opened': False, 'reason': 'already_opened'}

                reward = CASE_TIER_REWARDS.get(row_tier, 0)
                if reward <= 0:
                    # Защита от tier'а удалённого из config (старые кейсы)
                    await conn.execute("ROLLBACK")
                    return {'opened': False, 'reason': 'invalid_tier_no_reward'}

                # Mark opened + record final reward (защита от изменения config
                # после открытия — historical accuracy)
                await conn.execute(
                    "UPDATE cases SET opened_at = CURRENT_TIMESTAMP, reward_points = ? "
                    "WHERE id = ? AND opened_at IS NULL",
                    (reward, case_id)
                )

                # Кредитуем крустики в viewers.points (UPSERT — на случай если
                # юзер недавно создан и записи нет)
                await conn.execute("""
                    INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk)
                    VALUES (?, ?, ?, datetime('now'), datetime('now'), 0)
                    ON CONFLICT(channel_id, username) DO UPDATE SET
                        points = points + excluded.points,
                        last_seen = datetime('now'),
                        is_afk = 0
                """, (cid, uname, reward))

                # Получаем новый баланс
                cur = await conn.execute(
                    "SELECT points FROM viewers WHERE channel_id = ? AND username = ?",
                    (cid, uname)
                )
                balance_row = await cur.fetchone()
                new_balance = balance_row[0] if balance_row else 0

                await conn.commit()
                return {
                    'opened': True,
                    'tier': row_tier,
                    'reward_points': reward,
                    'new_balance': new_balance,
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def list_cases(
        self,
        username: str,
        channel_id: Optional[int] = None,
        include_opened: bool = True,
        limit: int = 50,
    ) -> list:
        """Список кейсов юзера, новейшие первыми.

        Args:
            username: имя
            channel_id: канал (None → ContextVar)
            include_opened: True = все кейсы; False = только закрытые
            limit: max записей (UI обычно показывает 50 макс)

        Returns:
            [{'id': ..., 'tier': ..., 'source': ..., 'awarded_at': ...,
              'opened_at': ..., 'reward_points': ...}]
        """
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        query = (
            "SELECT id, tier, source, awarded_at, opened_at, reward_points "
            "FROM cases WHERE channel_id = ? AND username = ?"
        )
        if not include_opened:
            query += " AND opened_at IS NULL"
        query += " ORDER BY awarded_at DESC LIMIT ?"

        async with self._connect() as conn:
            cur = await conn.execute(query, (cid, uname, limit))
            rows = await cur.fetchall()
            return [
                {
                    'id': r[0],
                    'tier': r[1],
                    'source': r[2],
                    'awarded_at': r[3],
                    'opened_at': r[4],
                    'reward_points': r[5],
                }
                for r in rows
            ]

    async def count_unopened_cases(
        self,
        username: str,
        channel_id: Optional[int] = None,
    ) -> Dict[str, int]:
        """Сколько закрытых кейсов у юзера, разбивка по tier.

        Используется UI для badge'а на иконке «Кейсы» — сколько ждёт открытия.

        Returns:
            {'common': N, 'rare': N, 'epic': N, 'legendary': N, 'total': N}
        """
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT tier, COUNT(*) FROM cases "
                "WHERE channel_id = ? AND username = ? AND opened_at IS NULL "
                "GROUP BY tier",
                (cid, uname)
            )
            rows = await cur.fetchall()

        counts = {'common': 0, 'rare': 0, 'epic': 0, 'legendary': 0}
        for tier, count in rows:
            if tier in counts:
                counts[tier] = count
        counts['total'] = sum(counts.values())
        return counts

    async def count_all_cases(
        self,
        username: str,
        channel_id: Optional[int] = None,
    ) -> int:
        """Сколько ВСЕГО кейсов выпало юзеру за всё время (open + closed).

        Sprint 5.28: используется UI для empty-state messaging — отличить
        «новый юзер, ни одного не получал» от «всё открыл».
        """
        cid = resolve_channel_id(channel_id)
        uname = username.lower()
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM cases "
                "WHERE channel_id = ? AND username = ?",
                (cid, uname)
            )
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def is_trigger_fired(
        self,
        username: str,
        trigger_key: str,
        channel_id: Optional[int] = None,
    ) -> bool:
        """Проверить сработал ли one-time trigger для (channel, user, trigger_key).

        Helper для логики триггеров чтобы не дёргать grant_case впустую.
        """
        cid = resolve_channel_id(channel_id)
        uname = username.lower()
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT 1 FROM case_triggers_fired "
                "WHERE channel_id = ? AND username = ? AND trigger_key = ?",
                (cid, uname, trigger_key)
            )
            return await cur.fetchone() is not None

    # ===== PETS MVP (Phase 7, 2026-05-11) — CROSS-CHANNEL =====
    # ВАЖНО: pets-таблицы GLOBAL per user (без channel_id в PK).
    # Это explicit exception от multi-tenant invariant (см. ARCHITECTURE.md §3.1).
    # channel_id хранится в pet_purchases только для revenue attribution (§7.5).

    async def ensure_pet(self, username: str) -> Dict:
        """Гарантирует что у юзера есть pet (creates 🥚 если нет).

        Returns:
            {'pet': {username, pet_type, hatched_at, last_seen, name},
             'created': bool}
        """
        uname = username.lower()
        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                cur = await conn.execute(
                    "SELECT username, pet_type, hatched_at, last_seen, name "
                    "FROM pets WHERE username = ?",
                    (uname,)
                )
                row = await cur.fetchone()
                if row:
                    # Update last_seen
                    await conn.execute(
                        "UPDATE pets SET last_seen = CURRENT_TIMESTAMP WHERE username = ?",
                        (uname,)
                    )
                    await conn.commit()
                    return {
                        'created': False,
                        'pet': {
                            'username': row[0], 'pet_type': row[1],
                            'hatched_at': row[2], 'last_seen': row[3],
                            'name': row[4],
                        },
                    }
                # Hatch new pet
                from config import PET_BASE_TYPE
                await conn.execute(
                    "INSERT INTO pets (username, pet_type) VALUES (?, ?)",
                    (uname, PET_BASE_TYPE)
                )
                cur = await conn.execute(
                    "SELECT username, pet_type, hatched_at, last_seen, name "
                    "FROM pets WHERE username = ?",
                    (uname,)
                )
                row = await cur.fetchone()
                await conn.commit()
                return {
                    'created': True,
                    'pet': {
                        'username': row[0], 'pet_type': row[1],
                        'hatched_at': row[2], 'last_seen': row[3],
                        'name': row[4],
                    },
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def get_my_pet(self, username: str) -> Dict:
        """Pet juicy info: pet appearance + inventory + equipped slots.

        Cross-channel: НЕ scope'ит по channel_id (pets global per user).
        """
        uname = username.lower()
        await self.ensure_pet(username)

        async with self._connect() as conn:
            # Pet base
            cur = await conn.execute(
                "SELECT pet_type, hatched_at, last_seen, name FROM pets WHERE username = ?",
                (uname,)
            )
            pet_row = await cur.fetchone()
            pet = {
                'pet_type':   pet_row[0],
                'hatched_at': pet_row[1],
                'last_seen':  pet_row[2],
                'name':       pet_row[3],
            }

            # Inventory + catalog join
            # Sprint 5.21: добавлен svg_path для items с inline SVG art
            cur = await conn.execute(
                "SELECT pi.item_id, pc.name, pc.slot, pc.rarity, pc.emoji, "
                "       pc.svg_path, pi.acquired_at "
                "FROM pet_inventory pi "
                "JOIN pet_catalog pc ON pc.item_id = pi.item_id "
                # deprecated НЕ фильтруем: снятый с продажи item остаётся в инвентаре
                # владельца (лимитка/эксклюзив — купивший сохраняет его навсегда).
                "WHERE pi.username = ? "
                "ORDER BY pi.acquired_at DESC",
                (uname,)
            )
            inventory = [
                {'item_id': r[0], 'name': r[1], 'slot': r[2], 'rarity': r[3],
                 'emoji': r[4], 'svg_path': r[5], 'acquired_at': r[6]}
                for r in await cur.fetchall()
            ]

            # Equipped slots
            cur = await conn.execute(
                "SELECT pe.slot, pe.item_id, pc.name, pc.emoji, pc.rarity, "
                "       pc.svg_path "
                "FROM pet_equipped pe "
                "JOIN pet_catalog pc ON pc.item_id = pe.item_id "
                "WHERE pe.username = ?",
                (uname,)
            )
            equipped = {
                r[0]: {'item_id': r[1], 'name': r[2], 'emoji': r[3],
                       'rarity': r[4], 'svg_path': r[5]}
                for r in await cur.fetchall()
            }

            return {
                'username':  uname,
                'pet':       pet,
                'inventory': inventory,
                'equipped':  equipped,
            }

    async def list_pet_catalog(self, include_owned: Optional[str] = None) -> list:
        """Список активных catalog items. Если include_owned=username — для
        каждого item возвращается owned: bool (juicy для UI).
        """
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT item_id, name, slot, price_bits, rarity, emoji, svg_path, png_path "
                "FROM pet_catalog WHERE deprecated = 0 "
                "ORDER BY price_bits, rarity DESC"
            )
            items = [
                {'item_id': r[0], 'name': r[1], 'slot': r[2],
                 'price_bits': r[3], 'rarity': r[4], 'emoji': r[5],
                 'svg_path': r[6], 'png_path': r[7]}
                for r in await cur.fetchall()
            ]

            if include_owned:
                uname = include_owned.lower()
                cur = await conn.execute(
                    "SELECT item_id FROM pet_inventory WHERE username = ?",
                    (uname,)
                )
                owned_set = {r[0] for r in await cur.fetchall()}
                for item in items:
                    item['owned'] = item['item_id'] in owned_set

            return items

    async def purchase_pet_item(
        self,
        username: str,
        item_id: str,
        channel_id: int,
    ) -> Dict:
        """Купить cosmetic за Bits.

        Args:
            username: cross-channel user
            item_id: catalog item_id
            channel_id: где совершена покупка (для revenue attribution §7.5)
            bits_receipt: Twitch Bits transaction ID (REQUIRED if mode='bits')
            mode: 'mock' для разработки / 'bits' для production

        Returns:
            {'purchased': True, 'item_id', 'price_bits', 'purchase_id'}
            | {'purchased': False, 'reason': 'item_not_found' | 'deprecated' |
                                            'already_owned' | 'receipt_already_used' |
                                            'receipt_required'}

        Compliance: атомарная транзакция — receipt проверяется UNIQUE,
        item added в inventory + purchase audit в одной TX.
        """
        from config import PET_COSMETIC_PRICES, PET_BASE_TYPE
        uname = username.lower()

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                # Validate item
                cur = await conn.execute(
                    "SELECT rarity, slot, deprecated FROM pet_catalog WHERE item_id = ?",
                    (item_id,)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'purchased': False, 'reason': 'item_not_found'}
                rarity, slot, deprecated = row
                if deprecated:
                    await conn.execute("ROLLBACK")
                    return {'purchased': False, 'reason': 'deprecated'}
                price = PET_COSMETIC_PRICES.get(rarity, PET_COSMETIC_PRICES['common'])

                # Already owned?
                cur = await conn.execute(
                    "SELECT 1 FROM pet_inventory WHERE username = ? AND item_id = ?",
                    (uname, item_id)
                )
                if await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    return {'purchased': False, 'reason': 'already_owned'}

                # Списываем крустики атомарно (в той же TX). points >= price, иначе
                # 0 строк затронуто → не хватает → откат, предмет не выдаём.
                cur = await conn.execute(
                    "UPDATE viewers SET points = points - ? "
                    "WHERE channel_id = ? AND username = ? AND points >= ?",
                    (price, channel_id, uname, price)
                )
                if cur.rowcount == 0:
                    await conn.execute("ROLLBACK")
                    return {'purchased': False, 'reason': 'insufficient_crustics', 'price': price}

                # Ensure pet exists (для new юзеров)
                await conn.execute(
                    "INSERT OR IGNORE INTO pets (username, pet_type) VALUES (?, ?)",
                    (uname, PET_BASE_TYPE)
                )

                # Hatch check: первая покупка → egg переходит в hatched.
                # Считаем "первая" по inventory ДО текущего INSERT (всё в TX).
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM pet_inventory WHERE username = ?",
                    (uname,)
                )
                (existing_count,) = await cur.fetchone()
                is_first_purchase = (existing_count == 0)

                # Add to inventory
                await conn.execute(
                    "INSERT INTO pet_inventory (username, item_id) VALUES (?, ?)",
                    (uname, item_id)
                )

                # Авто-надеваем купленный предмет в его слот (купил → сразу виден,
                # не нужно отдельно жать «Надеть»). Перетирает прежний скин в слоте.
                await conn.execute(
                    "INSERT INTO pet_equipped (username, slot, item_id) VALUES (?, ?, ?) "
                    "ON CONFLICT(username, slot) DO UPDATE SET "
                    "item_id = excluded.item_id, equipped_at = CURRENT_TIMESTAMP",
                    (uname, slot, item_id)
                )

                hatched = False
                if is_first_purchase:
                    # Только если pet ещё в egg-state — апдейтим в hatched
                    cur = await conn.execute(
                        "UPDATE pets SET pet_type = 'hatched' "
                        "WHERE username = ? AND pet_type = 'egg'",
                        (uname,)
                    )
                    hatched = (cur.rowcount > 0)

                # Audit (bits_amount/mode — legacy-колонки: храним крустик-цену, mode='mock')
                cur = await conn.execute(
                    "INSERT INTO pet_purchases "
                    "(username, item_id, channel_id, bits_amount, bits_receipt, mode) "
                    "VALUES (?, ?, ?, ?, NULL, 'mock')",
                    (uname, item_id, channel_id, price)
                )
                purchase_id = cur.lastrowid
                await conn.commit()

                return {
                    'purchased':   True,
                    'item_id':     item_id,
                    'price':       price,
                    'purchase_id': purchase_id,
                    'hatched':     hatched,  # True если egg → 🐣 произошёл
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def equip_pet_item(
        self,
        username: str,
        item_id: Optional[str],
        slot: Optional[str] = None,
    ) -> Dict:
        """Equip / unequip cosmetic.

        Args:
            item_id: если None → unequip slot. Если задан → equip + lookup slot.
            slot: required если item_id is None (для unequip). Если item_id
                  задан — slot берётся из catalog.

        Returns:
            {'equipped': True, 'slot': X, 'item_id': Y | None}
            | {'equipped': False, 'reason': 'not_owned' | 'item_not_found' | 'invalid_args'}
        """
        uname = username.lower()
        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                if item_id is None and slot is None:
                    await conn.execute("ROLLBACK")
                    return {'equipped': False, 'reason': 'invalid_args'}

                if item_id is None:
                    # Unequip slot
                    cur = await conn.execute(
                        "DELETE FROM pet_equipped WHERE username = ? AND slot = ?",
                        (uname, slot)
                    )
                    await conn.commit()
                    return {'equipped': True, 'slot': slot, 'item_id': None,
                            'action': 'unequip'}

                # Lookup item slot from catalog.
                # deprecated (снятый с продажи) НЕ блокирует equip у владельца:
                # лимитка/эксклюзив — купивший свободно переодевает. Новых не
                # пускает purchase_pet_item; здесь гейт — только ownership (ниже).
                cur = await conn.execute(
                    "SELECT slot FROM pet_catalog WHERE item_id = ?",
                    (item_id,)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'equipped': False, 'reason': 'item_not_found'}
                catalog_slot = row[0]

                # Check ownership
                cur = await conn.execute(
                    "SELECT 1 FROM pet_inventory WHERE username = ? AND item_id = ?",
                    (uname, item_id)
                )
                if not await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    return {'equipped': False, 'reason': 'not_owned'}

                # Replace existing equip in slot
                await conn.execute(
                    "INSERT INTO pet_equipped (username, slot, item_id) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(username, slot) DO UPDATE SET "
                    "item_id = excluded.item_id, equipped_at = CURRENT_TIMESTAMP",
                    (uname, catalog_slot, item_id)
                )
                await conn.commit()
                return {'equipped': True, 'slot': catalog_slot,
                        'item_id': item_id, 'action': 'equip'}
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def get_channel_pets_setting(self, channel_id: int) -> bool:
        """Включен ли pets-overlay на канале."""
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT overlay_enabled FROM channel_pet_settings WHERE channel_id = ?",
                (channel_id,)
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else True  # default ON

    async def set_channel_pets_setting(self, channel_id: int, enabled: bool) -> None:
        """Стример toggle'ит pets-overlay на канале."""
        async with self._connect() as conn:
            await conn.execute(
                "INSERT INTO channel_pet_settings (channel_id, overlay_enabled) "
                "VALUES (?, ?) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "overlay_enabled = excluded.overlay_enabled, "
                "updated_at = CURRENT_TIMESTAMP",
                (channel_id, 1 if enabled else 0)
            )
            await conn.commit()

    async def get_channel_greet_settings(self, channel_id: int) -> dict:
        """Приветствия ботом в чате: {'sub': bool, 'follow': bool}.

        Default ON для обоих (нет строки → оба True) — новый канал
        приветствует сразу. m74.
        """
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT sub_enabled, follow_enabled FROM channel_greet_settings "
                "WHERE channel_id = ?",
                (channel_id,)
            )
            row = await cur.fetchone()
            if not row:
                return {"sub": True, "follow": True}  # default ON
            return {"sub": bool(row[0]), "follow": bool(row[1])}

    async def set_channel_greet_setting(
        self, channel_id: int, kind: str, enabled: bool
    ) -> None:
        """Стример toggle'ит приветствие на своём канале.

        kind: 'sub' (подписки) или 'follow' (фолловы). Upsert: задаём только
        нужную колонку, вторая берёт default (1) при первой вставке. m74.
        """
        col = "sub_enabled" if kind == "sub" else "follow_enabled"
        async with self._connect() as conn:
            await conn.execute(
                f"INSERT INTO channel_greet_settings (channel_id, {col}) "
                "VALUES (?, ?) "
                f"ON CONFLICT(channel_id) DO UPDATE SET "
                f"{col} = excluded.{col}, "
                "updated_at = CURRENT_TIMESTAMP",
                (channel_id, 1 if enabled else 0)
            )
            await conn.commit()

    async def record_watch_streak(
        self, channel_id: int, username: str,
        streak_count: int, points_awarded: int = 0,
    ) -> None:
        """Записать watch-streak (серию просмотров) зрителя. m75.

        Upsert по (channel_id, username): streak_count = последнее значение
        (текущая серия), best_streak = максимум, total_points = накопительно.
        """
        async with self._connect() as conn:
            await conn.execute(
                "INSERT INTO watch_streaks "
                "(channel_id, username, streak_count, best_streak, "
                "total_points, last_streak_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id, username) DO UPDATE SET "
                "streak_count = excluded.streak_count, "
                "best_streak = MAX(best_streak, excluded.streak_count), "
                "total_points = total_points + excluded.total_points, "
                "last_streak_at = CURRENT_TIMESTAMP",
                (channel_id, username, streak_count, streak_count,
                 max(0, points_awarded)),
            )
            await conn.commit()

    async def get_watch_streaks(
        self, channel_id: int, limit: int = 20,
    ) -> list:
        """Лидерборд серий просмотров канала (топ по текущей серии). m75."""
        limit = max(1, min(int(limit), 100))
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT username, streak_count, best_streak, total_points, "
                "last_streak_at FROM watch_streaks WHERE channel_id = ? "
                "ORDER BY streak_count DESC, best_streak DESC LIMIT ?",
                (channel_id, limit),
            )
            rows = await cur.fetchall()
        return [
            {
                "username": r[0],
                "streak_count": r[1],
                "best_streak": r[2],
                "total_points": r[3],
                "last_streak_at": r[4],
            }
            for r in rows
        ]

    async def get_active_viewers_with_pets(
        self,
        channel_id: int,
        active_window_sec: int = 600,
        limit: int = 20,
    ) -> list:
        """Список активных viewers с их pets для overlay rendering.

        - Multi-tenant читает viewers WHERE channel_id (per channel)
        - Cross-channel читает pets+equipped (global per user)

        Returns: [{username, pet_type, equipped: {head, accessory, ...}}]
        """
        async with self._connect() as conn:
            # Fast active viewers list
            cur = await conn.execute(
                "SELECT username FROM viewers "
                "WHERE channel_id = ? AND last_seen >= datetime('now', ?) "
                "ORDER BY last_seen DESC LIMIT ?",
                (channel_id, f"-{active_window_sec} seconds", limit)
            )
            active = [r[0] for r in await cur.fetchall()]
            if not active:
                return []

            # Pet types + equipped slots for all in single query (где есть pet)
            placeholders = ",".join("?" * len(active))
            cur = await conn.execute(
                f"SELECT username, pet_type FROM pets WHERE username IN ({placeholders})",
                tuple(active)
            )
            pet_types = {r[0]: r[1] for r in await cur.fetchall()}

            cur = await conn.execute(
                f"SELECT pe.username, pe.slot, pe.item_id, pc.emoji, pc.svg_path "
                f"FROM pet_equipped pe "
                f"JOIN pet_catalog pc ON pc.item_id = pe.item_id "
                f"WHERE pe.username IN ({placeholders})",
                tuple(active)
            )
            equipped_by_user = {}
            for row in await cur.fetchall():
                u, slot, item_id, emoji, svg_path = row
                if u not in equipped_by_user:
                    equipped_by_user[u] = {}
                equipped_by_user[u][slot] = {
                    'item_id': item_id, 'emoji': emoji, 'svg_path': svg_path,
                }

            # 2026-07-27: уровень зрителя для подписи над питомцем на overlay.
            # Тот же уровень, что расширение показывает зрителю («LVL 38»), —
            # считается из времени просмотра. Берём ОДНИМ агрегатом на всех
            # сразу: по запросу на зрителя было бы 20 обращений к базе на
            # каждый тик overlay'я. Формула — общая (level_from_total_exp),
            # копии здесь намеренно нет.
            cur = await conn.execute(
                f"SELECT username, COALESCE(SUM(watch_time), 0) FROM activity_stats "
                f"WHERE channel_id = ? AND username IN ({placeholders}) "
                f"GROUP BY username",
                (channel_id, *active)
            )
            level_by_user = {
                r[0]: self.level_from_total_exp(int(r[1] / 60))[0]
                for r in await cur.fetchall()
            }

            # Build result
            result = []
            for username in active:
                if username in pet_types:
                    result.append({
                        'username':  username,
                        'pet_type':  pet_types[username],
                        'equipped':  equipped_by_user.get(username, {}),
                        # 1 — уровень по умолчанию: зритель без записей о просмотре
                        # (то же, что отдаёт get_user_level на пустой выборке).
                        'level':     level_by_user.get(username, 1),
                    })
            return result

    async def set_pet_name(self, username: str, name: Optional[str]) -> bool:
        """Юзер задаёт имя своему pet."""
        from config import PET_NAME_MAX_LEN
        uname = username.lower()
        if name:
            name = name.strip()[:PET_NAME_MAX_LEN]
        async with self._connect() as conn:
            cur = await conn.execute(
                "UPDATE pets SET name = ? WHERE username = ?",
                (name, uname)
            )
            await conn.commit()
            return cur.rowcount > 0

    # ===== VOTING EVENTS (Phase 4, 2026-05-11) =====
    # §6.1.4 Twitch Extension Guidelines: voting activities прямо разрешены.
    # Применяет skills/code-review-excellence: грунт-руль атомарных txns +
    # access-control + structured error returns.

    async def create_voting_template(
        self,
        name: str,
        options: list,  # [{key, label, description}, ...]
        is_default: bool = False,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Стример создаёт template голосования.

        Validates:
          - 2..VOTING_MAX_OPTIONS вариантов
          - Все option_key unique within template
          - Если is_default=True — снимает default с других templates канала

        Returns:
            {'created': True, 'template_id': N}
            | {'created': False, 'reason': 'invalid_options' | 'duplicate_keys'}
        """
        from config import VOTING_MAX_OPTIONS
        import json
        cid = resolve_channel_id(channel_id)

        if not options or not isinstance(options, list):
            return {'created': False, 'reason': 'invalid_options', 'message': 'Нужны варианты'}
        if not (2 <= len(options) <= VOTING_MAX_OPTIONS):
            return {'created': False, 'reason': 'invalid_options',
                    'message': f'2-{VOTING_MAX_OPTIONS} вариантов'}

        keys = [o.get('key', '').strip() for o in options]
        if not all(keys):
            return {'created': False, 'reason': 'invalid_options',
                    'message': 'У каждого варианта должен быть key'}
        if len(set(keys)) != len(keys):
            return {'created': False, 'reason': 'duplicate_keys'}

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                if is_default:
                    # Снять флаг с предыдущих default'ов
                    await conn.execute(
                        "UPDATE streamer_voting_templates SET is_default = 0 "
                        "WHERE channel_id = ? AND is_default = 1",
                        (cid,)
                    )

                cur = await conn.execute(
                    "INSERT INTO streamer_voting_templates "
                    "(channel_id, name, options_json, is_default) VALUES (?, ?, ?, ?)",
                    (cid, name.strip()[:100], json.dumps(options),
                     1 if is_default else 0)
                )
                tpl_id = cur.lastrowid
                await conn.commit()
                return {'created': True, 'template_id': tpl_id}
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def list_voting_templates(
        self,
        channel_id: Optional[int] = None,
    ) -> list:
        """Все templates канала. Применяя fastapi-pro pattern — explicit JSON
        parse в helper, не на endpoint level."""
        import json
        cid = resolve_channel_id(channel_id)
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT id, name, options_json, is_default, created_at "
                "FROM streamer_voting_templates WHERE channel_id = ? "
                "ORDER BY is_default DESC, created_at DESC",
                (cid,)
            )
            rows = await cur.fetchall()
            return [
                {
                    'template_id': r[0], 'name': r[1],
                    'options': json.loads(r[2] or '[]'),
                    'is_default': bool(r[3]), 'created_at': r[4],
                }
                for r in rows
            ]

    async def delete_voting_template(
        self,
        template_id: int,
        channel_id: Optional[int] = None,
    ) -> bool:
        """Удалить template. Не может затронуть уже-запущенные events
        (template_id у них уже в snapshot voting_options.label/key)."""
        cid = resolve_channel_id(channel_id)
        async with self._connect() as conn:
            cur = await conn.execute(
                "DELETE FROM streamer_voting_templates WHERE id = ? AND channel_id = ?",
                (template_id, cid)
            )
            await conn.commit()
            return cur.rowcount > 0

    async def start_voting_event(
        self,
        template_id: int,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Стартует event из template. Snapshot options → voting_options.

        Защита от двойного active event per channel — uq_voting_events_active.

        Returns:
            {'started': True, 'event_id': N, 'options_count': K, 'ends_at': ISO}
            | {'started': False, 'reason': 'active_event_exists' | 'template_not_found'}
        """
        from config import VOTING_EVENT_DURATION_SEC
        import json
        from datetime import datetime as _dt, timedelta as _td
        cid = resolve_channel_id(channel_id)

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                # Load template
                cur = await conn.execute(
                    "SELECT name, options_json FROM streamer_voting_templates "
                    "WHERE id = ? AND channel_id = ?",
                    (template_id, cid)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'started': False, 'reason': 'template_not_found'}
                tpl_name, options_json = row
                options = json.loads(options_json or '[]')

                # Create event (UNIQUE active per channel защитит от двойного start)
                ends_at = (_dt.utcnow() + _td(seconds=VOTING_EVENT_DURATION_SEC)).isoformat()
                try:
                    cur = await conn.execute(
                        "INSERT INTO voting_events "
                        "(channel_id, template_id, template_name, ends_at, status) "
                        "VALUES (?, ?, ?, ?, 'active')",
                        (cid, template_id, tpl_name, ends_at)
                    )
                    event_id = cur.lastrowid
                except Exception as e:
                    # Likely UNIQUE violation (already active event)
                    await conn.execute("ROLLBACK")
                    if 'UNIQUE' in str(e):
                        return {'started': False, 'reason': 'active_event_exists'}
                    raise

                # Snapshot options
                for opt in options:
                    await conn.execute(
                        "INSERT INTO voting_options "
                        "(event_id, option_key, label, description, pool) "
                        "VALUES (?, ?, ?, ?, 0)",
                        (event_id, opt.get('key', ''), opt.get('label', ''),
                         opt.get('description', ''))
                    )

                # Reset pool counter for this channel — следующий event только
                # после нового accumulation cycle
                await conn.execute(
                    "INSERT INTO voting_pool_counters (channel_id, pool_units) "
                    "VALUES (?, 0) "
                    "ON CONFLICT(channel_id) DO UPDATE SET pool_units = 0",
                    (cid,)
                )

                await conn.commit()
                return {
                    'started': True,
                    'event_id': event_id,
                    'template_name': tpl_name,
                    'options_count': len(options),
                    'ends_at': _utc_for_client(ends_at),
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def place_voting_bid(
        self,
        event_id: int,
        option_id: int,
        username: str,
        amount: int,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Юзер вкидывает крустики в опцию голосования. Атомарно:
          - Списать viewers.points
          - +pool у voting_options
          - +total_pool у voting_events
          - INSERT в voting_bids (audit)

        НЕ возвращает refund (collective voting model §6.1.4).

        Validates:
          - event active + same channel
          - option belongs к event
          - amount >= VOTING_MIN_BID
          - sufficient funds
        """
        from config import VOTING_MIN_BID
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        if amount < VOTING_MIN_BID:
            return {'placed': False, 'reason': 'too_small',
                    'message': f'Минимум {VOTING_MIN_BID}💎'}

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                # Verify event active + same channel
                cur = await conn.execute(
                    "SELECT id, channel_id, ends_at FROM voting_events "
                    "WHERE id = ? AND status = 'active'",
                    (event_id,)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'placed': False, 'reason': 'event_not_active'}
                if row[1] != cid:
                    await conn.execute("ROLLBACK")
                    return {'placed': False, 'reason': 'wrong_channel'}

                # Verify option в event
                cur = await conn.execute(
                    "SELECT id FROM voting_options WHERE id = ? AND event_id = ?",
                    (option_id, event_id)
                )
                if not await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    return {'placed': False, 'reason': 'option_not_in_event'}

                # Atomic списание из viewers
                cur = await conn.execute(
                    "UPDATE viewers SET points = points - ? "
                    "WHERE channel_id = ? AND username = ? AND points >= ?",
                    (amount, cid, uname, amount)
                )
                if cur.rowcount == 0:
                    await conn.execute("ROLLBACK")
                    return {'placed': False, 'reason': 'insufficient_funds'}

                # Update pools (option + event total)
                await conn.execute(
                    "UPDATE voting_options SET pool = pool + ? WHERE id = ?",
                    (amount, option_id)
                )
                await conn.execute(
                    "UPDATE voting_events SET total_pool = total_pool + ? WHERE id = ?",
                    (amount, event_id)
                )

                # Audit
                await conn.execute(
                    "INSERT INTO voting_bids "
                    "(event_id, option_id, channel_id, username, amount) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (event_id, option_id, cid, uname, amount)
                )

                await conn.commit()
                return {'placed': True, 'event_id': event_id, 'option_id': option_id,
                        'amount': amount}
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def get_active_voting_event(
        self,
        channel_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """Текущий active event на канале + опции + total_pool.

        Идёт также top-bidders per option.
        """
        cid = resolve_channel_id(channel_id)
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT id, template_name, started_at, ends_at, total_pool, allow_proposals "
                "FROM voting_events WHERE channel_id = ? AND status = 'active'",
                (cid,)
            )
            row = await cur.fetchone()
            if not row:
                return None
            event_id, tpl_name, started_at, ends_at, total_pool, allow_proposals = row

            cur = await conn.execute(
                "SELECT id, option_key, label, description, pool "
                "FROM voting_options WHERE event_id = ? ORDER BY pool DESC",
                (event_id,)
            )
            options = [
                {'id': r[0], 'key': r[1], 'label': r[2], 'description': r[3],
                 'pool': r[4]}
                for r in await cur.fetchall()
            ]

            return {
                'event_id':       event_id,
                'template_name':  tpl_name,
                'started_at':     started_at,
                'ends_at':        _utc_for_client(ends_at),
                'total_pool':     total_pool,
                'allow_proposals': bool(allow_proposals),
                'options':        options,
            }

    async def finalize_voting_event(
        self,
        event_id: int,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Завершить event — выбрать option с max pool, set winner.

        Если total_pool == 0 (никто не голосовал) → status='cancelled',
        winning=None. Иначе — status='finished'.

        Returns:
            {'finalized': True, 'outcome': 'finished' | 'cancelled',
             'winner_option': {...} | None}
        """
        cid = resolve_channel_id(channel_id) if channel_id is not None else None

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                cur = await conn.execute(
                    "SELECT id, channel_id, total_pool, status FROM voting_events "
                    "WHERE id = ?",
                    (event_id,)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'finalized': False, 'reason': 'not_found'}
                _, evt_cid, total_pool, status = row
                if cid is not None and evt_cid != cid:
                    await conn.execute("ROLLBACK")
                    return {'finalized': False, 'reason': 'wrong_channel'}
                if status != 'active':
                    await conn.execute("ROLLBACK")
                    return {'finalized': False, 'reason': 'not_active'}

                # M88: pending viewer-предложения при финализации — reject.
                # Они НЕ были списаны (списание только на approve) → возвращать нечего.
                await conn.execute(
                    "UPDATE voting_proposals SET status = 'rejected' "
                    "WHERE event_id = ? AND status = 'pending'",
                    (event_id,)
                )

                if total_pool == 0:
                    # Никто не голосовал — cancel
                    await conn.execute(
                        "UPDATE voting_events SET status = 'cancelled' WHERE id = ?",
                        (event_id,)
                    )
                    await conn.commit()
                    return {'finalized': True, 'outcome': 'cancelled',
                            'winner_option': None}

                # Find max-pool option
                cur = await conn.execute(
                    "SELECT id, option_key, label, pool FROM voting_options "
                    "WHERE event_id = ? ORDER BY pool DESC, id LIMIT 1",
                    (event_id,)
                )
                winner = await cur.fetchone()
                w_id, w_key, w_label, w_pool = winner

                await conn.execute(
                    "UPDATE voting_events SET status = 'finished', "
                    "winning_option_id = ?, winning_option_key = ?, "
                    "winning_option_label = ? WHERE id = ?",
                    (w_id, w_key, w_label, event_id)
                )

                await conn.commit()
                return {
                    'finalized': True, 'outcome': 'finished',
                    'winner_option': {
                        'id': w_id, 'key': w_key, 'label': w_label, 'pool': w_pool,
                    },
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def get_voting_top_bidders(
        self,
        event_id: int,
        limit: int = 5,
    ) -> list:
        """Top-N bidders по сумме вкладов в текущий event."""
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT username, SUM(amount) AS total FROM voting_bids "
                "WHERE event_id = ? GROUP BY username ORDER BY total DESC LIMIT ?",
                (event_id, limit)
            )
            return [
                {'username': r[0], 'total': r[1]}
                for r in await cur.fetchall()
            ]

    async def increment_voting_pool(
        self,
        channel_id: int,
        units: int,
    ) -> int:
        """Increment pool counter канала (вызывается из reward_points_loop
        для watch units и из chat-handler для chat units).

        Returns: new pool_units value.
        """
        async with self._connect() as conn:
            await conn.execute(
                "INSERT INTO voting_pool_counters (channel_id, pool_units, last_increment_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "pool_units = pool_units + excluded.pool_units, "
                "last_increment_at = CURRENT_TIMESTAMP",
                (channel_id, units)
            )
            cur = await conn.execute(
                "SELECT pool_units FROM voting_pool_counters WHERE channel_id = ?",
                (channel_id,)
            )
            row = await cur.fetchone()
            await conn.commit()
            return row[0] if row else 0

    async def get_voting_pool(
        self,
        channel_id: Optional[int] = None,
    ) -> int:
        cid = resolve_channel_id(channel_id)
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT pool_units FROM voting_pool_counters WHERE channel_id = ?",
                (cid,)
            )
            row = await cur.fetchone()
            return row[0] if row else 0

    async def find_expired_voting_events(self) -> list:
        """All active events с ends_at в прошлом — для voting_loop.

        2026-08-05 (владелец: «не работает таймер автоокончания»). Здесь было
        `ends_at <= CURRENT_TIMESTAMP` — сравнение ДВУХ СТРОК в разных форматах.
        Питон пишет `2026-08-05T09:00:00.123456` (через «T»), а
        `CURRENT_TIMESTAMP` отдаёт `2026-08-05 11:49:19` (через пробел). Внутри
        одной даты «T» больше пробела по коду символа, поэтому истёкшее сегодня
        голосование НЕ находилось — и закрывалось только после смены даты по
        UTC, то есть после полуночи. `datetime()` приводит обе стороны к одному
        виду, и сравнение снова про время, а не про порядок символов.
        """
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT id, channel_id FROM voting_events "
                "WHERE status = 'active' AND datetime(ends_at) <= datetime('now')"
            )
            return [{'event_id': r[0], 'channel_id': r[1]}
                    for r in await cur.fetchall()]

    async def find_channels_ready_for_voting(
        self,
        threshold: int,
    ) -> list:
        """Каналы с pool_units >= threshold + default template + БЕЗ active event.

        Returns: [{channel_id, pool_units, default_template_id}]
        """
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT pc.channel_id, pc.pool_units, t.id "
                "FROM voting_pool_counters pc "
                "JOIN streamer_voting_templates t ON t.channel_id = pc.channel_id "
                "WHERE pc.pool_units >= ? AND t.is_default = 1 "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM voting_events e "
                "  WHERE e.channel_id = pc.channel_id AND e.status = 'active'"
                ")",
                (threshold,)
            )
            return [
                {'channel_id': r[0], 'pool_units': r[1], 'default_template_id': r[2]}
                for r in await cur.fetchall()
            ]

    # ===== «Народный выбор игры» — streamer-triggered open mode (M88) =====
    # Стример открывает раунд, где зритель может ПРЕДЛОЖИТЬ свою игру (UGC).
    # Предложение с пледжем → очередь → approve стримера (списание) / reject (ничего).
    # Compliance: списание строго после approve; отклонённое/pending не списано.

    async def start_open_voting_event(
        self,
        channel_id: Optional[int] = None,
        duration_sec: Optional[int] = None,
        options: Optional[list] = None,   # [{label} | "label"] pre-seed стримера
    ) -> Dict:
        """Стример стартует «открытый» раунд (allow_proposals=1) без шаблона.
        options — необязательный pre-seed. Защита от двойного active per channel.

        Returns {'started': True, 'event_id', 'ends_at', 'options_count'}
                | {'started': False, 'reason': 'active_event_exists'}
        """
        import re as _re
        from config import VOTING_EVENT_DURATION_SEC
        from datetime import datetime as _dt, timedelta as _td
        cid = resolve_channel_id(channel_id)
        dur = duration_sec if isinstance(duration_sec, int) and duration_sec > 0 else VOTING_EVENT_DURATION_SEC
        dur = max(60, min(3600, dur))
        seed = options if isinstance(options, list) else []

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                ends_at = (_dt.utcnow() + _td(seconds=dur)).isoformat()
                try:
                    cur = await conn.execute(
                        "INSERT INTO voting_events "
                        "(channel_id, template_name, ends_at, status, allow_proposals) "
                        "VALUES (?, ?, ?, 'active', 1)",
                        (cid, "Народный выбор игры", ends_at)
                    )
                    event_id = cur.lastrowid
                except Exception as e:
                    await conn.execute("ROLLBACK")
                    if 'UNIQUE' in str(e):
                        return {'started': False, 'reason': 'active_event_exists'}
                    raise

                cnt = 0
                for opt in seed:
                    label = (opt.get('label') if isinstance(opt, dict) else str(opt)) or ''
                    label = label.strip()[:60]
                    if not label:
                        continue
                    key = (_re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')[:40]) or 'opt'
                    await conn.execute(
                        "INSERT INTO voting_options (event_id, option_key, label, description, pool) "
                        "VALUES (?, ?, ?, '', 0)",
                        (event_id, key, label)
                    )
                    cnt += 1

                await conn.commit()
                return {'started': True, 'event_id': event_id,
                        'ends_at': _utc_for_client(ends_at),
                        'options_count': cnt}
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def create_voting_proposal(
        self,
        channel_id: Optional[int] = None,
        username: str = "",
        label: str = "",
        pledge: int = 0,
    ) -> Dict:
        """Зритель предлагает свою игру в открытый раунд (в очередь на approve).
        Пледж НЕ списывается здесь — только на approve. Проверяем баланс на
        достоверность + анти-спам капы (мин. пледж, N pending/юзер, общий кап).

        Returns {'created': True, 'proposal_id'} | {'created': False, 'reason': ...}
        """
        from config import (VOTING_PROPOSE_MIN_PLEDGE, VOTING_MAX_OPTIONS,
                             VOTING_MAX_PENDING_PER_USER)
        cid = resolve_channel_id(channel_id)
        uname = (username or "").lower()
        label = (label or '').strip()[:60]
        if len(label) < 2:
            return {'created': False, 'reason': 'bad_label'}
        try:
            pledge = int(pledge)
        except (TypeError, ValueError):
            pledge = 0
        if pledge < VOTING_PROPOSE_MIN_PLEDGE:
            return {'created': False, 'reason': 'too_small',
                    'message': f'Минимальный вклад {VOTING_PROPOSE_MIN_PLEDGE}💎'}

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                cur = await conn.execute(
                    "SELECT id, allow_proposals FROM voting_events "
                    "WHERE channel_id = ? AND status = 'active'",
                    (cid,)
                )
                ev = await cur.fetchone()
                if not ev:
                    await conn.execute("ROLLBACK")
                    return {'created': False, 'reason': 'no_active_event'}
                if not ev[1]:
                    await conn.execute("ROLLBACK")
                    return {'created': False, 'reason': 'proposals_closed'}
                event_id = ev[0]

                # credibility: у зрителя есть баланс на пледж (не списываем)
                cur = await conn.execute(
                    "SELECT points FROM viewers WHERE channel_id = ? AND username = ?",
                    (cid, uname)
                )
                brow = await cur.fetchone()
                if not brow or (brow[0] or 0) < pledge:
                    await conn.execute("ROLLBACK")
                    return {'created': False, 'reason': 'insufficient_funds'}

                # анти-спам: не больше N pending на зрителя
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM voting_proposals "
                    "WHERE channel_id = ? AND event_id = ? AND username = ? AND status = 'pending'",
                    (cid, event_id, uname)
                )
                if (await cur.fetchone())[0] >= VOTING_MAX_PENDING_PER_USER:
                    await conn.execute("ROLLBACK")
                    return {'created': False, 'reason': 'too_many_pending'}

                # общий кап: live options + pending предложения < VOTING_MAX_OPTIONS
                cur = await conn.execute(
                    "SELECT (SELECT COUNT(*) FROM voting_options WHERE event_id = ?) + "
                    "(SELECT COUNT(*) FROM voting_proposals "
                    " WHERE event_id = ? AND status = 'pending')",
                    (event_id, event_id)
                )
                if (await cur.fetchone())[0] >= VOTING_MAX_OPTIONS:
                    await conn.execute("ROLLBACK")
                    return {'created': False, 'reason': 'full'}

                cur = await conn.execute(
                    "INSERT INTO voting_proposals "
                    "(event_id, channel_id, username, label, pledge, status) "
                    "VALUES (?, ?, ?, ?, ?, 'pending')",
                    (event_id, cid, uname, label, pledge)
                )
                pid = cur.lastrowid
                await conn.commit()
                return {'created': True, 'proposal_id': pid}
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def list_voting_proposals(
        self,
        channel_id: Optional[int] = None,
        status: str = 'pending',
    ) -> list:
        """Предложения канала для активного события (для дашборда стримера)."""
        cid = resolve_channel_id(channel_id)
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT p.id, p.username, p.label, p.pledge, p.created_at "
                "FROM voting_proposals p "
                "JOIN voting_events e ON e.id = p.event_id AND e.status = 'active' "
                "WHERE p.channel_id = ? AND p.status = ? "
                "ORDER BY p.created_at ASC",
                (cid, status)
            )
            return [
                {'id': r[0], 'username': r[1], 'label': r[2], 'pledge': r[3],
                 'created_at': r[4]}
                for r in await cur.fetchall()
            ]

    async def approve_voting_proposal(
        self,
        proposal_id: int,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Стример одобряет предложение → создаёт опцию, списывает пледж
        (best-effort: если баланс уехал — опция при 0), сеет пул. Атомарно.

        Returns {'approved': True, 'option_id', 'label', 'pool', 'event_id'}
                | {'approved': False, 'reason': ...}
        """
        import re as _re
        cid = resolve_channel_id(channel_id)
        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                cur = await conn.execute(
                    "SELECT event_id, username, label, pledge, status "
                    "FROM voting_proposals WHERE id = ? AND channel_id = ?",
                    (proposal_id, cid)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'approved': False, 'reason': 'not_found'}
                event_id, uname, label, pledge, status = row
                if status != 'pending':
                    await conn.execute("ROLLBACK")
                    return {'approved': False, 'reason': 'not_pending'}

                cur = await conn.execute(
                    "SELECT status FROM voting_events WHERE id = ? AND channel_id = ?",
                    (event_id, cid)
                )
                erow = await cur.fetchone()
                if not erow or erow[0] != 'active':
                    await conn.execute("ROLLBACK")
                    return {'approved': False, 'reason': 'event_not_active'}

                key = (_re.sub(r'[^a-z0-9]+', '-', (label or '').lower()).strip('-')[:40]) or 'opt'
                cur = await conn.execute(
                    "INSERT INTO voting_options (event_id, option_key, label, description, pool) "
                    "VALUES (?, ?, ?, '', 0)",
                    (event_id, key, label)
                )
                option_id = cur.lastrowid

                # Списать пледж. 2026-07-29: раньше это было «best-effort» —
                # если к моменту одобрения крустиков у зрителя уже не было,
                # списание молча не проходило, а опция ВСЁ РАВНО попадала в
                # голосование с пулом 0. То есть заявленная цена предложения
                # обходилась: пообещал 100💎, потратил их до одобрения — и
                # твой вариант в бюллетене бесплатно. Теперь нехватка средств
                # отменяет одобрение целиком, и стример видит причину.
                charged = 0
                if pledge and pledge > 0:
                    ccur = await conn.execute(
                        "UPDATE viewers SET points = points - ? "
                        "WHERE channel_id = ? AND username = ? AND points >= ?",
                        (pledge, cid, uname, pledge)
                    )
                    if ccur.rowcount != 1:
                        await conn.execute("ROLLBACK")
                        return {'approved': False, 'reason': 'pledge_unpaid',
                                'username': uname, 'pledge': pledge}
                    charged = pledge
                    await conn.execute(
                        "UPDATE voting_options SET pool = pool + ? WHERE id = ?",
                        (charged, option_id)
                    )
                    await conn.execute(
                        "UPDATE voting_events SET total_pool = total_pool + ? WHERE id = ?",
                        (charged, event_id)
                    )
                    await conn.execute(
                        "INSERT INTO voting_bids "
                        "(event_id, option_id, channel_id, username, amount) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (event_id, option_id, cid, uname, charged)
                    )

                await conn.execute(
                    "UPDATE voting_proposals SET status = 'approved', option_id = ? "
                    "WHERE id = ?",
                    (option_id, proposal_id)
                )
                await conn.commit()
                return {'approved': True, 'option_id': option_id, 'label': label,
                        'pool': charged, 'event_id': event_id}
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def reject_voting_proposal(
        self,
        proposal_id: int,
        channel_id: Optional[int] = None,
    ) -> bool:
        """Стример отклоняет предложение (ничего не списано — возвращать нечего)."""
        cid = resolve_channel_id(channel_id)
        async with self._connect() as conn:
            cur = await conn.execute(
                "UPDATE voting_proposals SET status = 'rejected' "
                "WHERE id = ? AND channel_id = ? AND status = 'pending'",
                (proposal_id, cid)
            )
            await conn.commit()
            return cur.rowcount > 0

    # ===== ГИЛЬДИИ (Phase 3, 2026-05-11) =====
    # Социальная механика per канал. Multi-tenant scope:
    # - guilds.channel_id определяет принадлежность канала
    # - один юзер = одна гильдия per канал (UNIQUE index)
    # - имя UNIQUE within channel (но один и тот же name можно на другом канале)

    async def create_guild(
        self,
        name: str,
        master_username: str,
        tagline: str = "",
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Создать гильдию + добавить master'а как первого member'а.
        Атомарно списать GUILD_CREATE_COST из master.points.

        Validates:
          - master не уже в другой гильдии на этом канале
          - name не занят (case-sensitive, в рамках канала)
          - master имеет достаточно крустиков для создания

        Returns:
            {'created': True, 'guild_id': N, 'remaining_balance': K}
            | {'created': False, 'reason': 'already_in_guild' | 'name_taken' |
                                          'insufficient_funds' | 'invalid_name'}
        """
        from config import (
            GUILD_CREATE_COST, GUILD_NAME_MIN_LEN, GUILD_NAME_MAX_LEN,
            GUILD_TAGLINE_MAX_LEN,
        )
        cid = resolve_channel_id(channel_id)
        uname = master_username.lower()
        name = (name or "").strip()
        tagline = (tagline or "").strip()[:GUILD_TAGLINE_MAX_LEN]

        if not (GUILD_NAME_MIN_LEN <= len(name) <= GUILD_NAME_MAX_LEN):
            return {'created': False, 'reason': 'invalid_name',
                    'message': f'Имя должно быть {GUILD_NAME_MIN_LEN}-{GUILD_NAME_MAX_LEN} символов'}

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                # Уже в гильдии?
                cur = await conn.execute(
                    "SELECT guild_id FROM guild_members "
                    "WHERE channel_id = ? AND username = ? LIMIT 1",
                    (cid, uname)
                )
                if await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    return {'created': False, 'reason': 'already_in_guild'}

                # Имя занято в этом канале (не disbanded)?
                cur = await conn.execute(
                    "SELECT id FROM guilds WHERE channel_id = ? AND name = ? "
                    "AND disbanded_at IS NULL LIMIT 1",
                    (cid, name)
                )
                if await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    return {'created': False, 'reason': 'name_taken'}

                # Списываем cost (атомарно, защита от race)
                cur = await conn.execute(
                    "UPDATE viewers SET points = points - ? "
                    "WHERE channel_id = ? AND username = ? AND points >= ?",
                    (GUILD_CREATE_COST, cid, uname, GUILD_CREATE_COST)
                )
                if cur.rowcount == 0:
                    await conn.execute("ROLLBACK")
                    return {'created': False, 'reason': 'insufficient_funds',
                            'message': f'Нужно {GUILD_CREATE_COST:,}💎 для создания'}

                # Создаём гильдию
                cur = await conn.execute(
                    "INSERT INTO guilds (channel_id, name, tagline, master_username, balance) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (cid, name, tagline, uname)
                )
                guild_id = cur.lastrowid

                # Master как первый member
                await conn.execute(
                    "INSERT INTO guild_members (guild_id, channel_id, username, role) "
                    "VALUES (?, ?, ?, 'master')",
                    (guild_id, cid, uname)
                )

                # Get remaining balance
                cur = await conn.execute(
                    "SELECT points FROM viewers WHERE channel_id = ? AND username = ?",
                    (cid, uname)
                )
                row = await cur.fetchone()
                remaining = row[0] if row else 0

                await conn.commit()
                return {
                    'created': True, 'guild_id': guild_id,
                    'remaining_balance': remaining, 'cost': GUILD_CREATE_COST,
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def join_guild(
        self,
        guild_id: int,
        username: str,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Вступить в гильдию.

        Checks:
          - guild существует и не disbanded
          - guild на ТОМ ЖЕ channel_id что юзер
          - user не уже в гильдии
          - количество members < max_members (base + skills bonus)
        """
        from config import GUILD_MAX_MEMBERS_BASE, GUILD_SKILLS_CONFIG
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                # Уже в гильдии?
                cur = await conn.execute(
                    "SELECT guild_id FROM guild_members "
                    "WHERE channel_id = ? AND username = ? LIMIT 1",
                    (cid, uname)
                )
                if await cur.fetchone():
                    await conn.execute("ROLLBACK")
                    return {'joined': False, 'reason': 'already_in_guild'}

                # Guild существует и активна?
                cur = await conn.execute(
                    "SELECT id, channel_id, name FROM guilds "
                    "WHERE id = ? AND disbanded_at IS NULL",
                    (guild_id,)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'joined': False, 'reason': 'guild_not_found'}
                if row[1] != cid:
                    await conn.execute("ROLLBACK")
                    return {'joined': False, 'reason': 'wrong_channel'}
                guild_name = row[2]

                # Считаем текущих members + max_members (base + bonus from extra_member_slots skill)
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM guild_members WHERE guild_id = ?",
                    (guild_id,)
                )
                current = (await cur.fetchone())[0]

                cur = await conn.execute(
                    "SELECT level FROM guild_skills "
                    "WHERE guild_id = ? AND skill_key = 'extra_member_slots'",
                    (guild_id,)
                )
                slot_row = await cur.fetchone()
                slot_level = slot_row[0] if slot_row else 0
                slot_bonus = slot_level * GUILD_SKILLS_CONFIG['extra_member_slots']['effect_per_level']
                max_members = GUILD_MAX_MEMBERS_BASE + slot_bonus

                if current >= max_members:
                    await conn.execute("ROLLBACK")
                    return {'joined': False, 'reason': 'guild_full',
                            'current': current, 'max': max_members}

                # Join
                await conn.execute(
                    "INSERT INTO guild_members (guild_id, channel_id, username, role) "
                    "VALUES (?, ?, ?, 'member')",
                    (guild_id, cid, uname)
                )
                await conn.commit()
                return {'joined': True, 'guild_id': guild_id, 'guild_name': guild_name}
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def leave_guild(
        self,
        username: str,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Выйти из своей гильдии. Master не может leave — должен disband.

        Returns:
            {'left': True, 'guild_id': N} | {'left': False, 'reason': X}
        """
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT guild_id, role FROM guild_members "
                "WHERE channel_id = ? AND username = ?",
                (cid, uname)
            )
            row = await cur.fetchone()
            if not row:
                return {'left': False, 'reason': 'not_in_guild'}
            guild_id, role = row
            if role == 'master':
                return {'left': False, 'reason': 'master_must_disband',
                        'message': 'Master не может покинуть — используй disband'}

            await conn.execute(
                "DELETE FROM guild_members WHERE guild_id = ? AND username = ?",
                (guild_id, uname)
            )
            await conn.commit()
            return {'left': True, 'guild_id': guild_id}

    async def contribute_to_guild(
        self,
        username: str,
        amount: int,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Вклад крустиков в balance гильдии. Списывается из viewers.points,
        прибавляется к guilds.balance + audit запись в guild_contributions.

        Атомарно через BEGIN IMMEDIATE.
        """
        from config import GUILD_MIN_CONTRIBUTE
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        if amount < GUILD_MIN_CONTRIBUTE:
            return {'contributed': False, 'reason': 'too_small',
                    'message': f'Минимум {GUILD_MIN_CONTRIBUTE}💎'}

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                cur = await conn.execute(
                    "SELECT guild_id FROM guild_members "
                    "WHERE channel_id = ? AND username = ?",
                    (cid, uname)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    return {'contributed': False, 'reason': 'not_in_guild'}
                guild_id = row[0]

                # Списываем атомарно
                cur = await conn.execute(
                    "UPDATE viewers SET points = points - ? "
                    "WHERE channel_id = ? AND username = ? AND points >= ?",
                    (amount, cid, uname, amount)
                )
                if cur.rowcount == 0:
                    await conn.execute("ROLLBACK")
                    return {'contributed': False, 'reason': 'insufficient_funds'}

                # Прибавляем в guild balance
                await conn.execute(
                    "UPDATE guilds SET balance = balance + ? WHERE id = ?",
                    (amount, guild_id)
                )

                # Audit
                await conn.execute(
                    "INSERT INTO guild_contributions (guild_id, channel_id, username, amount) "
                    "VALUES (?, ?, ?, ?)",
                    (guild_id, cid, uname, amount)
                )

                # Get new balance
                cur = await conn.execute("SELECT balance FROM guilds WHERE id = ?", (guild_id,))
                new_balance = (await cur.fetchone())[0]

                await conn.commit()
                return {
                    'contributed':   True,
                    'guild_id':      guild_id,
                    'amount':        amount,
                    'new_balance':   new_balance,
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def kick_member(
        self,
        master_username: str,
        target_username: str,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Master выгоняет участника. Master cannot kick себя."""
        cid = resolve_channel_id(channel_id)
        muname = master_username.lower()
        tuname = target_username.lower()

        if muname == tuname:
            return {'kicked': False, 'reason': 'cannot_kick_self'}

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                cur = await conn.execute(
                    "SELECT guild_id, role FROM guild_members "
                    "WHERE channel_id = ? AND username = ?",
                    (cid, muname)
                )
                row = await cur.fetchone()
                if not row or row[1] != 'master':
                    await conn.execute("ROLLBACK")
                    return {'kicked': False, 'reason': 'not_master'}
                guild_id = row[0]

                cur = await conn.execute(
                    "DELETE FROM guild_members "
                    "WHERE guild_id = ? AND username = ? AND role != 'master'",
                    (guild_id, tuname)
                )
                await conn.commit()
                if cur.rowcount == 0:
                    return {'kicked': False, 'reason': 'target_not_member'}
                return {'kicked': True, 'guild_id': guild_id, 'target': tuname}
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def upgrade_guild_skill(
        self,
        master_username: str,
        skill_key: str,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Master прокачивает skill на следующий уровень из guild.balance.

        Cost берётся из GUILD_SKILLS_CONFIG[skill_key]['cost_per_level'][level].
        max_level limit enforced.
        """
        from config import GUILD_SKILLS_CONFIG
        cid = resolve_channel_id(channel_id)
        muname = master_username.lower()

        if skill_key not in GUILD_SKILLS_CONFIG:
            return {'upgraded': False, 'reason': 'unknown_skill'}
        config = GUILD_SKILLS_CONFIG[skill_key]

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                # Verify master
                cur = await conn.execute(
                    "SELECT guild_id, role FROM guild_members "
                    "WHERE channel_id = ? AND username = ?",
                    (cid, muname)
                )
                row = await cur.fetchone()
                if not row or row[1] != 'master':
                    await conn.execute("ROLLBACK")
                    return {'upgraded': False, 'reason': 'not_master'}
                guild_id = row[0]

                # Current level
                cur = await conn.execute(
                    "SELECT level FROM guild_skills WHERE guild_id = ? AND skill_key = ?",
                    (guild_id, skill_key)
                )
                row = await cur.fetchone()
                current_level = row[0] if row else 0

                if current_level >= config['max_level']:
                    await conn.execute("ROLLBACK")
                    return {'upgraded': False, 'reason': 'max_level',
                            'level': current_level}

                cost = config['cost_per_level'][current_level]

                # Atomic списание из balance
                cur = await conn.execute(
                    "UPDATE guilds SET balance = balance - ? "
                    "WHERE id = ? AND balance >= ?",
                    (cost, guild_id, cost)
                )
                if cur.rowcount == 0:
                    await conn.execute("ROLLBACK")
                    return {'upgraded': False, 'reason': 'insufficient_guild_balance',
                            'cost': cost}

                # UPSERT skill level
                new_level = current_level + 1
                await conn.execute(
                    "INSERT INTO guild_skills (guild_id, skill_key, level, exp) "
                    "VALUES (?, ?, ?, 0) "
                    "ON CONFLICT(guild_id, skill_key) DO UPDATE SET "
                    "level = excluded.level, updated_at = CURRENT_TIMESTAMP",
                    (guild_id, skill_key, new_level)
                )

                # Get new balance
                cur = await conn.execute("SELECT balance FROM guilds WHERE id = ?", (guild_id,))
                new_balance = (await cur.fetchone())[0]

                await conn.commit()
                return {
                    'upgraded':    True,
                    'skill_key':   skill_key,
                    'new_level':   new_level,
                    'cost':        cost,
                    'new_balance': new_balance,
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def get_my_guild(
        self,
        username: str,
        channel_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """Текущая гильдия юзера + summary."""
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT g.id, g.name, g.tagline, g.master_username, g.balance, "
                "g.created_at, gm.role FROM guild_members gm "
                "JOIN guilds g ON g.id = gm.guild_id "
                "WHERE gm.channel_id = ? AND gm.username = ? AND g.disbanded_at IS NULL",
                (cid, uname)
            )
            row = await cur.fetchone()
            if not row:
                return None
            g_id, g_name, g_tagline, g_master, g_bal, g_created, my_role = row

            # Member count
            cur = await conn.execute(
                "SELECT COUNT(*) FROM guild_members WHERE guild_id = ?", (g_id,)
            )
            member_count = (await cur.fetchone())[0]

            # Skills
            cur = await conn.execute(
                "SELECT skill_key, level FROM guild_skills WHERE guild_id = ?",
                (g_id,)
            )
            skills = {r[0]: r[1] for r in await cur.fetchall()}

            return {
                'guild_id':      g_id,
                'name':          g_name,
                'tagline':       g_tagline,
                'master':        g_master,
                'balance':       g_bal,
                'created_at':    g_created,
                'my_role':       my_role,
                'member_count':  member_count,
                'skills':        skills,
            }

    async def get_guild(
        self,
        guild_id: int,
        channel_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """Public info о гильдии + members list.

        channel_id для access-control: если задан, гильдия с другого канала
        не возвращается.
        """
        cid = resolve_channel_id(channel_id) if channel_id is not None else None

        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT id, channel_id, name, tagline, master_username, balance, "
                "created_at FROM guilds WHERE id = ? AND disbanded_at IS NULL",
                (guild_id,)
            )
            row = await cur.fetchone()
            if not row:
                return None
            if cid is not None and row[1] != cid:
                return None

            g_id, g_cid, g_name, g_tagline, g_master, g_bal, g_created = row

            cur = await conn.execute(
                "SELECT username, role, joined_at FROM guild_members "
                "WHERE guild_id = ? ORDER BY role DESC, joined_at",
                (g_id,)
            )
            members = [
                {'username': r[0], 'role': r[1], 'joined_at': r[2]}
                for r in await cur.fetchall()
            ]

            cur = await conn.execute(
                "SELECT skill_key, level FROM guild_skills WHERE guild_id = ?",
                (g_id,)
            )
            skills = {r[0]: r[1] for r in await cur.fetchall()}

            # Top-5 contributors
            cur = await conn.execute(
                "SELECT username, SUM(amount) as total FROM guild_contributions "
                "WHERE guild_id = ? GROUP BY username ORDER BY total DESC LIMIT 5",
                (g_id,)
            )
            top_contribs = [
                {'username': r[0], 'total': r[1]}
                for r in await cur.fetchall()
            ]

            return {
                'guild_id':       g_id,
                'name':           g_name,
                'tagline':        g_tagline,
                'master':         g_master,
                'balance':        g_bal,
                'created_at':     g_created,
                'members':        members,
                'skills':         skills,
                'top_contributors': top_contribs,
            }

    async def list_guilds(
        self,
        channel_id: Optional[int] = None,
        limit: int = 20,
    ) -> list:
        """Top гильдий канала по balance."""
        cid = resolve_channel_id(channel_id)
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT g.id, g.name, g.tagline, g.master_username, g.balance, "
                "(SELECT COUNT(*) FROM guild_members WHERE guild_id = g.id) as members "
                "FROM guilds g "
                "WHERE g.channel_id = ? AND g.disbanded_at IS NULL "
                "ORDER BY g.balance DESC LIMIT ?",
                (cid, limit)
            )
            rows = await cur.fetchall()
            return [
                {'guild_id': r[0], 'name': r[1], 'tagline': r[2], 'master': r[3],
                 'balance': r[4], 'member_count': r[5]}
                for r in rows
            ]

    async def disband_guild(
        self,
        master_username: str,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Master расформировывает гильдию. Soft delete (disbanded_at).
        Members удаляются. Balance — теряется (sink крустиков системе).
        """
        cid = resolve_channel_id(channel_id)
        muname = master_username.lower()

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                cur = await conn.execute(
                    "SELECT guild_id, role FROM guild_members "
                    "WHERE channel_id = ? AND username = ?",
                    (cid, muname)
                )
                row = await cur.fetchone()
                if not row or row[1] != 'master':
                    await conn.execute("ROLLBACK")
                    return {'disbanded': False, 'reason': 'not_master'}
                guild_id = row[0]

                # Soft-disband + remove all members
                await conn.execute(
                    "UPDATE guilds SET disbanded_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (guild_id,)
                )
                await conn.execute(
                    "DELETE FROM guild_members WHERE guild_id = ?",
                    (guild_id,)
                )
                await conn.commit()
                return {'disbanded': True, 'guild_id': guild_id}
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    # ===== MATCHMAKING (Phase 5.0, 2026-05-11) =====
    # Generic multi-game matchmaking. Game-specific логика (RPS / TicTacToe / Dice)
    # хранится в state JSON и обрабатывается в game-specific helpers либо
    # в routes/match endpoints перед сохранением.

    async def enqueue_match(
        self,
        username: str,
        game_type: str,
        elo_spread: int = 100,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Поставить юзера в очередь matchmaking.

        Защита от двойного enqueue: partial UNIQUE index uq_match_queue_active_user.
        Если уже стоит — возвращает existing queue_id.

        Returns:
            {'enqueued': True, 'queue_id': N, 'elo_at_queue': M, 'game_type': X}
            | {'enqueued': False, 'reason': 'already_queued', 'queue_id': N}
            | {'enqueued': False, 'reason': 'in_active_room', 'room_id': X}
        """
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                # Уже в активном room? Не пускаем в очередь
                cur = await conn.execute(
                    "SELECT room_id FROM match_rooms "
                    "WHERE channel_id = ? AND status = 'active' AND game_type = ? "
                    "AND (player_a = ? OR player_b = ?) LIMIT 1",
                    (cid, game_type, uname, uname)
                )
                room_row = await cur.fetchone()
                if room_row:
                    await conn.execute("ROLLBACK")
                    return {'enqueued': False, 'reason': 'in_active_room', 'room_id': room_row[0]}

                # Уже в очереди?
                cur = await conn.execute(
                    "SELECT id FROM match_queue "
                    "WHERE channel_id = ? AND username = ? AND game_type = ? AND status = 'queued'",
                    (cid, uname, game_type)
                )
                existing = await cur.fetchone()
                if existing:
                    await conn.execute("ROLLBACK")
                    return {'enqueued': False, 'reason': 'already_queued', 'queue_id': existing[0]}

                # Получаем текущий ELO юзера для этой игры (создаём если нет)
                cur = await conn.execute(
                    "SELECT elo FROM duel_stats "
                    "WHERE channel_id = ? AND username = ? AND game_type = ?",
                    (cid, uname, game_type)
                )
                elo_row = await cur.fetchone()
                if elo_row:
                    current_elo = elo_row[0]
                else:
                    current_elo = 1100  # ELO_START default

                # Insert into queue
                cur = await conn.execute(
                    "INSERT INTO match_queue "
                    "(channel_id, username, game_type, elo_at_queue, elo_spread) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (cid, uname, game_type, current_elo, elo_spread)
                )
                queue_id = cur.lastrowid
                await conn.commit()

                return {
                    'enqueued': True,
                    'queue_id': queue_id,
                    'elo_at_queue': current_elo,
                    'game_type': game_type,
                }
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def cancel_queue(
        self,
        username: str,
        game_type: str,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Юзер выходит из очереди.

        Returns:
            {'cancelled': True, 'queue_id': N} | {'cancelled': False, 'reason': 'not_queued'}
        """
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        async with self._connect() as conn:
            cur = await conn.execute(
                "UPDATE match_queue SET status = 'cancelled' "
                "WHERE channel_id = ? AND username = ? AND game_type = ? AND status = 'queued' "
                "RETURNING id",
                (cid, uname, game_type)
            )
            row = await cur.fetchone()
            await conn.commit()
            if row:
                return {'cancelled': True, 'queue_id': row[0]}
            return {'cancelled': False, 'reason': 'not_queued'}

    async def expire_stale_queue_entries(self, ttl_minutes: int = 30) -> int:
        """Снять с очереди тех, кто висит в 'queued' дольше ttl_minutes.

        Найдено линтером 2026-07-30 (проверка `partial-lock`). Индекс
        `uq_match_queue_active_user(channel_id, username, game_type)
        WHERE status = 'queued'` — частичный, то есть ЗАМОК: пока строка висит,
        зритель не может встать в очередь на эту игру снова. Обычных выходов
        два — нашлась пара (`matched`) или зритель отменил сам (`cancelled`);
        третьего, «по времени», не было вовсе. `matchmaking_loop` только ищет
        пары и очередь не чистит, а константа `MATCHMAKING_QUEUE_TTL_SEC` была
        удалена 29.07 как неиспользуемая — то есть TTL задумывался и не доехал.

        На проде замок пока не сработал (0 строк в 'queued' на 29.07: 101
        отмена, 66 матчей) — это защита на будущее, а не разбор аварии.
        Мини-игры бесплатны, поэтому денег такой замок не съедает: он просто
        не даёт играть.

        Returns affected count. Вызывается фоновым циклом в main.py.
        """
        async with self._connect() as conn:
            cur = await conn.execute(
                "UPDATE match_queue SET status = 'expired' "
                "WHERE status = 'queued' "
                f"  AND queued_at < datetime('now', '-{int(ttl_minutes)} minutes')")  # tenant-ok: cross-channel expiry sweep
            affected = cur.rowcount
            await conn.commit()
        return affected

    async def get_queue_status(
        self,
        username: str,
        game_type: str,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Текущий статус юзера в matchmaking-системе.

        Returns:
            {'status': 'queued', 'queue_id': N, 'queued_at': ..., 'elo_at_queue': M, 'queue_position': K}
            | {'status': 'matched', 'room_id': X, 'opponent': Y}
            | {'status': 'in_room', 'room_id': X, 'opponent': Y}
            | {'status': 'idle'}
        """
        cid = resolve_channel_id(channel_id)
        uname = username.lower()

        async with self._connect() as conn:
            # Активный room?
            cur = await conn.execute(
                "SELECT room_id, player_a, player_b FROM match_rooms "
                "WHERE channel_id = ? AND status = 'active' AND game_type = ? "
                "AND (player_a = ? OR player_b = ?) LIMIT 1",
                (cid, game_type, uname, uname)
            )
            room_row = await cur.fetchone()
            if room_row:
                room_id, p_a, p_b = room_row
                opponent = p_b if p_a == uname else p_a
                return {'status': 'in_room', 'room_id': room_id, 'opponent': opponent}

            # В очереди?
            cur = await conn.execute(
                "SELECT id, status, queued_at, elo_at_queue, room_id FROM match_queue "
                "WHERE channel_id = ? AND username = ? AND game_type = ? "
                "AND status IN ('queued', 'matched') ORDER BY queued_at DESC LIMIT 1",
                (cid, uname, game_type)
            )
            q_row = await cur.fetchone()
            if q_row:
                q_id, status, q_at, elo, q_room = q_row
                if status == 'matched' and q_room:
                    return {'status': 'matched', 'room_id': q_room, 'queue_id': q_id}

                # Считаем queue_position (сколько раньше тебя стоит)
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM match_queue "
                    "WHERE channel_id = ? AND game_type = ? AND status = 'queued' "
                    "AND queued_at < ?",
                    (cid, game_type, q_at)
                )
                position = (await cur.fetchone())[0] + 1
                return {
                    'status': 'queued',
                    'queue_id': q_id,
                    'queued_at': q_at,
                    'elo_at_queue': elo,
                    'queue_position': position,
                }

            return {'status': 'idle'}

    async def find_match_pairs(
        self,
        channel_id: int,
        game_type: str,
    ) -> int:
        """Атомарно матчит пары юзеров в очереди по близкому ELO внутри
        (channel_id, game_type). Создаёт match_rooms для каждой пары,
        переводит queue-записи в 'matched'.

        Алгоритм:
          1. SELECT queued users ORDER BY elo_at_queue (для greedy pairing)
          2. Pair consecutive если abs(elo_a - elo_b) <= max(spread_a, spread_b)
          3. Per pair: create room, update queue rows, link через matched_with/room_id

        Returns:
            int — количество созданных пар (rooms)
        """
        import uuid
        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")

                cur = await conn.execute(
                    "SELECT id, username, elo_at_queue, elo_spread FROM match_queue "
                    "WHERE channel_id = ? AND game_type = ? AND status = 'queued' "
                    "ORDER BY elo_at_queue, queued_at",
                    (channel_id, game_type)
                )
                queued = await cur.fetchall()

                if len(queued) < 2:
                    await conn.execute("ROLLBACK")
                    return 0

                pairs_made = 0
                i = 0
                while i + 1 < len(queued):
                    a = queued[i]
                    b = queued[i + 1]
                    a_id, a_user, a_elo, a_spread = a
                    b_id, b_user, b_elo, b_spread = b

                    # ELO-spread check: разница не больше чем max позволяет
                    diff = abs(a_elo - b_elo)
                    max_allowed = max(a_spread, b_spread)
                    if diff > max_allowed:
                        # Не матчим эту пару, пробуем следующего как левый
                        i += 1
                        continue

                    # Создаём room
                    room_id = f"room_{game_type}_{uuid.uuid4().hex[:12]}"
                    await conn.execute(
                        "INSERT INTO match_rooms "
                        "(room_id, channel_id, game_type, player_a, player_b, "
                        " player_a_elo, player_b_elo, state, status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, '{}', 'active')",
                        (room_id, channel_id, game_type, a_user, b_user, a_elo, b_elo)
                    )

                    # Update queue records
                    await conn.execute(
                        "UPDATE match_queue SET status = 'matched', matched_with = ?, "
                        "room_id = ?, matched_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (b_id, room_id, a_id)
                    )
                    await conn.execute(
                        "UPDATE match_queue SET status = 'matched', matched_with = ?, "
                        "room_id = ?, matched_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (a_id, room_id, b_id)
                    )

                    pairs_made += 1
                    i += 2

                await conn.commit()
                return pairs_made
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def get_room(
        self,
        room_id: str,
        username: Optional[str] = None,
        channel_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """Получить данные комнаты. Если username передан — проверяет
        что юзер в этой комнате (защита от cross-user/channel snoop'а).

        Returns:
            {'room_id', 'channel_id', 'game_type', 'player_a/b', 'player_a/b_elo',
             'state' (dict), 'status', 'winner', 'outcome', 'created_at',
             'finished_at', 'opponent' (если username передан)}
            | None если не найдена / не разрешена
        """
        import json
        cid = resolve_channel_id(channel_id) if channel_id is not None else None
        uname = username.lower() if username else None

        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT room_id, channel_id, game_type, player_a, player_b, "
                "player_a_elo, player_b_elo, state, status, winner, outcome, "
                "created_at, finished_at FROM match_rooms WHERE room_id = ?",
                (room_id,)
            )
            row = await cur.fetchone()

        if not row:
            return None

        room = {
            'room_id':      row[0],
            'channel_id':   row[1],
            'game_type':    row[2],
            'player_a':     row[3],
            'player_b':     row[4],
            'player_a_elo': row[5],
            'player_b_elo': row[6],
            'state':        json.loads(row[7] or '{}'),
            'status':       row[8],
            'winner':       row[9],
            'outcome':      row[10],
            'created_at':   row[11],
            'finished_at':  row[12],
        }

        # Access control
        if cid is not None and room['channel_id'] != cid:
            return None
        if uname is not None:
            if room['player_a'] != uname and room['player_b'] != uname:
                return None
            room['opponent'] = room['player_b'] if room['player_a'] == uname else room['player_a']
            room['you_are'] = 'a' if room['player_a'] == uname else 'b'

        return room

    async def update_room_state(
        self,
        room_id: str,
        new_state: Dict,
        channel_id: Optional[int] = None,
    ) -> bool:
        """Атомарно обновить game-specific state комнаты (JSON). Только
        для active комнат — finished/aborted больше не принимают updates.
        """
        import json
        cid = resolve_channel_id(channel_id) if channel_id is not None else None

        async with self._connect() as conn:
            params = [json.dumps(new_state), room_id]
            sql = "UPDATE match_rooms SET state = ? WHERE room_id = ? AND status = 'active'"
            if cid is not None:
                sql += " AND channel_id = ?"
                params.append(cid)
            cur = await conn.execute(sql, params)
            await conn.commit()
            return cur.rowcount > 0

    async def finalize_match(
        self,
        room_id: str,
        winner: Optional[str],
        outcome: str,
        channel_id: Optional[int] = None,
    ) -> Dict:
        """Завершить матч: проставить winner, outcome, finished_at.
        Status переходит 'active' → 'finished'.

        ELO update и chat-notification — на caller (game-specific logic).

        Args:
            winner: username | None для draw
            outcome: 'win_a' | 'win_b' | 'draw' | 'timeout' | 'aborted'

        Returns:
            {'finalized': True, 'room_id': X, 'winner': Y, 'outcome': Z}
            | {'finalized': False, 'reason': 'not_active' | 'not_found'}
        """
        cid = resolve_channel_id(channel_id) if channel_id is not None else None
        valid_outcomes = {'win_a', 'win_b', 'draw', 'timeout', 'aborted'}
        if outcome not in valid_outcomes:
            return {'finalized': False, 'reason': 'invalid_outcome', 'outcome': outcome}

        status_to_set = 'aborted' if outcome == 'aborted' else 'finished'

        async with self._connect() as conn:
            params = [status_to_set, winner.lower() if winner else None,
                      outcome, room_id]
            sql = ("UPDATE match_rooms SET status = ?, winner = ?, outcome = ?, "
                   "finished_at = CURRENT_TIMESTAMP "
                   "WHERE room_id = ? AND status = 'active'")
            if cid is not None:
                sql += " AND channel_id = ?"
                params.append(cid)
            cur = await conn.execute(sql, params)
            await conn.commit()
            if cur.rowcount > 0:
                return {
                    'finalized': True,
                    'room_id': room_id,
                    'winner': winner,
                    'outcome': outcome,
                }
            return {'finalized': False, 'reason': 'not_active_or_not_found'}

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
                       eventsub_subscription_id, COALESCE(approved, 0)
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
                "approved":                 bool(row[11]),
                "oauth_access_token":       _decrypt_secret(row[7]),
                "oauth_refresh_token":      _decrypt_secret(row[8]),
                "oauth_expires_at":         row[9],
                "eventsub_subscription_id": row[10],
            }

    async def list_channels(self) -> list:
        """Список всех зарегистрированных стримеров (для admin / cross-channel ops)."""
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT channel_id, login, tier, active_module, registered_at, "
                "       COALESCE(approved, 0) "
                "FROM channels ORDER BY registered_at DESC"
            )
            rows = await cur.fetchall()
            return [
                {"channel_id": r[0], "login": r[1], "tier": r[2],
                 "active_module": r[3], "registered_at": r[4],
                 "approved": bool(r[5])}
                for r in rows
            ]

    async def set_channel_approved(self, channel_id: int, approved: bool) -> bool:
        """Одобрить канал или снять одобрение. True если строка нашлась.

        M99: ворота для стримеров. Регистрация самообслуживаемая, но работать
        канал начинает только после одобрения — пока путь установки не обкатан
        чужими руками, каждый неподготовленный стример это вечер переписки
        вместо разработки.
        """
        async with self._connect() as db:
            cur = await db.execute(
                "UPDATE channels SET approved = ? WHERE channel_id = ?",
                (1 if approved else 0, channel_id))
            await db.commit()
            return cur.rowcount > 0

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
                 _encrypt_secret(oauth_access_token), _encrypt_secret(oauth_refresh_token), oauth_expires_at),
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
                (_encrypt_secret(access_token), _encrypt_secret(refresh_token), expires_at, channel_id),
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
        """Достаёт новые и повторно поставленные в очередь actions.

        Новые строки выбираются по ``PK > since_id``. Повторно поставленная
        sweeper'ом строка имеет старый PK, но ненулевой ``dispatched_at`` — её
        тоже необходимо вернуть, иначе монотонный cursor делает retry навсегда
        невидимым до перезапуска connector'а.

        Перед возвратом строки атомарно помечаются ``status=dispatched``.

        Returns list of dicts: {id, action_id, type, data (JSON-парсенный),
        created_at}. Пустой список = нет новых actions (long-poll waits).
        """
        import json as _json
        async with self._connect() as db:
            # AUDIT 2026-05-29 (fix #5): read-first. Раньше BEGIN IMMEDIATE
            # (write-reserved lock) открывался на КАЖДЫЙ poll даже при 0 queued
            # actions → 50-100 каналов × 1 poll/сек = беспричинная write-
            # contention на единый SQLite. Теперь плоский SELECT (без write-lock);
            # write-tx открываем ТОЛЬКО когда реально есть строки для dispatch.
            # Безопасно: один connector на канал, long-poll последователен —
            # нет конкурентного poll'а за те же строки в рамках канала.
            cur = await db.execute(
                """
                SELECT id, action_id, type, data, created_at
                FROM module_actions
                WHERE channel_id = ? AND module_id = ?
                  AND status = 'queued'
                  AND (id > ? OR dispatched_at IS NOT NULL)
                ORDER BY id ASC
                LIMIT ?
                """,
                (channel_id, module_id, int(since_id), int(limit)),
            )
            rows = await cur.fetchall()
            if not rows:
                return []
            ids = [r[0] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                f"UPDATE module_actions SET status='dispatched', dispatched_at=CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders}) AND status='queued'",
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
        transition: bool = True,
    ) -> bool:
        """Connector подтвердил получение/исполнение action.

        Возвращает True только если ACK перевёл живую строку из
        queued/dispatched в acked/failed. Поздний или повторный ACK возвращает
        False, чтобы маршрут не запускал повторный refund, но сам receipt всё
        равно сохраняется в ack_received_at/ack_success/ack_error. Terminal
        status и REFUNDED-маркер при этом никогда не перезаписываются.
        """
        target_status = "acked" if success else "failed"
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                """
                SELECT status
                FROM module_actions
                WHERE channel_id = ? AND module_id = ? AND action_id = ?
                LIMIT 1
                """,
                (channel_id, module_id, action_id),
            )
            row = await cur.fetchone()
            if not row:
                await db.commit()
                return False

            previous_status = row[0]
            await db.execute(
                """
                UPDATE module_actions
                SET ack_received_at = CURRENT_TIMESTAMP,
                    ack_success     = ?,
                    ack_error       = ?
                WHERE channel_id = ? AND module_id = ? AND action_id = ?
                """,
                (1 if success else 0, error_msg,
                 channel_id, module_id, action_id),
            )

            transitioned = previous_status in ("queued", "dispatched")
            if transitioned and transition:
                await db.execute(
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
            return transitioned

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
        """player.unlinked → DELETE only this channel's pawn and details."""
        viewer_id = (viewer_id or "").strip().lower()
        if not viewer_id:
            return False
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "SELECT id FROM rimworld_pawns "
                    "WHERE channel_id=? AND username=?",
                    (channel_id, viewer_id),
                )
                row = await cur.fetchone()
                if not row:
                    await db.execute("ROLLBACK")
                    return False
                pawn_id = int(row[0])
                for table in (
                    "rimworld_pawn_equipment",
                    "rimworld_pawn_skills",
                    "rimworld_pawn_hediffs",
                    "rimworld_pawn_traits",
                    "rimworld_pawn_genes",
                ):
                    await db.execute(
                        f"DELETE FROM {table} "
                        "WHERE channel_id=? AND pawn_id=?",
                        (channel_id, pawn_id),
                    )
                await db.execute(
                    "DELETE FROM rimworld_pawns "
                    "WHERE channel_id=? AND id=?",
                    (channel_id, pawn_id),
                )
                await db.commit()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

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
                INSERT INTO rimworld_pawn_traits
                    (channel_id, pawn_id, trait_def, degree, label, trait_desc)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (channel_id, pawn_id, trait_def, int(degree),
                 label or trait_def, description or ""),
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
                "DELETE FROM rimworld_pawn_traits "
                "WHERE channel_id=? AND pawn_id=? AND trait_def=?",
                (channel_id, pawn_id, trait_def),
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
                INSERT INTO rimworld_pawn_genes
                    (channel_id, pawn_id, def_name, label, is_active, xenogene, gene_class)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (channel_id, pawn_id, def_name, label or def_name,
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
                "DELETE FROM rimworld_pawn_genes "
                "WHERE channel_id=? AND pawn_id=? AND def_name=?",
                (channel_id, pawn_id, def_name),
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
                    (channel_id, pawn_id, body_part, hediff_label, hediff_type,
                     severity, icon, is_permanent, description)
                VALUES (?, ?, ?, ?, 'implant', ?, ?, ?, ?)
                """,
                (channel_id, pawn_id, body_part or "", hediff_label,
                 float(severity), icon,
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
