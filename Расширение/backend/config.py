import os
import platform
import re as _re
import sys
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# ===== ПРОВЕРКА ОБЯЗАТЕЛЬНЫХ ПЕРЕМЕННЫХ =====
REQUIRED_ENV_VARS = [
    'TWITCH_OAUTH_TOKEN',
    'TWITCH_CLIENT_ID',
    'TWITCH_CLIENT_SECRET',
    'TWITCH_BOT_ID'
]

missing_env = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_env:
    print(f"❌ Отсутствуют переменные в .env файле: {', '.join(missing_env)}")
    print("📁 Создайте файл .env в папке с ботом со следующим содержимым:")
    print("""
TWITCH_OAUTH_TOKEN=oauth:ваш_токен
TWITCH_CLIENT_ID=ваш_client_id
TWITCH_CLIENT_SECRET=ваш_client_secret
TWITCH_BOT_ID=имя_бота
TWITCH_CHANNEL_NAME=ваш_канал
    """)
    sys.exit(1)

# ===== TWITCH НАСТРОЙКИ =====
TWITCH_OAUTH_TOKEN = os.getenv('TWITCH_OAUTH_TOKEN')
TWITCH_CHANNEL_NAME = os.getenv('TWITCH_CHANNEL_NAME', 'default_channel').lower().strip()
TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')
TWITCH_BOT_ID = os.getenv('TWITCH_BOT_ID')
TWITCH_EXTENSION_SECRET = os.getenv('TWITCH_EXTENSION_SECRET', '')
if not TWITCH_EXTENSION_SECRET:
    print("⚠️  TWITCH_EXTENSION_SECRET не задан в .env — JWT верификация будет отклонять все токены")

# ===== M4.3: TWITCH OAUTH FOR STREAMER REGISTRATION =====
# Стример проходит OAuth на /streamer чтобы зарегистрироваться в платформе.
# REDIRECT_URI должен совпадать с настройкой Twitch Developer Console.
TWITCH_OAUTH_REDIRECT_URI = os.getenv(
    'TWITCH_OAUTH_REDIRECT_URI',
    'https://shedoy23.ru/api/streamer/auth/callback'
)
# Скоупы: user:read:email чтобы получить login + user_id, channel:read:redemptions
# для будущего EventSub auto-register (M4.5 положит channel.channel_points_*).
TWITCH_OAUTH_SCOPES = 'user:read:email channel:read:redemptions'

# ===== Этап 3 step 5: Module API player events feature flag =====
# При false (default) — `player.linked` / `player.died` / `player.respawned` /
# `player.unlinked` / `player.state_update` events от connector'а ЛОГИРУЮТСЯ,
# но НЕ записываются в rimworld_pawns. Запись делает легаси-путь
# /api/rimworld/link / /sync_pawns_bulk / etc.
#
# При true — RimWorldAdapter сам пишет в БД через специализированные db-helpers.
# Это даёт двойную запись в переходный период (легаси /api/rimworld/* всё ещё
# работает) — для production нужно сначала переключить connector мода на
# Module API path, потом флипнуть флаг, потом отключить легаси routes.
#
# Ставим в true только при ручном тесте на dev-VPS или после Step 6 wrapper
# migration. До тех пор — false (безопасный default).
MODULE_API_PLAYER_EVENTS_ENABLED = os.getenv('MODULE_API_PLAYER_EVENTS_ENABLED', 'false').lower() == 'true'

# ===== Этап 3 step 2: Module API token signing =====
# Module API токены — HMAC-подписанные per-channel-per-module credentials.
# Стример получает токен из admin-UI dashboard, вставляет в connector
# (мод/плагин), connector использует в Authorization: Bearer <token>.
#
# **ВАЖНО (regression 2026-05-17):** если MODULE_TOKEN_SECRET не задан,
# fallback на TWITCH_EXTENSION_SECRET ломает существующие mod-токены при
# любой ротации TWITCH_EXTENSION_SECRET (вне зависимости от того,
# планировали ли мы trogat module API). Поэтому MODULE_TOKEN_SECRET
# **должен быть задан отдельно** на любом prod-deployment — fallback
# теперь даёт громкий warning при startup чтобы это заметить.
_MODULE_TOKEN_SECRET_ENV = os.getenv('MODULE_TOKEN_SECRET', '').strip()
MODULE_TOKEN_SECRET = _MODULE_TOKEN_SECRET_ENV or TWITCH_EXTENSION_SECRET
if not MODULE_TOKEN_SECRET:
    print("⚠️  MODULE_TOKEN_SECRET и TWITCH_EXTENSION_SECRET не заданы — Module API auth не будет работать")
elif not _MODULE_TOKEN_SECRET_ENV:
    print(
        "⚠️  MODULE_TOKEN_SECRET не задан явно — fallback на TWITCH_EXTENSION_SECRET. "
        "При ротации TWITCH_EXTENSION_SECRET все mod-токены станут невалидны (regression 2026-05-17). "
        "Рекомендуется: secrets.token_urlsafe(32) в .env как MODULE_TOKEN_SECRET=... — "
        "после этого mod-токены не зависят от extension secret rotation."
    )

# ===== M5: Per-channel rate limits + tier-based квоты =====
# Лимит запросов в минуту на канал. Применяется в require_jwt_user/_channel
# (M5 hook): JWT-аутентифицированный запрос для канала X считается в bucket
# канала X. Если лимит превышен — 429.
#
# Квоты по тарифам — основа будущего биллинга. Free достаточен для
# разогрева/тестов, Pro для типичного стрима 50-200 онлайна, VIP с запасом
# на крупные стримы 1000+ онлайна.
#
# Можно переопределить в .env через RATE_LIMIT_FREE / _PRO / _VIP (req/min).
RATE_LIMITS_BY_TIER = {
    'free': int(os.getenv('RATE_LIMIT_FREE', '300')),   # ~5 req/sec на канал
    'pro':  int(os.getenv('RATE_LIMIT_PRO',  '1200')),  # 20 req/sec
    'vip':  int(os.getenv('RATE_LIMIT_VIP',  '6000')),  # 100 req/sec
}
# Tier для каналов которые ещё не имеют записи (или fallback при кэш-промахе).
RATE_LIMIT_DEFAULT_TIER = 'free'

# ===== M4.5: EventSub AUTO-REGISTER (feature flag) =====
# При false — register_eventsub_subscriptions регистрирует подписки только для
# TWITCH_BROADCASTER_ID из .env (текущая single-tenant логика, безопасный default).
# При true — iterate db.list_channels() и регистрируем по подписке на каждого
# зарегистрированного стримера. Требует что у каждого канала есть OAuth-токен
# (M4.3 OAuth flow) — без этого Twitch не примет subscription для broadcaster'а
# который не авторизовал наш scope.
#
# Phase A (2026-05-16): регистрируется 3 типа подписок на канал —
# channel_points, stream.online, stream.offline. См. eventsub.PHASE_A_SUBSCRIPTIONS.
#
# Флипать в true когда: 1) есть >1 зарегистрированного стримера, 2) проверена
# логика на dev-VPS или unit-тестами. До того момента — оставлять false чтобы
# прод single-tenant поведение не менялось.
EVENTSUB_AUTO_REGISTER = os.getenv('EVENTSUB_AUTO_REGISTER', 'false').lower() == 'true'

# ===== DEV MODE (только для локального тестирования) =====
# Добавьте DEV_MODE=true и DEV_USERNAME=ваш_ник в .env чтобы обойти JWT верификацию
# НИКОГДА не включайте на продакшн сервере
DEV_MODE     = os.getenv('DEV_MODE', 'false').lower() == 'true'
DEV_USERNAME = os.getenv('DEV_USERNAME', 'dev_user').lower().strip()

# Testing-без-стрима. Если True — require_stream_live() всегда возвращает None.
# Используется для функционального тестирования без необходимости поднимать стрим.
# WARN: НЕ оставлять True в проде надолго — viewer'ы смогут тратить очки на дуэли
# / события когда канал офлайн. Включать только на test-канале или коротко.
TESTING_BYPASS_STREAM_LIVE = os.getenv('TESTING_BYPASS_STREAM_LIVE', 'false').lower() == 'true'
if DEV_MODE:
    print(f"⚠️  DEV_MODE включён — JWT верификация отключена, пользователь: '{DEV_USERNAME}'")

# ===== УТИЛИТЫ (используются в нескольких модулях) =====

def sanitize_username(username: str) -> str:
    """Очищает username — только ASCII буквы, цифры, _ и - (Twitch usernames ASCII-only)"""
    if not username:
        return ''
    clean = _re.sub(r'[^a-zA-Z0-9_\-]', '', str(username).strip())
    return clean[:64]

def validate_username(username: str) -> bool:
    if not username or len(username) < 2 or len(username) > 64:
        return False
    bad = ["'", '"', ';', '--', '<', '>', '/', '\\', '..']
    low = username.lower()
    return not any(b in low for b in bad)

# ===== НАСТРОЙКИ БОТА =====
POINTS_PER_MINUTE = 25  # Базовые очки в минуту (снижено с 50 для баланса экономики)
CHECK_INTERVAL = 60      # секунд

# ===== ОКНА АКТИВНОСТИ ЗРИТЕЛЯ =====
# Сигнал активности = heartbeat расширения / сообщение в чате / любое действие (спин/ставка/…).
# Возраст сигнала (age) измеряется от момента последнего касания:
#   age < ACTIVE_WINDOW                  → status="active",  100% очков
#   ACTIVE_WINDOW ≤ age < REDUCED_WINDOW → status="reduced", 50%  очков
#   age ≥ REDUCED_WINDOW                 → status="offline", 0   (не начисляем)
ACTIVE_WINDOW  = 900    # 15 минут
REDUCED_WINDOW = 1800   # 30 минут

# Backward-compat алиасы — постепенно удалить. Внешние модули могут ещё импортить.
AFK_TIMEOUT         = ACTIVE_WINDOW
AFK_PENALTY_TIMEOUT = REDUCED_WINDOW

# Минимальный heartbeat (секунд watch_time) чтобы засчитать сигнал активности.
# Отсекает пустые/нулевые пинги и осложняет накрутку через сырые POST-ы.
MIN_HEARTBEAT_SECONDS = 30

# ===== Chat-bonus антифрод (M7) =====
# IRC bot ловит каждое сообщение в чате и может выдать бонус (1-10 поинтов)
# за длинное сообщение. Без защиты — спам мелкими репликами или копи-паст
# даёт unfair advantage. Триггеры pre-bonus:
#   1. Cooldown — один бонус раз в N секунд (per channel, user)
#   2. Min length — короткие сообщения не получают бонус
#   3. Dedup — повтор в недавнем окне = no bonus (anti copy-paste)
CHAT_BONUS_COOLDOWN_SEC = 10
CHAT_BONUS_MIN_CHARS    = 10
CHAT_BONUS_DEDUP_WINDOW = 10  # помним последние N хэшей сообщений на (channel, user)

# ===== НАСТРОЙКИ ДРОПОВ =====
DROP_INTERVAL = 1200     # 20 минут
DROP_CHANCE = 0.25       # 25% шанс

# ===== СИСТЕМНЫЕ ТАЙМАУТЫ =====
RIMWORLD_OFFLINE_TIMEOUT = 600  # 10 минут без пинга = RimWorld офлайн
CACHE_EVICTION_INTERVAL  = 600  # 10 минут между чистками внутреннего кэша
WATCH_TIME_CAP           = 3600 # максимум времени просмотра за один запрос (1 час)
LOGIN_ATTEMPT_TTL        = 3600 # через 1 час сбрасывается счётчик неудачных входов

# ===== ПУТИ RIMWORLD (автоопределение) =====
def get_rimworld_path():
    """Автоматически определяет путь к RimWorld в зависимости от ОС"""
    system = platform.system()
    
    if system == "Windows":
        base = os.path.join(os.environ['USERPROFILE'], 
                           'AppData', 'LocalLow', 'Ludeon Studios', 
                           'RimWorld by Ludeon Studios')
    elif system == "Linux":
        base = os.path.join(os.path.expanduser('~'), 
                           '.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios')
    elif system == "Darwin":  # macOS
        base = os.path.join(os.path.expanduser('~'), 
                           'Library/Application Support/RimWorld')
    else:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rimworld_data')
    
    # Создаём папку, если её нет
    os.makedirs(base, exist_ok=True)
    return base

if not os.getenv('RIMWORLD_PRICES_PATH'):
    RIMWORLD_BASE_PATH = get_rimworld_path()
    RIMWORLD_PRICES_PATH = os.path.join(RIMWORLD_BASE_PATH, 'TwitchPrices.json')
    RIMWORLD_COMMANDS_PATH = os.path.join(RIMWORLD_BASE_PATH, 'TwitchCommands.txt')
    RIMWORLD_REFUNDS_PATH = os.path.join(RIMWORLD_BASE_PATH, 'TwitchRefunds.txt')
else:
    RIMWORLD_PRICES_PATH = os.getenv('RIMWORLD_PRICES_PATH')
    RIMWORLD_COMMANDS_PATH = os.getenv('RIMWORLD_COMMANDS_PATH')
    RIMWORLD_REFUNDS_PATH = os.getenv('RIMWORLD_REFUNDS_PATH')
    if RIMWORLD_PRICES_PATH:
        RIMWORLD_BASE_PATH = os.path.dirname(os.path.abspath(RIMWORLD_PRICES_PATH))
    else:
        RIMWORLD_BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# ===== ПРОЧИЕ НАСТРОЙКИ =====
# DONATION_MULTIPLIER + ECONOMY_CONFIG donation keys удалены 2026-05-14
# (Phase 8.F donate removal — §5.2/§5.4 compliance).
RAFFLE_COOLDOWN = 300    # 5 минут
AUTO_MESSAGES_ENABLED = True
AUTO_MESSAGE_INTERVAL = 180  # 3 минут

AUTO_MESSAGES = [
    '💎 Чтобы участвовать в интеграции, купи в наградах канала ПОЛУЧИТЬ ДОСТУП К...',
    # Донат-сообщение удалено 2026-05-14 (Phase 8.F)
    '📜 Ежедневные квесты обновляются в 00:00 МСК!',
    '🎁 Кейсы падают каждые 20 минут с шансом 25%!',
    '💬 Пиши в чат и получай бонусные очки!',
    '⏰ Активные зрители получают больше очков!'
]

# ===== НАСТРОЙКИ ИВЕНТА =====
EVENT_CONFIG = {
    'min_donations_for_event': 500,
    'min_points_for_event': 100000,
    'event_duration': 180,   # 3 минуты (уменьшено с 5)
    'min_bid': 100,
    'cooldown_hours': 0.1,     # Минимум 1 час между ивентами (защита экономики)
    # Продление таймера при смене лидера в аукционе
    'extend_on_leader_change': True,   # включить продление
    'extend_threshold': 30,            # если до конца осталось меньше N секунд
    'extend_duration': 30,             # на сколько секунд продлять
    'extend_max_total': 600,           # максимум продления за весь ивент (суммарно)
}

EVENT_ITEMS = [
    {'name': '🪵 Деревяшка', 'item_id': 'деревяшка', 'chance': 25, 'emoji': '🪵', 'value': 1},
    {'name': '🪨 Камень', 'item_id': 'камень', 'chance': 25, 'emoji': '🪨', 'value': 6},
    {'name': '🔮 Амулет', 'item_id': 'амулет', 'chance': 25, 'emoji': '🔮', 'value': 32},
    {'name': '👑 Корона', 'item_id': 'корона', 'chance': 25, 'emoji': '👑', 'value': 200},
]

EVENT_TYPES = {
    # 'roulette' тип удалён 2026-05-10 (Phase 1.E compliance rework — gambling
    # по §6.2.3 + §6.2.6: взвешенный рандом по сумме ставок = lottery с monetary
    # value reward). Остался только аукцион (детерминированный max-bid winner).
    # В Phase 4 переделается полностью в голосование за действие стримера.
    'auction': {
        'name': '⚖️ АУКЦИОН',
        'description': 'Кто больше накидал за 5 минут - тот и победил!',
        'chance': 100
    }
}

# CASINO_CONFIG удалён в Phase 1.A (2026-05-10) — gambling по §6.2.3 Twitch Extension Guidelines.
# См. COMPLIANCE_REWORK_PLAN.md §4 Phase 1.

# ===== MATCHMAKING (Phase 5.0, 2026-05-11) =====
# Интервал matchmaking_loop — как часто ищем пары в очереди (sek).
# Trade-off: ниже — быстрее матч после enqueue, выше — меньше БД-нагрузка.
MATCHMAKING_INTERVAL = 5

# Какие game_types обслуживает matchmaking_loop. Добавляются по мере
# реализации игр.
# 'rps'       — legacy дуэли (Phase 1.F убрала ставки, остался ELO-only)
# 'tictactoe' — Phase 5.1 MVP
# 'dice'      — Phase 5.2 (vs bot + PvP)
MATCHMAKING_GAME_TYPES = ('rps', 'tictactoe', 'dice')

# ELO-spread по умолчанию (если юзер не указал свой).
MATCHMAKING_DEFAULT_ELO_SPREAD = 100

# Auto-expire queue entries старше N секунд (cleanup от disconnected клиентов).
MATCHMAKING_QUEUE_TTL_SEC = 300

# ===== PETS MVP (Phase 7, 2026-05-11) =====
# Compliance критично: catalog задаётся ТУТ, не стримером (§6.2.8 protection).
# Items deterministic, не mystery box за Bits (§6.2.4 ban).
# Cosmetics-only — НЕТ utility (бустов / преимуществ).

# Bits integration mode. Когда зарегистрируем Bits products в Twitch
# Developer Console — flip на True. До этого moments — mock-режим без
# реальных Bits transactions.
PETS_BITS_REQUIRED = False                  # ENV override: PETS_BITS_REQUIRED=true

# Default pet appearance — 🥚 яичко-маскот (символ начала, см. PROJECT_PLAYBOOK §5.4)
PET_BASE_TYPE = 'egg'

# Какие slots существуют. Если добавляем новый — расширяем CHECK в migration M13.
PET_SLOTS = ('head', 'accessory', 'background', 'body')

# Max pet name length (опц.)
PET_NAME_MAX_LEN = 24

# ===== ГОЛОСОВАНИЯ (Phase 4, 2026-05-11) =====
# Voting events — стример настраивает варианты действий, юзеры вкидывают
# крустики на свой выбор. §6.1.4 Twitch Extension Guidelines прямо разрешает.

# Pool accumulation: пассивная активность зрителей наполняет pool units.
# При достижении порога — auto-start event (если default template есть).
VOTING_POOL_THRESHOLD = 1000              # units для auto-start
VOTING_POOL_PER_WATCH_MIN = 1             # +1 unit за минуту активного просмотра per viewer
VOTING_POOL_PER_CHAT_MSG = 5              # +5 unit за каждое чат-сообщение

# Event duration after start
VOTING_EVENT_DURATION_SEC = 300           # 5 минут на голосование

# Bid constraints
VOTING_MIN_BID = 50                       # минимальный bid крустиков
VOTING_MAX_OPTIONS = 6                    # макс вариантов в template

# Matchmaking-style loop: проверка завершения events каждые N сек
VOTING_LOOP_INTERVAL = 10

# ===== ГИЛЬДИИ (Phase 3, 2026-05-11) =====
# Cost создания гильдии — sink крустиков из личного баланса master'а.
GUILD_CREATE_COST = 100_000

# Лимиты:
GUILD_NAME_MIN_LEN = 3
GUILD_NAME_MAX_LEN = 30
GUILD_TAGLINE_MAX_LEN = 80
GUILD_MAX_MEMBERS_BASE = 10    # без skills прокачки
GUILD_MIN_CONTRIBUTE = 100     # минимальный взнос в balance

# Skills config (Phase 3 placeholder — v1 две ветки).
# Расширяется в Phase 3.1+ когда увидим что просят юзеры (§13.10 числа = параметры).
# cost_per_level — стоимость прокачки уровня N из balance гильдии.
GUILD_SKILLS_CONFIG = {
    'extra_member_slots': {
        'name':           'Расширение состава',
        'description':    '+5 слотов для участников на уровень',
        'max_level':      5,
        'cost_per_level': [50_000, 100_000, 200_000, 400_000, 800_000],
        'effect_per_level': 5,  # +5 max_members per level
    },
    'cosmetic_banner_unlock': {
        'name':           'Кастомный баннер',
        'description':    'Разблокирует выбор баннера для гильдии',
        'max_level':      1,
        'cost_per_level': [200_000],
        'effect_per_level': 1,  # unlock-style: 1 level = enabled
    },
}

# ===== НАСТРОЙКИ КЕЙСОВ (Phase 2, 2026-05-11) =====
# Фиксированная награда крустиков per tier. Балансится через config, не через
# миграцию — позволяет корректировать без БД-изменений (см. урок 13.10
# COMPLIANCE_AND_ARCHITECTURE.md: числа = параметры, не законы).
#
# Compliance: содержимое каждого кейса детерминированно (нет RNG в reward).
# Кейсы выдаются бесплатно за активность — §5.3 Twitch Extension Guidelines
# permits loot boxes "as long as contents do not have monetary value" (наша
# валюта non-tradable, non-exchangeable → no monetary value).
CASE_TIER_REWARDS = {
    'common':     1_000,
    'rare':       10_000,
    'epic':       100_000,
    'legendary':  500_000,
}

# Valid sources для cases.source (audit-trail откуда выдан кейс).
# Расширяется по мере добавления новых триггеров (Phase 6 drops loop, etc).
CASE_SOURCES = (
    'quest',            # daily quest completion → common
    'streak',           # streak milestones (10) → rare
    'watch_milestone',  # watch hour milestones (100h) → epic
    'season_top',       # sезонный топ-3 → legendary
    'drop',             # Phase 6 drops loop (tier weights 70/25/4/1)
    'admin_grant',      # выдан admin'ом руками
    'promo',            # через промокод (future)
)

# ===== НАСТРОЙКИ TTS =====
TTS_CONFIG = {
    'enabled': True,
    'cost': 100,
    'max_length': 120,
    'cooldown': 1.5,
    'lang': 'ru',
    'volume': 0.95
}

# ===== НАСТРОЙКИ EVENTSUB =====
EVENTSUB_CONFIG = {
    'secret_required': True,      # Требовать секрет всегда (без fallback)
    'log_errors': True,           # Логировать все ошибки верификации
}

# ===== НАСТРОЙКИ ЗВУКОВ =====
SOUND_CONFIG = {
    'enabled': True,
    'cooldown': 2.0,
    'volume': {
        'default': 0.7,
        'win': 0.9,
        # 'jackpot' удалён 2026-05-12 (Phase 8.A.2 lexicon scrub — dead key)
        'coin': 0.4,
        'error': 0.3,
        'gift': 0.8,
        'wedding': 0.9,
        'divorce': 0.8,
        'chat': 0.3  # Звук нового сообщения
    }
}

# ===== НАСТРОЙКИ ПРОИЗВОДИТЕЛЬНОСТИ =====
PERFORMANCE_CONFIG = {
    'db_timeout': 10.0,
    'db_retry_count': 3,
    'cache_ttl': 30,
    'stats_update_interval': 5000,
    'max_log_lines': 1000,
    'cleanup_temp_files': True,
    'temp_files_max_age': 3600
}

# ===== КОНФИГУРАЦИЯ ПРЕДМЕТОВ =====
ITEMS_CONFIG = [
    {
        'name': 'деревяшка',
        'display_name': 'Деревяшка',
        'value': 1,
        'rarity': 'common',
        'craft_level': 1,
        'description': 'Простая палка. +1 очко/мин',
        'emoji': '🪵'
    },
    {
        'name': 'камень',
        'display_name': 'Камень',
        'value': 6,
        'rarity': 'uncommon',
        'craft_level': 2,
        'description': 'Тяжёлый камень. +6 очков/мин',
        'emoji': '🪨'
    },
    {
        'name': 'амулет',
        'display_name': 'Амулет',
        'value': 32,
        'rarity': 'rare',
        'craft_level': 3,
        'description': 'Магический амулет. +32 очка/мин',
        'emoji': '🔮'
    },
    {
        'name': 'корона',
        'display_name': 'Корона',
        'value': 200,
        'rarity': 'epic',
        'craft_level': 4,
        'description': 'Золотая корона. +200 очков/мин!',
        'emoji': '👑'
    }
]

# ===== НАСТРОЙКИ КВЕСТОВ =====
QUESTS_CONFIG = {
    # Квесты на время просмотра
    'watch_time_30': {
        'target': 30,
        'reward_points': 1500,
        'reward_item': None,
        'display_name': '📺 30 минут просмотра',
        'emoji': '⏱️',
        'type': 'time'
    },
    'watch_time_60': {
        'target': 60,
        'reward_points': 3000,
        'reward_item': None,
        'display_name': '📺 1 час просмотра',
        'emoji': '⌛',
        'type': 'time'
    },
    'watch_time_120': {
        'target': 120,
        'reward_points': 6000,
        'reward_item': None,
        'display_name': '📺 2 часа просмотра',
        'emoji': '⏳',
        'type': 'time'
    },
    'watch_time_180': {
        'target': 180,
        'reward_points': 8000,
        'reward_item': None,
        'display_name': '📺 3 часа просмотра',
        'emoji': '⌚',
        'type': 'time'
    },
    'watch_time_240': {
        'target': 240,
        'reward_points': 9000,
        'reward_item': None,
        'display_name': '📺 4 часа просмотра',
        'emoji': '⏰',
        'type': 'time'
    },
    'watch_time_300': {
        'target': 300,
        'reward_points': 10000,
        'reward_item': None,  # 2026-05-13 (Phase 8.C): item rewards убраны (§5.3 compliance)
        'display_name': '📺 5 ЧАСОВ ПРОСМОТРА!',
        'emoji': '🏆',
        'type': 'time'
    },
    
    # Квесты на сообщения в чате
    'chat_messages_10': {
        'target': 10,
        'reward_points': 500,
        'reward_item': None,
        'display_name': '💬 10 сообщений в чате',
        'emoji': '💬',
        'type': 'chat'
    },
    'chat_messages_25': {
        'target': 25,
        'reward_points': 1200,
        'reward_item': None,
        'display_name': '💬 25 сообщений в чате',
        'emoji': '🗣️',
        'type': 'chat'
    },
    'chat_messages_50': {
        'target': 50,
        'reward_points': 2500,
        'reward_item': None,  # 2026-05-13 (Phase 8.C): item rewards убраны (§5.3 compliance)
        'display_name': '💬 50 сообщений в чате',
        'emoji': '💎',
        'type': 'chat'
    },
    'chat_messages_100': {
        'target': 100,
        'reward_points': 5000,
        'reward_item': None,
        'display_name': '💬 100 сообщений в чате',
        'emoji': '👑',
        'type': 'chat'
    },
    

}

# Порядок отображения квестов
QUEST_ORDER = [
    # Временные квесты
    'watch_time_30',
    'watch_time_60',
    'watch_time_120',
    'watch_time_180',
    'watch_time_240',
    'watch_time_300',
    # Чат-квесты
    'chat_messages_10',
    'chat_messages_25',
    'chat_messages_50',
    'chat_messages_100',
]

# ===== НАСТРОЙКИ ОТСЛЕЖИВАНИЯ АКТИВНОСТИ =====
ACTIVITY_CONFIG = {
    'watch_time_update_interval': 60,  # Отправлять статистику каждые 60 секунд
    'chat_bonus_enabled': True,        # Включить бонусы за сообщения в чате
    'bonus_per_message': 5,            # Очки за каждое сообщение
    'max_daily_chat_bonus': 500,       # Максимальный дневной бонус за чат
}

# ===== TWITCH КАНАЛ ДЛЯ ПРОВЕРКИ ОНЛАЙНА =====
TWITCH_STREAM_CHANNEL = os.getenv('TWITCH_STREAM_CHANNEL', 'shedoy23')  # Канал для проверки онлайна

# ===== НАСТРОЙКИ ЭКОНОМИКИ =====
# 2026-05-14 (Phase 8.F donate removal): убраны donation-keys
# (points_per_rub, donation_item_threshold, min_event_donations) — §5.2/§5.4
# Twitch Extension Guidelines, real-money flow вне Bits недопустим.
ECONOMY_CONFIG = {
    'min_transfer': 10,             # Минимум очков для перевода зрителю
    'min_event_contribute': 100,    # Минимум очков для вклада (voting events)
    'income_no_items': 5,           # Доход/мин (отображение)
}

# ===== НАСТРОЙКИ СЕМЬИ =====
FAMILY_CONFIG = {
    # 'income_per_min' / 'bonus_per_min' удалены 2026-05-10 (Phase 1.G compliance
    # rework — financial pool вырезан, marriage теперь чисто social).
    # 'marriage_cost' тоже удалён (был не используется в коде).
    'divorce_cost': 500,            # Sink крустиков, гейт от случайных разводов
}

# ===== НАСТРОЙКИ RIMWORLD =====
RIMWORLD_CONFIG = {
    # Стоимость действий с пешкой
    'heal_cost': 150,               # Лечение пешки
    'resurrect_cost': 500,          # Воскрешение пешки
    'spawn_pawn_cost': 200,         # Создание пешки зрителя
}

# ===== НАГРАДЫ ЗА СТРИКИ ПРОСМОТРОВ =====
# Twitch присылает USERNOTICE с msg-id=viewership-milestone когда зритель
# смотрит N стримов подряд. Ключи — количество стримов, значения — алмазы.
STREAK_REWARDS = {
    5:   5000,
    10:  10000,
    20:  20000,
    30:  30000,
    40:  40000,
    50:  50000,
    100: 100000,
}

# ===== MULTI-TENANT FALLBACK =====
# Используется в helpers (add_points, touch_viewer и др.) и inline INSERT'ах
# где channel_id ещё НЕ протолкнут из JWT. M1 миграция требует channel_id
# во всех TENANT-таблицах; без явного значения берём этот fallback.
# TODO M3: после полного query scoping убрать fallback, требовать channel_id явно.
try:
    DEFAULT_CHANNEL_ID = int(os.getenv('TWITCH_BROADCASTER_ID', '98319857') or 98319857)
except (TypeError, ValueError):
    DEFAULT_CHANNEL_ID = 98319857

# ===== CHANNEL POINTS → IN-EXTENSION АЛМАЗЫ (loyalty reward) =====
# Зритель redeem'ит channel-point reward — бэк начисляет внутренние алмазы.
#
# Compliance (см. mini-audit 2026-05-16):
#   - Twitch Channel Points Acceptable Use Policy явно разрешает CP →
#     in-extension currency, при условии что эта currency не имеет monetary
#     value и не cash-out'ится в реальные деньги. У нас алмазы только тратятся
#     внутри расширения (cases/cosmetics). Disclosure показан зрителю
#     в extension.html / mobile.html (compliance-disclosure block).
#   - Названия наград — formulated как loyalty reward (не «обмен/exchange»):
#     "Награда: ..." не воспринимается reviewer'ами как commercial transaction.
#
# !!! ВАЖНО про синхронизацию с Twitch Dashboard !!!
# Ключи в `rewards` ДОЛЖНЫ ТОЧНО совпадать с custom reward titles
# в Twitch Creator Dashboard → Channel Points → Manage Rewards. Если
# поменял здесь — обязательно поменяй и там, иначе EventSub redemption
# event прилетит с title который не найдётся в config и будет ignored.
#
# TWITCH_BROADCASTER_ID — числовой ID стримера (не ник).
# Получить можно тут: https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/
CHANNEL_POINTS_CONFIG = {
    'enabled': True,
    'broadcaster_id': os.getenv('TWITCH_BROADCASTER_ID', ''),
    # title → сколько алмазов начислить как loyalty reward
    'rewards': {
        'Награда: 5000 алмазов':  {'channel_points_cost': 5000,  'diamonds': 5000},
        'Награда: 12000 алмазов': {'channel_points_cost': 10000, 'diamonds': 12000},
        'Награда: 35000 алмазов': {'channel_points_cost': 25000, 'diamonds': 35000},
    },
    # Секрет для верификации EventSub вебхука (32+ url-safe bytes).
    # Ротирован 2026-05-16 на secrets.token_urlsafe(32).
    'eventsub_secret': os.getenv('EVENTSUB_SECRET', ''),
}

# ===== СПИСОК ИСКЛЮЧЕНИЙ ИЗ ДРОПА =====
# Пользователи из этого списка не получают дропы
DROP_BLACKLIST: set = set(filter(None, os.getenv('DROP_BLACKLIST', 'shedoy23').split(',')))

# ===== ВЫВОД ИНФОРМАЦИИ ПРИ ЗАПУСКЕ =====
if __name__ == '__main__':
    print("✅ Конфигурация загружена успешно!")
    print(f"📺 Канал: {TWITCH_CHANNEL_NAME}")
    print(f"💎 Очки в минуту: {POINTS_PER_MINUTE}")
    print("💬 Бонус за сообщение в чате: до 10💎 (макс 500 сообщений/день)")
    print(f"🎁 Дропы: каждые {DROP_INTERVAL//60} мин, шанс {DROP_CHANCE*100}%")
    print(f"📁 RimWorld путь: {RIMWORLD_BASE_PATH}")
    print(f"📜 Квестов настроено: {len(QUESTS_CONFIG)}")
