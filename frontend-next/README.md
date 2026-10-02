# Новая Preact панель и мини-игры

Локальный кандидат. Замороженные `Расширение/frontend/`, старые мини-игры,
Twitch ZIP, production и релизный упаковщик не меняются.

## Входы

- `panel-extension.html`, `panel-mobile.html`: отдельный Preact-кандидат подэкранов
  развития героя Bannerlord, магазина/инвентаря, боевых действий (без турниров),
  свиты, клана, отряда и армии.
  Это ещё не вся старая панель; фактический published/local scope указан в
  `docs/PANEL_PREACT_RESULT_2026-10-03.md`.
  Парные входы одинаковы, используют прежний Twitch resolver и тот же проверяемый
  build-time EBS origin. Старые viewer scripts в их граф не входят
- `index.html`, `extension.html`, `mobile.html`: одинаковое Preact-приложение
  новых мини-игр. Обычный вход использует настоящий `HttpSkillgameTransport`,
  проверенный сервером Twitch Helper JWT и `/api/skillgames/*` выбранного при сборке EBS
- `tournament.html`: прежний полностью синтетический макет турнира, без HTTP
  mutations. Доступен отдельно по ссылке из новых панелей
- `extension.html?demo=catalog|battleship|minesweeper`: явно подписанные
  display-only fixtures. Они не обращаются к API и не реализуют клиентский
  движок. Нажатия объясняют, что для игры нужен настоящий сервер

Самостоятельный Vite preview без Twitch-авторизации показывает ожидание
авторизации. Он не переключается автоматически в demo и не подставляет токен.
URL-параметр не может задать API origin или JWT. Для настоящего Twitch CDN
EBS задаётся при сборке через `VITE_SKILLGAME_EBS_ORIGIN`; тот же origin попадает
в CSP трёх игровых входов. Нужны согласованная внешняя конфигурация Twitch,
CORS выбранного EBS и обычный Local/Hosted Test → Review → owner-approved Release. Публикация не выполнялась.

Для локального ASGI-стенда родительский runner отдаёт те же собранные ассеты,
настоящие routes, временную SQLite и тестовый Helper. Только этот helper имеет
`environment: 'local-integration'`: UI показывает крупный баннер локального
API-стенда. Это проверка реальных запросов локально, не интеграция с Twitch live.

## Воспроизведение

Node.js 22.12+ (здесь Node 24.19.0), npm:

```sh
python -m pip install -r frontend-next/requirements-contract-tests.txt
npm --prefix frontend-next ci
npm --prefix frontend-next test
npm --prefix frontend-next run build
npm --prefix frontend-next run preview
```

Для одного frontend contract-теста нужен Python 3 с PyYAML: он передаёт настоящий
telemetry batch неизменённому `backend/ui_usage.py`, без запуска сервера или БД.
По умолчанию тест ищет `python3` (Windows: `python`); `PANEL_BACKEND_PYTHON` позволяет
указать готовый интерпретатор/venv. CI устанавливает эту зависимость явно, отдельно
от backend job. Остальные UI-тесты выполняются в Node/jsdom.

Статические входы: `http://127.0.0.1:4173/extension.html`, `/mobile.html`,
`/tournament.html`. Для картинки без API добавьте `?demo=minesweeper`.
Использовать статическую сборку: строгий CSP не предназначен для Vite HMR.
`frontend-next/dist/` игнорируется Git и не связан с корневым release `dist/`.

## EBS origin и Twitch-вход

По умолчанию origin пустой: локальные относительные запросы. Для hosted-кандидата
перед сборкой задаётся ровно HTTPS origin без пути (включая завершающий `/`),
credentials, query или fragment. Значение валидируется, нормализуется и одинаково
используется identity resolver, игровым API, telemetry и CSP. Никакого production
адреса по умолчанию, runtime CDN-конфига или адреса из query-string нет.

```sh
# Только пример сборки; .invalid не является работающим EBS.
VITE_SKILLGAME_EBS_ORIGIN=https://ebs.example.invalid npm --prefix frontend-next run build
# Вернуть обычную локальную сборку: запуск без этой переменной.
npm --prefix frontend-next run build
```

Twitch `onAuthorized` сам по себе не открывает игры. `IdentityBootstrap` сначала
отправляет POST `/api/user/resolve-twitch-token` с единственными полями
`{token, opaque_id}`. Проверка JWT, числовая личность, Helix login и сохранение
связи остаются на сервере. Клиент не декодирует JWT и не передаёт выдуманный login.
Только ответ с непустым `login` разрешает игровой polling и команды.

При `login:null`, ошибке/timeout или отсутствии Helper виден честный экран входа.
Кнопка «Поделиться Twitch ID» вызывает `Twitch.ext.actions.requestIdShare()`
только после клика. Одобрение не предполагается: после успешной передачи Twitch
сам вызывает новый `onAuthorized`; после отказа/закрытия окна игры остаются
закрыты. Повторная проверка разрешена отдельной кнопкой. Серверная ошибка
показывается текстом. Сетевое ожидание ограничено 20 секундами.

Каждый новый token проходит resolver заново. Старый ответ не авторизует новый
token/viewer/channel. Во время проверки polling, команды и telemetry закрыты;
старый токен одного и того же зрителя остаётся только для уже начатой мутации.
Его UI временно скрыт, но остаётся смонтированным: черновик флота не теряется.
Смена зрителя/канала очищает данные и черновик, без мигания чужой партии.
Источник Helper API: https://dev.twitch.tv/docs/extensions/reference/

## Настоящий HTTP-контракт

Источник истины: `Расширение/backend/routes/skillgames.py`,
`skillgames/config.py`, `skillgames/service.py` и серверные projections движков.

- GET `/api/skillgames/config`; GET `/api/skillgames/state?session_id=...`
- POST `/api/skillgames/start`, `/action`, `/queue`, `/queue/cancel`
- Заголовок `X-Twitch-JWT` читается при каждом вызове
- Сервер решает личность, канал, правила, исход, рейтинг и время
- Мутация содержит UUID `request_id`; ход также содержит `session_id`/`version`
- Игровые мутации не передают очки, победителя, клиентское время, identity или seed
- Неизвестные reason/message отказа сохраняются; `stale_version` ведёт к GET,
  без автоматического повторения устаревшего хода
- Потерянный ответ блокирует новые команды; безопасный повтор использует
  в точности исходное тело/UUID только внутри опубликованного сервером окна
  `request_retention_seconds`. Время отсчитывается монотонными часами клиента.
  Неизвестное/истёкшее окно запрещает POST-retry; успешный GET снимает старую
  неопределённость и предлагает выбрать новое действие отдельно. UUID никогда
  не заменяется автоматически. Текущий сервер: receipts 24 часа, не более 4096
  запросов зрителя за это окно; приватные завершённые поля очищаются через
  30 дней, журнал результатов сохраняется отдельно. Это разные сроки и гарантии
- 20-секундный сетевой timeout охватывает также чтение JSON body. Потерянный
  ответ мутации остаётся uncertain; timeout не трактуется как серверный отказ
- Один poll одновременно; медленная сеть не делает каждый ответ устаревшим
- Auth/lifecycle barriers подавляют старые GET. Обновление токена того же
  зрителя не сбрасывает pending mutation; новая личность не наследует UI
- Закрытие/visibility/reload не отправляют quit. Reload читает сохранённую
  партию с сервера. Выход и сброс требуют отдельного подтверждения
- Active UI использует immutable `session.rules`, а каталог — актуальные
  правила сервера. Таймер рисует `expires_at` с поправкой по `server_time`;
  локальные часы не могут присудить поражение

## Управление

Морской бой: выбор корабля → направление → тап первой клетки → сохранить весь
флот → готовность. Авторасстановка идёт через сервер. Редактируемый локальный
черновик не стирается изменениями соперника, polling или обновлением токена;
он обновляется только при смене партии/владельца или собственного флота на сервере. В игре основное поле —
поле соперника; собственное переключается одной кнопкой. На своём поле нельзя
выстрелить. Клиент не получает и не восстанавливает скрытый флот соперника.

Сапёр: явный режим «Открыть»/«Флаг», отдельные рейтинг/тренировка и сложности
из серверного каталога. До первого открытия поле не генерируется на клиенте.
Победа/поражение/флаги/проверка решаемости принадлежат серверу. Сброс завершает
старую попытку с опубликованными последствиями; новую начинает отдельный клик.

Доступность новых партий берётся из `availability.enabled/reason`; отключение
не блокирует ходы существующей партии. Результаты показывают локализованные
`message/reason_message`, с исходным reason-code как fallback.

Награды, бесплатный вход, предварительность баланса, организатор и отсутствие
Twitch/Apple среди спонсоров выводятся из серверной конфигурации. Нет обещания
одобрения платформы или автоматической выплаты за победу.

## Безопасные счётчики

`usage.ts` передаёт только allowlisted semantic counters в существующий
`/api/viewer/ui-usage`: открытие игры и попытка действия. Нет клеток, кораблей,
минирования, имён, рейтинга или payload. Только память, до 20 keys / 100 counts
за пакет / 20 на key; отправка не чаще раза в 15 секунд. Смена viewer/channel
выбрасывает старые данные. Ошибки и потерянные ответы не повторяются, gameplay
от telemetry не зависит. При повторной проверке личности отправка ждёт нового
подтверждения и использует свежий JWT. Demo telemetry не отправляет.

## Проверки и границы

107 React/unit/build-contract tests на 02.10, включая прежние 37, плюс отдельный
успешный opt-in тест настоящего HTTP адаптера. Без env этот сетевой тест пропущен.
Отдельные RED-коммиты показали отсутствие транспорта/контролов/телеметрии
и конкретные интеграционные ошибки до GREEN. `typecheck`, Vite build и build
policy gate проходят. Gate проверяет 4 входа, одинаковость extension/mobile,
Helper первым скриптом, readable bundled React, локальные JS/CSS без inline/eval,
отсутствие legacy dispatcher/production URL, наличие HTTP minigame adapter и
лицензий закреплённых зависимостей. Source maps локальные и включены.

Локальный TCP/API smoke выполнен через `scripts/test-skillgames-network.py`.
Дополнительно `test/skillgame-live.test.ts` использует настоящие `IdentityBootstrap`
и `HttpSkillgameTransport` с реальным HTTP: unlinked → явная передача ID →
серверный resolver → сапёр start/open/resume/quit → оба игрока морского боя
place/autoplace/ready/fire/quit. Подделана только внешняя OAuth/Helix-сеть в
локальном Python runner; gameplay/DTO/parsers/auth-cache — настоящие.

```sh
# Backend-зависимости должны быть доступны выбранному Python.
python scripts/run-skillgames-local.py --allow-local-demo --port 4182 &
runner=$!
trap 'kill "$runner" 2>/dev/null || true' EXIT
until curl --silent --fail http://127.0.0.1:4182/ >/dev/null; do sleep .1; done
LOCAL_TEST_BASE_URL=http://127.0.0.1:4182 npm --prefix frontend-next run test:live
```

Runner и тест запускать в одном shell: некоторые sandbox-окружения изолируют
сеть между отдельными exec-вызовами. Сетевой тест допускает только loopback HTTP
origin с явным портом и никогда не обращается к production.
Визуальный браузерный прогон заблокирован средой (`ERR_BLOCKED_BY_CLIENT` для
localhost); скриншоты настоящих 318px viewport пока не получены. Здесь не заявлено прохождение
Twitch Hosted Test, реальные мобильные устройства, production auth и публичный
release. Клиентские тесты не доказывают работу серверной генерации или рейтинга;
для этого нужны backend/ASGI проверки и настоящий локальный сетевой прогон.

## Preact runtime

Preact 11.0.0 закреплён точно (npm latest проверен 02.10.2026). Компоненты
сохраняют React API через `preact/compat`; React/ReactDOM/scheduler в дереве
зависимостей отсутствуют. `tsconfig.json` задаёт единую таблицу aliases для
TypeScript, Vite и Vitest через `preact.config.ts`. Тесты рендерят настоящий
Preact с `@testing-library/preact`, без React peer runtime.

Сборка остаётся неминифицированной, с sourcemaps. `check-build.mjs` сверяет
лицензию Preact и все внешние пакеты в картах исходников. При добавлении новой
библиотеки нужно осознанно обновить этот список и notices.
