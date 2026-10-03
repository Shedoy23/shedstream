# Полный перенос панели: локальный результат

Локальная финальная поставка после независимого re-review. По сообщению родителя,
замечание Colony remount закрыто, новых дефектов runtime `6a048385` относительно
`e5ab10e` не найдено. Reviewer читал код и предоставленные доказательства;
собственных прогонов не выполнял. Проверенный checkpoint `23aca6b` дополняется
только документами и финальным HTTP evidence; runtime остаётся тем же.
Архив — новый согласованный компактный экспорт финального checkpoint, не старый e5
плюс частичная дельта. Полный frontend-next и build доступны непосредственно;
полный Git tree восстанавливается из точной исходной базы через вложенный patch. Точные HEAD/tree/состав/хеши находятся в DELIVERY.json.
Узкий разбор: [Colony remount](PANEL_COLONY_REMOUNT_REVIEW_2026-10-03.md);
привязка проверок: [финальный checkpoint](PANEL_FULL_PORT_FINAL_CHECKPOINT_2026-10-03.md).

Подготовлена общая Preact-сборка для ПК и телефона: оставшийся Bannerlord,
общие разделы, RimWorld, ShedColony, оболочка и streamer config. Таблица
«раздел / перенесён / parity / мутация / скриншот» находится в
[COVERAGE](PANEL_FULL_PORT_COVERAGE_2026-10-03.md), сверка каждой группы старых
кнопок — в [RECONCILIATION](PANEL_FULL_PORT_RECONCILIATION_2026-10-03.md).

Действующая кнопка принятия **социального** брака оставлена заблокированной
с объяснением: сервер выбирает последнего заявителя вместо выбранного.
Это не касается браков детей Bannerlord. Сервер не исправлялся.

После независимого review промежуточного `f00c7f0` исправлены три дефекта UI:
зависание RimWorld после JWT refresh, starvation медленных Colony polls и
ошибочное превращение определённого pre-action 429 в неизвестный исход.
История red→green и границы доказательств: [REVIEW](PANEL_FULL_PORT_REVIEW_FIXES_2026-10-03.md).
Артефакты `f00c7f0` сохранены как промежуточные и не являются этой сдачей.

Остаётся унаследованное ограничение Voting: потеря ответа на взнос допускает
ручной повтор, а API разрешает повторные взносы. Возможен двойной платёж;
автоматической сверки исхода и idempotency в этом контракте нет. Это не объявляется
исправленным или безопасным повтором; сервер в данной задаче не менялся.

## База и границы

- Изолированный checkout `shedstream-full`, ветка `feature/panel-preact-full`.
- Исходная подтверждённая база: `b2064f4b045025d33d05aaf166ca1694ae0f5475`.
- Разрешённый владельцем локальный merge `e66e82098f894bc8f6e0dbe9598ddf2516088636`
  импортировал progression `1682ebf4823a548162e1687a47a60d4292c3c7f7`.
  Конфликты и устранение дублирования M134 описаны в
  [MERGE](PANEL_FULL_PORT_MERGE_2026-10-03.md).
- После merge не изменены backend, моды и старый frontend. В `Расширение/`
  менялся только документ передачи контекста. Пользовательский checkout и
  чужие ветки не перезаписывались.
- Push, GitHub writes, PR, удалённый merge, deploy, Twitch submission не выполнялись.
- Точный экспортируемый HEAD, SHA-256 и размеры файлов фиксируются в
  `DELIVERY.json` внутри пакета; сам отчёт не создаёт самоссылочного хеша коммита.

## Проверки

| Проверка | Результат / evidence |
|---|---|
| Полный suite | **1251 passed / 2 skipped**, 63 файла passed, exit0,373.85s; review-colony-remount-full-suite-green.log, CLI timeout30s |
| Два opt-in HTTP теста | На checkpoint23aca6b / runtime6a048385: **2/2 passed**, exit0,19.66s; final-reviewed-http.log, новый одноразовый loopback4180 |
| Typecheck/build/CSP/maps | exit0; review-colony-remount-build.log |
| Legacy gates | **18/18**, exit0; review-colony-remount-legacy.log |
| ESLint / globals / consistency | Все exit0; review-colony-remount-eslint.log / globals.log / consistency.log |
| Мутации | **57/57** red1→green0, problemNamed=true, SHA восстановлены; mutations/verification.json |
| Браузер | **188 снимков, 0 ошибок, 0 external**, exit0; review-colony-remount-browser.log + browser/verification.json |

Базовые 53 мутации дополнены тремя probes первого review и owner/JWT probe второго.
Мутации изменённых файлов повторены после исправлений; все 57 записей имеют red1→green0, problemNamed=true
и восстановленный SHA-256 текущих исходников. Ранний inherited runner имел
ошибку текстового маркера кузницы; диагностический лог сохранён, исправленный
повтор дал exit0. Ни один surviving mutant не считается успехом.

Браузер: Chromium **145.0.7632.6**, Playwright **1.58.2**, реальный локальный
loopback-стенд с fixtures. **188 снимков**, 1280 и 375 px, **0 page errors /
0 external requests**, sandbox включён, CSP bypass выключен. Использованы
оба фактических входа: `panel-extension.html` и `panel-mobile.html`. Скрипт
проходит разделы кликами, подтверждения и локальные формы. Проверенные снимки
находятся в `evidence/full-port/browser/verification.json`; лишние старые PNG
в каталоге не включены в число 188.

После второго review просмотрены свежие colony-jwt-resolving-375 и
colony-unknown-after-jwt-375: игры нет в resolving; после ready объяснение
неизвестного исхода видно, платные кнопки отключены. На1280/375 сервер получил
ровно один POST до remount и один суммарно после попытки повторного клика.
После первого review просмотрены colony-confirm-375 и rimworld-pawn-375.
Предыдущая проверка глазами: сгруппированные навыки 375 px, PNG-питомец
1280 px и свёрнутая панель 375 px. Предыдущие срезы отдельно проверяли игровые
формы, династию, RimWorld и мини-игры. Не утверждается, что визуально просмотрен
каждый PNG или каждый вариант каждого игрового состояния.

Изначальный финальный suite дал **1213 passed / 1 failed / 2 skipped**:
тест двух полных DOM и минуты polling превысил стандартные 5 секунд при
одновременном браузере/build. Лог `final-suite.log` сохранён. Локальный timeout
этого тяжёлого файла расширен до 30 секунд, assertions не ослаблялись.
Отдельный повтор с шестью дополнительными сценариями дал **21/21**.

После Colony remount первый свежий suite дал **1249 passed / 2 failed / 2 skipped**:
неизменённый telemetry-тест превысил 5s; следующий дал trace mismatch. Изолированный
файл с прежним лимитом прошёл8/8. Общий повтор с CLI `--testTimeout=30000` прошёл1251/1251;
assertions не ослаблялись. Причинность второго падения отдельно не доказана.
Все логи сохранены. Десять новых whole-shell сценариев прошли вместе с затронутыми
Colony/bootstrap/controls тестами: **86/86**. Подробности и пределы защиты:
[Colony remount review](PANEL_COLONY_REMOUNT_REVIEW_2026-10-03.md).

Первый новый browser run с обрывом HTTP до первых байтов ответа получил6 POST
и завершился exit1. Диагностический probe без приложения подтвердил транспортный
повтор: один fetch → два одинаковых POST. Финальный probe обрывает начатый JSON
после полного получения POST; в нём1 POST до/после remount. Логи обоих режимов
сохранены. UI guard не решает транспортные повторы, полный reload или серверную
идемпотентность; наличие client_action_id само по себе не доказывает дедупликацию.

Найденный пробел прежнего equipment harness воспроизведён красным тестом:
отсутствовало исходное тело запроса. Теперь сравнивается raw JSON, а мутация
порядка полей отдельно проверяет, что parsed JSON не маскирует расхождение.

## Parity и осознанные отличия

Oracle исполняет неизменённые старые JS. Сравниваются полный trace выбранного
host, method/path/query, raw JSON, JWT, cache, polling, delayed tails и usage.
Отдельный whole-shell oracle запускает настоящий DOMContentLoaded/onAuthorized
и совместный host каждой игры, проверяет 1–5 минут, JWT, hidden, module off,
общий баланс, Dynasty/collapse и дополнительные consent clicks. Матрицы
действий разделов и whole-shell сценарии дополняют друг друга; не каждый
возможный вариант формы прогнан с целой оболочкой.

Кроме исходно принятого `expected_item_id` кузницы, отличия имеют узкие
тесты и причину в коммите. Непроизвольные ID нормализуются, тело запроса
не пересобирается для сокрытия порядка полей. Основные осознанные отличия:

- Новые платные подтверждения добавляют настоящий click в `/activity`.
  Whole-shell проверяет TTS, гильдии, голосование, Colony heal, питомца,
  progression, закон, покупки Bannerlord/upgrade/reequip/выкуп и RimWorld.
- Старый switchTab читает два RimWorld GET даже на Bannerlord/Colony.
  Новый UI читает активную игру. Harness перед исключением проверяет
  **целиком две конкретные соседние строки**, остальные сравнивает без фильтра.
- Game-owned каталоги/котировки заменяют старые локальные культуры, workshop
  types, policies, focus/attribute/XP тарифы. Скрытые cap детей/вассалов/bulk
  upgrades не изобретаются; неизвестный отказ показывает ответ сервера.
- Цена предложения брака детей берётся из config вместо старого literal100.
- `_bnrConfirm` старой панели всегда разрешает возрождение; новая форма
  действительно предупреждает и допускает отмену.
- Старый notice ack мог потерять второй/третий отложенный toast. Новый UI
  показывает весь подтверждённый batch сразу, HTTP порядок сохранён.
- Realtime отписывается при смене identity/channel, отбрасывает старые
  callbacks и использует событие только как повод перечитать API.
- Канат понимает реальное server `queued`; невыпущенные taps отменяются
  при закрытии, старый UI отправлял их позднее в уже невидимую комнату.
- RimWorld не копирует выдуманные 5min event lock и 900s heal cooldown.
  Показывает pending до актуального серверного ответа; восстановлена кнопка
  ручного refresh, которую старый renderer удалял.
- В выбранном Dynasty host допустима только описанная соседняя перестановка
  независимых initial catalog/stats GET: медленный kingdom-state не должен
  блокировать hero. Whole-shell порядок проверен отдельно.

Полные детали, включая inherited exceptions, находятся в тестах и DEFERRED.

## Непереносимое без изменения контракта и найденные дефекты

1. **Social marriage accept — блокер кнопки.** Реальный
   `POST /api/marriage/accept` игнорирует `from_user`, выбирает
   `ORDER BY created_at DESC LIMIT 1`. При Bob→Alice, затем Carol→Alice
   запрос с Bob женит Alice на Carol. Доказательство —
   `social-family-responses.json: accept_wrong_target` и тест
   `social family blocks accept because real route ignores chosen proposer and marries another user`.
   Нужен серверный выбор конкретной заявки в транзакции. Даже одна видимая
   заявка не защищает от появления другой между показом и POST.
2. **RimWorld current xenotype/metabolism.** `my-pawn` не публикует эти данные
   и `is_overridden`; UI сообщает отсутствие данных, не угадывает их по генам.
   Выбор и покупка каталожного ксенотипа перенесены.
3. **Атомарная идентичность/цена.** Pet unequip и старый equipment/legacy
   discard могут принимать только slot; ряд RW покупок не принимает
   expected_price/pawn generation; social divorce не принимает expected partner;
   вассалы/выкуп/bulk upgrades и Colony targets не имеют нужного expected-context
   во всех ручках. Локальные guards связывают выбор с показанным объектом и
   отменяют устаревший consent, но не закрывают серверную гонку после POST.
4. **Унаследованная свита.** API даёт recruit prices/cap, но не готовые
   UpgradeTargets и точную bulk training quote. Сохранена прежняя явно
   приблизительная оценка с inherited tier5/6 eligibility. Это не доказательство
   точной game-owned цены/лимита для модовых troop trees. Совместить абсолютное
   требование тонкого клиента с полным сохранением этой функции без расширения
   контракта нельзя. Самостоятельная серверная/модовая правка не выполнялась.

Первоначальные блокеры культур и мастерских сняты **разрешённым merge** и
fixture/DOM/browser проверками, а не выдуманным клиентским каталогом.
Старая общая вкладка Shop была заглушкой; рабочий shop.js перенесён в RimWorld.
Ручные duel invitations и fief boost уже отсутствовали в действующей старой UI;
новые функции поверх мёртвого кода не добавлялись.

## Размеры

Node zlib gzip level 9, десятичные байты, каждый файл сжат отдельно. Источник:
`evidence/full-port/review-colony-remount-sizes.json` и фактические browser startupAssets.

- Static import closure панели: **46 874 gzip / 162 830 raw**.
- Фактический Bannerlord startup до первого клика: **107 592 gzip / 418 931 raw**
  для ПК и 375 px; учтены немедленные Common/Bannerlord/Tournament imports.
- Бюджет **150 000 gzip** соблюдён. Source maps, API JSON и неизменённый
  Twitch Helper не считаются локальными initial assets.
- Исторические 29 656 относились к отдельному skillgames `mobile.html`;
  ошибочная ранняя подпись исправлена. Это не размер панели.

| Lazy entry | Raw JS | Gzip JS | Raw CSS | Gzip CSS |
|---|---:|---:|---:|---:|
| src/colony/ColonyView.tsx | 14155 | 4450 | 3551 | 1268 |
| src/common/CasesView.tsx | 4745 | 1844 | 0 | 0 |
| src/common/CommonView.tsx | 13002 | 3885 | 3551 | 1268 |
| src/common/CommunityGamesView.tsx | 20013 | 5730 | 0 | 0 |
| src/common/GuildsView.tsx | 11459 | 3183 | 3551 | 1268 |
| src/common/PetsView.tsx | 9822 | 3182 | 3551 | 1268 |
| src/common/SocialFamilyView.tsx | 7834 | 2624 | 0 | 0 |
| src/common/StatisticsView.tsx | 2364 | 1000 | 0 | 0 |
| src/common/VotingView.tsx | 11492 | 3664 | 3551 | 1268 |
| src/common/bannerlord-entry.tsx | 226064 | 50644 | 8995 | 3002 |
| src/panel/TournamentPanel.tsx | 5671 | 2034 | 483 | 315 |
| src/rimworld/RimworldView.tsx | 16546 | 4483 | 0 | 0 |

Это размеры каждого chunk без повторного суммирования общих зависимостей. Полный manifest и размеры общих JS/CSS/maps лежат в JSON evidence.

`minify:false`, читаемые исходники/карты и проверка Preact-only runtime
сохранены. Новых внешних скриптов нет. Local gzip не доказывает время Twitch
CDN, §3.3 или загрузку на физическом телефоне.

## Не проверено

- Production API/настоящие JWT/списания; серверные и игровые side effects.
- Запущенные Bannerlord/RimWorld/ShedColony и установленный мод.
- Twitch Hosted Test, настоящий Helper/PubSub/chat/network, загрузка CDN <3s.
- Физический телефон, реальный WebView, мобильная сеть, другие браузеры.
- Текущие удалённые версии пакетов/CVE/внешний XSS audit: отдельный аудит
  остановлен ограничениями среды, а не решением владельца; здесь не возобновлялся. Установленные версии и
  lockfiles проверены локальной сборкой; свежесть в registry не утверждается.

Проверки не обращались к production. Два opt-in HTTP теста используют
неизменённый локальный runner, временную БД, искусственные identity и реальные
маршруты skillgames; это не end-to-end проверка игровых модов.

## Пакет и продолжение

Финальный компактный ZIP содержит все tracked файлы `frontend-next` в
`sources/frontend-next`, актуальный readable `build/`, отчёты и таблицы,
актуальные browser/мутационные evidence, полный `panel-preact-full.patch`
от исходной базы и `COMMITS.txt` с историей причин изменений. Patch проверен
отдельным Git index до точного tree всего репозитория. DELIVERY.json фиксирует
HEAD, базу, tree, состав и хеш каждого вложенного файла. Старый e5 ZIP не нужен.
Полный checkout требует указанную базу репозитория; архив не содержит повторной
копии неизменённых модов/backend, node_modules, кэшей или старых ZIP.
Большой предварительный экспорт с source.zip/bundle оставлен отдельно как
промежуточный; его частично переданные части не относятся к финальному манифесту.
Инструкция импорта: [Claude](CLAUDE_FULL_PORT_HANDOFF_2026-10-03.md).

Если транспорт Library требует части, они образуют один новый ZIP. Манифест
указывает IDs, порядок, размеры и SHA-256 каждой части и всего ZIP; assembler
проверяет итоговый SHA и CRC. Родитель передаёт пользователю один собранный ZIP.
Промежуточные e5 и review-delta сохраняются, но не заменяют финальный экспорт.
Нет node_modules, локальных БД, настоящих секретов или токенов; fixture credentials
не являются действующими. Library-отчёт обновляется под прежним
`libfile_82edd4f274b081919a6bada8838456b4`. Публикация и установка не разрешены.
