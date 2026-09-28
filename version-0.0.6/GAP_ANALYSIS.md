# ShedLink 0.0.6: что есть, чего не хватает и в каком порядке делать

Дата: 28.09.2026. Область: текущие локальные исходники, архитектура и план миграции. Код механик в этой задаче не менялся.

## Вывод

Платформенный фундамент уже существует: Module API, адаптеры трёх игр, manifests, очередь действий, ACK/refund, защита повторов, game registry и общий frontend action helper. Следующая версия должна расширить эти части. Новый транспорт, новая очередь и полная перепись frontend не нужны для первого этапа.

Главного пока нет: работающий мод не описывает свои capabilities и нормализованное состояние так, чтобы один UI показывал две разные игры; нет общего исполняемого контракта доступности/результата и классификации экономики. Backend manifest сейчас преимущественно перечисляет события и команды. Это не capabilities персонажа.

**Уточнённый результат первой итерации 0.0.6:** предметы, культуры создания героя и законы Bannerlord поступают из реально запущенной игры с её модами. Добавление стандартной игровой сущности не требует изменения JS/Python-списков. Затем тот же контракт каталогов/компонентов проверяется на RimWorld и расширяется до identity/health/skills. Старый клиент 0.0.5 продолжает работать.

### Уточнение владельца: реальные данные игры важнее абстрактной универсальности

Поток: **игра с установленными модами → BannerLink извлекает действующие каталоги и состояние → backend проверяет, хранит проекцию → frontend показывает данные**. Недостаточно перенести список из JS в Python или YAML: тогда источником по-прежнему остаётся наша ручная копия.

Проверено 28.09.2026 в копии 0.0.6:

| Пример | Сейчас | Требуемое поведение |
|---|---|---|
| Предметы | `EquipmentShopBehavior.cs:259` перечисляет загруженные ItemObject. `:111–147` оставляет известные типы экипировки, торговые предметы и подходящих ездовых животных. `:160–173` формирует данные предмета | Каталог отображаемых сущностей отделить от допуска к покупке/надеванию. Новые предметы стандартных типов из модов отображаются по ID, игровому имени и свойствам без ручного добавления. Недоступность действия объясняется отдельно |
| Культура героя | `viewer-bannerlord.js:5128` содержит шесть культур; `routes/bannerlord.py:1900` дублирует allowlist | Список и названия из текущей игры. Мод сообщает, доступна ли культура именно для создания героя, включая наличие подходящего шаблона. Backend проверяет по каталогу текущей сессии, а не по шести литералам |
| Законы | `viewer-bannerlord.js:2356` содержит `_BNR_POLICIES` с ручными названиями и эффектами; `DiplomacyHandlers.cs:89` уже ищет реальный PolicyObject по ID | Полный актуальный каталог политик, игровые названия/описания и доступные через игровой API эффекты; отдельно принятые/ожидающие политики и возможность предложить конкретную. Не вычислять эффекты по старой таблице ванильной игры |

Создание героя содержит дополнительный gap: `AdoptHeroHandler.cs:108–143` при отсутствии шаблонов выбранной культуры переходит к случайной другой. Требование для нового контракта: не подменять явный выбор; сообщать недоступность/отказ. Случайный выбор остаётся отдельным явным запросом пользователя.

Каталогам нужны `catalog_id`, версия схемы, session/save scope, revision и сущности с устойчивыми ID. Пустой актуальный каталог должен отличаться от неполученного/устаревшего. Смена набора модов или сейва требует замены каталога, включая удаление исчезнувших записей. Для больших наборов — ограниченные страницы/пакеты. Изображения передаются через отдельный механизм ресурсов, не предполагается, что браузер может открыть игровую текстуру с диска стримера.

Граница обещания «любые моды»: новые экземпляры поддерживаемых игровых типов должны подхватываться автоматически. Совершенно новый тип/механика мода может требовать адаптации BannerLink. Для неизвестной сущности нужен безопасный базовый показ (имя/описание/доступные свойства), без выдуманных характеристик и без кнопок неподдерживаемых действий. Наличие сущности в каталоге не означает разрешение её купить или использовать.

Критерий готовности: добавить модовый предмет, культуру и закон → они появляются из игрового каталога без изменений frontend/backend-списков; удалить/сменить набор → старые записи исчезают из актуального каталога; невозможное действие возвращает причину из игры. Проверить не только fixtures, но и реальный модифицированный сейв.

## 1. База и границы проверки

- Источник: `C:/Users/Edward/Desktop/work/.claude/worktrees/codex-public-release`, HEAD `d4ef67e0aeb493f28a416e7c2ceb8f83b914a6a9` плюс рабочие изменения. Исторический `hopeful-agnesi-ea9afe/dist/audit` не использовался как текущий продукт.
- Копия: `C:/Users/Edward/Desktop/work/0.0.6`, самостоятельный локальный Git. Начальный коммит `8594242`; оригинальная история не импортирована, source HEAD и статус сохранены отдельно.
- 1 313 файлов / 94 893 433 байта проверены SHA-256. Полный перечень — `SNAPSHOT.json`. Это снимок исходников и выбранных release-артефактов, не копия установленной игры или production.
- Документация найдена через `scripts/docs-search.py`: `MODULE_API.md`, `ARCHITECTURE.md`, `ARCH_DATA_OWNERSHIP.md`, прежний `R0_GAP_ANALYSIS_2026-08-15.md`. Старые статусы не принимались за текущие без чтения кода.
- CodeGraph: `database is locked`. Использованы чтение файлов и текстовый поиск. Полный граф вызовов и исчерпывающий аудит всех обработчиков не заявляются.
- Minecraft представлен backend-модулем `shedcolony`; исходники его игрового коннектора не находятся в этой копии. Доказательство совместимости строим сначала на двух доступных C# коннекторах.
- Production, Twitch Console, OBS и живые игры не проверялись. Текущий статус review не переподтверждался. Сохранён локальный submitted-артефакт 0.0.5.

Все пути в таблицах ниже относительны корню 0.0.6; номера строк относятся к скопированным исходникам.

## 2. Матрица текущего состояния

| Область | Что реально есть | Чего не хватает | Доказательство |
|---|---|---|---|
| Подключение игр | ModuleManifest, ModuleEnvelope, ModuleAdapter, загрузчик и три backend adapter | Расширить существующий протокол, а не создавать второй | `Расширение/backend/modules/_base.py:28,57,80`; `_loader.py` |
| Capability discovery | hello отдаёт `accepted_capabilities` со списками backend events/actions | Мод сообщает фактическое подмножество возможностей, версии схем, ограничения текущей сессии; сервер согласует их | `_base.py:108–120`; `routes/module_api.py:121–124` |
| Подключение модов | Bannerlord шлёт session_start; RimLink использует legacy session-start | Обновить оба мода: один backend/frontend рефакторинг discovery не создаст | `BannerlordLink/src/BannerlordLinkModule.cs:194–201`; `RimLink/Source/API/RimLinkAPI.cs:123` |
| Состояние | Есть player.state_update и специфические snapshots | Общие EntityRef, schema version, units, revision, freshness, save/session scope; payload каждой capability | `modules/bannerlord/_adapter.py:1151–1200`; `modules/rimworld/_adapter.py:213–225`; `BannerlordLink/src/Util/HeroStateSync.cs:192` |
| Проверка payload | Фильтрация известных типов по manifest | Исполняемые схемы входящих capability/state/event/action/result. Комментарий про JSON Schema не является валидатором | `_base.py:143–145`; `routes/module_api.py:370–396` |
| Доставка действий | Общая durable очередь, scoped IDs, dispatched, ACK receipt, повторная доставка | Декларативный action descriptor и общий внешний статус результата | `database.py:4483–4505,4565–4583,4609–4661`; `main.py:2020–2056,2108` |
| Возвраты | Защита гонки TTL, резерв failed ACK, retry возврата; адаптеры возвращают очки | Общий settlement contract, связанный с конкретной валютой/операцией, вместо новой дублирующей кассы | `routes/module_api.py:578–593,662–671`; `modules/_base.py:173–197`; `modules/bannerlord/_adapter.py:770` |
| Повторы в игре | Durable outcome journals Bannerlord и RimLink | Условия восстановления после effect-before-journal crash, save rollback и неизвестного исхода | `BannerlordLink/src/Net/ActionPoller.cs:178,280,310`; `BannerlordLink/src/Net/ActionOutcomeStore.cs:60–89`; `RimLink/Source/Managers/CommandQueue.cs:231–246,274–294,307–340,374` |
| Источник игровой правды | MarryHandler проверяет возраст; игра списывает Hero.Gold, проверяет результат; защита порядка snapshots | Единая availability с reason, revision и временем; серверные игровые проверки постепенно перевести в проекции/предварительные отказы | `BannerlordLink/src/Actions/MarryHandler.cs:78,159–168`; `modules/bannerlord/_adapter.py:1158–1184`; `routes/bannerlord_family.py:203–225` |
| Frontend platform | Game registry, start/stop lifecycle, ShedLink.buyAction и single-flight | Registry компонентов/capabilities и нормализованная view model | `Расширение/frontend/viewer-registry.js:44–84`; `viewer-actions.js:97–135` |
| Общие действия в UI | Общий helper для ряда путей | RimWorld direct POST нужно мигрировать вместе с backend: заменить только кнопку недостаточно | `viewer-rimworld.js:262–265,292,332,358,385`; `pawn.js:512,574` |
| Игровые правила в UI | Bannerlord mapping attributes→skills, focus cap 5, attribute cap 10; RimWorld шкала skills /20 | Получать пределы, группы, прогресс, стоимость, статусы и действия из данных | `viewer-bannerlord.js:1109–1116,1158–1162,1193–1197`; `pawn.js:126–148` |
| Availability | Магазин экипировки получает can_manage/can_buy/pending/reason/message; builds — available/reason | Сделать формат общим, разделить наличие capability и доступность конкретного действия | `viewer-bannerlord-equipment.js:74–100,197–198,272`; `viewer-bannerlord-builds.js:49–50,82–87` |
| Экономика | Platform points и игровое золото уже разделяются; points ledger фиксирует движения | Currency registry, provenance, прямые связи ledger↔action, policy metadata и validator | `modules/_base.py:28–62`; `migrations/m118_points_ledger.py:47–87`; `routes/bannerlord.py:2549` |

Пути без префикса в backend-строках таблицы находятся в `Расширение/backend/`, frontend — в `Расширение/frontend/`.

## 3. Что нельзя ошибочно назвать отсутствующим

**Достижения уже есть.** Платформенный UI (`viewer.js:1492,1543`) и Bannerlord UI (`viewer-bannerlord.js:4440–4484`) используют разные поля. Backend Bannerlord хранит счётчики и unlock (`routes/bannerlord_achievements.py:98,153,211`). Задача — общий AchievementCard, scope/source/id и адаптация двух систем. Общий игровой achievement engine ещё требует контракта событий и дедупликации.

**Статистика есть частично.** UI показывает totals просмотра/чата и боевые показатели Bannerlord (`viewer.js:1500–1509`, `viewer-bannerlord.js:3381–3432`). Это не доказывает универсальный lifetime-statistics service. Для него нужно решить, что переживает смерть героя, смену сейва, сезон и reset канала.

**Семья, наследники и вассалы уже отображаются** (`viewer-bannerlord.js:1830,2839,2875`). Их надо адаптировать к related_entities/relationships. Наличие этих сущностей не означает готовую глубину companions или универсальные organizations.

**Prestige/legacy не найден как общий контракт** в проверенных frontend/Module API путях. Не считать пользовательскую платформенную прогрессию доказательством игрового prestige. Его правила и жизненный цикл должны быть определены отдельно.

**Bits не являются готовой оплатой.** В `routes/pets.py:9–10,27–28` явно описан loyalty-only путь; фактическое списание — points, а legacy `bits_amount/mode` хранит крустики (`database.py:2031,2080–2087`). Имена старых колонок не доказывают активную Bits-интеграцию. Отдельный EventSub cheer тоже не является чеком покупки Extension.

## 4. Поправки к предложенному плану

1. **Контракт действий проектировать одновременно с контрактом возможностей и состояния.** Skills без action descriptors, availability и result снова породит специальный JS. Реализацию переносить постепенно, общий дизайн нужен в начале.
2. **Compliance metadata определить на этом же этапе.** Полный Bits payment слой можно отложить. В 0.0.6 достаточно строгих типов, классификатора и запрета неподдерживаемых комбинаций; активные Bits-продукты не входят в первый срез.
3. **Capabilities мода не являются разрешением на коммерцию.** Сервер сопоставляет advertised capabilities с разрешённым manifest, поддерживаемыми версиями и политиками канала. Не доверяет переданным клиентом price, actor, channel или флагу «разрешено».
4. **Game-as-source-of-truth сохраняет backend-проекции.** Backend авторитетен для identity binding, tenant, допуска, очков и policy; игра — для игрового состояния и окончательного игрового исхода. Предварительная доступность не гарантирует успех спустя задержку.
5. **Generic UI не означает присылаемые HTML/JS.** Игра передаёт типизированные данные и безопасные ссылки на заранее зарегистрированные компоненты. Renderer включён в submitted frontend. Карта Кальрадии/hediffs могут оставаться специальными.
6. **Не смешивать delivery, execution и settlement в один status.** «Refunded» описывает расчёт, «rejected» — игровой отказ, «dispatched» — доставку. Внешняя модель должна показывать их согласованно, но не терять разные оси.

## 5. Минимальный контракт v1 — проект, ещё не реализация

| Сущность | Обязательная семантика |
|---|---|
| GameSession | channel из авторизации; module_id; connector_version; protocol_version; session_id; world/save epoch; heartbeat/expiry |
| CapabilityDescriptor | namespaced capability_id, schema_version, supported component kinds, snapshot mode, supported action types; enabled/disabled/unknown и причина |
| EntityRef | устойчивый entity_id + kind + game/session/world scope; owner viewer ID отдельно от display name |
| State | entity_ref; capability_id/schema_version; monotonic revision внутри epoch; observed_at; полный snapshot или delta; явное null/unknown; единицы и диапазоны |
| ActionDefinition | action_type, capability, parameter schema, допустимые target kinds, presentation, policy classification, currency/cost authority |
| ActionAvailability | available, reason_code, message_key/fallback text, reason_params, revision, checked_at, expires_at, cooldown_until |
| ActionRequest | client_request_id/idempotency key, action_type, target, parameters, expected revision/quote; actor и channel выводятся сервером |
| ActionRecord | server action_id, session/world binding, validated cost/quote, policy revision, correlation, delivery status, execution status, settlement status |
| ActionResult | action_id, applied/rejected/partial/unknown, reason, observed effect/amount, resulting revision, retryability; без успешного исхода по умолчанию |
| GameEvent | unique event_id, type/schema_version, source session/world, sequence, time, entity refs, typed data; повтор не выдаёт вторую награду |

Не путать action_type (`character.train_skill`) с action_id (экземпляр запроса). Переименование всех старых команд не является условием запуска: адаптер может сопоставлять новые definitions существующим именам.

Для результата полезны три независимые оси: `delivery = queued/dispatched/acknowledged/expired`, `execution = pending/applied/rejected/partial/unknown`, `settlement = not_required/reserved/charged/refund_pending/refunded/manual_review`. Это проект модели, а не список новых значений, которые можно без миграции записать в существующую SQL-колонку.

При потере ACK после игрового эффекта нельзя автоматически возвращать деньги и повторять действие. Durable journal уменьшает окно неопределённости, но не образует транзакцию с сохранением мира. Контракт обязан предусматривать reconciliation/unknown, особенно при откате сейва.

## 6. Экономика и Twitch

### Технические пробелы

- Registry валют: WATCH_POINTS, GAME_GOLD, GAME_RESOURCE, NON_TRANSFERABLE_REWARD; BITS — отдельный settlement rail, не произвольный игровой баланс. WATCH_POINTS здесь обозначает внутренние очки ShedLink, не Twitch Channel Points.
- Возможность transfer/trade/random reward/convert задаётся серверной политикой; неизвестные типы и переходы запрещены по умолчанию. Реестр не означает, что все перечисленные операции разрешаются.
- Нужны происхождение ценности, scope владельца/канала/сейва, назначение награды и разрешённые преобразования. Один `currency_type` не описывает всю цепочку.
- Текущий points ledger фиксирует delta/before/after, но сам не знает причин и action ID (`m118_points_ledger.py:27–31,47–56`). Нужна прямая корреляция операции, цены, резервирования и возврата.
- У проекта уже есть пути получения игрового золота за крустики (`routes/bannerlord.py`, pricing `player.give_item` и GIVE_GOLD_PRESETS). Их требуется инвентаризировать и оформить явной политикой; нельзя писать, будто конвертаций сейчас совсем нет. Старые константы обратной конвертации в файлах не доказывают активное начисление.
- `routes/misc.py:113–123` хранит историю удаления transfer/donate. Это решение прежней версии; оно само по себе не доказывает всеобщий запрет Twitch на любой подарок предмета.
- UGC — не только boolean: тип контента, автор, публикация, модерация и удаление. Существующие имена персонажей/питомцев тоже должны попадать в инвентаризацию.

### Проверенные внешние положения

Проверка официальных страниц: 28.09.2026. Политики — ограничения проектирования, а не подтверждение одобрения конкретной механики.

Twitch §5.2 допускает обмен Items за loyalty points или Bits при соблюдении других правил; отсюда не следует ни полный запрет P2P, ни автоматическое разрешение marketplace. §6.2.4/6.2.6 запрещают случайные неизвестные loot boxes и wagering за Bits. §6.2.8 ограничивает произвольно определяемые пользователем/стримером Bits-продукты. §6.1.3 относится к free-to-play: его нельзя автоматически распространить на платные игры. §2.7–2.8 требует обработки динамических данных и включения frontend-кода в ZIP. Для UGC действуют требования §7 к идентификации, атрибуции и модерации/удалению. [Extensions Guidelines & Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/).

Для монетизированного Extension проверка `isBitsEnabled` обязательна; при false Bits-функции скрывают/отключают. Нужны каталог продуктов и проверяемая обработка транзакций. [Monetization Guide](https://dev.twitch.tv/docs/extensions/monetization/).

**Решение для 0.0.6:** подготовить metadata/policy boundary, не включать Bits и marketplace в первую итерацию. Разрешённость конкретной экономики оценивать по всей цепочке «источник → оплата → случайность → награда → передача», а не по одному зелёному boolean.

## 7. Порядок работ и критерии готовности

| Этап | Работа | Проверяемый выход |
|---|---|---|
| 0 — выполнен | Отдельная копия, immutable baseline 0.0.5, аудит | SHA manifest; старый ZIP совпадает; исходное дерево не изменено этой задачей |
| 1 | ADR и исполняемые schemas для GameSession/Catalog/Entity/Capability/State/Action/Event/Result + economy metadata | Fixtures каталогов предметов/культур/законов, включая модовые ID; ошибочные types/versions/tenant/price отклоняются; описано владение полями |
| 2 | Действующие игровые каталоги и discovery BannerLink, negotiation по сессии, compatibility adapter | Предметы, культуры и законы приходят из игры; смена сейва/модов заменяет каталог; неизвестная версия не включает действие |
| 3 | UI каталогов без ручных списков; затем второй игровой адаптер и identity/health/skills | Модовые сущности показываются без изменения списков JS/Python; те же стандартные блоки принимают данные RimWorld; unknown/stale показаны честно |
| 4 | По одному существующему действию на игру: общий descriptor/availability/request/result | Полный сценарий accepted→applied и refused→refund, duplicate click/ACK, timeout, session switch; неизменная совместимость 0.0.5 |
| 5 | Расширение inventory/equipment/actions, затем related_entities и achievements | Старые данные мигрируются/адаптируются без второго источника истины; список переведённых действий поимённый |
| 6 | BLT GAP audit, clean-room карта механик | Каждая механика: capability, текущая реализация, gap, generic/custom UI, экономика, Twitch, source/license и критерий live-проверки |
| 7 | Новая глубина по результатам аудита | Stats/achievements/legacy/companions/orders только после доказанного контракта; феоды/организации позже, торговля отдельно |

Кандидаты для первого action-среза — существующее лечение или тренировка. Выбирать после сопоставления реальных ограничений обеих игр; это не обещание универсальной формулы здоровья. Не включать новую платную механику ради проверки архитектуры.

Большую часть цели 0.0.6 составляет миграция. Фиксировать «80/20» как процент готовности не нужно: общий компонент выбирается там, где он сохраняет смысл данных.

## 8. Обязательные сценарии проверки нового контракта

- Два канала с одинаковыми именами сущностей; запрос чужого actor/channel/target отклоняется.
- Старый frontend 0.0.5 и новый 0.0.6 работают с одним backend; новые поля не ломают старые ответы.
- Нет capability; неизвестный type/schema; старый мод; пустое значение против неизвестного; capability временно недоступна.
- Смена игры/мира/сейва во время запроса; старый snapshot/result не обновляет новую сущность.
- Приходит delta раньше snapshot, повтор event, revision назад, потеря sequence; есть запрос полного восстановления.
- Цена подменена или изменилась, cooldown устарел, действие стало недоступно после показа. Backend и игра повторяют свои проверки.
- Duplicate click, потеря ответа enqueue, повтор доставки/ACK, поздний отказ, refund retry, restart, effect-before-journal. Не обещать exactly-once без игрового доказательства.
- Unknown reason выводится безопасно; данные мода не становятся HTML/JS; длинные списки ограничены/пагинируются.
- Один и тот же набор fixtures проходит desktop/mobile; затем Hosted Test и реальные игровые сценарии отдельно.

Не создавать тесты, которые только ищут слово capability в исходнике: сценарии должны исполнять валидаторы, UI и action lifecycle.

## 9. Что проверено в этой задаче

| Проверка | Результат |
|---|---|
| SHA-256 копии | Все 1 313 файлов совпали при создании; источник не изменился во время копирования |
| `python scripts/verify-candidate.py --version 0.0.5` | exit 0; ZIP 266 722 байта; 27 frontend-файлов совпадают |
| `python tests/test_frozen_client_0_0_5.py` | exit 0; проверка старого клиента и отрицательные контроли |
| `python tests/test_module_action_races.py` | exit 0; TTL/delivery/ACK/refund races |
| `python tests/test_module_delivery_gaps.py` | exit 0; лог `checks/delivery.log` |
| `python tests/test_frontend_module_lifecycle.py` | exit 0; лог `checks/lifecycle.log` |
| `python tests/test_points_ledger.py` | exit 0; лог `checks/ledger.log` |
| `python scripts/lint_consistency.py` | Первый прогон копии exit 1: новая Git-история сделала дату RUNBOOK старой. В исходном дереве exit 0. В копии добавлена явная запись о переносе; финальный результат — `checks/lint-final.log` |

Хеш frozen ZIP: `6f8e07f56b7d6a0b4f628a2731d81686a47b77dd8b7cfcc912dd1f8af3f90672`.

Обнаружен дрейф старой справки: скопированный `dist/shedlink-0.0.5.verification.json`
называет другой архив (`35d0d95d…`, 266 734 байта, 28 файлов). Он сохранён как
часть исходного состояния, но не является доказательством текущего кандидата.
Актуальные измерения ZIP и `verify-candidate.py` выше имеют приоритет.

Линтер также сообщает пропуск чтения policy IDs из недоступной игровой сборки. Эти проверки подтверждают локальный baseline и отдельные гарантии существующей системы. Они не доказывают ещё не реализованный контракт 0.0.6, безопасность всех endpoints, работу в живой игре или одобрение Twitch.

## 10. Что отложено и почему

- BLT feature audit: после первого общего среза двух игр; в этой задаче не проводился аудит BLT source. Сохраняется clean-room подход, копирование чужих классов не планируется.
- Marketplace/auctions/gifting: до provenance, currency policy и отдельного разбора конкретной модели обмена.
- Bits payments: до product/entitlement design, проверки транзакций и UX при недоступных Bits.
- Prestige/legacy: до решения о scope прогресса и save/reset semantics.
- Общие organizations/owned_entities/upgrades: после базовых entities и переноса существующих семейных/вассальных данных.
- Полная миграция RimWorld: идти по маршрутам; `RimLinkAPI.cs:189–223,266–278,315–357` показывает coexistence generic actions/ACK и legacy state/catalog.
- Minecraft live discovery: нужен доступ к отдельному исходному проекту connector; backend manifest недостаточен для утверждения готовности.

Следующая задача для реализации: **контракт игровых каталогов и срез предметы/культуры/законы Bannerlord в этой папке, с сохранением совместимости 0.0.5; затем проверка универсальности на RimWorld**. Это конкретная отправная точка, а не разрешение одновременно реализовать весь roadmap.
