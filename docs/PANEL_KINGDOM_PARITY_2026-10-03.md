# Королевство и политика: локальный Preact checkpoint

Работа идёт только в `frontend-next`; публикация GitHub, merge, deploy и Twitch submission заблокированы. Legacy frontend, backend, моды, OBS и frozen ZIP не меняются. Браузер/318 px/телефон/Hosted Test и игровые эффекты не проверены.

## K1: полная карточка «Королевство»

Исходник `5234be7`; red `6eef9c4` (20 отсутствующих экранных/паритетных сценариев) и `7c33215` (37 safety red, 2 уже зелёных absence gates). После исправления ошибочного сравнения whitespace целой модалки каждый её смысловой узел сравнивается отдельно; финальный focused набор **58/58 exit 0**, typecheck exit 0. После точного восстановления каждой из четырёх request-family mutations общий прогон **642 passed + 2 opt-in HTTP skipped**, build/typecheck/check-build exit 0. K2 ещё в работе.

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

Source checkpoint `dbc125c`, уточнения prices/feedback `b969dd0` + `ace9e2b`, дополнительные safety checks `07741be`. Red `39d7ba9`:36/36, `c10f56a`:37/37. Первичный K2 focused73/73; далее общий focused K1+K2 вырос до172 сценариев (69 K1 +103 K2). Финальные aggregate/build/HTTP ниже добавляются после восстановления mutations.

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
