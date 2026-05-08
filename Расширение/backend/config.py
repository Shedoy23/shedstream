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

# ===== M4.5: EventSub AUTO-REGISTER (feature flag) =====
# При false — register_eventsub_channel_points регистрирует ОДНУ подписку для
# TWITCH_BROADCASTER_ID из .env (текущая single-tenant логика, безопасный default).
# При true — iterate db.list_channels() и регистрируем по подписке на каждого
# зарегистрированного стримера. Требует что у каждого канала есть OAuth-токен
# (M4.3 OAuth flow) — без этого Twitch не примет subscription для broadcaster'а
# который не авторизовал наш scope.
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
# DONATION_MULTIPLIER устарел — используй ECONOMY_CONFIG['points_per_rub']
RAFFLE_COOLDOWN = 300    # 5 минут
AUTO_MESSAGES_ENABLED = True
AUTO_MESSAGE_INTERVAL = 180  # 3 минут

AUTO_MESSAGES = [
    '💎 Чтобы участвовать в интеграции, купи в наградах канала ПОЛУЧИТЬ ДОСТУП К...',
    '🎁 Донат 1₽ = 100 очков!',
    '📜 Ежедневные квесты обновляются в 00:00 МСК!',
    '🎁 Предметы падают каждые 20 минут с шансом 25%!',
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
    'roulette': {
        'name': '🎲 РУЛЕТКА',
        'description': 'Чем больше очков вкинул, тем выше шанс на победу!',
        'chance': 50
    },
    'auction': {
        'name': '⚖️ АУКЦИОН',
        'description': 'Кто больше накидал за 5 минут - тот и победил!',
        'chance': 50
    }
}

# ===== НАСТРОЙКИ КАЗИНО =====
CASINO_CONFIG = {
    'min_bet': 50,
    'cooldown_threshold': 1000000,
    'cooldown_duration': 600,
    'win_chances': {
        'loss': 0.6,
        'double': 0.35,
        'jackpot': 0.05
    }
}

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
        'jackpot': 1.0,
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
        'reward_item': 'амулет',
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
        'reward_item': 'камень',
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
ECONOMY_CONFIG = {
    'points_per_rub': 100,          # Очков за 1 рубль доната
    'donation_item_threshold': 50,  # Минимум рублей для получения предмета с доната
    'min_transfer': 10,             # Минимум очков для перевода зрителю
    'min_event_contribute': 100,    # Минимум очков для вклада в копилку рулекциона
    'min_event_donations': 500,     # Минимум рублей донатов для старта ивента
    'income_no_items': 5,           # Доход/мин без предметов (отображение)
}

# ===== НАСТРОЙКИ СЕМЬИ =====
FAMILY_CONFIG = {
    'income_per_min': 50,            # Базовый доход пары без предметов
    'bonus_per_min': 15,            # Бонус к доходу за семью
    'marriage_cost': 200,           # Стоимость создания пешки / вступления в брак
    'divorce_cost': 500,            # Стоимость развода
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

# ===== ОБМЕН CHANNEL POINTS TWITCH НА АЛМАЗЫ =====
# Зритель тратит очки канала — бот зачисляет алмазы.
# TWITCH_BROADCASTER_ID — числовой ID стримера (не ник).
# Узнать можно тут: https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/
# Название награды должно точно совпадать с тем что создано в Twitch Dashboard.
CHANNEL_POINTS_CONFIG = {
    'enabled': True,
    'broadcaster_id': os.getenv('TWITCH_BROADCASTER_ID', ''),
    # Название кастомной награды в Twitch → сколько алмазов давать
    'rewards': {
        '5000 очков → алмазы': {'channel_points_cost': 5000, 'diamonds': 5000},
        '10000 очков → алмазы': {'channel_points_cost': 10000, 'diamonds': 12000},
        '25000 очков → алмазы': {'channel_points_cost': 25000, 'diamonds': 35000},
    },
    # Секрет для верификации EventSub вебхука (любая строка, мин. 10 символов)
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
