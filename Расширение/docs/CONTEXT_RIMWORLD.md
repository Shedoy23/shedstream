# RimWorld Module — Context (chat handoff)

**Назначение:** для чата по RimWorld-модулю (legacy + Module API rework).
Общее — см. `CONTEXT.md`. Bannerlord — `CONTEXT_BANNERLORD.md`.

**Last updated:** 2026-09-12 (подсказка каталога описывает протезы —
багрепорт #50; DLL пересобрана, в игре НЕ проверена)

**Подсказки каталога (12.09).** Каталог намеренно пускает в магазин протезы:
фильтр имплантов принимает рецепт, если `addsHediff.addedPartProps != null`
(бионические рука, нога, глаз). А подсказка строилась только из
`stage.statOffsets / statFactors / capMods` — у протеза они пусты, потому что
его выгода выражена эффективностью добавленной части тела. Зритель видел
карточку без единой строки «✦», хотя у соседнего импланта они были: это и
есть багрепорт #50 («не у всех отображает бонусы к параметрам», kuro_gothic,
09.09). Теперь `TooltipImplant` читает `addedPartProps.partEfficiency` и
`solid`. Собрано без предупреждений; **в игре не проверено** — для проверки
нужен запуск RimWorld с новой DLL, каталог заливается при загрузке
сохранения. Багрепорт держать открытым до подтверждения.

## TL;DR

**Первый** gaming-модуль платформы. **Legacy** code из эпохи single-tenant
(до multi-tenant refactor). Большая часть прошла через Phase 1-7
compliance rework. Команды и ACK уже идут по **Module API** generic pattern
(как Bannerlord); каталоги и состояние пешек пока остаются на legacy routes.

## 2026-09-05 — у мода свой файл лога, Player.log больше не единственный

**Что было.** RimLink писал только через `Verse.Log`, то есть в `Player.log`.
Движок выключает этот файл после `Reached max messages limit. Stopping logging
to avoid spam`, и мод замолкает вместе с ним. 05.09 лимит выбрал чужой
`AutoPriorities` (4144 исключения за сессию): в логе осталось 298 команд из 630,
вторая половина эфира по игровой стороне стала непроверяемой.

**Что стало.** `RimLink/Source/RimLinkLog.cs` пишет в
`AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\ModLogs\rimlink_ГГГГММДД.txt`
напрямую через `File.AppendAllText`; счётчик движка на это не влияет. Все 165
вызовов `Log.Message/Warning/Error` в моде переведены на `RimLinkLog.Msg/Warn/Err`.
Порядок внутри намеренный: **сначала файл, потом `Verse.Log`** — движок вправе
отказать, строка к этому моменту уже записана. Дублирование в `Verse.Log`
сохранено, чтобы сообщения по-прежнему были видны в игре.

**Чем держится.** `RimLink/tests/LogFileHarness` (в CI рядом с `PausedSyncHarness`):
стаб движка отказывает, а харнес требует, чтобы строка всё равно оказалась в
файле. Видел красным — при перестановке `Verse.Log` вперёд падает с
«В файле 2 строк вместо 3».

**Где читать в триаже.** Теперь `rimlink_ГГГГММДД.txt`; `Player.log` остаётся
нужен только ради чужих модов и стектрейсов движка.

## 2026-07-29 — трек C прогнан. И сначала выяснилось, что прогнать его было НЕЧЕМ

**Главное, что стоит унести из этого раздела.** В реестре аудита было записано,
что RimWorld проверяется `scripts/fake-mod.py` — «единственный способ доказать,
что модуль работает, без запуска игры». **Это было неправдой, и заметить её
можно было только попробовав.**

`fake-mod.py` разговаривает **только по Module API** (`/v1/module/<игра>/hello`,
`/events`, `/actions`, `/ack` — пути зашиты). А платные ручки RimWorld кладут
команду в **другую очередь** — таблицу `rimworld_pending_commands`
(`rimworld.py::_charge_and_enqueue`), которую мод забирает через
`GET /api/rimworld/commands` и подтверждает через `POST /api/rimworld/ack-command`.
Моста между ними нет: адаптер прямо объявляет `dispatch_action остаётся stub'ом
до Step 3` (`modules/rimworld/_adapter.py:13`).

Практический итог: запуск fake-mod в режиме опроса увидел бы `hello` и события —
и **ни одной платной покупки**. Отчёт «трек C прогнан» был бы ложным, причём
выглядел бы совершенно нормально. Это тот же класс, что «механика жива, потому
что код есть»: инструмент назвали рабочим, не проверив, куда он смотрит.

**Что сделано:** `fake-mod.py` научен второй очереди — флаг `--rimworld-legacy`.
Для RimWorld он нужен почти всегда.

### Чем прогнано и что доказано

`python scripts/audit-rimworld-track-c.py` — **exit 0**. Скрипт достраивает то,
чего в проде нет: присылает каталог магазина так же, как это делает игра
(`POST /api/rimworld/shop-catalog`), заводит пешку и страсть в базе.

| Механика | Доказано |
|---|---|
| Создать пешку (200💎) | списано ровно 200, команда в очереди |
| Двойной клик | повтор отвечает успехом и **не списывает второй раз** (M98) |
| Лечение (150💎) | списано ровно 150; кулдаун отказал второму запросу и денег не взял |
| Воскрешение (500💎) | списано ровно 500 |
| **Магазин** | команда уходит типом `equip_item` — фикс `_rwBuyItem` подтверждён **на живом пути**; несуществующий товар отказывает без списания |
| Пассия / сброс | 500 и 300, обе команды в очереди |
| **Отказ мода** | вернулось ровно 200, строка очереди закрыта, **повторный отказ второй раз не платит** |

**НЕ покрыто (клетки оставлены пустыми осознанно):** гены и черты
(прогрессивная цена — нужен свой сценарий) и ивенты (нужен каталог от мода).

### Три ложные тревоги прогона — чтобы не расследовать заново

1. **«Списано 700 вместо 1200».** Первая покупка выдаёт достижение
   `first_rimworld_buy` и начисляет **500💎** (`database.py:470`). Не баг.
   Заодно это ответ на вопрос границы валют: крустики начисляет **ядро**
   (механика достижений), однократно и за действие, а не игровой модуль.
2. **«Лечение не прошло».** Кулдаун лежит в базе (`rimworld_heal_cooldowns`) и
   переживает прогон — второй запуск скрипта видел «ещё 13 минут».
3. **«Страсти нет».** Поддельный мод команду подтверждает, но состояние пешки
   не меняет — в живой игре страсть проставляет мод.

**Состояние прода:** все таблицы пешек пусты, каталог магазина пуст — в RimWorld
действительно никто не играл. Это не поломка, а факт, который надо помнить:
данными этот модуль не проверяется, только прогоном.

## 🏗 АРХИТЕКТУРНЫЙ ДИАГНОЗ 2026-07-24 — почему модуль хрупкий (не список багов)

Сравнение с Bannerlord (Module API) по 8 осям. Вывод: **это не набор багов,
которые чинятся по одному, а другой — досетевой — способ построения модуля.**

| Ось | Bannerlord | RimWorld |
|---|---|---|
| Мод→бэк | один канал `/v1/module/<id>/events` + манифест как гейт типов | **30+ своих эндпоинтов**, гейта типов нет |
| Авторизация | channel_id ВСЕГДА из module-token на транспортном слое | надстройка, строгий/мягкий режим — **env-флагом** |
| Бэк→мод | `module_actions` + long-poll (до 25с) | своя таблица + поллинг раз в 30–300с |
| Рефанд | generic, идемпотентный | своя вторая реализация той же идеи |
| Мультитенант | `WHERE channel_id` везде | `shop_catalog` **без channel_id вообще**; `purchase_counters`, `heal_cooldowns`, часть путей к пешкам — по одному username |
| Пул БД | `get_db()._connect()` | сырой `aiosqlite.connect` на каждый вызов, мимо пула |
| Деньги | списание + очередь в ОДНОЙ транзакции | `remove_points` коммитит отдельно от постановки команды |
| Идемпотентность | `client_action_id` + уникальный индекс | **нет вообще** — двойной клик/ретрай спишет дважды |
| Синк | событийный, сразу после изменения | полный bulk-снапшот по таймеру, delete+reinsert дочерних строк |
| Ошибки мода | структурный ACK success/fail | `try { Post } catch { Log.Warning }` — молча, следа на бэке нет |

### ТОП-3 по ущербу

1. **Межканальные утечки** — `DELETE FROM shop_catalog` при заливке стирает
   каталог ВСЕМ стримерам сразу; зрители с одинаковым ником на разных каналах
   делят пешку, кулдаун лечения и счётчик прогрессивных цен. Отсюда
   `tenant-lint: skip-file`. **Рванёт на втором стримере.**
2. **Не атомарные деньги** — крах между двумя коммитами = крустики списаны,
   записи о команде нет, возвращать нечего даже теоретически. Плюс отсутствие
   идемпотентности: ретрай списывает повторно.
3. **Поллинг + полный ре-снапшот** — платная покупка до 30–300с не отражается,
   выглядит как «не сработало».

### ⚠️ Противоречие, которое надо назвать вслух

Модуль числится «выключенным техдолгом», но **фактически он живой**: его каталог
(2.2 МБ) грузился у КАЖДОГО зрителя при открытии расширения, даже когда стример
играет в Bannerlord (починено 2026-07-24: двойная загрузка убрана, но сама
загрузка осталась безусловной), а его магазин входит в версию, поданную на
ревью Twitch. «Выключен» — только на бумаге.

### Вывод (стратегический)

Латать по одному багу — бесконечно: каждый фикс упирается в то, что модуль
устроен иначе. Варианты по-честному: (а) **переезд на Module API** — большая
работа, но чинит все три пункта разом; (б) **реально выключить** — не грузить
каталог и не показывать вкладку, пока не переписан. Развивать как есть — не
стоит (см. `docs/MARKET_LANDSCAPE.md`: ниша занята зрелым Twitch Toolkit).

## Текущий статус

### 🔎 2026-07-22 — аудит покупок (найдено, НЕ чиню: владелец держит паузу до ревью Twitch)

Быстрый проход по платным эндпоинтам `rimworld.py`. От худшего к мелкому:

1. **НОВЫЙ, реальный: прогрессивный счётчик не откатывается при рефанде →
   зритель переплачивает за следующую покупку.** Гены/трейты дорожают по числу
   купленных (`purchase_counters`, ген №1=1000, №2=2000…). Счётчик инкрементится
   ПРИ покупке (`rimworld.py:1457` гены, `:1726` трейты), ДО того как известен
   исход. Путь рефанда (`_refund_cmd_row_tx`) возвращает только ОЧКИ
   (`add_points_tx`) и **счётчик не трогает**. Мод корректно отдаёт `success=false`
   на no-op (нет пешки / ген уже есть — `AddGeneCommand.Execute` возвращает false),
   рефанд срабатывает — но счётчик уже уехал вверх. Итог: неудачный ген №1
   вернул 1000, счётчик=1, следующий РЕАЛЬНЫЙ ген №1 стоит уже 2000. Баг
   вскрылся взаимодействием свежего рефанда (19.07) со старым счётчиком.
   Фикс: в `_refund_cmd_row_tx` декрементить счётчик для gene/trait (decrement
   уже есть в remove-gene, `:1812` — переиспользовать). Проверяемо: цена
   следующего гена после отменённого.

2. **Подтверждён старый (аудит #3): `purchase_counters` глобальный, не
   channel-scoped.** Код пишет в `purchase_counters WHERE username` без
   channel_id (`:1391`, `:1812`), хотя channel-scoped `rimworld_purchase_counters`
   существует. Прогрессивная цена гена/трейта **потечёт между каналами**, когда
   подключится 2-й стример. Латентно: RimWorld пока на одном канале.

3. **Кулдаун лечения тоже глобальный.** `rimworld_heal_cooldowns` ключуется
   только по `username` (`:300`), без channel_id → полечился на канале A →
   на кулдауне и на канале B. Тот же латентный класс.

4. **id команды с секундной точностью** — `f"buy_{username}_{int(time.time())}"`.
   Два действия одного типа в одну секунду → одинаковый cmd_id → второй ловит
   `UNIQUE(channel_id, cmd_id)` в `_db_enqueue_command` (после фикса очереди),
   в БД не попадает, но в in-memory очередь уже добавлен → уедет моду без
   строки → на провале рефанда не будет. Прикрыто клиентским кулдауном 3с
   (обходится через devtools). Низкая severity, самоадресный. Фикс:
   добавить в id суффикс (`uuid4().hex[:6]` или счётчик).

**НЕ баг (проверено):** `remove_points` атомарен против ухода в минус (один
UPDATE с `points >= amount`) — двойной траты на балансе нет. Мод детектит no-op
генов/пешек и возвращает false → рефанд по очкам работает.

## Текущий статус

### 🟢 2026-07-22 — связь подтверждена, два скрытых бага закрыты

**Связь мод→прод РАБОТАЕТ.** Июльский фикс (https + Bearer) подтверждён логом
последней сессии игры: `Сервер: https://shedoy23.ru`, `Event catalog synced:
248 events` — и на проде ровно 248 строк в `rimworld_event_catalog`. Тема
«POST не доходят» закрыта, секции ниже — история.

**Баг 1 — каталог магазина не заливался (413).** Лог: `BuildCatalogWithPrices:
2559 предметов` → `SyncShopCatalog failed: (413) Request Entity Too Large`.
В nginx на проде не был задан `client_max_body_size` → действовал дефолт 1 МБ,
а 2559 предметов с русскими описаниями в него не влезают. Зрители видели
устаревший срез `shop_catalog` из **493 позиций от 19.07 10:10** — последнюю
удачную заливку. Починено: `client_max_body_size 20m` в
`/etc/nginx/sites-enabled/twitchbot` (бэкап рядом: `/root/twitchbot.nginx.bak.*`),
`nginx -t` + graceful `reload`. Проверено: тело 2.6 МБ доходит до приложения
(401 вместо 413). **Остаётся сделать:** заливать каталог порциями — при росте
числа модов он снова упрётся в любой лимит, а приёмник делает полную замену
(`DELETE` + вставка), так что чанкам нужен протокол (первая порция сбрасывает,
остальные дописывают).

**Баг 2 — очередь команд не сохранялась НИ РАЗУ с миграции m1.** m1 пересоздала
`rimworld_pending_commands` со схемой `channel_id INTEGER NOT NULL` +
`UNIQUE(channel_id, cmd_id)`, а локальный `CREATE TABLE IF NOT EXISTS` остался
досетевым (без channel_id) и на мигрированной базе не срабатывал. `INSERT OR
IGNORE` не передавал channel_id → нарушение NOT NULL, и «OR IGNORE» глотало
строку молча. На проде в таблице **0 строк**. Следствия: обещание «команда
переживёт рестарт сервера» не выполнялось, и рефанд-механика от 19.07 физически
не могла работать — возвращать было не из чего. Починено (`6a54b58`): схема в
коде приведена к схеме миграции, INSERT передаёт channel_id, «OR IGNORE» убран
(нарушение теперь шумит), команда без channel_id логируется явно.
**Почему не поймал линтер:** `rimworld.py` помечен `tenant-lint: skip-file` как
известный долг — исключение спрятало ровно тот класс бага, ради которого
проверка и заводилась.

**Не проверено:** пешки/колонисты. В последней сессии была новая игра
(«Загружено пешек: 0»), поэтому `rimworld_pawns/_skills/_traits` пустые — это
может быть отсутствие данных, а не поломка. Нужен запуск с реальной колонией.

**Замечено:** `rimworld_catalog` (0 строк) — в неё никто не пишет, каталог живёт
в `shop_catalog`. Похоже на мёртвый дубль раннего дизайна, надо проверить, кто
её читает.

### 🟡 2026-07-19 — ROOT CAUSE НАЙДЕН + ПОФИКШЕН, ждёт запуска игры

Причина «POST не долетают»: **DLL в игре была собрана 2026-06-12 со старым
`http://31.130.132.224:8000`**; фикс Security 2.1 (https://shedoy23.ru + Bearer)
внесли в исходники 2026-06-27, но DLL не пересобрали — мод месяц стучался
на голый IP:8000 plain-HTTP (вероятно, POST'ы туда режет DPI провайдера —
тот же, что резал RTMP; GET'ы мелкие и проскакивали). Сделано (`04338ee`):
- DLL пересобрана из репо-исходников → в игре (md5 сверен), зашит `https://shedoy23.ru`;
- + форс TLS 1.2 (Mono/WebClient), + heartbeat-ошибки логируются (раньше Release молчал);
- прод проверен курлом: `POST /api/rimworld/heartbeat` + токен из настроек мода = **200**,
  без токена = **401** (строгий режим уже работает, токен в конфиге мода валиден до ~2027-06).
**Осталось:** запустить RimWorld → проверить в логе `Сервер: https://shedoy23.ru`,
`Session started`, и на проде `rimworld_catalog` > 0 строк. Секция ниже — история.

### 🔴 KNOWN ISSUE (2026-06-14) — мод НЕ заливает данные на прод (POST не доходят)

Обнаружено при проверке module-token: **исходящие POST'ы мода до прода не долетают**,
доходит только `GET /api/rimworld/status` (+`/api/event/status`) — проба «я на связи».

Доказательства (prod `31.130.132.224`):
- мод (debug log) рапортует `Shop catalog synced: 493 items` / `Session started`, НО
  `rimworld_catalog` в `viewers.db` = **0 строк**;
- в `/var/log/twitchbot.out.log` **ноль POST'ов** с IP мода — только GET'ы статуса
  (при этом uvicorn POST'ы пишет: чужие `POST /api/viewer/attendance` видны → дело не в логе);
- мод в release-сборке **глотает сетевые ошибки**, поэтому в игре пишет «synced» оптимистично.

Вывод: проблема на **стороне мода/сети** (запрос не доходит до uvicorn — иначе залогировался бы
даже с ошибкой), НЕ в бэкенд-коде. GET работает, POST нет → сужает круг: сериализация / таймаут /
TLS на больших телах / другой код-путь отправки POST. Начинать с `RimLink/Source/API/RimLinkAPI.cs`
(методы POST vs `Ping()`/GET) + где ловятся/глотаются исключения отправки.

**Связанное:** backend имеет SOFT-режим module-token авторизации (`rimworld.py:56`,
`RIMWORLD_REQUIRE_TOKEN`). Флипать в STRICT **нельзя пока POST не доходят** — защищать нечего,
а STRICT просто 401-ит и так не доходящие запросы. Токен в настройках мода ВСТАВЛЕН и валиден
(проверено) — он не причина. Оставлен SOFT.

Приоритет: отложено (2026-06-14, по решению владельца — фокус на Bannerlord, RimWorld legacy).

### ✅ Что работает (production)

**Backend:**
- `routes/rimworld.py` (~2000 строк, legacy endpoints) — pawn create,
  equip, skills, hediffs, traits, genes, xenotype, settlement sync
- 11 `rimworld_*` таблиц в `database.py` (через M1-M6 migrations):
  pawns, pawn_equipment, pawn_skills, pawn_hediffs, pawn_traits,
  pawn_genes, colonists, skills, catalog, pending_commands, ...
- `modules/rimworld/_adapter.py` (316 строк) — Module API adapter
  (Step 2 of migration plan: lifecycle + log-only)

**C# mod** (legacy, **отдельный repo** или path):
- `RimLink/Source/Managers/` — PawnManager, EventManager,
  ShopManager, CommandQueue, PawnDataBuilder
- Communicates через старый file-based protocol (TwitchCommands.txt
  polling, не HTTP yet)

**Frontend:**
- `extension.html` tab «🔌 Интеграция» когда active_module='rimworld'
- Pawn card, equipment, skills, shop, events panel

### 🟡 Pending — остаток Module API migration

См. `docs/MODULE_MIGRATION.md` план. Текущий status (примерно):
- **Step 2 ✓** lifecycle hooks реализованы в adapter
- **Step 3 ✓ (04.09)** новый DLL long-poll'ит `/v1/module/rimworld/actions`
  и ACK'ает `/v1/module/rimworld/ack`; backend выбирает generic outbox по
  свежему liveness-сигналу, поэтому старый DLL продолжает legacy без дублей.
  Отказ атомарно возвращает цену и счётчик прогрессивной покупки.
- **Step 4-6** ⏳ player events → upsert в rimworld_pawns через adapter
  (вместо legacy /api/rimworld/sync_pawns_bulk)

Это **большая** работа потому что меняется С# mod transport layer
(file → HTTP/JWT). Legacy endpoints `/api/rimworld/*` должны
сосуществовать с new Module API endpoints `/v1/module/rimworld/*`
до миграции mod'а.

### 🟢 Compliance status

Все Phase 1-7 cleanup'ы применены:
- Casino / craft / market / donate / transfer вырезаны
- Items value=0 (cosmetic-only)
- Quest rewards без `reward_item`
- Roulette mode removed
- Lexicon scrub passed

См. `COMPLIANCE_REWORK_PLAN.md` §1-7 для деталей.

## Stack

- **C# mod:** `.NET Framework 4.7.2` net472, RimWorld 1.5+, Harmony
- **Backend transport:** HTTP polling (legacy) → Module API (target)
- **Auth:** Twitch Extension JWT (стандартный extension flow)

## Файл map

### Backend (Python)
| Где | Что |
|---|---|
| `Расширение/backend/routes/rimworld.py` | Legacy endpoints (2000 строк) |
| `Расширение/backend/rimworld.py` | Helpers + middleware |
| `Расширение/backend/modules/rimworld/manifest.yaml` | Module API declaration |
| `Расширение/backend/modules/rimworld/_adapter.py` | Module API adapter (~316 строк) |
| `Расширение/backend/migrations/m1_multitenant.py` | RimWorld tables → multi-tenant |
| `Расширение/backend/database.py` | `rimworld_*` table definitions |
| `Расширение/docs/MODULE_MIGRATION.md` | Step-by-step plan for legacy → Module API |

### C# mod (RimLink)
Не в monorepo. Локация на dev машине:
- `C:\Users\Edward\Desktop\Рабочая версия\RimLink\Source\`
- `Managers/PawnManager.cs` — pawn registration + sync
- `Managers/EventManager.cs` — event lifecycle
- `Managers/ShopManager.cs` — shop catalog
- `Managers/CommandQueue.cs` — pending commands processor
- `Components/RimLinkGameComponent.cs` — GameComponent tick loop
- `Actions/EventCommands.cs` — game-side action handlers

### Frontend
| Где | Что |
|---|---|
| `Расширение/frontend/pawn.js` | Pawn card render |
| `Расширение/frontend/shop.js` | Shop catalog UI |
| `Расширение/frontend/xenotype.js` | Xenotype picker |
| `Расширение/frontend/duels.js` | Pawn dueling UI (но dueling — core feature, не rimworld-specific) |

## Endpoints (RimWorld-specific)

Legacy `/api/rimworld/*`:
- `POST /api/rimworld/sync_pawns_bulk` — mod пушит pawn state batch
- `POST /api/rimworld/pawn_link` — link Twitch login ↔ in-game pawn
- `POST /api/rimworld/spawn_pawn` — create new pawn for viewer
- `GET /api/rimworld/my_pawn/{username}` — pawn info для extension
- `POST /api/rimworld/heal_pawn` — heal action
- `POST /api/rimworld/equip_pawn` — equip item
- `POST /api/rimworld/event/*` — event triggers
- `POST /api/rimworld/shop/*` — catalog queries

Module API (новый, на пути миграции):
- `POST /v1/module/rimworld/events` — generic event ingest
- `GET /v1/module/rimworld/actions` — long-poll outbox
- `POST /v1/module/rimworld/ack` — ACK исполнения

## Что бы делать в этом чате

**Хорошо подходит:**
- C# mod (RimLink) изменения — code в `RimLink/Source/`
- Module API migration steps 3-6 (HTTP transport, player events handlers)
- RimWorld-specific bugs в `rimworld.py` / `routes/rimworld.py`
- Pawn / skill / xenotype / hediff features
- Mod manifest update

**Лучше другой чат:**
- Multi-tenant / auth / overall extension architecture → `CONTEXT.md`
- Bannerlord work → `CONTEXT_BANNERLORD.md`
- Compliance / lexicon / submission → `CONTEXT.md` + COMPLIANCE_REWORK_PLAN.md

## Open вопросы / next steps

1. **Module API migration** — mod transport на HTTP/JWT (steps 3-6)
2. **Pawn equipment slot naming** — слот «Primary» vs «weapon» (см. project_twitch_rimworld.md memory)
3. **RimLink.dll recompile** после изменений PawnManager.cs (по memory note)
4. **Rebrand?** В отличие от Bannerlord (BLT reference), RimLink — наш
   изначальный mod, нет third-party license concerns

## Repo

- **GitHub backend:** `Shedoy23/shedstream` (private monorepo, есть)
- **RimLink C# mod:** не в monorepo. Возможно отдельный repo (нужно
  уточнить у юзера) либо локальный код в `RimLink/`

---

**Использование для нового чата:** скинуть этот файл + сказать
*«Читай CONTEXT_RIMWORLD.md, продолжаем работу над RimWorld-модулем»*.
