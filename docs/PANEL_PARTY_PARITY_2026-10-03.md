# Панель Preact: свита, затем клан/отряд/армия

## Замороженный срез A: вся карточка «Свита»

Исходники `3f67c38`, финальные проверки `f593be3`. Реализована вся видимая карточка перед развитием героя: состав/тир/элита, серверный лимит, basic/elite найм либо upgrade, массовая тренировка с приблизительной ценой, золото, общий серверный cooldown найма, отдельный cooldown тренировки, раскрытие и телеметрия. Production entrypoint использует её через настоящий PanelApp/HeroDevelopmentView; отдельного bodyguard-функционала нет.

### Контракт и доказательства

- Эталон — текущие неизменённые 23 скрипта `Расширение/frontend/` в настоящем jsdom/VM; добавлен только выбранный host `bnr-retinue-slot`. Полный chronological trace содержит метод/path/query/body/JWT/cache, shell stats/level/duels, action tail 3500 ms, скрытую страницу, оборудование, боевые и общие polls, usage. Не фильтруем записи. Нормализация только случайных action/batch ID
- `test/panel-fixtures/generate-party-responses.py` вызывает настоящие наружные HTTP handlers на временной SQLite с полными миграциями; `RIMWORLD_PRICES_PATH` задан до imports. 63 формы ответов для A/B и будущего отдельного вассального среза. `fixture_*` — явно засеянные локальные идентичности, не данные текущей игры. Наличие заготовок вассалов не означает реализованного UI
- Сначала `857e3e7`: новые DOM/parity тесты красные, 16 failed/1 passed, отсутствующие controls. `f6913f4`: дополнительный red stale-handler test действительно отправлял лишний POST. После реализации: 32 focused tests зелёные
- По одному controlled mutation на каждое request family: инверсия `is_elite`, неверный action type тренировки. Также снятие stale hero-context guard. Каждый exit 1; byte-exact восстановление собственного backup, одинаковый SHA256; после восстановления общий прогон зелёный
- Все unit/DOM: **506 passed**, 2 opt-in HTTP skipped; отдельный свежий изолированный real HTTP: **2 passed**. Typecheck, build и check-build exit 0. `minify:false`, source maps/readable Preact/licenses сохранены
- `measure-build.mjs`, gzip -9 каждого файла отдельно: panel-mobile initial **157264 raw / 44018 gzip bytes**. Это import closure с HTML/CSS/JS без внешнего Twitch Helper, HTTP responses и sourcemaps. Полный список файлов в evidence

### Намеренные безопасные отличия

1. Пустая свита при gold 0→500000 больше не остаётся неактивной. Старый renderer кешировал только `retinue:[]`; новый вывод зависит также от gold/cap/config. Отдельный тест оставляет старый oracle красным именно по исправляемому поведению, HTTP parity проверяется независимо
2. Без серверных цен/множителя или лимита действия недоступны, есть «Обновить цены свиты» с настоящим no-store config GET. Нет подстановки пяти слотов либо бесплатной цены. У legacy оставались fallback numbers
3. Старые обработчики не отправляют действие после наблюдаемой смены героя/личности или остановки. Общий unknown-outcome transport lock сохранён; обычное обновление JWT не ломает живую кнопку. Generic action JWT guard исправлен отдельно родительским checkpoint `fc0dde7`
4. Cooldown refusal карточки показывается на кнопке серверными секундами, без повторного toast, как у legacy. Не подменяем queue-success игровым применением

### Неизменённые ограничения server contract

Максимумы basic tier 5 / elite tier 6 и расчёт приблизительной тренировки унаследованы от старого UI, а не выданы за серверные authoritative quotes. API не экспортирует `can_recruit/can_train/max_tier` или точные UpgradeTargets. Их проверяет игра; её поведение не доказано этими тестами. Цены и cap берём только из ответа. Возвраты/поздние отказы остаются общим механизмом панели.

## Завершённый локальный срез B: клан, свой отряд и армия

Исходники `80ad0b6` + telemetry fix `41d3477`, финальные тесты `b5108ab`. Production `main.tsx` включает новый раздел «Клан, отряд и армия»; сохранённый `bnr_active_tab=dynasty` восстанавливает его. Это ограниченный полный путь управления этими механиками, а не завершение всей Династии.

- Clanless: создать клан с необязательным именем до 32 символов; вступить по непустому имени до 64 символов; trim/Enter, преждевременные повторные клики, сохранение черновиков при poll/config retry
- Member и leader: две точные версии предупреждения перед выходом; исходные Yes/No controls. Лидерская карточка показывает название, tier/renown/число героев/отрядов/поселений; создание отряда либо существующее число clan parties
- Все шесть приказов `siege/defend/raid/garrison/patrol/recruit`: active/released/expired/none, текущая задача партии, сортировка и фильтр реальных own/enemy settlements, preselection, известный пустой список либо отсутствующий список с ручным вводом, minimum 3 символа, назначение и release
- Армия: исходный kingdom gate, create и подтверждаемый disband; никаких новых army API или выбора участников. Карточка идёт после приказов, как в текущем frontend
- Настоящие reads только в активном видимом разделе для alive clan leader. Закрытая наружная карточка не отключает чтения. Открытый editor переживает обычный poll. Дополнительные action tails 1500/2000/3500 ms, включая разрешённые explicit reads скрытой страницы, сохранены с lifecycle/identity/JWT ownership
- Показаны точные server messages и общие refunds; queue-success не означает применение в игре. Общий unknown-outcome lock блокирует также свиту/снаряжение/развитие/бой
- Семья, наследование, вассалы, королевство, дипломатия, кузница и остальные dynasty-карточки не входят и не монтируются наполовину

### Финальные проверки B

| Проверка | Результат |
|---|---|
| Все frontend-next unit/DOM на `b5108ab` | **584 passed**, 2 opt-in HTTP skipped |
| B focused | **78 passed**: 32 parity + 46 safety |
| Свежий изолированный real HTTP после финальной сборки | **2 passed** |
| Legacy frontend aggregate | **17/17**, exit 0 |
| Typecheck + build + check-build | exit 0 |
| `git diff --check`, защищённые области, lockfiles | чисто |
| panel-mobile initial import closure | **184297 raw / 50336 gzip-9 bytes** |

Сначала committed red `de057bc`: 23/23 отсутствующих экранов/путей. Затем `0964f67`: red устаревшего hero-completion, который мог начать уже новый party read. `7dfcd88`: 4 red real collector traces обнаружили потерянные details exposures; исправление `41d3477`. Тесты/контроллер/реальный HttpPanelTransport/IdentityBootstrap связаны через настоящий PanelApp; первый быстрый ввод+Enter не теряет имя. Старые 23 scripts выполняются неизменёнными, выбранные Dynasty body/marker/slots сохраняют настоящую details binding, без соседних feature hosts и без фильтрации HTTP.

Независимый обзор `41d3477`: 566 общих тестов (60 B на том SHA), types/build/check-build/diff exit 0, размер тот же; дополнительных замечаний нет. Независимый target-list-change probe подтвердил блокировку устаревшего выбора. Финальные 78 B / 584 общих — более поздний `b5108ab`, не приписываем их более раннему обзору. Независимый A обзор исходника `3f67c38` проверял 504 общих; две последующие проверки дали 506 в замороженном A `2057909`.

### Исправленные старые frontend defects и честные исключения паритета

1. Legacy party responses действительно могут применяться в обратном порядке и рисовать после `_stopBannerlordPolling`. Отдельные тесты исполняют оба старых дефекта; Preact применяет ответы монотонно без starvation и отбрасывает старые ownership/context/token. Игнорируемое старое hero-completion больше не запускает новый запрос для следующей личности
2. Legacy army confirmation действительно отправляет POST уже с изменённым JWT после stop. В Preact подтверждение привязано к наблюдаемым hero/clan/kingdom/army/quote и поколению host, проверяется также непосредственно на Yes, закрывается при изменении/навигации/teardown. Добавлены безопасные Escape/backdrop dismissal, focus/restore и keyboard trapping. Невидимая смена game session при полностью одинаковых экспортированных полях остаётся неразличимой: API не даёт session/army ID
3. Legacy локальные 1.5s/2s callbacks действительно читают с новым JWT после stop. Новые callbacks принадлежат исходному поколению/герою/клану/токену; same-user idle refresh не делает текущие кнопки мёртвыми
4. Legacy recruit оставлял select и отправлял `target_settlement_name='— нет доступных целей —'`. Исправленная форма скрывает цель и отправляет обе target строки пустыми. Это **намеренное изменение одного поля**, а не названный строгим паритет: тест отдельно проверяет старый дефект и полный trace с ровно этим ожидаемым исключением. У остальных пяти приказов декоративное имя `(город, ~2 дн)` сохранено дословно
5. Missing/malformed quotes для create/join clan, create party, army create, party set и известных priced controls закрывают действие с retry. Старые fallback цены не выдаются за серверные

### Мутации B

После commit выполнялись только локальные controlled mutations собственных файлов с собственными backup. Восстановление byte-exact и SHA256 записано; последний общий прогон выполнен после восстановления.

- **8/8 request families убиты, exit 1**: create clan, join clan, leave clan, create party, order set, order release, army create, army disband. Мутировали поля/пустое тело фактического POST, не подменяли oracle
- **4 поведенческие мутации убиты, exit 1**: reversed-read fence, danger quote context, scheduled-tail current-token fence, одновременно обе original-token fences pending-action tail
- **1 явно задокументированный survivor, exit 0**: снятие только post-await token check при сохранённом втором check внутри timer. Второй check всё равно блокирует HTTP. Это избыточная защита, не доказательство отсутствия тестирования запрета и не повод портить правильный код ради kill-count
- Итого 12 killed / 1 redundant survivor; [точные мутации и SHA восстановления](evidence/panel-party-2026-10-03/party-mutations.json), все логи сохранены рядом

### Что API не обещает и что не меняли

- `clan_info.parties_count` — число отрядов клана, не доказательство собственного MobileParty. Сохранён inherited create gate; `WarPartyLimit/can_create_party` не экспортируются
- Legacy army UI использует `party_info.in_army`, хотя DTO уже содержит `has_army/army_party_count/cohesion`. Не выдаём наличие данных за старую реализованную функцию. У участника чужой армии disband control сохранён; фактическое лидерство/исход проверяет backend/мод. Не изобретали leave-army action
- `hero.leave_clan` отсутствует в config `action_prices`: UI сохраняет unpriced command, не блокируется по несуществующему quote. Настоящий handler fixture подтверждает `charged:0` крустиков и queued `price:0` без `hero_gold_cost`; эти поля не доказывают новое обещание об эффектах движка
- Для create clan/join/create party outer response тоже `charged:0`, но backend queued payload содержит `hero_gold_cost` 1000000/50000/200000. Не называем эти действия бесплатными. UI передаёт только прежние пользовательские поля + `client_action_id`, без UI-price/cap/username
- DB active party order может предшествовать применению модом; `expires_at` — серверная real-time граница, не выдуманный game-day timer
- Полный backend aggregate в B не запускался и не правился. Известная прежняя asynchronous heartbeat flake остаётся [отдельно описанной](PANEL_CI_FLAKE_2026-10-03.md). Новые fixtures прогнаны настоящими handlers в изоляции; свежие mini-game HTTP тесты проверяют свой ограниченный контур

### Воспроизводимая локальная проверка

1. `/tmp/preact-backend-venv/bin/python frontend-next/test/panel-fixtures/generate-party-responses.py "$PWD"` — новые 63 handler bodies во временной базе; IDs/time естественно изменяются
2. `npm --prefix frontend-next test`, затем `npm --prefix frontend-next run build`
3. `node frontend-next/scripts/measure-build.mjs frontend-next/dist panel-mobile.html`
4. Свежий `scripts/run-skillgames-local.py --allow-local-demo --port 4202` и `LOCAL_TEST_BASE_URL=http://127.0.0.1:4202 npm --prefix frontend-next run test:live` в одном shell; остановить свой server после завершения
5. `npm run test:frontend`. Первый запуск выявил отсутствующий root `linkedom`; declared root dependencies восстановлены через offline `npm ci --cache /tmp/preact-npm-cache --offline --ignore-scripts`, lockfiles не изменились; повторный aggregate17/17 exit0

## Границы проверки и среда

- Документальный поиск: `docs-search.py свита` подтвердил перенос карточки перед progression; `party orders` нашёл `Расширение/docs/ARMY_MVP_SPEC.md`. Историческая спека имеет устаревшие строки про порядок карточек; реальный текущий frontend — oracle
- Browser loopback запрещён, desktop offline: визуальный проход 318 px/телефон/Hosted Test Twitch не выполнялся. Никаких обходов запрета. DOM/HTTP не называем живой игрой
- Первый HTTP запуск отдельным exec не видел loopback server другого exec (ECONNREFUSED); свежий server+tests в одном shell прошёл. Это проверка HTTP CLI, не обход браузерного ограничения
- Legacy frontend/backend (включая их тесты), моды, OBS и frozen ZIP не менялись. GitHub writes/CI, merge/deploy/Twitch/game actions не выполнялись
- [Сохранённые логи, размеры и мутации](evidence/panel-party-2026-10-03/): `retinue-*` — A, `party-*` — B. Никакого remote CI результата для финального B не заявляем: GitHub writes остановлены по текущему указанию
