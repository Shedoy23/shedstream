# Покрытие полного переноса Preact — актуальная таблица

База: `feature/panel-preact-dev` @ `b2064f4b045025d33d05aaf166ca1694ae0f5475`. Локальная ветка: `feature/panel-preact-full`. Публикация запрещена и не выполнялась. Файлы `full-port-inventory-*.md` фиксируют инвентаризацию на базе; актуальный статус находится здесь. Исторические этапы ниже сохранены; итоговые коды возврата и ограничения перечисляются в финальном отчёте.

| Раздел | Состояние переноса | Parity / проверки | Мутация | Браузер 1280 / 375 |
|---|---|---|---|---|
| Унаследованные Bannerlord развитие/снаряжение/бой/свита/клан/королевство/кузница | Сохранены, общий host подключён | Унаследованный suite + whole-shell bootstrap/минутные сценарии | Унаследованные + 7 новых red1→green0, включая raw JSON field order | Снимки есть; не означает проверки каждого действия |
| Прокачка после progression merge | Фокус/атрибуты/XP используют игровые предложения и context; нет старых тарифов и пределов 5/10 | 7 новых + матрица 24 кнопок, полный raw JSON; общий повторный срез Bannerlord 306/306 (11 файлов), exit 0 | wrong-game-gold-quote red1→green0 | Подтверждение 1280/375, локальный Chromium exit 0 |
| Законы из игрового каталога | Статический список удалён; custom IDs/описания, отсутствие данных, отмена устаревшего подтверждения | 3 новых + прежняя матрица с явным синтетическим серверным каталогом; включены в 306/306 | wrong-game-policy-id red1→green0 | policy-confirm 1280/375 |
| Создание/возрождение героя | Культуры и context из игры, случайный выбор, пустой/недоступный каталог, настоящее предупреждение о новом герое | 9/9, полные raw JSON и хвосты; ответы 16 реальных обработчиков временной БД; typecheck/build/gates exit 0 | wrong-created-culture red1→green0 | hero-create/hero-respawn 1280/375 |
| Настоящий турнир Bannerlord | Перенесён | 11 тестов, настоящий legacy VM и полный трафик выбранного host | 3 red→green | Да |
| Streamer config | Перенесён | 6 тестов, оригинальный config.js | 1 red→green | Да |
| Кейсы | Перенесён | 6 выбранных + 2 whole-shell minute: один/все, отказ, таймеры, scope/native fetch | 1 red→green | Да |
| Питомцы | Перенесены действия, stage/layers, яйцо/аура/breathing и reduced motion | 8 выбранных тестов + whole-shell purchase minute, +1 consent click; rename/equip/unequip/purchase и защита цены | 1 red→green | Да |
| ShedColony | 33 действия перенесены; slow polling, policy refusal и pending/unknown после remount исправлены | 36 parity + 15 review + 10 настоящих shell/remount тестов; игровые fixtures ручные, policy captures реальный ASGI; действия перечислены независимо из старого исходника; полный выбранный host за 30с + whole-shell 5мин/JWT/paid heal | wrong-colony-skill + review-colony-slow-poll / review-colony-policy / review-colony-jwt-owner red→green | Да, вкладки, выбранный навык после poll, held resolver и unknown после JWT на1280/375 |
| Общая оболочка: core config, resolver, presence, activity, attendance, perks, notices/refunds, chat | Реализована и подключена | Настоящий полный DOMContentLoaded + Twitch onAuthorized старой панели; 5 минут полного трафика на канале без активной игры. Hidden, refresh JWT, refund, chat, auth recovery | wrong-notice-ack-id red1→green0 | Да, включая возврат |
| Realtime | Реализован scoped bus | Dedupe и смена private subscription; интеграция подписчиков голосования/общих игр проверена | Вместе с оболочкой | Helper fixture; настоящий Twitch не проверен |
| Статистика/achievements/streak | Перенесены | Полные три GET no-store, refresh, минута на активной вкладке, attendance reward на закрытой | cached-streak-read red1→green0 | Да |
| Active module и полный игровой host | Lazy маршрутизация Bannerlord/RimWorld/ShedColony, collapse/restore | Полный boot каждой игры, JWT/hidden/module off, общий баланс, порядок Dynasty, hero replacement и collapse/restore; 21/21 game-host + 4/4 shell-controls tests | wrong-dynasty-read-order / stale-host-balance red1→green0 | Все три игры, shell-collapsed 1280/375 |
| Ежедневная награда Bannerlord | Перенесена, суммы только из daily-status | 4 теста: gold/xp/refusal/status, raw POST и немедленный +1500ms хвост | wrong-daily-reward red1→green0 | daily-1280/375.png |
| Пол героя | Перенесён, цена /config, подтверждение/отказ | male/female raw parity, generic tails, missing-price guard | wrong-hero-gender red1→green0 | gender-confirm-1280/375 |
| Личный брак/развод/зачатие/семейное дерево | Перенесены, полные данные родителей/супруга/детей | 9 profile-тестов вместе с полом; супруг/цена/context fenced. Лимит детей не опубликован API, отличающийся сценарий старого cap явно покрыт | wrong-family-action red1→green0 | hero-family/marry/divorce/make-baby 1280/375 |
| Мастерские | Перенесены: список/покупка/продажа, game workshop_types | Raw parity подтверждённых действий и хвостов; модовый тип отдельно, старый UI его не предлагает | wrong-workshop-type red1→green0 | properties/ws-buy/ws-sell 1280/375 |
| Караваны | Перенесены: список/покупка/продажа, общий кэш городов 60s | Raw parity и 1500/2000/3500ms хвосты, в том числе отказ | wrong-caravan-town red1→green0 | properties/caravan-buy/caravan-sell 1280/375 |
| Владения | Перенесён просмотр реальных владений и дохода; удалённый boost не продаётся | Полный выбранный host, GET без выдуманных параметров | wrong-fief-income red1→green0 | properties-1280/375.png |
| Наследие | Перенесён журнал, группировка по датам и суммы | Exact inheritance-log?limit=15 | wrong-inheritance-limit red1→green0 | properties-1280/375.png |
| Взрослые дети, предложения брака и наследники | Перенесены rename/looks/respec/propose/respond/cancel, входящие/исходящие, автоматические наследники | 12 проверок, raw parity и хвосты; цена предложения из config, отдельный тест отличия от старого literal100 | wrong-renamed-child / wrong-heir-name red1→green0 | children-heirs/child-rename/child-propose 1280/375 |
| Магазин Bannerlord/status | Динары, персональный XP, необязательный серверный каталог; цены и статус API | 15 commerce тестов; с соседними35/35; полный выбранный host raw traffic | wrong-gold-offer / wrong-connection-status red1→green0 | shop-gold/xp/catalog-confirm 1280/375 |
| Карточка героя/старое снаряжение | Наблюдаемые детали, upgrade/reequip, вещи и discard с именем/guard | Exact payloads, отказ, все1200/3500ms хвосты, замена слота | wrong-legacy-gear-action / wrong-observed-armor / wrong-discard-slot red1→green0 | hero-summary/legacy-upgrade/reequip/discard-confirm 1280/375 |
| Вассальные кланы | Список, наследники, создание и переименование; формы переживают опрос | 11 тестов вместе с выкупом; точные запросы и все хвосты, отказ и отсутствие цен | wrong-vassal-heir red1→green0 | vassals-ransom/vassal-create/rename-confirm 1280/375 |
| Выкуп пленных | Данные плена, сбор и взнос с подтверждением; смена пленителя отменяет запрос | Raw parity принятия/отказа +1200/+3500ms, без обещания мгновенного освобождения | wrong-ransom-viewer red1→green0 | ransom-confirm 1280/375 |
| Улучшения клана | Lazy каталог, bulk выбор/покупка, pending из игры, подтверждение | 9 тестов вместе с достижениями; exact POST и немедленные catalog/hero хвосты; cap11 — явное исключение с серверным отказом | wrong-clan-upgrade-id red1→green0 | clan-upgrades/confirm 1280/375 |
| Достижения Bannerlord | Lazy каталог, текущие значения/порог/открытие от API | Точное чтение и отказ, прогресс37/100 из реального счётчика | wrong-hero-achievement-progress red1→green0 | hero-achievements 1280/375 |
| Профиль/квесты/промо/TTS/обратная связь | Перенесены | Полный shell parity: реальные тела/хвосты, debounce, цена/отказ/отмена; TTS подтверждение добавляет один реальный activity click (причина и тест в коммите) | 1 red→green | Да |
| Гильдии | Перенесены | 9 тестов полного shell: просмотр, создание, вклад, навыки, вступление, выход, роспуск, отказы | 1 red→green | Да |
| Голосование | Перенесено | 9 тестов полного shell: ставка, предложение, polls, realtime, смена раунда, окончание, отмена и клавиатура | 1 red→green | Да |
| Дуэли/RPS, TTT, tug | Реальные очереди, раунды, рейтинги, ходы/тапы, закрытие, TTT realtime | 23 теста, с shell38/38; весь трафик минуты, JWT refresh, отказ, исход/хвосты | wrong-rps-move / wrong-ttt-cell / wrong-tug-batch red1→green0 | queued/match/finished каждого,1280/375 |
| RimWorld viewer/pawn/shop/implants/traits/genes/passions/neuro/xenotypes/events | Все действия перенесены; текущий ксенотип не публикуется API | 32 теста +shell15=47/47; настоящий полный boot, 5мин polls/JWT/tab, все raw POST/хвосты и явные дополнительные клики подтверждения | 7 red1→green0 с восстановлением SHA | Все действия1280/375; финальный прогон184 снимка,0 errors/external |
| Социальная семья | Просмотр, предложение, отклонение, развод; принятие заблокировано серверным дефектом bob→carol | 7/7 полного shell, сырые JSON/минутные хвосты | wrong-social-proposer red1→green0 | заявки/предложение/развод1280/375; финальный прогон184 снимка |

## Изменение базы по прямой инструкции владельца

После среза `f560cf967537674e03f0051cd383d5abd1667903` владелец разрешил merge свежей `origin/feature/game-progression` (не rebase). До merge сохранены исходники и доказательства: 48 снимков, browser errors=0/externalRequests=0, 12 результативных red→green мутаций. Импорт существующих backend/mod/legacy изменений разрешён, самостоятельные правки этих областей и публикация запрещены. После merge прежние parity результаты считаются историческими до повторного сравнения с новым эталоном. Каталоговые блокеры снимаются только после fixture/DOM/browser проверок.

Merge выполнен: `e66e82098f894bc8f6e0dbe9598ddf2516088636`, импортирован `1682ebf4823a548162e1687a47a60d4292c3c7f7`. Проверка legacy gates после согласования их фикстур: 18/18, exit 0. Каталоги культур и мастерских доступны в контракте; соответствующие UI закрыты последующими срезами (таблица выше). Подробности — `PANEL_FULL_PORT_MERGE_2026-10-03.md`.

В progression parity обе стороны получают native `Response`. Сценарий «герой ответил раньше подтверждения действия» явно задаёт сетевую очередь ответа в fixture; быстрый ответ действия отдельно покрыт новыми тестами. Это устраняет искусственную гонку разной глубины Promise, не фильтрует запросы и не изменяет старый исходник. Нормализация сохраняет сырые JSON-байты; меняет лишь случайные ID и заранее принятое поле кузницы. Новые подтверждения прокачки/закона сохраняют действие и все хвосты, но добавляют пользовательский клик; это осознанное выполнение требования подтверждать платные действия. Полная минутная activity-проверка этих дополнительных кликов пройдена в panel-game-bootstrap-parity.

Полный прогон после progression: 1041 passed, 9 failed, 2 skipped, exit 1 — это промежуточный результат, не финальный зелёный suite. Исправлены старые селекторы/ожидания подтверждений и неблокирующий запуск дочерних загрузчиков героя. Повторные 9 файлов дали 351/352, затем единственный оставшийся файл 32/32 (exit 0). Backend validator пройден с явным `PANEL_BACKEND_PYTHON` в разрешённом запуске; первый `spawnSync python EPERM` был ограничением пути/запуска, не прохождением проверки.

Отдельное точное исключение порядка в выбранном Dynasty-host: первый независимый GET content-catalogs от уже ответившего kingdom-state может идти сразу после GET stats, тогда как старый VM-стенд завершает его перед stats. У нового героя нет зависимости от завершения запроса kingdom-state, который может зависнуть; исходный вариант ожидания выявлен тестом `fresh observed state remains quarantined while replacement hero waits for agreeing state`. Сравнение допускает только перестановку этих двух соседних стартовых GET, сохраняет все строки/headers/cache/raw bodies/последующие polls. Это явно отличается от полного игрового boot, который позднее проверен отдельно в whole-shell bootstrap; другие перестановки не разрешены.

Мутации `wrong-game-gold-quote` и `wrong-game-policy-id`: red exit 1 → green exit 0, восстановление SHA-256 подтверждено. Нормальные локальные браузерные клики progression завершены без ошибок/внешних запросов; для закона и жизненного цикла добавлены отдельные сценарии.

## Узкие блокеры первоначальной базы (исторически, до разрешённого merge)

- Только выбор культуры при создании героя: база b206 не предоставляет динамический каталог. В более новой progression `cd125a5` уже есть `/api/bannerlord/content-catalogs` с cultures и связанная ingestion/storage/validation цепочка. Это несовпадение баз, не отсутствие реализации вообще. Самовольный перенос backend/mod запрещён. Случайное создание героя этим не блокируется.
- Только покупка мастерской с выбором типа: нет каталога типов мастерских из игры даже в проверенной progression. Список городов и принадлежащие мастерские доступны; просмотр/продажа этим не блокируются.

## Зафиксированные отличия и дефекты

- Новый UI показывает весь подтверждаемый batch notices сразу: старый ack выполнялся до 2-го/3-го отложенного тоста, которые терялись при закрытии. Wire сохранён, тест refund parity зелёный; причина в коммите.
- Новый realtime снимает старую private подписку при смене viewer/channel и отбрасывает старые callbacks. Старый `_ready` навсегда игнорировал повторный init. Тест проверяет изоляцию; payload — только подсказка, не источник финансовой истины.
- Legacy `online.channel_id` фактически содержит extension clientId. Сохранено byte parity; канал авторизуется серверным JWT.
- Старый frontend вычисляет следующую награду streak собственной формулой. Новый показывает только возвращённую сервером награду и текущий/максимальный streak.
- Pet unequip передаёт только slot: атомарный expected_item_id отсутствует в API. UI проверяет наблюдаемый предмет локально, но серверную гонку между проверкой и исполнением устранить без серверной правки нельзя.
- Legacy `_bnrConfirm` всегда возвращает `Promise.resolve(true)`: предупреждение перед возрождением фактически не отображается. Новый UI показывает его и не отправляет POST при отмене; тест отдельно воспроизводит старый немедленный POST. Старый исходник не исправлялся.
- При первой браузерной проверке найден и исправлен вызов native fetch с чужим receiver. Гипотеза о dispose из Suspense не подтвердилась; регрессионный тест проверяет фактическую причину.

Финальные размеры, suite, список непроверенного и реквизиты пакета находятся в итоговом отчёте. Production, настоящая игра, Twitch Hosted Test и физический телефон не использовались. Локальный gzip не доказывает Twitch timing.

## Review промежуточного f00c7f0

Три runtime-дефекта подтверждены red и исправлены в 2091d24 (RimWorld JWT busy,
Colony slow polling, строгие pre-action 403/429); детали и доказательства:
docs/PANEL_FULL_PORT_REVIEW_FIXES_2026-10-03.md. Voting unknown outcome оставлен
явным унаследованным ограничением: повторный взнос может списать деньги второй раз.
Обычные Colony игровые fixtures созданы вручную; реальные ASGI captures здесь
доказывают только policy/auth отказы. XSS-аудит был остановлен ограничениями среды,
не владельцем. Артефакты f00c7f0 промежуточные; публикация не разрешена.
## Второй review: Colony и remount оболочки

Checkpoint e5ab10e/Library report v1 промежуточный. При JWT-resolving ViewerShell
размонтировал ColonyView, который терял pending/unknown guard. Red f264ac2:
8 failed/2 passed; fix6a048385b144199b56772eb8d0ac444baf741d49: состояние действия
хранится в ColonyController по shedcolony/channel/login. Затронутые86/86,exit0.
Смена identity/channel/game не переносит guard на другого владельца и не стирает
его при возврате; поздний исход сохраняется для исходного owner. Определённые
429/успех и raw traffic сохранены. Это не серверная идемпотентность и не защита
после полного reload. Подробности: docs/PANEL_COLONY_REMOUNT_REVIEW_2026-10-03.md.
Большой пакет и report v1 до повторного review не заменяются. Публикации нет.

## Финал после независимого re-review

Родитель подтвердил закрытие Colony-remount замечания и отсутствие новых найденных
runtime-дефектов6a048385 относительно e5. Reviewer читал код/evidence, собственные
прогоны не делал. Общий checkpoint23aca6b: suite1251 passed/2 skipped,57 мутаций,
browser188 снимков; два HTTP-теста повторены2/2 на том же runtime. Последующие
коммиты меняют только документацию/evidence. Финальный экспорт целостный, большой
e5 ZIP не используется как новая поставка. Полный reload, транспортные повторы,
идемпотентность, social marriage accept, Voting и DTO-ограничения остаются явными.
XSS-аудит остановлен ограничениями среды/инструментов, не пользователем.
Push/PR/deploy/Twitch submission не выполнялись и не разрешены.
