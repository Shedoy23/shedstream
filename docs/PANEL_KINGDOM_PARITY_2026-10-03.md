# Королевство и политика: локальный Preact checkpoint

Работа идёт только в `frontend-next`; публикация GitHub, merge, deploy и Twitch submission заблокированы. Legacy frontend, backend, моды, OBS и frozen ZIP не меняются. Браузер/318 px/телефон/Hosted Test и игровые эффекты не проверены.

## K1: полная карточка «Королевство»

Исходник `5234be7`; red `6eef9c4` (20 отсутствующих экранных/паритетных сценариев) и `7c33215` (37 safety red, 2 уже зелёных absence gates). После исправления ошибочного сравнения whitespace целой модалки каждый её смысловой узел сравнивается отдельно; финальный focused набор **58/58 exit 0**, typecheck exit 0. После точного восстановления каждой из четырёх request-family mutations общий прогон **642 passed + 2 opt-in HTTP skipped**, build/typecheck/check-build exit 0. K2 ещё в работе.

K1 mutations: create-name, join-name, leave empty-body, hire empty-body — каждый exit 1, побайтовое восстановление своего backup и затем соответствующий focused exit 0. Полные логи и SHA в `docs/evidence/panel-kingdom-2026-10-03/mutations/summary.json`.

Карточка вставлена в существующую Dynasty после клана и перед приказами. Это не новый игровой режим. Информация о королевстве, независимый create/join, восстание вассала, выход и NPC-наём правителя перенесены целиком. Создание вассального клана из наследника сюда не входит. Семья, наследование, upgrades, ransom, workshops, fiefs и caravans не монтируются.

- 23 текущих legacy scripts исполняются неизменёнными в отдельном DOM. Реальные клики/Enter/details/подтверждения идут через их исходные bindings
- Production PanelApp, IdentityBootstrap, HttpPanelTransport и PanelUsage используются новым host. Сравниваются полные хронологические трассы метода/path/query/body/JWT/Content-Type/cache/keepalive, включая 8s/2.5s polling, общий 3.5s hero-tail, stats/level/duels и 30s usage. Нормализуются только генерируемые ID
- `generate-kingdom-responses.py` создаёт изолированный полный SQLite schema и ДО backend imports выставляет временный RIMWORLD_PRICES_PATH. **59 реальных handler bodies**, синтетические fixture IDs, state через настоящий BannerlordAdapter. Это не live-game доказательство
- Create/rebellion требует числовую nonnegative gold quote; NPC hire обе gold+crustics quotes. Нулевые цены допустимы. Retry сохраняет draft. Join намеренно сохраняет текущий legacy fallback 100000, не выдаваем его за серверную quote
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
