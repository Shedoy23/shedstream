# Королевство и политика: завершённые локальные карточки Preact

Последний проверенный app/test SHA **03917d7a7312b21190fdd4d7b1a7be183c531cd7** (соседний army/order fix ecfb3f2): **773 unit/DOM +2 real HTTP**,17legacy gates; canonical panel-mobile **219043 raw /57742 gzip-9**. Предыдущий763/K1K2 этап85ad2cd остаётся проверенным, а независимая соседняя армейская находка закрыта в дополнении ниже. Кандидат9b0056f по-прежнему отозван после исходного split-realm замечания.

Работа идёт только в `frontend-next`; публикация GitHub, merge, deploy и Twitch submission заблокированы. Legacy frontend, backend, моды, OBS и frozen ZIP не меняются. Браузер/318 px/телефон/Hosted Test и игровые эффекты не проверены.

## K1: полная карточка «Королевство»

Исходник `5234be7`; red `6eef9c4` (20 отсутствующих экранных/паритетных сценариев) и `7c33215` (37 safety red, 2 уже зелёных absence gates). После исправления ошибочного сравнения whitespace целой модалки каждый её смысловой узел сравнивается отдельно; финальный focused набор **58/58 exit 0**, typecheck exit 0. После точного восстановления каждой из четырёх request-family mutations общий прогон **642 passed + 2 opt-in HTTP skipped**, build/typecheck/check-build exit 0. На этом первом историческом checkpoint K2 ещё не был перенесён; итог обеих карточек ниже.

K1 mutations: create-name, join-name, leave empty-body, hire empty-body — каждый exit 1, побайтовое восстановление своего backup и затем соответствующий focused exit 0. Полные логи и SHA в `docs/evidence/panel-kingdom-2026-10-03/mutations/summary.json`.

Карточка вставлена в существующую Dynasty после клана и перед приказами. Это не новый игровой режим. Информация о королевстве, независимый create/join, восстание вассала, выход и NPC-наём правителя перенесены целиком. Создание вассального клана из наследника сюда не входит. Семья, наследование, upgrades, ransom, workshops, fiefs и caravans не монтируются.

- 23 текущих legacy scripts исполняются неизменёнными в отдельном DOM. Реальные клики/Enter/details/подтверждения идут через их исходные bindings
- Production PanelApp, IdentityBootstrap, HttpPanelTransport и PanelUsage используются новым host. Сравниваются полные хронологические трассы метода/path/query/body/JWT/Content-Type/cache/keepalive, включая 8s/2.5s polling, общий 3.5s hero-tail, stats/level/duels и 30s usage. Нормализуются только генерируемые ID
- `generate-kingdom-responses.py` создаёт изолированный полный SQLite schema и ДО backend imports выставляет временный RIMWORLD_PRICES_PATH. **59 реальных handler bodies**, синтетические fixture IDs, state через настоящий BannerlordAdapter. Action fixtures вызывают внутренний `_bannerlord_buy_action_locked`, не внешний HTTP/JWT wrapper; read handlers получают подменённую тестовую identity. Проверяется форма передаваемого JWT header, не его криптографическая проверка. Это не live-game доказательство
- Create/rebellion требует числовую nonnegative gold quote; NPC hire обе gold+crustics quotes. Нулевые цены допустимы. Retry сохраняет draft. Начальный K1 сохранял legacy join fallback; после независимого замечания он удалён: настоящий config содержит числовой hero_gold_costs.join_kingdom=100000, а missing/null/string/negative теперь блокируют действие с retry без потери имени (red e9671ce → fix b969dd0)
- Короткие price labels повторяют прежний formatter. NPC-confirm показывает полные суммы и проверяет их заново. В запросе только прежние поля плюс client_action_id; нет price/expected_kingdom_id/config_revision/username
- Недостаток сторонников не становится новым frontend запретом: current backend принимает заявку, конечная eligibility остаётся в моде. Prisoner controls сохранены, но переход prisoner-state отменяет уже открытое опасное подтверждение

### Явные безопасные отклонения от старых ошибок

1. Старый leave действительно отправляет запрос с новым JWT после stop. Новый confirm привязан к generation, исходному JWT, hero/clan/kingdom/role/prisoner context и активному host. Проверка непосредственно на Yes защищает также сохранённый DOM callback
2. Старый NPC confirm переживает accepted hero update с другим nested kingdom ID/non-ruler. Новый context берётся из реального `hero.kingdom_info.id`, а не отсутствующего `hero.kingdom_id`; старый confirm/формы сбрасываются
3. Ruler warning теперь прямо сообщает о роспуске королевства, vassal warning о потере владений. Это исправление опасно неполного текста, подтверждённое текущим LeaveKingdomHandler и `docs/BANNERLORD_VIEWER_KINGDOM_AI_2026-09-21.md`, а не изменение игрового действия
4. Escape/backdrop отменяют без POST, focus удерживается/возвращается. Старый helper не имел этих handlers
5. Same-viewer idle JWT refresh сохраняет поля и позволяет новое действие с текущим JWT; уже открытый опасный confirm требует нового согласия. Обычный poll сохраняет имя, наблюдаемая смена realm/role/identity очищает старую форму

### Неразрешимые здесь границы

Нет session ID, expected-context и atomic expected-price/config-revision. Совершенно одинаковая внешне смена игровой сессии и race между локальной проверкой и обработкой сервером не закрываются фронтендом. Широкая quote/eligibility унификация требует backend/mod контракта и вне разрешённого scope. Нулевой `charged` gold-action значит ноль крустиков, а не бесплатный NPC/kingdom.


## K2: полная карточка «Политика»

Source checkpoint `dbc125c`, уточнения prices/feedback `b969dd0` + `ace9e2b`, дополнительные safety checks `07741be`. Red `39d7ba9`:36/36, `c10f56a`:37/37. Первичный K2 focused73/73; далее общий focused K1+K2 вырос до172 сценариев (69 K1 +103 K2). Финальные aggregate/build/HTTP после восстановления mutations приведены ниже.

- Все12 существующих policy IDs/names/descriptions, включая настоящий spelling `policy_land_grands_for_veteran`. Active/pending/removed badge state приходит с сервера; неизвестная active law отображается, но не выдумывает selectable option. Pending не отправляет POST
- Direct peace сохраняет отдельную форму: trim ≥2, тот же введённый текст в обоих target fields, `parseInt(value)||0`, отрицательная дань, отсутствие Enter binding, close-before-submit. Даже20000 остаётся wire20000, server clamp не присваивается клиенту
- Tax0/10/25/50, текущий preset остаётся кликабельным, payload только tax_rate_pct. Не добавлен price/expected-context и не объявлен игровой доход по DB echo
- War/peace-vote берут порядок/IDs/names из hero.kingdom_info.all_kingdoms. Нет static cultures, offered_tribute у vote, оптимистического мира/войны. Separate7s message говорит об отправке на голосование, не выполнении
- Kingdom-state GET следует active/visible Dynasty hero cadence, включая collapsed card. Закрытие/открытие details и30s actual usage trace проверены. Local tails: tax1200ms, policy/direct peace2000ms, war/vote peace немедленно. Общий3500ms hero/build tail только hero.*, не kingdom.*
- Server cooldown только для двух vote buttons: positive finite duration, fractional/zero/missing/unknown key, old-buff action revision barrier, fresh clear, возврат актуальной price label. Generic wrapper исходный JWT guard и viewer-owned buildPending/revision не перенесены в другую область ответственности

### K2 безопасные отклонения

1. Настоящий старый reader откатывает tax при reverse completion и дорисовывает после stop. Новый применяет монотонно успешно завершённые ответы, не starving slow polls; life, JWT и nested realm context удерживаются. Принятая mutation создаёт barrier старым pre-action reads
2. Старые локальные tax/policy/direct peace callbacks начинают GET с новым JWT после stop. Новый проверяет ownership до постановки таймера и при срабатывании. Pending POST/GET после stop+rebind не начинает чужую работу
3. Старый открытый direct-peace переживает принятый другой kingdom/non-ruler и отправляет старую форму. Новая форма очищается при наблюдаемой смене hero/realm/role/identity; normal poll и same-viewer idle token renewal сохраняют draft. Теперь обновляются остальные актуальные данные карточки без широкого legacy freeze, сохраняя сам draft
4. Unknown-price K2 law/direct peace/votes теперь fail-closed с retry. Реальные action_prices есть. Законный числовой0 работает; null/string/negative/missing не превращаются в магическую цену. Normal valid-price HTTP/tails совпадают полностью; исчезновение старого fallback-покупочного действия обозначено как безопасное отклонение. Tax presets и payload прежние
5. Повторный одинаковый успешный vote получил свой полный7s feedback interval: старый timer не гасит новое сообщение. Red03a80e2 воспроизвёл эту новую ошибку и потерянное предупреждение изменившейся NPC quote, fix b969dd0

### Контрактные границы K2

Нет public policy catalog, полной authoritative live-policy snapshot, общего eligibility/reason DTO и atomic expected-context/expected-price. Curated12 descriptions, tax presets и inherited explanatory texts остаются прежними статическими данными. `peace_offers` существуют в GET, но старый UI их не показывал и здесь новый pending widget не выдуман. `kingdom-state` не имеет wars: target catalog из nested hero DTO согласуется с realm ID. Backend proposal prevalidation слабее mod eligibility; backend/mod вне правки. Ransom и остальные соседи отдельно не завершены.

### Финальные controlled mutations

После последних price/feedback corrections повторены4 K1 request mutations: каждый mutation exit1, own byte-exact restore, соответствующий restored focused exit0. Для K2 выполнены5 request families (law name, direct tribute, tax rate, war name, peace-vote name) и6 guard mutations. **10 killed exit1 /1 redundant survivor exit0**, все11 restored focused exit0. Survivor — удаление только nested kingdom ID из kingdomOwner: независимая проверка совпадения diplomacy-state/hero realm ID продолжает блокировать действие. Это явно не убитая мутация, не повод убирать независимую защиту. Более ранний strict mutation runner остановился на этом survivor, source был восстановлен finally; затем ожидаемый исход зафиксирован и весь набор повторён.


## Исторический прогон 9b0056f: отозван как финальный

Проверки ниже были зелёными на **9b0056fc3a76b3f120bb1b726158943f627c6a26**, но независимый review нашёл наблюдаемый split-realm blocker; этот SHA **не финальный и не принят**. Исправление и повторный итог ниже.

| Проверка | Итог |
|---|---|
| Полный frontend-next unit/DOM aggregate | **756 passed**,2 HTTP opt-in skipped в этом запуске |
| K1 и K2 внутри aggregate | **69 +103 =172** сценария |
| Свежие реальные HTTP мини-игр | **2 passed**; новый disposable SQLite, server+tests в одной exec-сессии |
| Legacy frontend gates | **17/17**,exit0 |
| Typecheck/build/check-build | exit0 |
| Legacy ESLint + globals self-test | exit0 |
| Mobile initial import closure | **217852 raw /57551 gzip-9 bytes** |
| Защищённые frontend/backend/mod/OBS/ZIP и root STATUS/DEFERRED | не изменены этим исполнителем |

Сравнение canonical panel-mobile: предыдущие clan/army184297/50336 → K1 197836/52899 → полный K1+K2 **217852/57551**. Команда `node frontend-next/scripts/measure-build.mjs frontend-next/dist panel-mobile.html`; файл и импортируемые локальные runtime JS/CSS входят, внешний Twitch Helper/API/maps исключены. Прежний черновой sizes-файл случайно использовал default `mobile.html` мини-игр; до финального checkpoint он заменён правильным panel-mobile измерением. Это не mobile load-time тест. `node_modules` — собственный обычный каталог checkout, не внешний symlink. Читаемый unminified build и original source maps сохранены.

Полные логи и machine-readable итог — `docs/evidence/panel-kingdom-2026-10-03/final-verification.json` и соседние файлы. Новые quotes0/null/string/missing, реальные отказы, stale ownership, saved Dynasty startup, collapse/details telemetry, pending read/action/rebind и cooldown barriers покрыты. Direct-handler fixtures НЕ проверяют внешний JWT wrapper; отдельный мини-игровой HTTP smoke не превращает их в проверку Bannerlord HTTP auth или игровых эффектов.

Облачный browser loopback ранее denied, компьютер владельца offline. Не обходили эти ограничения. Визуальный318px/телефон, Hosted Test Twitch, использование с настоящим game/mod, атомарность согласия между UI и server/engine ещё не подтверждены. Ни публикации GitHub, ни merge, deploy, загрузки ZIP/Twitch не было. Полностью готовы только перечисленные карточки; оставшаяся Dynasty и остальные области панели отдельно.


## Независимо найденное расхождение realm/role

Независимый probe на07741be показал: свежий kingdom-state другого королевства отбрасывался `return {}`, оставляя старую actionable ruler state. Это наблюдаемое расхождение двух API, не «невидимая session смена». Свежий non-ruler ответ того же realm также не отменял K1 NPC/leave consent. Дополнительный hero update мог стирать quarantine раньше согласования.

Red **e09d3b5** воспроизвёл6/6 таких отправок/незащищённых состояний. Fix **38beb21** хранит последнюю принятую diplomacy observation даже при расхождении, карантинит K1 и K2 mutations и очищает опасный consent/draft. Сравниваются realm presence, nested ID и наблюдаемые ruler/clan-leader роли. Quarantine не теряется при следующем hero update и снимается только когда оба источника согласованы. Пока diplomacy read ещё вовсе не было, K1 не блокируется; это отдельно проверено. Genuine nohero по-прежнему очищает Politics slot, а K1 остаётся закрыт при известном противоречии.

Тестовая поддержка теперь по умолчанию выбирает согласованные настоящие hero/kingdom handler fixtures для independent/vassal/ruler/other. Противоречие задаётся явно в специальных тестах, а не наследуется случайно от дефолтного ruler. Ни одно ожидаемое нормальное request поле или tail для этого не нормализовано. Полный focused после correction **179/179 exit0**, typecheck0. Дополнительные3 mutations возвращают discard observation, premature clear и K1 admission bypass. Все3 новые mutations убиты exit1 и побайтно восстановлены; полный набор и aggregate повторены, итог ниже.


## Проверенный этап K1/K2 до соседней армейской правки

Проверенный source/test **85ad2cd9aa6a03d6a031efc77be2e802c74eda31**, runtime fix **38beb21**. Полный aggregate после последнего byte-exact restore: **763 passed**,2 opt-in skipped. Затем новый отдельный disposable HTTP server на loopback4295 запущен и оба mini-game HTTP tests исполнены в той же exec-сессии: **2 passed**; сервер остановлен. **17/17** legacy gates, typecheck/build/check-build, ESLint/globals и diff check — exit0. K1 **74**, K2 **105** (вместе179) included unit/DOM scenarios. Старые756/217852/57551 относятся исключительно к отозванному9b и не являются последним результатом.

Все4 K1 и5 K2 request-family mutations после correction снова дали exit1, own byte-exact restore и green0. С учётом guard mutations: **17 killed +1 redundant survivor;18 verified restores и18 соответствующих green runs**. Новые3 guards отдельно доказывают, что свежую противоречивую observation нельзя отбросить, преждевременно стереть при hero update или обойти в K1 admission. `diplomacy-mutations-quarantine/summary.json` + `kingdom-mutations-quarantine/summary.json` — окончательные summaries.

Canonical `panel-mobile.html` import closure **218909 raw /57729 gzip-9 bytes**, отдельный Helper/API/maps не входят. Команда и полный список файлов — `kingdom-quarantine-final-sizes.json`. Source/tests после последнего прогонa не менялись; завершающий commit сохраняет только этот report и доказательства. Final machine-readable record — `final-verification.json`; более ранний record переименован `superseded-9b0056-verification.json` и относится к кандидату, отклонённому независимым обзором.

Независимое замечание не замолчано: исходный механизм, committed red, исправление, дополнительная защита K1 и повторный полный прогон сохранены. Browser318px/телефон/Hosted/game и atomic consent остаются честными ограничениями. GitHub publication/merge/deploy/Twitch submission не выполнялись.


## Соседняя безопасность армии и приказа: bounded follow-up

Независимый executable probe показал, что уже открытое подтверждение `army_disband` ещё отправляло POST после принятого kingdom-state другого realm. Дополнительный проверенный сценарий обнаружил такое же поведение у открытого party-order editor со старым own/enemy target catalog. Это было наблюдаемое противоречие, а не неизвестная game session. Старое поведение действительно исполнено неизменённым legacy DOM, новый POST до фикса тоже зафиксирован.

- Red **ddd523e**:6 армейских сценариев упали,2 независимых no-observation/retinue сценария уже были зелёными. Red **709ccfa**:1/1 открытый order editor отправил старую enemy target
- Fix **ecfb3f2** добавляет один узкий общий admission gate в `partyAllowed`: во время `kingdomConflicted` недоступны только `hero.army_create`, `hero.army_disband`, `hero.party_order_set`. Существующий confirmation lifecycle отменяет старый army consent и повторно проверяет saved Yes непосредственно перед отправкой
- Согласование snapshots восстанавливает кнопки и редактор; старое army согласие не оживает, нужен новый confirm. До первого diplomacy observation прежние корректные army controls остаются доступны
- Order cancellation/release, clan leave и retinue recruit не блокируются этим gate и исполнены отдельными тестами. Общий `mutationBlocked` не используется как подмена такого узкого запрета. Ни transport.ts, ни отдельный policy transport worktree не менялись
- Паритетное окружение party теперь получает согласованный **настоящий** `my_kingdom_state` response для исходного Vlandia fixture, а не случайный ruler другого fixture realm. `generate-party-responses.py` добавляет ровно этот read; временный SQLite/config изолированы до imports, **64 handler bodies**. Wire assertions не ослаблены, oracle scripts не изменены

После последнего собственного byte-exact restore: **773 unit/DOM passed +2 отдельно исполненных fresh real HTTP**, **17/17** legacy gates, typecheck/build/check-build и lint/globals exit0. Новый server4296 и HTTP tests работали в одной exec-сессии на новом disposable SQLite, затем server остановлен. **10** новых adjacent cases, прежние179 K1/K2 cases остаются зелёными. Controlled mutations удаляли каждый из3 gate членов отдельно: все **3 exit1 → own exact restore → focused exit0**, summary в `army-quarantine-mutations/summary.json`.

Проверенный source/test **03917d7a7312b21190fdd4d7b1a7be183c531cd7**; canonical panel-mobile **219043 raw /57742 gzip-9 bytes**. Raw logs `army-quarantine-*`, новый итог `final-verification.json`, прежний корректный763/K1K2 record сохранён побайтно как `verified-k1-k2-stage-85ad2cd.json`. Последующий report commit не меняет app/tests. Backend/legacy/mod/OBS/ZIP и публикация не затронуты; Browser/318px/phone/Hosted/game остаются неисполненными проверками.
