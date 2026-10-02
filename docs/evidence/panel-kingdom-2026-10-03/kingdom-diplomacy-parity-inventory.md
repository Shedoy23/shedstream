# Bannerlord: «Королевство» и «Политика» — инвентарь Preact-паритета

Дата: 2026-10-02. Read-only подготовка в `panel-preact-implementation`; собственные файлы только `../preact-evidence/kingdom-diplomacy-*`. Репозиторий, backend, мод, legacy, prod, ZIP, OBS не изменялись. Общие build/mutation suites не запускались. Прочитаны AGENTS.md, CLAUDE.md, LESSONS.md часть2 и связанные lifecycle-уроки, текущий план миграции. `.agents` в доступных workspace roots пусты, в worktree каталога нет; CodeGraph tool отсутствует, поиск выполнен по исходникам. `scripts/docs-search.py дипломатия королевство` нашёл согласованный план, экономический checkpoint, правила viewer-kingdom AI и игровой checklist; релевантные разделы прочитаны.

## Результат и минимальные законченные границы

1. **K1, вся карточка «Королевство»**: информация о королевстве; независимый клан → создать/вступить; вассальный клан → восстание/выйти; правитель → выйти/нанять NPC-вассальный клан. Сюда входят обе lazy-формы, цена/retry, Enter, подтверждения и смена контекста. Это ближайший маленький завершённый срез после подготовки отряда/армии.
2. **K2, вся карточка «Политика»**: 12 кликабельных законов, активные/pending badges, прямой мир с полем дани, четыре налоговые кнопки, два разных предложения голосования (война/мир). Включать целиком: нельзя назвать «дипломатия перенесена», оставив прямой мир или налог неработающим.
3. **Выкуп — соседний отдельный срез** (`bnr-ransom-slot`, `/ransom-pool`, `hero.pay_ransom`), не часть этих двух законченных карточек. В исходнике находится рядом и вызывается тем же Dynasty loader, но не требует королевства. Не монтировать его пустым обещанием в K1/K2. Семья, наследование, клановые апгрейды, феоды/караваны/мастерские также вне K1/K2.

Создание/вступление/выход из **клана**, создание своего MobileParty, армия и личные вассальные кланы из наследников уже описаны в `party-army-parity-inventory.md`; не копировать их сюда. NPC-вассал за динарную цену в K1 — **другая** покупка, `hero.recruit_vassal_clan`, не `hero.create_vassal_clan`.

**Критический UX-нюанс:** выход правителя распускает королевство; обычный выход вассала отдаёт владения по игровому пути `ApplyByLeaveKingdom`. Legacy предупреждение не называет ни роспуск, ни потерю владений. `docs/BANNERLORD_VIEWER_KINGDOM_AI_2026-09-21.md` явно фиксирует, что предупреждение правителю и expected-kingdom binding тогда не включались. Это известная опасная недосказанность, не новая игровая механика; изменение текста/подтверждения признать отдельным исправлением, не выдавать за strict parity.

## Артефакты и границы доказательств

- `kingdom-diplomacy-response-probe.py` → `kingdom-diplomacy-real-responses.json`, `kingdom-diplomacy-response-probe.log`
- `kingdom-diplomacy-legacy-probe.mjs` → `kingdom-diplomacy-legacy-probe-results.json`, `kingdom-diplomacy-legacy-probe.log`, `kingdom-diplomacy-legacy-red.log`

Команды из worktree:

```
/tmp/preact-backend-venv/bin/python ../preact-evidence/kingdom-diplomacy-response-probe.py "$PWD"
node ../preact-evidence/kingdom-diplomacy-legacy-probe.mjs "$PWD"
node ../preact-evidence/kingdom-diplomacy-legacy-probe.mjs "$PWD" --assert-fixed
```

- Backend probe: **exit0, 59 настоящих handler bodies**. `_build_db` из `tests/test_bannerlord_buy_action.py` создаёт полную схему во временном SQLite; RIMWORLD_PRICES_PATH до импортов указывает во временный каталог; пул закрывается. Никаких HTTP к prod или живой игре.
- Снимки королевства и клана создаются представительными DTO по `HeroStateSync.BuildKingdomInfo` и реально применяются через `BannerlordAdapter._on_player_state_update`, затем читаются через настоящие `bannerlord_my_hero` и `my_kingdom_state`. `fixture_*` — местные тестовые идентичности. Они не выдаются за реальные IDs пользовательской кампании. Auth locally resolves test `alice`/channel; реальная проверка JWT здесь не тестируется.
- Очередные action responses исполняют настоящий `_bannerlord_buy_action_locked`; сохраняются и наружный response, и последний queued payload. Переход policy pending→enacted→removed засевается явным SQL для проверки формы GET; это **не** симуляция подтверждённого игрового эффекта.
- DOM probe: **exit0, 32 сценария, все23 локальных script-файла неизменёнными** в порядке `extension.html`. jsdom/VM, инертный Twitch SDK, выбранные реальные hosts, строгие routes без fallback. Сохранены method/path/query/body/JWT/Content-Type/cache и полные traces. Неизвестный route падает. Общие ответные чтения используют уже существующие real panel/combat fixtures.
- `--assert-fixed`: **ожидаемый exit1**, девять красных сценариев (часть — повторное доказательство той же ошибки через полноценный accepted hero pipeline). Это диагностика старого кода, не committed Preact regression suite и не утверждение, что новый фронт уже исправлен.
- 12 law-clicks в одном DOM-сценарии проверяют все request shapes на отдельных handler-derived ответах, **не** утверждают, что живой backend разрешает12 платных действий подряд без своего300s cooldown.
- Браузер/318px/Hosted Test/игра не проверялись: cloud loopback denied, desktop offline. Обходов нет.

SHA256 в JSON provenance; неизменный `viewer-bannerlord.js`: `87c439858b98171936aaf020cbcaf01f9215e6eef275603951cf2b144fbc35da`, `viewer-actions.js`: `2acf7cf3070ba475643790db371c95d01ea625837424ecabef0ac912cd7a7b2c`. Commit HEAD может двигаться из-за параллельного исполнителя; snapshot HEAD хранится в JSON.

## Общий транспорт / стоимость / результат

- Чтения K1/K2: `GET /api/bannerlord/my-hero`, `/config`, `/kingdom-state`, `/my-buffs`; query отсутствует, body отсутствует. JWT: `X-Twitch-JWT: authToken || ''`.
- Config обязательно `cache:'no-store'`. У перечисленных Bannerlord hero/kingdom/buffs GET legacy не задаёт cache-option; не приписывать им no-store.
- Все кнопки действий: `POST /api/bannerlord/action`, `Content-Type: application/json`, тот же JWT, envelope `{action_type, data:{...ниже, client_action_id}}`. ID генерируется общим dispatcher и остаётся **внутри data**.
- UI не отправляет price/gold-cost/cooldown/username/initiated_by/снимок королевства/expected_kingdom_id. Сервер обогащает payload; для law сам добавляет `kingdom_id` и `want`, для прямого мира `my_kingdom_id`, для gold actions `hero_gold_cost` и `price:0`. Backend queued fields нельзя копировать в client request.
- Single-flight ключ: game+action+параметры кроме client_action_id. Повтор одинакового pending запроса даёт0 дополнительного POST; разные targets не склеивать.
- Реальный наружный success: `{success:true, action_id, charged, message, perk:'viewer', perk_price_mult:1.0, cooldown_applied_s}`. Это очередь, не выполненный закон/мир/основание. Содержательные сообщения специальных diplo handlers наружу в этих fixtures не попадают: общий orchestrator возвращает generic `Action … в очереди`.
- Обычный отказ: `{success:false,message}`. CD-отказ добавляет `cooldown_remaining_s`. Неизвестный server message должен показываться дословно; не заменять локальными предположениями.
- `charged:0` для gold action означает0 крустиков; динары списывает мод. Нельзя писать «бесплатно» для создания/вступления/найма по charged0.
- `/my-buffs` содержит cooldowns `{power_key,remaining_s}`; action result содержит применённую длительность. На панели использовать серверный абсолютный clock, не вводить новый `_DIPLO_CD=300`.
- Политический POST не возвращает actual policy/war/kingdom state. Последующий hero GET несёт `recent_refunds:[{action_id,type,reason,refunded}]` для позднего игрового отказа; это обязательный общий путь обратной связи.

### Фактически наблюдённые цены и cooldowns, не новые клиентские константы

| Action | Источник цены | Значение fixture | CD response |
|---|---|---:|---:|
| hero.create_kingdom | config.hero_gold_costs.create_kingdom | 5 000 000💰 |1200s|
| hero.join_kingdom | config.hero_gold_costs.join_kingdom |100 000💰|120s|
| hero.leave_kingdom | бесплатный server branch |0|60s|
| hero.recruit_vassal_clan | hero_gold_costs.recruit_vassal + action_prices[action] |3 000 000💰 +0💎|300s|
| hero.enact_policy | config.action_prices[action] |1500💎|300s|
| hero.make_peace | config.action_prices[action] |2000💎|600s|
| kingdom.propose_war | config.action_prices[action] |2000💎|300s|
| kingdom.propose_peace | config.action_prices[action] |3000💎|300s|
| kingdom.set_tax_rate | config.action_prices[action], server free default |0|0|

Manifest comments о war1000/peace1500 устарели: реальные prices из handler config —2000/3000. Не брать values из комментария или этого report вместо response.

## K1. Полная карточка «Королевство»

Источники: `viewer-bannerlord.js:4982–5194`, skeleton `:5756–5764`, config helpers `:942–1034`; backend `routes/bannerlord.py:2302–2349,2422–2490`; mod `CreateKingdomHandler`, `JoinKingdomHandler`, `LeaveKingdomHandler`, `VassalHandlers.RecruitVassalClanHandler`.

### Доступ/данные/информация

В обычном host: active Bannerlord integration + visible panel/document + active Dynasty + alive hero + `hero.clan_info.is_leader`. Не-лидеру Dynasty показывает locked clan UI, а не эту карточку. Нельзя смешивать `clan_info.is_leader`, `kingdom_info.is_clan_leader`, `kingdom_info.is_ruler`.

Outer `<details data-bnr-details="dyn-kingdom" open>` изначально раскрыт. `loadBannerlordKingdomMgmt()` сам HTTP не делает: читает `_bannerlordLastHero.hero` из hero GET. HasKingdom определяется `!!hero.kingdom_name`, а ID для контекста берётся из **`hero.kingdom_info.id`**.

Поля `kingdom_info`: `id,name,ruler_name,is_ruler,is_clan_leader,clans_count,fiefs_count,at_war_count,at_war_names,all_kingdoms,rebellion_supporters,rebellion_supporters_required,rebellion_relation_required,culture` плюс own/enemy settlements для отрядов. DTO origin — мод. Никаких новых guessed kingdom IDs/сортировки по своему списку.

Текст: имя; правитель (+«ты»), число кланов и поселений; войны «N корол. (имена)» либо«нет». У независимого клана текст«Клан независим — без королевства».

### Все controls

| State/control | Exact data (кроме client_action_id) | Поведение |
|---|---|---|
| Независимый: details kingdom-create | Нет POST | Lazy input + create |
| Create input #bnr-kingdom-name-input, maxlength32 | — | Можно пусто; trim; button и Enter одинаковы |
| #bnr-k-confirm | hero.create_kingdom, `{kingdom_name:trimmed}` | Закрывает details до dispatcher, без danger-confirm |
| Независимый: details kingdom-join | Нет POST | Lazy join form |
| Join input #bnr-join-name-input, maxlength64 | — | Trim; пустое →0POST; button и Enter |
| #bnr-j-confirm | hero.join_kingdom, `{kingdom_name:trimmed}` | Закрывает details; без danger-confirm |
| Любой member kingdom: .bnr-kingdom-leave | hero.leave_kingdom, `{}` | HTML danger-confirm; до Yes0POST |
| Вассал (`hasKingdom && !is_ruler && is_clan_leader`): details kingdom-create | Нет POST | Тот же create action/form, надпись «Поднять восстание» |
| Правитель: .bnr-recruit-vassal | hero.recruit_vassal_clan, `{}` | Quote + HTML danger-confirm + context/price recheck |
| Price state: «Обновить цены» | GET /config, no-store | Сохраняет draft name, обновляет price/disabled локально |

Для create/rebellion обязательны `config ready` и конечный nonnegative number в hero_gold_costs.create_kingdom. Строка `'5000000'`, null/absent, отрицательное/NaN не цена; законный0 допустим. Action_prices ключ для create не нужен, потому что собственный gold-only branch. Disabled submit + explanatory status + retry; Enter и общий dispatcher тоже блокируют отсутствие quote. Quote — наличие цены, **не** проверка доступного gold или eligibility.

Join пока остаётся старым fallback-path `_bnrGoldLabel('join_kingdom',100000)`. Не объявлять его fail-closed по аналогии с create. Недостаток gold сервер показывает своим сообщением.

Rebellion отображает N сторонников/required и список имён; required берётся из DTO, fallback2; relation threshold из DTO, fallback50. Список сторонников `{id,name,fiefs_count}`. При N<required текст красный, **кнопка не блокируется**; fixture с1/2 реально принимается backend в очередь, мод затем отказывает. Нельзя считать этот disabled gate уже существующим.

Creation text говорит о `[BLink]` имени, +2K influence и2M kingdom wallet. Это inherited тексты/engine constants, не подтверждённые текущим gameplay прогоном. Для rebellion текст обещает сохранение собственных владений и переход подходящих сторонников; обычное leave перед rebellion не вставлять.

### Confirmations и lifecycle

- Реальные modal labels: «✅ Да» / «❌ Нет», title«⚠️ Подтверди». Передаваемые строки«Да, покинуть»/«Да, нанять» текущий helper игнорирует.
- No удаляет modal; MutationObserver разрешает promise false. Новый showConfirm заменяет предыдущий modal. Backdrop/Escape не имеют отдельного закрывающего binding; не считать их автоматически cancel.
- Leave message: «Покинуть королевство? Обратно примут только новым вступлением, и только если согласятся принять.» Нет имени/ID, роли правителя, текста роспуска. После Yes в legacy нет проверки lifecycle/JWT/kingdom; доказан POST уже от нового пользователя.
- Hire quote требует оба ключа, gold и crustics, с тем же строгим типом. Цена в confirm форматируется полностью, например3 000 000💰, и читается в момент клика. После Yes проверяются captured lifecycle+JWT, quote existence, точное equality gold/crustics; изменившаяся цена → warning/0POST, нужен новый confirm. Эти правильные guards перенести.
- Hire не проверяет realm/role change при том же JWT. Подтверждение, открытое в старом королевстве, остаётся и отправляет action после принятого нового hero-state. Не выдавать это за доказанное успешное списание: DOM доказал неверную отправку, настоящий backend для non-ruler fixture отказывает.
- Успешный hire заменяет generic toast на7s«Заявка принята… появятся … после обработки в игре. Динары спишутся при создании». Другие K1-actions используют общий server toast.
- Пока create или join details открыт, renderer не перерисовывает **всю карточку**, чтобы не стереть имя. Обычный poll обязан сохранять draft; смена hero/user/channel/kingdom/eligibility должна очистить/пересогласовать, а не унаследовать эту широкую заморозку.
- K1 controls не имеют data-bnr-cd, countdown не рисуется. CD-отказ остаётся текстом server message.

### Реальные server/mod gates

Backend create: trim/≤32/запрещённые символы; hero exists; clan_name начинается `[BLink]`; gold≥server5M. Backend не проверяет rebellion supporters, actual leader либо already ruler в этом branch. Mod: alive/nonprisoner/actual clan leader, не действующий ruler, для rebellion≥exported supporters; достаточное gold, уникальное имя, faction change не затрагивает player battle. Landless kingdom разрешён; не придумывать обязательный феод.

Backend join: nonempty≤64, `[BLink]` clan name, sufficient gold; mod additionally actual leader, ещё без kingdom, resolve by actual IDs/title/culture with exact/fuzzy fallback, target exists/not eliminated, battle guard. UI остаётся свободным текстом; dropdown всех kingdoms в K2 не является контрактом join.

Backend leave только выставляет price0, специальные условия проверяет мод. Mod distinguishes ruler and vassal: ruler эвакуирует кланы и распускает kingdom; vassal выполняет leave. Frontend не должен оптимистически стирать kingdom до authoritative hero sync.

Backend hire: `[BLink]` clan, derived kingdom present, is_ruler, gold≥cost; mod actual leader/ruler/nonprisoner/gold, NPC template/create/join/postconditions. Список heir vassals и их limit5 **не относится** к этой кнопке; у текущего hire нет числового UI-лимита.

## K2. Полная карточка «Политика»

Источники: `viewer-bannerlord.js:2540–2869`; backend `routes/bannerlord_diplomacy.py`; mod `DiplomacyHandlers.cs`.

### Read/result/state

`loadBannerlordDiplomacy` GET `/kingdom-state`. Ответ:

```
{success,has_hero,kingdom_id,kingdom_name,is_clan_leader,is_king,captured,
 kingdom_tax_pct,policies_pending,policies_enacted,peace_offers}
```

- Auth refusal `{success:false,message:'auth required'}`. Legacy any success===false/network failure сохраняет last render.
- Нет hero: `{success:true,has_hero:false}` → пустой slot.
- Есть hero, но нет kingdom_id → locked informational text«доступна когда герой вступит в королевство», без controls.
- canEnact = is_king || is_clan_leader; canMakePeace = is_king. В обычной Dynasty outer-gate по clan leader уже действует; direct isolated renderer member fixture не означает, что в реальной оболочке члену показывают всю Dynasty.
- Header kingdom name/id +«КОРОЛЬ» для king. Active и pending badges из response отображают `policy_name || policy_id`, даже если law не в hardcoded selectable catalog.
- Policies items `{id,policy_id,policy_name,requester,status,requested_at}`. Backend учитывает последний enacted/removed state; removed law не воскресает от старой enacted записи. Pending отдельно, shared across kingdom/channel.
- `peace_offers` items `{id,target_kingdom_id,target_kingdom_name,offered_tribute,status,offered_at}`. **Legacy их не отображает**. `captured` также не отдельный видимый control здесь. Не выдумывать существующий pending peace widget.
- Нет `wars` field в этом GET, несмотря на старый docstring. Target list берётся из **hero.kingdom_info.all_kingdoms**, war summary из K1 kingdom_info. Два источника надо читать согласованно по kingdom identity.

### Законы: все12 controls

`details data-bnr-details="diplo-policy"`; каждая `.bnr-diplo-policy-row` — непосредственный клик без дополнительного подтверждения. `hero.enact_policy`, `{policy_id,policy_name}`. Active row ✓, pending row серый/data-policy-pending, клик →0POST. Открытый policy list не блокирует repaint, потому что текстового draft нет.

| ID | Передаваемый policy_name |
|---|---|
|policy_forgiveness_of_debts|Прощение долгов|
|policy_land_grands_for_veteran|Земля ветеранам|
|policy_precarial_land_tenure|Условное землевладение|
|policy_royal_guard|Королевская гвардия|
|policy_sacred_majesty|Священное величие|
|policy_trial_by_jury|Суд присяжных|
|policy_imperial_towns|Имперские города|
|policy_noble_retinues|Дружины знати|
|policy_lords_privy_council|Тайный совет лордов|
|policy_council_of_the_commons|Совет общин|
|policy_serfdom|Крепостное право|
|policy_citizenship|Гражданство|

`land_grands` — именно существующий spelling ID; не «исправлять» на grants. Названия/description12 entries сейчас legacy `_BNR_POLICIES`, **не** server catalog. Public policy catalog route не найден в текущих routes/module/mod export. Не придумывать дополнительный API или утверждать, что политики теперь динамические.

Frontend не отправляет `want:'enact'/'remove'`: backend вычисляет intent по последнему DB state и включает его в queued data. Мод проверяет expected kingdom, actual leader, PolicyObject ID, `ResolvePolicyIntent(want,hasNow)` и наблюдаемый эффект. EnactPolicyHandler применяет AddPolicy/RemovePolicy **непосредственно**, не голосование кланов. Старый backend docstring про EnactPolicyDecision не является фактом текущей реализации. Pending«На обсуждении» — унаследованный UI-текст, не доказательство actual vote.

### Прямой мир: отдельная механика от vote-peace

King-only `details diplo-peace` → `_renderMakePeaceInline`. Поля:
- `#bnr-peace-target`, text maxlength80; trim; минимум2 символа, иначе warning/0POST
- `#bnr-peace-tribute`, number default0, min−10000/max10000/step100; обработчик parseInt(value)||0
- `#bnr-peace-confirm`: `hero.make_peace`, `{target_kingdom_id:tgt,target_kingdom_name:tgt,offered_tribute:integer}`; в оба target поля идёт **тот же введённый текст**, не подставленный ID из dropdown
- Form закрывается перед action, отдельного danger-confirm/Enter-binding нет
- Негативная дань сохраняется. HTML min/max не означает clamp перед submit: обработчик может отправить20000; backend реально ограничивает до±10000. Не менять wire payload, называя это parity

Пока diplo-peace открыта, renderer после GET не меняет **всю diplomacy card**, сохраняя draft. Это также замораживает labels/tax/role/target lists; контекстная смена должна ломать freeze. Backend требует king, nonself target, ≥2chars; актуальную войну/target/engine возможность проверяет мод. Backend pending peace rows не показываются отдельным UI, duplicate pending возвращает свой message. Completed/failed old queue rows снимают pending lock; это server lifecycle, клиент его не имитирует.

### Налог

King-only current `kingdom_tax_pct ||0`, кнопки `0%`, `10%`, `25%`, `50%`, `.bnr-tax-btn[data-tax-pct]`. Выбранная ставка подсвечивается, **не disabled**. Каждая отправляет `kingdom.set_tax_rate`, `{tax_rate_pct:0|10|25|50}`, без modal. Server accepts/clamps0..100; UI текущие четыре presets не является server catalog. Config price0, CD0. Server проекция tax обновляется при очереди, actual mod остаётся авторитетом. Не выдавать HTTP tax echo за факт игрового ежедневного дохода.

### Голосования: война и мир

Только canEnact и непустой array `hero.kingdom_info.all_kingdoms:[{id,name,at_war}]`.
- War targets: `k && !k.at_war`; peace: `k && k.at_war`; порядок как в mod DTO, первая option по умолчанию. Мод исключает own/eliminated kingdom до экспорта; не заменять список static cultures.
- `#bnr-war-target` + `#bnr-war-propose[data-bnr-cd="kingdom.propose_war"]`: `kingdom.propose_war`, `{target_kingdom_id:select.value.trim(),target_kingdom_name:selectedOption.textContent.trim() || id}`
- `#bnr-peace-vote-target` + `#bnr-peace-vote-propose[data-bnr-cd="kingdom.propose_peace"]`: аналогично, **без offered_tribute**
- Empty selected ID →0POST; без targets war control отсутствует; без peace targets текст«Сейчас ни с кем не воюем — мир предлагать некому»
- No modal confirmation. Успех даёт отдельный7s toast«Заявка … на голосование … не мгновенно», а не обещание, что война/мир уже наступили. Не потерять его при migration
- Только эти две кнопки K2 имеют видимый server-CD countdown. Политики, direct-peace и tax data-bnr-cd не имеют. Не изобретать локальный cooldown при обычном refusal/network failure/missing cooldown field
- Backend generic action для propose war/peace **не повторяет отдельную kingdom/clan-leader prevalidation**. Probe с nonleader и с no-kingdom получил queue-success charged2000. Mod отказывает no_kingdom/not_clan_leader, checks current target/relation/duplicate unresolved decision/decision admissibility. Это backend defense-in-depth gap, не разрешение ослабить frontend gate или чинить backend в этом срезе

## Read tails, polling и visibility: точные различия

Общий scheduler/его сопутствующие endpoints уже подробно описаны в party-army inventory. Здесь существенные различия:

- K1 reader синхронен без HTTP; вызывается после accepted hero result и при входе/visible Dynasty. K2 делает один kingdom-state GET на каждый permitted Dynasty load, в том числе при collapsed outer card
- Legacy hero cadence8s; buffs2.5s и countdown1s; выбранная Dynasty required. Не включать background kingdom GET на других tabs. DOM probe: hidden0 → visible1 → member still1 reads
- Open create/join/peace forms замораживают repaint, **не** GET. Нельзя перейти к latest-issued-only guard: latency>cadence должна продолжать принимать успешно завершённые снимки, пока более новый ещё не применён
- Каждый success dispatcher вызывает loadUserData. В выбранном host trace это GET `/api/viewer/stats/alice` → `/api/user/level/alice` → `/api/duel/list` (без query, JWT). При перезапуске модуля shell может дополнительно запустить config/classes/build/buffs/battle-status; probe сохранил эти requests, не отфильтровал
- Только `hero.*`, `player.*`, `power.*`, `tournament.*` попадают в generic success handler: invalidate hero/vassal sequence; через3500ms guarded lifecycle+JWT: `loadBannerlordHero`, `loadBannerlordBuild`, `loadBannerlordEquipmentShop`, `loadBannerlordTournament`. Функции могут early return при отсутствии host. **kingdom.* не попадает в этот generic delayed refresh**
- K1 create/join/leave/hire: только общий success-tail, своего kingdom-state timeout нет. Поздний hero refresh снова вызовет K1/K2 только при visible Dynasty
- Policy click: после await dispatcher, независимо от success/refusal, `setTimeout(loadBannerlordDiplomacy,2000)`; плюс generic3500ms только success
- Direct peace: то же2000ms + success-only generic3500ms
- Tax: после await dispatcher1200ms kingdom-state GET, независимо от outcome; generic3500ms нет
- War/vote peace: после await dispatcher немедленный `loadBannerlordDiplomacy()` и при success special toast; generic3500ms нет
- Эти локальные diplomacy tails и сам legacy reader не имеют lifecycle/identity/sequence guard. `_stopBannerlordPolling` очищает общий scheduler/cache, **не** эти timeouts/DOM. В новом host life ownership должен охватить и создание delayed GET, и application позднего результата
- После failed/read refusal сохраняется last good render; genuine nohero clear. Stale response для старой identity/kingdom нельзя трактовать как legitimate absence новой

## Исполнением подтверждённые frontend defects

Ниже не выводы по regex: каждый сценарий исполняет unchanged scripts и находится в JSON/log. Исправлять только new frontend с committed red regression до кода, помечая intentional parity exceptions; legacy не переписывать.

1. **Leave confirm identity bleed**: открыть при Alice; stop; Bobby JWT/login; Yes → POST hero.leave_kingdom с Bobby JWT. Опасность не ограничивается «устарел label»: действие реально отправлено за другого пользователя. Нужны confirmation ownership и0POST после смены user/channel/hero/module/kingdom
2. **Hire confirm realm/role stale**: old ruler dialog → accepted hero update to another kingdom as nonruler → Yes всё ещё POST hire. Price/token guards верны, realm eligibility guard отсутствует. Варианты прямой setter и настоящий `loadBannerlordHero→_loadBannerlordDynasty` дали одинаковый результат
3. **Diplomacy read reorder**: новый ответ tax50 завершился первым, старый tax10 позже → UI откатился к10. Нужен monotonic applied sequence, с отдельными context/action barriers
4. **Diplomacy read after stop**: read начался до stop, завершился позже → карточка снова рисуется. Нужны life/auth/host identity guards и teardown
5. **Local tails after stop**: policy2s и tax1.2s после stop+нового JWT начинают kingdom-state GET от Bobby. Generic3500ms guard не помогает. Эти2 сценария — один класс local timers ownership
6. **Frozen direct-peace crosses realm change**: открыта форма короля, новый hero/kingdom accepted (nonruler Other Kingdom), форма и header старого Fixture Kingdom остаются; draft отправляется. Проверено через полноценный accepted hero pipeline, не только прямой renderer. Нужна invalidation по stable kingdom ID/role/hero, при обычном poll draft сохранять

Дополнительный источник класса6: `/my-hero` не экспортирует top-level hero.kingdom_id/clan_id, а старый struct hash их читает. Это не утверждение, что королевство вообще не синкается: актуальный adapter сохраняет DB kingdom_id/kingdom_name/is_king, и actual nested DTO содержит ID. Новый frontend должен брать существующий nested ID, не требовать выдуманного server field.

## Contract gaps / известные ограничения — отдельно от frontend defects

1. **Policy catalog и descriptions статичны.** Нет текущего exported catalog/capabilities/reasons для всех policy controls. Thin-front цель остаётся неполной при копировании старого списка. Список нужен для strict old-behavior parity; dynamic/modded policy catalog требует нового backend/mod контракта, вне этого разрешённого scope
2. **Нет atomic expected-price/config_revision** у дорогих gold actions. Quote validation и recheck местного config не гарантирует shown=charged при server change между GET и POST. Не добавлять несуществующее поле и не обещать эту гарантию
3. **Нет frontend expected-context в action body** для leave/hire/create/peace/votes/tax. Frontend может остановить уже известную смену context; закрыть race после POST до применения в игре без server/mod контракта не может. Law queued `kingdom_id` отдельно проверяется модом, но это server-derived значение, не подтверждённое зрителем old UI
4. **Role/supporter/eligibility gates не симметричны.** DTO содержит usable role/supporter info, но нет единого can_create/can_rebel/can_leave/can_hire/blocked_reason. Backend create/join используют имя `[BLink]`, а мод actual clan leader. Rebellion недостаток сторонников и vote membership подтверждаются уже в моде. Не синтезировать authoritative free/gold/доступность по локальным defaults
5. **Политический state не полный мир игры.** policies_enacted выводится из журнала extension requests/latest result; это не exhaustive current game-policy snapshot. peace_offers есть, но не rendered. wars нет в kingdom-state, target catalog из другого response. Не заявлять новые live statuses без API
6. **Часть economics всё ещё fallback.** Join и K2 crustics labels используют старые fallback; create и hire fail-closed. Tax presets0/10/25/50, tribute bounds±10000, create bonuses2K/2M и some DTO fallback2/50 не exported general config. Не превращать report values в новый источник истины
7. **Danger-copy известна неполной.** Роспуск realm правителем/обычный leave с феодами не объяснены старым confirm. Сам риск документирован21.09. Для changed Preact warning назвать изменение явно, сохранить прежний wire action и не выдавать за добавленную server guarantee
8. **Комментарии протухли.** kingdom-state говорит «is_king/kingdom_id never sync», но текущий adapter их синкает; `/my-hero` всё равно не отдаёт top-level ID. Manifest старые prices; diplomacy module docstring обещает policy vote, мод применяет напрямую. Handler/runtime shapes важнее комментариев
9. **Ransom отдельно.** Нахождение рядом в файле и общем loader не делает весь ransom UI частью готового politics scope. Если нужен перенос всего Dynasty, придётся отдельно закрыть выкуп и остальные карточки

## Минимальная приёмка следующего исполнителя

K1:
- independent/vassal/ruler/member/clanless/dead/prisoner states; outer Dynasty access без лишних reads
- create blank/custom/32/invalid name; Enter/click; missing/wrong-type/negative/zero/nondefault quote; retry не стирает draft; old config cannot revive new life
- join trim/nonempty/Enter + exact field; response poor server text; старый fallback обозначен
- rebellion1/2 и2/2, DTO required/relation отличные от2/50; та же action_name; не вставлен предварительный leave
- leave yes/no/reopen/backdrop; explicit warning decision;0POST после user/channel/hero/kingdom/role/module смены
- hire gold+crustics nondefault/zero/missing-one; полный confirm; same-price/changed-price; token refresh/realm/role changes; pending singleflight; server refusal;7s queue toast
- нормальный slow poll сохраняет draft, смена контекста не сохраняет действие старого короля; все success tails и generic refusals

K2:
- nohero/no-kingdom/auth/network last-good preservation; independent roles; all12 exact IDs/names; unknown enacted badge; enacted/pending/removed; pending0POST
- direct peace separate from vote: ≥2 trim, negative tribute, parseInt, no Enter binding, exact same text→two fields; close-before-submit;2s tail
- tax все4 incl reselect current0; no extra expected price;1.2s tail, no invented generic3500ms
- actual dynamic target catalog, empty/absent/null/name fallback, all at peace/all at war, target order, no self-derived static cultures
- war/peace success/pending message, ordinary refusal, no cooldown on missing duration, fractional/zero/unknown cooldown; buffs old-response barrier + allowed fresh clear; expiry restores actual priced label
- visibility/collapsed/open editor; reverse-completion; latency>8s steady progress; pending GET/POST/timeout stop+rebind; same user refreshed JWT vs changed logical identity; kingdom_info.id/role changes
- compare **полные** HTTP traces old/new, normalizing only action IDs/time. For corrected bugs old expectation stays red, new expected safe behavior green separately; do not filter extra reads away

Useful existing suites to extend (not executed here): `scripts/test-frontend-bannerlord-economic-config.mjs`, `scripts/test-frontend-bannerlord-diplomacy-cooldowns.mjs`; backend action + policy/peace outcome tests; `frontend-next/test/panel-legacy-harness.ts` and real-fixture generators. UI/game verification remains separate required evidence.
