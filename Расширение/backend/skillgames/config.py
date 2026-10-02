"""Versioned server rules; new-game prizes deliberately need owner calibration."""
from . import battleship, minesweeper

GAME_TYPES = ('battleship', 'minesweeper')
ELO_START = 1000
ELO_K = 32
PUZZLE_RATINGS = {'beginner': 1000, 'advanced': 1200}
ATTEMPT_SECONDS = 600
FIRST_MOVE_WAIT_SECONDS = 600
SETUP_SECONDS = 120
TURN_SECONDS = 45
TOTAL_SECONDS = 1200
GRACE_SECONDS = 10
QUEUE_SECONDS = 300
POLL_INTERVAL_MS = 2000
HEARTBEAT_SECONDS = 2
GENERATION_CONCURRENCY = 2
GENERATION_SECONDS = 10
STARTS_PER_MINUTE = 6
REQUEST_RETENTION_SECONDS = 24 * 60 * 60
SESSION_RETENTION_SECONDS = 30 * 24 * 60 * 60
MAX_RECEIPTS_PER_USER = 4096
GAME_AVAILABILITY = {game: {'enabled': True, 'reason': None} for game in GAME_TYPES}

MESSAGES = {
    'active_session': 'Сначала заверши текущую игру',
    'active_ranked_session': 'У тебя уже идёт игра',
    'already_queued': 'Сначала выйди из очереди',
    'generation_busy': 'Сервер готовит другие поля. Попробуй ещё раз чуть позже',
    'generation_in_progress': 'Поле ещё готовится, подожди обновления',
    'generation_failed': 'Не удалось подготовить поле. Попытка отменена без потери рейтинга',
    'stale_version': 'Состояние игры изменилось. Обнови его перед следующим ходом',
    'expiry_verification_pending': 'Проверяем завершение таймера. Подожди обновления',
    'request_id_reused': 'Этот запрос уже использован для другого действия',
    'request_rate_limited': 'Достигнут дневной предел действий. Повтор запроса по прежнему номеру безопасен',
    'start_rate_limited': 'Слишком много новых попыток. Подожди минуту',
    'service_unavailable': 'Сервис был недоступен. Попытка отменена без изменения рейтинга',
    'season_changed': 'Сезон сменился. Незавершённая попытка отменена без изменения рейтинга',
    'first_move_not_started': 'Первый ход не сделан вовремя. Рейтинг не изменился',
    'attempt_expired': 'Время попытки истекло',
    'setup_expired': 'Время расстановки истекло',
    'turn_expired': 'Время хода истекло',
    'total_time_expired': 'Общий лимит времени истёк: ничья',
    'completed': 'Партия завершена по правилам игры',
    'quit': 'Игрок завершил попытку',
    'restart': 'Попытка завершена перед новой игрой',
    'not_found': 'Игра не найдена или недоступна',
    'game_unavailable': 'Новые игры временно недоступны',
    'first_action_must_open': 'Начни с открытия клетки',
    'invalid_action': 'Это действие сейчас недоступно',
    'body_too_large': 'Запрос слишком большой',
    'invalid_request': 'Некорректные параметры запроса',
}


def message(reason):
    return MESSAGES.get(reason, 'Не удалось выполнить действие. Обнови состояние игры')
REWARDS_ENABLED = False
REWARDS_REASON = 'Награды новых игр отключены до калибровки сезонов владельцем'


def catalog():
    common = dict(balance_status='Предварительные настройки; награды ещё не калиброваны',
                  contest={'sponsor':'ShedLink (разработчик расширения)', 'free_entry':True,
                           'not_sponsors':['Twitch','Apple'], 'eligibility':'Авторизованные зрители канала, которым правила платформы разрешают участие'},
                  rating={'initial': ELO_START, 'k': ELO_K, 'system': 'ELO'},
                  rewards={'enabled': REWARDS_ENABLED, 'reason': REWARDS_REASON,
                           'immediate_points': 0, 'seasonal_points': 0})
    return [
        dict(game_type='battleship', availability=dict(GAME_AVAILABILITY['battleship']), name='Морской бой', modes=['ranked'],
             difficulties=[], rules_version=battleship.RULES_VERSION,
             board={'rows': battleship.ROWS, 'cols': battleship.COLS}, fleet=list(battleship.FLEET),
             timers={'setup_seconds': SETUP_SECONDS, 'turn_seconds': TURN_SECONDS,
                     'total_seconds': TOTAL_SECONDS, 'grace_seconds': GRACE_SECONDS,
                     'queue_seconds': QUEUE_SECONDS},
             rules=['Бесплатная игра против другого зрителя, без ботов.',
                    'Корабли прямые, не пересекаются и не соприкасаются, в том числе углами.',
                    'Ходы чередуются после каждого выстрела, включая попадание.',
                    'До готовности обоих: истечение срока проигрывает неготовый, если второй готов; если никто не готов, матч отменён.',
                    'До готовности любого сдача отменяет матч; после готовности хотя бы одного сдача означает поражение.',
                    'Пропуск срока хода означает поражение, общий лимит — ничью. К срокам добавляется указанное время допуска.',
                    'Сбой сервиса отменяет матч без изменения рейтинга.',
                    'Закрытие панели и обновление страницы не сдают матч; таймер продолжает идти.'], **common),
        dict(game_type='minesweeper', availability=dict(GAME_AVAILABILITY['minesweeper']), name='Сапёр', modes=['ranked', 'practice'], rules_version=minesweeper.RULES_VERSION,
             board={'rows': minesweeper.ROWS, 'cols': minesweeper.COLS},
             difficulties=[{'id': key, 'label': ('Начальный' if key == 'beginner' else 'Продвинутый'),
                            'mine_count': tier['mine_count'], 'puzzle_rating': PUZZLE_RATINGS[key]}
                           for key, tier in minesweeper.TIERS.items()],
             timers={'attempt_seconds': ATTEMPT_SECONDS, 'first_move_wait_seconds': FIRST_MOVE_WAIT_SECONDS},
             rules=['Бесплатная логическая задача. Поле генерируется на сервере после первого открытия.',
                    'Первый ход и соседние клетки безопасны. Решаемость без угадывания проверена сервером.',
                    'Победа: открыты все безопасные клетки. Флаги можно ставить и снимать.',
                    'Рейтинговый результат считается против рейтинга сложности; скорость бонуса не даёт.',
                    'После первого хода сдача, перезапуск и истечение срока означают поражение.',
                    'Закрытие панели не сдаёт попытку; сбой сервиса отменяет её без изменения рейтинга.',
                    'Тренировка не меняет рейтинг.'], **common),
    ]
