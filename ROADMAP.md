# ShedLink Product Roadmap

Версия: 1.1
Дата: 2026-08-16
Горизонт: от текущего рабочего продукта до подтверждённого self-service SaaS
Статус: новый roadmap; заменяет завершённый предыдущий roadmap

> Baseline актуального HEAD и production повторно проверен 2026-08-15.
> Результаты и evidence: `docs/R0_GAP_ANALYSIS_2026-08-15.md`.

---

## 1. Цель нового этапа

Ближайшая цель ShedLink — не максимальное количество функций или игр.

Нужно доказать следующую цепочку:

```text
self-service setup
    → technical activation
    → first real viewer action
    → second streamer session
    → retention
    → first payment
```

Главный результат этапа:

> Незнакомый стример самостоятельно устанавливает ShedLink, использует его
> минимум в двух стримах и добровольно оставляет частью своего стрима.

После этого следующий результат:

> Первый незнакомый стример платит за ShedLink и может объяснить, за какую
> регулярную ценность он платит.

---

## 2. Продуктовая позиция

ShedLink — не набор одноразовых воздействий зрителя на игру.

```text
viewer
  → persistent identity
  → character in a game world
  → persistent state and progression
  → actions and relationships
  → continuity across future streams
```

Рабочая формулировка:

> Your viewers don't control the game. They live in it.

Она должна определять onboarding, интерфейс Manager, Extension, выбор новых игр
и будущую монетизацию.

---

## 3. Что уже является фундаментом

Перед разработкой необходимо подтвердить это в актуальном HEAD, но audit-снимок
показывает существование следующих компонентов:

- Twitch OAuth для стримеров и channel registry;
- streamer dashboard и channel approval gate;
- Module API с envelope-протоколом;
- runtime adapters и manifests для Bannerlord, RimWorld и ShedColony;
- channel-scoped state и игровые heartbeats;
- очереди действий, ACK, dedup и refunds;
- stream sessions и базовый feature usage;
- fresh-install migrations и существенный набор денежных/multi-tenant тестов.

Следовательно, новый этап не должен заново изобретать runtime platform.
Основная новая работа — deployment/self-service layer, закрытие доказанных
reliability gaps и измерение продуктовой воронки.

---

## 4. Принципы исполнения

1. Сначала один end-to-end путь для одной игры, затем расширение охвата.
2. Работающая часть не переписывается без конкретного дефекта или измеримой
   стоимости сопровождения.
3. Денежные и tenant-инварианты важнее новых игровых функций.
4. Runtime manifest и installation manifest — связанные, но разные контракты.
5. Каждый milestone заканчивается наблюдаемым пользовательским результатом.
6. `Compiled`, `tests passed` и `installed` сами по себе не являются продуктовым
   результатом.
7. Все новые шаги onboarding должны оставлять продуктовые события.
8. Ручное вмешательство разработчика во время clean-install считается дефектом
   продукта или onboarding.
9. Пока Twitch Extension `0.0.2` находится в Review, её frontend, cache-bust и
   submitted ZIP неизменяемы. Manager, backend и игровые моды продолжаются;
   backend обязан обслуживать одновременно публичную `0.0.1` и поданную
   `0.0.2`. Следующий frontend-batch начинается только после вердикта Twitch.

---

## 5. Метрики и точные определения

### 5.1 Technical Ready

Manager подтверждает одновременно:

```text
Twitch authenticated
Backend reachable
Game detected
Integration installed
Compatible versions
Game running
Mod heartbeat received
Test action acknowledged
```

### 5.2 Time to Technical Ready — TTTR

Время от первого запуска Manager до первого успешного безопасного test action.

Цель M1:

- median `< 10 минут` на чистой поддерживаемой Windows-среде;
- долгосрочная цель `< 5 минут`, если игра уже установлена;
- ручная правка config или файлов недопустима.

### 5.2-бис Что на самом деле мерит TTTR — замечено 2026-08-20

Первый живой прогон по воронке: владелец скачал, поставил и дошёл до готовности
за **8 мин 52 с**. Из них на работу самого Manager ушло **14 секунд** — от
запуска до записанной конфигурации. Остальные восемь с половиной минут это
загрузка Bannerlord (6 мин 23 с до первого heartbeat) и пауза, пока человек
дошёл до кнопки «Проверить готовность».

Отсюда следствие для ворот M1 «медиана TTTR меньше 10 минут»: в нынешнем
определении они меряют скорее **скорость игры и терпение человека**, чем
продукт. Стример с модпаком потяжелее или машиной послабее не уложится, и это
не будет говорить о ShedLink ничего.

Метрику НЕ меняем — она определена как путь до первого успешного действия, и в
этом есть смысл: пользователю важно именно это время. Но рядом теперь считается
вторая, та, которой продукт управляет: **от запуска Manager до записанной
конфигурации**. Обе видны на странице воронки в админке, и подменять одну
другой нельзя.

Что с этим делать при разборе M1: если TTTR не проходит, сначала смотреть на
вторую цифру. Она отвечает, наш ли это долг.

### 5.3 Time to First Viewer Action — TTFVA

Время от `Technical Ready` до первого успешного действия реального зрителя.

Эта метрика измеряется отдельно от TTTR: наличие зрителя не контролируется
установщиком.

### 5.4 Activation

Стример активирован, если выполнены оба события:

1. `technical_ready`;
2. `first_viewer_action`.

### 5.5 Second Session Rate

Доля активированных стримеров, которые провели вторую ShedLink-сессию в течение
14 дней без персональной просьбы разработчика включить продукт снова.

### 5.6 Retention

- D7: была ShedLink-сессия на 7-й день или в окне ±2 дня;
- D30: была ShedLink-сессия на 30-й день или в окне ±5 дней;
- отдельно хранится количество и длительность сессий.

---

# Roadmap

## R0 — Current HEAD Baseline and Release Gate

### Цель

Получить достоверную исходную точку и закрыть только те риски, которые делают
внешний self-service эксперимент небезопасным.

### Работы

- [x] Повторить gap analysis в актуальном HEAD, не в `dist/audit`.
- [x] Составить список реально поддерживаемых integrations и их release-версий.
- [x] Зафиксировать текущую ручную установку каждой интеграции.
- [x] Инвентаризировать credentials, secrets, config files и update process.
- [x] Проверить специальные платные Bannerlord handlers на сохранение
      `price`, `client_action_id`, исходного `action_id` и terminal result.
- [x] Проверить tenant scope в queue/poll/ACK/state путях по текущему
      автоматическому покрытию.
- [x] Проверить lifecycle:
      `charge → enqueue → deliver → apply/refuse → ACK → refund`.
- [x] Проверить duplicate request, duplicate ACK, lost ACK, restart и reconnect;
      live RimWorld smoke остаётся release-gate задачей.
- [x] Выбрать первую Manager integration — RimWorld; live E2E, отказ, lost ACK
      и reconnect подтверждены на production 2026-08-16.
- [x] Зафиксировать минимальный набор telemetry для Manager и воронки.

### Результат baseline 2026-08-15

- текущий полный backend suite: 48/48 green;
- production healthy, DB `quick_check=ok`, незавершённых module actions нет;
- денежных и tenant P0 в проверенных путях не найдено;
- RimWorld утверждён первой Manager integration после production live smoke;
- restore свежего production backup проверен в изоляции, `quick_check=ok`;
- R0 release gate закрыт: apply/refuse, backend restart/reconnect и lost ACK
  подтверждены на реальной игре и production backend;
- обнаруженный P2 с M109 исправлен локально и покрыт regression; production ещё
  не обновлён.

### Release gate

Перед внешней alpha должны быть доказаны инварианты:

- пользователь не платит за инфраструктурный отказ;
- повтор запроса или события не создаёт неконтролируемый duplicate effect/reward;
- один канал не может читать или исполнять команды другого;
- restart не теряет оплаченные действия;
- пользовательский контент, требующий модерации, не проигрывается автоматически;
- migrations проходят с нуля и существует проверенный backup/restore путь.

### Definition of Done

- актуальный gap-analysis сохранён с привязкой к commit;
- каждый release-gate инвариант имеет автоматическую проверку либо документированный
  live-test с артефактами;
- нет открытого P0, влияющего на выбранную первую integration;
- P1, не затрагивающие M1-путь, явно вынесены в backlog и не блокируют Manager.

---

## R1 — Installation Contract

### Цель

Создать стабильный контракт между Manager и каждой устанавливаемой интеграцией,
не ломая существующий runtime Module API.

### Прогресс 2026-08-15

- создана строгая JSON Schema `manifests/installation/v1.schema.json`;
- создан первый RimWorld manifest с реальным archive size/SHA-256, detection,
  install/update/repair/uninstall, rollback, managed config и health probes;
- validator проверяет schema, границы repository path, size/hash и ZIP traversal;
- reference transaction проверяет staging, atomic directory swap, rollback и
  recovery после имитации жёсткого обрыва, не фиксируя будущую UI-технологию;
- тот же контракт перенесён в production `.NET` Manager Core: production
  manifest parsing, size/SHA-256, ZIP traversal/reparse rejection, staging,
  atomic swap, rollback и crash-journal recovery проходят Windows self-test;
- managed XML writer сохраняет неизвестные поля, атомарно меняет только
  manifest selectors и ставит user-only ACL до замены config;
- отдельный authenticated `auth-check` подтверждает module credential без
  ложной записи heartbeat/liveness; реальный heartbeat остаётся самостоятельным
  условием `Technical Ready`;
- production manifest использует immutable signed HTTPS source; RSA 4096 public
  key встроен в Manager, опубликованные bytes независимо проверены;
- production Manager Core объединяет `package → config → auth-check` в одну
  recoverable operation: до verify сохраняются обе rollback-копии, отказ
  откатывает пакет и XML, а verified crash завершается при следующем запуске.

Auth/credential contract зафиксирован в
`docs/MANAGER_AUTH_CREDENTIALS_V1.md`: system-browser pairing, отсутствие Twitch
tokens в desktop app, revocable opaque module credentials, Windows Credential
Manager, rotation overlap и legacy migration.

M110 локально добавляет persistent ledger pairing/session/module credentials с
hash-only secrets и strict constraints; M111 жёстко связывает Manager session с
одобренным `module_id`. Auth core и HTTP/browser flow реализуют одноразовый
exchange, deny/expire, safe OAuth return, approved-channel gate, CSRF и
request/rate limits. Manager API выдаёт, ротирует и немедленно отзывает opaque
`slmod_v1` credential; исходный secret возвращается только один раз и в БД не
хранится. Общий Module API и RimWorld ingest принимают новый credential с
точным scope `channel_id + module_id`, одновременно сохраняя legacy token на
период миграции. Rotation overlap ограничен 10 минутами и переживает restart.
Manager refresh token теперь одноразово ротируется; повтор использованного
token отзывает всю session family, а logout немедленно закрывает access и
refresh без неявного отзыва установленных module credentials.
Полный backend suite после подключения: 48/48 green.

### Разделение контрактов

#### Runtime Manifest — существующий слой

Описывает:

- core API compatibility;
- events;
- actions;
- catalogs;
- runtime capabilities;
- UI slots.

#### Installation Manifest — новый слой

Описывает:

- integration ID и release version;
- поддерживаемые версии игры;
- способы обнаружения installation path;
- допустимые installation targets;
- artefacts, sizes и SHA-256;
- publisher/signature metadata;
- prerequisites;
- config template и управляемые поля;
- install/update/repair/uninstall operations;
- rollback information;
- health probes;
- compatibility messages.

### Обязательные свойства installer

- [x] Manifest и локальный release artefact проверяются по schema/size/SHA-256.
- [x] Reference core сначала собирает и проверяет staging-копию.
- [x] Reference core выполняет atomic directory swap.
- [x] Reference core восстанавливает предыдущую версию после сбоя/обрыва.
- [x] Reference core отклоняет target за пределами разрешённого game path.
- [x] Пользовательские файлы не удаляются без явного подтверждения.
- [x] Secrets не включаются в manifest и diagnostic bundle.
- [x] Повторный `install()` и `repair()` идемпотентны.

### Definition of Done

- [x] JSON Schema или эквивалентная строгая схема Installation Manifest существует;
- [x] Одна integration описана без hard-coded game lifecycle в core Manager;
- [x] Invalid path, hash mismatch, interrupted install и rollback покрыты
      conformance-тестами;
- [x] Runtime manifest не перегружен deployment-деталями.

---

## R2 — ShedLink Manager MVP: One Game

### Цель

Довести одну игру от первого запуска Manager до `Technical Ready`.

### Прогресс 2026-08-16

- выбран Windows-native стек .NET 8 + WPF; решение и границы зафиксированы в
  `docs/ADR_MANAGER_DESKTOP_STACK_2026-08-16.md`;
- создан независимый `ShedLink.Manager.Core` без UI-зависимостей;
- API client проходит pairing pending/approve, credential issuance, refresh,
  logout и revoke без сохранения access token;
- refresh и module credential хранятся в Windows Credential Manager, атомарный
  `state.json` содержит только несекретные идентификаторы и пути;
- restart восстанавливает Manager session через обязательную refresh rotation;
- Windows self-test проверяет fake-backend flow и реальный Credential Manager
  round-trip; добавлен отдельный CI gate;
- WPF shell подключает pairing/resume и показывает account/game/integration
  stages без отображения secrets;
- RimWorld находится в основной или дополнительной Steam library; ручная папка
  принимается только при наличии `RimWorldWin64.exe` и `Mods`;
- production installation engine реализован в Core и проверяет реальный
  manifest; repository и signed HTTPS sources проходят единую recoverable
  orchestration `package → config → auth-check`. WPF CTA подключён к этой
  операции; release delivery gate закрыт, production Manager API и migrations
  M109–M112 развёрнуты и проверены 2026-08-16.
- HTTPS downloader и publisher verifier реализованы fail-closed: redirect/HTTP
  downgrade, wrong/truncated/oversized bytes, SHA mismatch, unknown key и
  RSA-PSS mismatch не доходят до staging. Policy зафиксирована в
  `docs/MANAGER_RELEASE_SIGNATURE_POLICY_V1.md`; offline signer проверяет ZIP,
  требует RSA 3072+ и атомарно обновляет manifest. Production RSA 4096 key и URL
  созданы, public key встроен в Manager.
- installation inspector различает отсутствующий, повреждённый, устаревший и
  актуальный RimLink; WPF показывает установленную/доступную версии и выбирает
  честный CTA `Установить / Обновить / Восстановить / Переустановить`.
- side-effect-free runtime status читает настоящий `module_last_seen`; WPF раз
  в 15 секунд показывает отсутствие, возраст или свежесть heartbeat, не
  изображая Manager запущенной игрой. Legacy RimLink heartbeat/offline теперь
  обновляют тот же M109 ledger, а не отдельный process-local словарь.
- M112 и `diagnostic_ping` проводят бесплатный no-op через настоящую RimWorld
  command queue, игровой main thread и ACK. WPF показывает `Technical Ready`
  только после свежего heartbeat, целых файлов и успешного сквозного ACK.
- WPF теперь выполняет явный logout с отдельным выбором отзыва ключа RimLink.
  Credential rotation меняет XML, vault и несекретный state как одну
  восстанавливаемую операцию; незавершённая смена продолжается после restart.
- RimWorld version читается из игрового `Version.txt` и сверяется с
  `game.supported_versions` installation manifest. Unknown/unsupported version
  fail-closed блокирует install и итоговый `Technical Ready`.
- EXE загружает встроенный каталог RimLink manifests и выбирает самый новый
  совместимый release; отсутствие совместимого релиза завершается безопасным
  отказом без установки случайной версии.
- Offline RSA 4096 key generator и signer готовы; artifact signing не требует
  платного сертификата. Production key создан вне repository с user-only ACL;
  отдельная offline backup и будущая Windows EXE signing остаются независимыми.
- Independent verifier и полный local release rehearsal подтверждают
  `generate → sign → size/SHA/RSA/ZIP/health verify` без production mutation.
- Publication runbook применён: immutable HTTPS URL опубликован через atomic
  upload, nginx backup/preflight/reload и external verification. HTTP/listing/
  POST закрыты, backend health не изменился.
- RimLink/installation manifest `0.1.1` signed и опубликован; deterministic ZIP
  связан с манифестом точными size/SHA и RSA-PSS signature.
- Production deploy прошёл с проверенным backup/restore и отдельной точкой
  отката кода. `/v1/module/rimworld/auth-check` отвечает 401 без credential
  вместо прежнего 404; pairing API успешно создал и удалил тестовую pending
  запись. База после миграций: `quick_check=ok`, M109–M112 и пять новых таблиц
  на месте, отрицательных points и незавершённых module actions нет. Evidence:
  `docs/PRODUCTION_MANAGER_DEPLOY_2026-08-16.md`.
- На реальной RimWorld `1.6.4871 rev590` Manager самостоятельно завершил Twitch
  pairing, signed install/configuration RimLink `0.1.1`, получил свежий heartbeat
  и ACK безопасного diagnostic action. UI показал `Technical Ready`; install,
  configure и verify production vertical slice подтверждены.
- Первый реальный UI feedback исправлен: действия integration перенесены под
  status-блок и адаптивно переносятся, поэтому заголовок и состояние больше не
  сжимаются на минимальной ширине окна.
- Production reliability smoke закрыт: 11 игровых команд получили успешный ACK;
  backend restart восстановился автоматически; намеренный `diagnostic_refuse`
  завершился `failed` без списаний; намеренно потерянный ACK через 120 секунд
  стал `expired`, команда удалена, поздний RimLink retry идемпотентно снял
  локальный `AckPending`. Итог: очередь `0`, отрицательных points `0`, DB
  `quick_check=ok`.

### Scope v1

#### Account

- [x] Twitch login через системный browser и безопасный OAuth flow.
- [x] Определение channel identity.
- [x] Получение channel-bound module credential.
- [x] Безопасное локальное хранение credential.
- [x] Logout, revoke и credential rotation.

#### Detection

- [x] Autodetect выбранной игры.
- [x] Ручной выбор path при неудаче.
- [x] Проверка, что path действительно относится к нужной игре.

#### Lifecycle

- [x] Install.
- [x] Configure без ручного JSON и копирования ID/token/API URL.
- [x] Verify.
- [x] Update — отдельная копия реальной установки обновлена из подписанного
      production HTTPS source; полный atomic replace и очистка подтверждены.
- [x] Repair — на отдельной копии удалён обязательный DLL, Manager определил
      `RepairRequired` и восстановил его из подписанного production source.
- [x] Uninstall с сохранением пользовательских данных по умолчанию.

Первые три пункта подтверждены реальным production-прогоном до `Technical Ready`
и покрыты success, auth failure и verified-crash recovery тестами. Uninstall
подключён к WPF, атомарен, идемпотентен и сохраняет managed XML/credential по
умолчанию. Repair/update decision покрыт отдельным inspection test для missing,
broken, outdated и healthy installation.

#### Diagnostics

Manager показывает конкретное состояние:

```text
Twitch authentication       ✓
ShedLink backend            ✓
Game installation           ✓
Integration                 ✓ version
Compatibility               ✓
Game running                ✓
Mod heartbeat               ✗ last seen 32s ago
Last error                  Authentication rejected
Recommended action          Rotate credential
```

#### Diagnostic bundle

- [x] Версии Manager/game/integration/API.
- [x] Результаты health probes.
- [x] Последние релевантные сообщения состояния.
- [x] Автоматическая redaction tokens, cookies, usernames и Windows profile path.
- [x] Явный preview содержимого перед экспортом.

### Не входит в MVP

- marketplace;
- community integrations;
- CK3;
- универсальная система plugins;
- auto-launch всех возможных launchers;
- сложная кастомизация UI;
- billing.

### Definition of Done

На чистой Windows VM, где установлена поддерживаемая игра, пользователь:

```text
download → login → detect → install → configure → run → test action
```

без исходников, dev tools, ручной правки файлов и общения с разработчиком.

---

## R3 — Internal Clean Install and M1

### Цель

Доказать self-service технически до приглашения внешних пользователей.

### Текущий практический шаг

- [x] Собрать единый versioned alpha-архив, пригодный для передачи пользователю.
- [x] Включить только необходимые runtime-файлы, manifests и короткую инструкцию.
- [x] Проверить запуск опубликованного self-contained EXE вне repository;
      отсутствие dev tools проверяется отдельно на чистой Windows.
- [x] Зафиксировать контрольные SHA-256 и известное предупреждение Windows для
      пока не подписанного EXE.

Clean Windows остаётся обязательным evidence для M1, но не требует прямо сейчас
покупки отдельного компьютера или платных инструментов. Проверка выполняется,
когда доступна VM, Windows Sandbox либо второй чистый Windows-компьютер.

### Матрица проверки

Пошаговый прогон с ожидаемым текстом по каждой строке —
`docs/R3_MATRIX_RUNBOOK.md`. Там же условие, как строку воспроизвести, и что
считается провалом.

- [ ] Чистая поддерживаемая Windows VM.
- [ ] Стандартный installation path игры.
- [ ] Нестандартный installation path.
- [ ] Игра не найдена.
- [ ] Недостаточно прав на запись.
- [ ] Повреждённая предыдущая установка.
- [ ] Backend недоступен.
- [ ] Неверная/отозванная credential.
- [ ] Несовместимая версия игры или integration.
- [ ] Update с успешным rollback после искусственного сбоя.

Галочки означают ПРОГОН на чистой Windows и ставятся только после него. Часть
критерия M1 — «ошибка объясняется понятным сообщением и следующим действием» —
отделена от прогона и с 2026-08-16 проверяется автоматически
(`ManagerFailureMessage` + `TestFailureMessages`): текст каждого класса сбоя из
матрицы обязан отличаться от общей отговорки и называть, что делать дальше.
Это НЕ заменяет прогон: тест проверяет текст, а прогон — что сценарий вообще
приводит к этому тексту, а не к чему-то третьему.

Там же закрыт дефект, найденный при разборе матрицы: отказ Windows в правах
(`UnauthorizedAccessException`) не попадал ни в один фильтр обработчиков
установки, удаления и смены ключа — они перечисляли `IOException`, а этот тип
наследуется от `SystemException`. Строка матрицы «недостаточно прав на запись»
до 2026-08-16 означала не сообщение, а закрытие приложения без объяснения.

### M1 — Self Service

M1 достигнут, когда незнакомый тестировщик без подсказок разработчика выполняет:

```text
download → login → install → run game → Technical Ready
```

Критерии:

- 3 последовательных clean-install прогона без ручного вмешательства;
- median TTTR менее 10 минут;
- 100% ошибок тестовой матрицы объясняются понятным сообщением и следующим
  рекомендуемым действием;
- диагностический bundle достаточен для удалённого разбора проблемы.

---

## R4 — Five-Streamer Alpha

### Как участники установят расширение — вопрос закрыт 2026-08-20

Разбирая план, я записал это как блокер: Twitch дословно пишет «After review,
changing the allowlist requires re-submitting your Extension for review», и
выходило, что каждый новый стример стоит цикла ревью.

**Проверка в Dev Console показала, что вопрос уже снят.** При подаче `0.0.2`
владелец очистил Streamer Allowlist, а по той же доке: «If this list is empty or
missing, all streamers can use the Extension». То есть после релиза `0.0.2`
расширение сможет установить любой стример, и участников R4 добавлять никуда не
нужно.

В Testing Account Allowlist при этом около шестидесяти аккаунтов — они видят
версию до публикации, что удобно для проверок, и очищается этот список сам после
релиза.

**Что из этого следует для плана:** R4 не упирается в ревью, но меняет профиль
риска. Расширение публичное — установить его сможет и тот, кого мы не готовы
поддерживать. Значит «пять стримеров» — это те, кого мы позвали и за кем
наблюдаем, а не те, кто вообще может поставить. Отказ в обслуживании остальных
надо продумать до релиза, а не после.

**Урок для меня, записан отдельно:** дыра была настоящей на бумаге и уже
закрытой в реальности. Прежде чем объявлять блокером то, что зависит от
внешней консоли, надо спросить владельца о фактическом состоянии — стоило это
одного вопроса.

### Цель

Проверить installation и первую реальную активацию, а не рекламировать продукт.

### Участники

Пять релевантных небольших или средних стримеров, не участвовавших в разработке.

### Правила эксперимента

- разработчик наблюдает, но не подсказывает до возникновения blocker;
- каждая подсказка записывается как support incident;
- ручное исправление файлов считается onboarding defect;
- исправляются реальные blockers, а не все пожелания;
- поведение важнее ответов интервью.

### Обязательные события

⚠ **`manager_downloaded` собрать нечем, и это не забывчивость.** Сам Manager
это событие отправить не может — в момент скачивания он ещё не запущен, — а
считать на стороне сервера пока нечего: Manager нигде не опубликован, на
`shedoy23.ru/releases/` лежат только три мода, приложение передаётся из рук в
руки. Поэтому воронка начинается со ВТОРОЙ ступени — `manager_started`.

Цена этой дыры конкретна: нельзя посчитать «скачал, но так и не запустил». А
это первая точка отвала, и именно там стоит неподписанный exe с
предупреждением Windows. Считать станет чем в тот день, когда Manager появится
по постоянному URL; тогда же добавить подсчёт (журнал nginx или отдающий
эндпоинт).

⚠ **Остальные события собраны 2026-08-20.** Ни одно из перечисленных ниже событий не
пишется сегодня: поиск по `backend` и `ShedLink.Manager` не находит ни
`manager_downloaded`, ни `install_started`, ни `technical_ready`. Есть только
`feature_usage` — счётчик использования фич внутри расширения.

Значит R4 начинается со скрытой работы: собрать приём и хранение двадцати типов
событий. Это надо либо перенести в R3 (прибор должен существовать до опыта),
либо признать частью R4 и заложить время. Сейчас план подразумевает, что
события просто есть.

```text
manager_downloaded
manager_started
manager_authenticated
game_detection_started
game_detected
integration_selected
install_started
install_completed
configuration_completed
mod_heartbeat_received
test_action_completed
technical_ready
extension_activated
first_viewer_open
first_viewer_join
first_viewer_action
stream_session_started
stream_session_ended
support_incident_created
```

Каждое событие содержит, где применимо:

- anonymous installation ID;
- channel ID;
- integration and version;
- Manager version;
- elapsed time;
- result/error code;
- source step;
- timestamp.

### Alpha exit criteria

- 5 стримеров начали setup;
- не менее 4 достигли `Technical Ready`;
- не менее 3 достигли `first_viewer_action`;
- причины всех неудач классифицированы;
- ни одна неудача не привела к потере денег или cross-channel effect;
- median support interventions не более одной на стримера.

---

## R5 — 10–20 Streamer Beta and Reliability Capacity

### Цель

Понять activation drop-off и безопасную вместимость текущей инфраструктуры.

### До расширения beta

- [ ] Alerting на backend unavailable, DB errors и queue backlog.
- [ ] Dashboard по funnel и integration health.
- [ ] Version mismatch виден и пользователю, и оператору.
- [ ] Документирован incident/rollback process.
- [ ] Representative load harness готов.

### Load scenarios

```text
A: 10 streamers × 20 viewers
B: 50 streamers × 30 viewers
C: 100 streamers × 50 viewers
```

Workload включает:

- Extension reads;
- viewer actions и economy operations;
- heartbeat/poll/ACK;
- state synchronization;
- background jobs;
- reconnect storm;
- несколько активных integrations.

Измеряются CPU, RAM, DB utilization, p50/p95/p99, error rate, SQLite lock
contention, queue depth и connection count.

### Beta exit criteria

- 10–20 стримеров начали setup;
- activation rate не ниже 50%;
- причины главного drop-off подтверждены данными;
- нет открытого P0;
- representative Scenario A проходит с минимум 30% headroom;
- установлены измеримые triggers для VPS, database, worker и CDN;
- support incidents на активированного стримера снижаются между alpha и beta.

---

## R6 — Retention Validation

### Цель

Доказать, что ShedLink нужен более одного раза.

### Работа

- [ ] Автоматически определять вторую и последующие ShedLink-сессии.
- [ ] Считать Second Session Rate, D7 и D30.
- [ ] Сегментировать retention по integration и размеру канала.
- [ ] Измерять viewer actions per stream и returning viewers.
- [ ] Проводить короткое интервью после нескольких стримов.
- [ ] Исправлять причины невозврата, а не добавлять случайные features.

### M3 — Retention

Для первой небольшой выборки:

- минимум 5 активированных стримеров;
- минимум 3 провели вторую сессию в течение 14 дней;
- включение второй сессии не было персонально запрошено разработчиком;
- для каждого не вернувшегося стримера известна классифицированная причина.

После 20+ активированных стримеров основной показатель — процентный:

> Second Session Rate ≥ 30%.

Порог является стартовой гипотезой и пересматривается только после накопления
данных, а не ради объявления milestone достигнутым.

---

## R7 — Second Manager Integration and CK3 Decision

### Цель

Проверить, действительно ли архитектура уменьшила стоимость следующей integration.

### Сначала

Подключить вторую уже существующую integration через Installation Manifest.
Это отделяет проблемы Manager architecture от сложности создания новой игры.

### Затем — CK3 decision gate

CK3 начинается, только если:

- onboarding выбранной первой integration стабилен;
- M1 достигнут;
- alpha дала реальные viewer actions;
- добавление второй существующей integration не потребовало переписывания core;
- CK3 не откладывает исправление подтверждённых retention blockers.

### Метрика архитектуры

Для каждой integration учитывать:

- часы core-platform работы;
- часы game-specific работы;
- количество новых backend/frontend concepts;
- количество hard-coded веток в Manager;
- число integration-specific support incidents.

Цель направления — приблизиться к `80% platform / 20% adapter`, но не подгонять
разные игровые модели под ложную общую абстракцию.

---

## R8 — Monetization Validation

### Условие старта

Монетизация включается после доказанной технической активации и первых сигналов
retention. Она не должна маскировать плохой onboarding.

### Модель первого эксперимента

#### Free

Полноценный core experience, достаточный для регулярного использования и роста
viewer network.

#### Pro

Стартовая ценовая гипотеза: `$7.99–9.99/month`.

Кандидаты в Pro только при доказанной дополнительной ценности:

- advanced streamer configuration;
- analytics;
- automation;
- advanced economy controls;
- expanded customization;
- management нескольких integrations.

### Trial

- 30 дней Pro без обязательного ввода оплаты;
- цена видна до начала trial;
- окончание trial приводит к downgrade to Free;
- viewer state и core history не удаляются.

### События

```text
trial_started
trial_expiring
trial_expired
pro_checkout_started
pro_started
pro_renewed
pro_payment_failed
pro_cancelled
free_downgrade_completed
```

### Milestones

1. Первый платящий незнакомый стример.
2. `$100 MRR` и покрытие инфраструктуры.
3. `$500 MRR` и подтверждение повторяемой маленькой экономики.
4. Около `$1000 MRR` — оценка stability, churn, runway и support load.

Broadcaster billing реализуется вне viewer Extension experience. Viewer commerce
внутри Extension в будущем использует разрешённый Twitch Bits flow.

---

## R9 — Platform and Ecosystem Transition

### Условие старта

Не раньше появления одновременно:

- устойчивого retention;
- нескольких integrations;
- внешнего интереса разработчиков/modders;
- доказанного повторяющегося integration contract.

### Возможные работы

- Integration SDK;
- reference integration;
- compatibility test kit;
- signed integration packages;
- verified integration status;
- documentation and samples;
- bounties/contractors;
- attribution/revenue-share experiments;
- community support process.

### Definition of Done направления

Внешний разработчик способен создать тестовую integration без изменений core
backend, core Manager и viewer identity model, а ShedLink способен проверить и
безопасно распространить её пакет.

---

## 6. Product dashboard

### Acquisition and setup

- Manager downloads;
- unique Manager starts;
- authenticated streamers;
- game detection success rate;
- install success rate;
- median/p95 TTTR;
- support incidents per setup.

### Activation

- Technical Ready rate;
- Extension activation rate;
- first viewer open/join/action;
- activation rate;
- median TTFVA.

### Engagement and retention

- active streamers 7d/30d;
- active viewers;
- viewer actions per stream;
- Second Session Rate;
- D7/D30 streamer retention;
- returning viewer rate.

### Reliability

- connected/disconnected mods;
- errors by integration/version;
- queue depth and oldest item age;
- duplicate/retry/refund counts;
- p95/p99 latency;
- critical incidents;
- version mismatch rate.

### Business

- trials;
- trial-to-Pro conversion;
- paying streamers;
- MRR;
- churn;
- infrastructure cost;
- MRR minus infrastructure cost;
- support time per paying streamer.

---

## 7. Приоритеты backlog

### P0 — немедленный блокер внешнего использования

- data loss/corruption;
- cross-channel access or effects;
- auth/authz bypass;
- double spending/reward;
- потерянный charge/refund;
- replay необратимого действия;
- unsafe installer/update;
- немодерируемый пользовательский контент, нарушающий review requirements.

### P1 — блокер M1/activation/reliability

- install/config blocker;
- reconnect/restart failure;
- stuck queue/state;
- version mismatch без безопасного отказа;
- непонятная диагностика;
- значимый onboarding drop-off;
- отсутствие telemetry для ключевого шага.

### P2 — retention и support cost

- recurring UX friction;
- advanced diagnostics;
- high-frequency viewer/streamer requests;
- polish, влияющий на понятность и возврат.

### P3 — идеи

- дополнительные игры без подтверждённого спроса;
- marketplace;
- большой SDK;
- сложная организация;
- инфраструктурные переписывания без измеренного trigger.

---

## 8. Что не делать до соответствующего gate

- не строить универсальный Steam/CurseForge;
- не начинать CK3 до стабильного onboarding;
- не добавлять много игр ради KPI;
- не мигрировать с SQLite без измеренного contention;
- не вводить microservices/Kubernetes ради архитектурного вида;
- не строить сложный billing до willingness-to-pay;
- не выпускать публичный SDK до повторяемого внутреннего контракта;
- не считать clean install успешным после ручного исправления;
- не считать M1 достигнутым по установке только у автора;
- не смешивать технические логи и product analytics;
- не хранить secrets в Twitch configuration segments или diagnostic bundles.

---

## 9. Правило выбора следующей задачи

Каждая крупная задача должна улучшать хотя бы одно:

- activation;
- retention;
- support cost;
- reliability;
- monetization;
- стоимость добавления integration.

Для задачи фиксируются:

```text
Expected outcome
Metric affected
Evidence required
Owner
Dependencies
Rollback or safe failure
Definition of Done
```

Если задача не влияет ни на один показатель, она остаётся допустимым творческим
экспериментом, но не вытесняет критический путь.

---

## 10. Ближайшая очередь работ

Практический порядок после закрытия R0, production `Technical Ready` и
Update/Repair rehearsal:

1. Подготовить versioned alpha-пакет Manager и короткую инструкцию.
2. Проверить пакет вне repository без установленных dev tools.
3. При доступной чистой Windows-среде провести matrix и три clean-install.
4. Передать пакет первому внешнему тестировщику и измерить TTTR.
5. Исправить измеренные onboarding blockers, затем провести five-streamer alpha.
6. Сделать offline backup production signing key на имеющийся отдельный носитель;
   это операционная защита, но не блокер текущей alpha-подготовки.
7. Провести 10–20 streamer beta и capacity test.
8. Проверить retention и только затем расширять integrations/monetization.

---

## 11. North Star

На ближайшее время:

> Незнакомый стример самостоятельно устанавливает ShedLink, получает первое
> действие зрителя, включает ShedLink снова и оставляет его частью стрима.

После достижения:

> Первый незнакомый стример платит, потому что ShedLink создаёт регулярную,
> понятную ему ценность.

Долгосрочно:

> Автор определяет направление ShedLink, но не является обязательным участником
> каждой установки, поддержки, сессии и новой игровой интеграции.
