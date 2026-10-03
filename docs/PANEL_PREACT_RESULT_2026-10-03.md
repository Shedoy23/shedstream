# Панель Preact: результат ночной работы 03.10.2026

## Финальный локальный checkpoint: добавлена полная кузница

На неизменённом после независимого review runtime **c00bf91**, финальные tests/fixtures
**04a011e**: **937 unit/DOM passed +2 explicit live skips**, отдельно **2/2 fresh HTTP**,
**17/17 legacy gate files**, typecheck/build/check-build/ESLint/globals/consistency exit0.
Кузница: **54 owner cases +6 independent probes**, **16 mutation red→green**.
[Полный forge-отчёт](PANEL_FORGE_PARITY_2026-10-03.md) и
[финальные команды/хеши/логи](evidence/panel-forge-2026-10-03/verification.json).

| Область | Результат | Граница |
|---|---|---|
| Развитие героя | Перенесено, request parity | Focus/attributes/classes/specialization/starter; не весь Hero |
| Магазин/инвентарь | Перенесено, request parity | EquipmentShop; legacy fallback отдельно |
| Бой | Перенесён, request parity | Приказы/стойки/призывы/активки/HUD/поздние отказы; без турнира |
| Свита/клановый вход/отряд/армия | Перенесено, request parity | Найм/тренировка/create/join/leave/6 orders/army; не вся Dynasty |
| Королевство/политика | Перенесено, request parity | Lifecycle, NPC-вассал,12законов,мир/дань/4налога/предложения |
| Кузница | Перенесена полностью | Старые10слотов,серверная цена,reforge wire/tails,без возвращения smith_item |
| Общий host перечисленного | Перенесён выбранный scope | Tabs/polls/identity/JWT/balance tails/usage; не вся оболочка |
| Настоящий турнир | Не перенесён | Исследование/fixtures есть; synthetic tournament.html его не заменяет |
| Остальной Hero/Dynasty | Не перенесён | Создание героя,daily,пол,конвертеры,achievements,семья/наследники/вассалы/upgrades/владения/ransom |
| Общее, RimWorld, ShedColony | Не перенесено | Кейсы/квесты/промо/голосования/статистика и отдельные game protocols |
| OBS | Вне задания | Не изменён |

Исправлена подтверждённая опасная ситуация кузницы: на экране старая вещь A, но уже
принятый inventory показывает B и slot-only касса улучшит B. Только спорный forge-слот
закрыт до согласования item_id/quality; остальная панель продолжает работать.
Невидимая GET→POST гонка/одинаковая session-смена без DTO ID не объявляются решёнными.
Также есть явное восстановление пропавшей forge quote. Все безопасные расхождения
со старым UI и пределы доказательств перечислены в отдельном отчёте.

Initial mobile graph **230996 raw /60804 gzip-9 bytes**. Не входят Helper/API/maps;
CDN/timing не измерены, минификация отключена. Старый frontend/backend/моды/OBS/ZIP
побайтно прежние относительно базы миграции **8a40391**.

**Локальный пакет новее GitHub.** Последние read-only проверенные remote heads:
`feature/skillgames-preact` **ccd1489486dc1703c60487bf2faa00f290cd109b** (CI success),
`feature/panel-preact` **58c2e4f9fc0a74303931b7eb335144ed1439706a** (первый321-test checkpoint,
CI success после одного повтора). Все последующие panel-изменения локальные:
после запрета/единственного повтора публикация остановлена до уточнения пользователя.
Нового GitHub CI на локальный финальный SHA нет; merge/deploy/submission не было.

**Браузер/318px/телефон/Hosted Test/реальная игра не проверены.** DOM, настоящая
временная касса и HTTP мини-игр не заменяют эти gates. Владельцу/Claude нужны review
локального пакета, разрешённая браузерная проверка и отдельное решение о публикации.

Ниже сохранены прежние checkpoints с их собственными SHA и числами.

## Предыдущий checkpoint: королевство, политика и отказы API

Исходный checkpoint **ac22deaf1235b6c428db6877edaee083bcf2c6c9**, tree
`332b3058da714c271ea354bb3f92af39b26b2ad0`: **883 unit/DOM passed**, затем отдельно
**2/2 свежих HTTP-сценария мини-игр**, **17/17 legacy gates**. Typecheck, build,
check-build, ESLint, globals и consistency с установленным pyflakes завершились
exit 0. Полный suite ограничен двумя workers, тесты не исключались.
[Команды/логи, точные SHA и карта интеграции](evidence/panel-integration-2026-10-03/verification.json).

| Область | Перенесена / паритет | Точная граница |
|---|---|---|
| Развитие героя | Да | Focus/attributes/classes/specializations/starter choices; не весь Hero |
| Магазин и инвентарь | Да | EquipmentShop, включая inventory/party inventory; не legacy fallback |
| Боевые действия | Да | Приказы, стойки, призывы, старые/новые способности, HUD и поздние отказы; без турнира |
| Свита, клановый вход, собственный отряд/армия | Да | Найм/тренировка, создать/вступить/покинуть клан, шесть приказов, create/disband army; не вся Династия |
| Королевство | Да | Информация, create/join/rebellion/leave, NPC-вассал правителя |
| Политика | Да | 12 законов, действующие/ожидающие решения, прямой мир/дань, 4 налога, предложения войны/мира |
| Общий выбранный host и счётчики | Да | Сохранённые вкладки, polls/read tails/identity/JWT и server UI events перечисленных областей; не вся общая оболочка |
| Кузница и настоящий турнир | Пока нет | Следующие полные границы; отдельный synthetic tournament.html их не заменяет |
| Остальные Hero/Dynasty controls | Нет | Создание нового героя, daily, пол, конвертеры/каталог действий, достижения, семья/наследники/вассалы, upgrades, владения, ransom |
| Общая оболочка, кейсы/квесты/промо/голосования/статистика | Нет | Balance tail — зависимость перенесённых действий, не весь экран |
| RimWorld / ShedColony | Нет | Отдельные протоколы и lifecycle; остаются прежними |
| OBS | Вне задания | Не изменялся |

Новый [K1/K2 отчёт](PANEL_KINGDOM_PARITY_2026-10-03.md) фиксирует настоящие
backend response shapes и исполняемые old/new traces. Исправлено наблюдаемое
расхождение realm/role между hero и kingdom-state: старые права/подтверждения
блокируются до согласования. Узкий запрет распространяется на army create/disband
и назначение стратегического приказа; отмена приказа, клан и свита не заморожены.
Невалидная или отсутствующая join quote больше не заменяется выдуманной ценой.
Это явно описанные безопасные расхождения со старым error-path, не новые механики.

[Transport policy fix](PANEL_TRANSPORT_POLICY_REFUSALS_2026-10-03.md) отличает три
проверенных внешних отказа до списания/очереди: channel_not_registered,
channel_pending_approval и channel_rate_limited. Реальный main.app с временной
БД подтвердил их происхождение. Сохраняется текст сервера; известный отказ не
превращается в вечный unknown lock. Произвольный 4xx, смешанный/неверный ответ,
5xx и timeout остаются неизвестным исходом; автоматического POST retry нет.
110 policy cases; 20 опасных mutations убиты, один избыточный guard отмечен честно.
K1/K2: 17 killed +1 redundant; соседние army/order gates: 3 killed. Восстановление
побайтное; затем выполнен весь объединённый suite. Независимый обзор подтвердил
каждую интегрированную runtime-часть до финального объединённого прогона.

Initial **panel-mobile.html + статический import graph: 220732 raw /58181 gzip-9
bytes**. Это локальная компрессия каждого файла, не доказанная CDN-передача.
Внешний Helper, API bodies/headers и maps не входят; полный список отдельно в
[измерении](evidence/panel-integration-2026-10-03/combined-sizes.json).
`minify:false`, `cssMinify:false`, sourcemaps и лицензии сохранены.

**Вся новая работа после первого checkpoint остаётся локальной.** Remote
`feature/panel-preact` — `58c2e4f9fc0a74303931b7eb335144ed1439706a`, первые 321 tests.
Для текущего SHA GitHub CI не запускался: дальнейшая публикация остановлена
после отказа и одного повтора до явного уточнения пользователя. Merge/deploy нет.
**Браузер, визуальные 318 px, телефон, Twitch Hosted Test, CDN/<3s и реальные игровые
эффекты не проверены.** Cloud loopback denied; последний доступный desktop check
21:38 UTC показал offline. DOM/HTTP не подменяют эти проверки.

Ниже сохранены исторические checkpoints с их собственными числами и доказательствами.


## Предыдущий checkpoint: свита, клан, отряд и армия

Frozen source/report `9075a2cc5273c4c9051ffefa5312f1d951b9b545`, runtime `41d3477`,
финальные tests `b5108ab`. Теперь закончены следующие отдельные области:

| Область | Перенесена / request parity | Что не входит |
|---|---|---|
| Развитие героя, снаряжение, боевые действия | Да, предыдущие checkpoints ниже | Не весь Hero tab; турнир отдельно |
| Свита | Да: basic/elite найм или upgrade, массовая тренировка, серверные cap/цены/CD, состояние и telemetry | Это не новая система bodyguards |
| Клановый вход | Да: создать/вступить/покинуть клан, создать отряд, реальные подтверждения | Семья, наследование, вассальные кланы и upgrades отдельно |
| Собственный отряд и армия | Да: все6 стратегических приказов, target editor/release, create/disband army | Это не вся Династия; роль/исход окончательно проверяет сервер/мод |

**584 unit/DOM passed +2 explicit live skips**, types/build/check-build exit0.
Отдельно **2/2 HTTP мини-игр** на свежем временном сервере, **17/17 legacy frontend
checks**, git diff/check и lockfiles чистые. Паритет для A/B сравнивает настоящие
23 старых scripts с реальными controls/confirmations, всем admitted-host trace,
включая сохранённую Dynasty, visibility, polling, явные action tails и UI counters.
Независимый review runtime `41d3477` проверил566tests и дополнительные probes;
поздние18test cases дают финальные584, не приписываются раннему review.

A:3 mutations red/restored. B:8 request families +4 behavior mutations red/restored;
один избыточный post-await JWT guard survivor записан честно, обе снятые JWT fences
обнаруживаются. Общий suite повторён после byte-exact восстановления.

Initial `panel-mobile.html` + статический import graph: **184297 raw /50336 gzip-9
bytes**. [Файлы и суммы](evidence/panel-party-2026-10-03/party-sizes.json).
Не входят Helper, API bodies/headers и sourcemaps; Twitch network/3s compliance не
заявляется. Минификация по-прежнему отключена, source maps и лицензии сохранены.

Исправлены подтверждённые старые UI defects: пустая свита не обновляла доступность
после изменения gold; party reads применялись в обратном порядке/после stop;
подтверждение армии и локальные delayed reads использовали новую личность/JWT;
recruit отправлял вместо цели текст placeholder. Нормальная wire-последовательность
совпадает, последнее поле recruit и безопасные invalidation paths явно перечислены
как intentional exceptions. Цена/cap без серверного подтверждения не выдумываются.

[Полный A/B отчёт и ограничения DTO](PANEL_PARTY_PARITY_2026-10-03.md).
**Этот checkpoint локальный.** GitHub writes остановлены после отказа/единственного
повтора, remote `feature/panel-preact` по-прежнему `58c2e4f` (первые321tests).
Нового GitHub CI нет. Backend/legacy/mods/OBS/frozenZIP не менялись; merge/deploy нет.
Браузер318px/телефон/Hosted Test/настоящая игра не проверены; desktop вновь подтверждён
offline21:38UTC. Следующий согласованный срез — королевство и дипломатия.


## Следующий проверенный checkpoint: боевые действия

Combat checkpoint `0bbc802bc0e37dacf62e353543bbbfef235eea17`, последний runtime
`fc0dde744ceed2089238185a305d27c5644ab313` (JWT callback ownership исправлен). Отдельный panel вход теперь включает
развитие героя, снаряжение **и полный боевой экран без турниров**. Это по-прежнему
не весь старый Hero/Battle tab и не вся панель. Свита/отряд/армия добавлены в следующем локальном checkpoint выше.

| Дополнение | Переписан / паритет | Что осталось |
|---|---|---|
| Боевые действия | Да: 8 приказов, 3 стойки, 2 призыва, 9 старых активок / 7 классов, 7 новых weapon choices, selected/common activation, battle/buff HUD | Турниры отдельно; применение в реальной игре не проверено |
| Общий host трёх областей | Да: default и saved combat/hero/inventory startup, actual controls, polls, hidden explicit tails, 60s balance dependency и счётчики | Это выбранный host, не весь старый SDK/bootstrap остальных модулей |
| Поздние отказы мода | Да: настоящий recent_refunds response, action_id dedup, 6s уведомление, identity ownership | Наблюдаются серверные сообщения; это не проверка игровых эффектов |

Полный suite: **474 passed + 2 explicit live skips**, typecheck/build/check-build exit0.
Отдельный новый disposable HTTP server: **2/2**, включая полный морской бой и6побед
сапёра. **27/27 combat mutations** обнаружены (exit1), исходники восстановлены
побайтно и aggregate снова зелёный. Дополнительно4 JWT mutations дали exit1;
после exact restore весь suite474 снова зелёный. Независимый review исходного combat runtime
также дал463/463, types/build/17legacy gates/lint/globals exit0; поздний узкий
saved-inventory preload отдельно прошёл независимый review469/469 и3 дополнительных
adversarial probes. Последний JWT/pending fix имеет отдельные red/green сценарии.

Мобильный initial import graph: **150518 bytes raw /42292 bytes gzip-9**,
+35886/+9312 к первому checkpoint. Отдельная чистая сборка с собственными
node_modules, прежние minify:false/cssMinify:false/sourcemaps/лицензии сохранены.
[Все ассеты](evidence/panel-combat-2026-10-03/final-local-sizes.json).

Найдены и исправлены: смысловые cooldown keys для powers/сторон призыва;
отвергнутая optimistic стойка (включая поздний отказ по собственному action_id);
ошибочный запрет боевых способностей через can_manage; пассивный баланс, без
обновления которого способность могла остаться недоступной; пропущенные late
refund notices; неправильный порядок первого GET при восстановленном inventory.
Missing/malformed prices и потеря свежих battle/buffs/build данных закрывают
зависимые действия. Все отличия от неисправного старого error-path перечислены.

[Подробный combat отчёт](PANEL_COMBAT_PARITY_2026-10-03.md) включает98реальных
handler-response записей,38успешных actions, все request families, тесты и границы.
Браузер/318px/телефон/Twitch Hosted Test/реальная игра по-прежнему **НЕ проверены**.
**Публикация текущего combat/JWT checkpoint заблокирована.** После отказа и одного
повтора по подтверждённому плану дальнейшие GitHub записи остановлены. Remote
`feature/panel-preact` остаётся на `58c2e4f9fc0a74303931b7eb335144ed1439706a`:
это только первый321-test checkpoint, без описанного выше combat/JWT кода.
Для новых локальных SHA GitHub CI **не запускался**. Все474/types/build/HTTP выше —
локальные проверки. Первый CI и единственный повтор сохранены ниже. Нет merge/deploy.


## Первый проверенный checkpoint: развитие героя, снаряжение, счётчики

Проверенный исходный кандидат `0d57d3e0c9330d7d37f6a36144ed3f39d712908d`, tree
`995023f51759ff2c2787c9477db3205b5c879100`. Первый опубликованный checkpoint с отчётом:
[`58c2e4f9fc0a74303931b7eb335144ed1439706a`](https://github.com/Shedoy23/shedstream/commit/58c2e4f9fc0a74303931b7eb335144ed1439706a),
tree `ce98da4f1fcdd80b589852449dee4d006655fa68`, в `feature/panel-preact`.
Все 40 опубликованных trees проверены по SHA и после git fetch совпали с локальной
историей; [карта публикации](evidence/panel-2026-10-03/first-checkpoint-publication.json).
Ветка продолжает **опубликованную** `feature/skillgames-preact` (`ccd1489`),
а не старую несведённую поставку. Все 38 промежуточных red/green шагов сохранены;
после переноса на опубликованную историю frontend каждого шага побайтно совпал.
[Карта локальных доказательств](evidence/panel-2026-10-03/local-proof-map.json).

Это исторический первый законченный срез; боевые действия добавлены checkpoint выше.
Ни весь Hero tab, ни вся старая панель пока не называются перенесёнными.
Старые `Расширение/frontend/*`, backend, моды, OBS и frozen ZIP не менялись.
Новой выкладки, слияния и подачи в Twitch нет.

## Покрытие экранов в историческом первом checkpoint

| Экран/область | Переписан | Паритет запросов | Отличия и оставшиеся границы |
|---|---|---|---|
| Развитие героя | Да: 18 focus, 6 attributes, 7 классов, 4 специализации, 3 starter choices | Да, все реальные DOM controls, full tails | Не весь Hero: создание/возрождение, семья, пол, retinue/daily вне этого среза |
| Магазин и инвентарь | Да: покупка, прямая покупка с заменой, equip/unequip/discard, фильтры, страницы, слоты | Да, реальные старые/новые подтверждения и все поля котировки | Legacy-equipment fallback вне этой карточки не переносился |
| Общий host двух экранов | Да | Да: входы вкладок, повторный вход, фаза polls, hidden explicit refresh, token/identity lifecycle | Полный startup остальных модулей не заявлен |
| Счётчики UI | Да, прежние server events | Да: реальные PanelApp traces + неизменённый collector/server validator | Только осмысленные intent/exposure events; no click scraping |
| Обновление баланса после действия | Общий transport tail | Да: stats → level + duels | Это не перенос всего самостоятельного экрана баланса/статистики |
| Боевые действия | Да, в следующем checkpoint выше | Да, scoped actual host | Турниры ещё не перенесены |
| Свита, клан/отряд/армия | Да, последующий локальный checkpoint выше | Да, с перечисленными безопасными исключениями | Не вся Династия |
| Дипломатия/королевство, кузница, турниры | Нет | Нет | Следующие согласованные области |
| Кейсы, квесты, промо, голосования, статистика | Нет | Нет | Остаток общих экранов |
| RimWorld, ShedColony | Нет | Нет | Последующие этапы |
| OBS overlay | Не изменялся | Вне задания | Остаётся прежним |

## Как доказан паритет

Старый клиент исполняется из **неизменённых 23 scripts** в порядке текущего
`extension.html`, внутри отдельного настоящего jsdom. Renderers создают DOM,
тесты кликают эти кнопки/select/настоящие confirm Yes/No. Подмена бизнес-handlers
или подтверждения на `true` не используется. Proxy DOM старого frozen harness
не годится для этих `addEventListener`-кнопок, поэтому создан отдельный честный host.

Сравнивается весь записанный след выбранных экранов: method, path, query,
JSON body, JWT, Content-Type, cache. Нормализованы только случайные action/batch IDs.
Регистр `Vigor`, выбранные owned/item IDs, amount, price, equip_now и все expected/
replacement поля сохраняются точно. Незапланированный fetch — ошибка, а не `{}`.
Таймерный oracle учитывает новую позицию interval в очереди при reschedule;
иначе одинаковые deadlines давали искусственный порядок, которого нет в actual host.

40 fixture-ответов получены настоящими Python handlers на временной SQLite с полной
схемой. В том числе общие stats/level/duels и успешный ответ UI-usage — реальные формы,
не выдуманные сокращённые JSON. Входное игровое состояние репрезентативное из
существующих тестов и сериализатора мода, **не выгрузка живой игры**. Дополнительные
изменённые цены/отказы/невалидные поля — явно названные тестовые варианты этих форм.
Генератор сам изолирует RimWorld config во временной папке до backend imports.

Telemetry сохраняет 30 s batching, 5 s timeout, две последующие попытки через 60 s
тем же batch ID/body, лимиты 20 distinct / 20 each / 100 total, UTC-day exposure,
token reset, visibility flush и gated identity. Poll/rerender не считается кликом.
Обычный duplicate action intent считается, а запрещённый вторичный build-family
клик не доходит до dispatcher, как раньше. Ошибка/исключение счётчика не тормозит
игровой запрос. В batch нет имени, токена, item payload или координат; настоящий
серверный validator принимает новый batch и отвергает такие лишние поля.

## Найденные и исправленные ошибки

- Два spec/kit клика в одном кадре проходили одновременно: добавлен синхронный
  общий build-family guard, обычные разные focus намерения не склеиваются
- Старое discard-подтверждение после Alice→Carol отправляло прежний owned_id
  с новым JWT. Новый экран проверяет identity/наблюдаемого героя/текущую вещь/quote.
  Доказан ошибочный запрос в тесте, **не реальное удаление чужой вещи**
- Старые GET могли стереть свежий pending/cooldown либо показать прежнего героя:
  revision/generation barriers, поддержка out-of-order и свежего authoritative GET
- Опрос скрытого inventory, отсутствие GET при входе/повторном входе, сброс фазы
  таймеров, пропущенные hidden Hero refresh tails и двойной in-flight GET исправлены
- Shared poll coalescing не держит новую identity/hero/action revision за старым
  зависшим GET; завершение старого запроса не отпускает блок нового
- После потери ответа/timeout могла возникнуть повторная покупка с новым ID.
  Теперь mutations этой личности блокируются в текущем transport, кнопки выключены,
  reads работают и исход явно назван неизвестным. Автоматического POST/retry нет
- Missing/malformed цены и direct quotes не изображаются бесплатными и не допускают
  покупку. Ноль и отрицательный net payment законны. Цена не рассчитывается локально
- Server refusal/loader text, серверные discard labels и проверенные tier colors
  сохранены; неизвестный текст выводится как текст, не HTML
- Action ID имеет прежний fallback при отсутствии randomUUID; ошибка до вызова
  fetch не выдаётся за уже отправленный неизвестный запрос

Некоторые защиты намеренно отличаются от неисправного старого error-path. Это
**не безусловный паритет каждого отказного поведения**, а перечисленные безопасные
исключения. Точные сценарии: [ядро](PANEL_CORE_PARITY_2026-10-02.md) и
[снаряжение](PANEL_EQUIPMENT_PARITY_2026-10-02.md).

### Важные ограничения

Максимумы focus 5 / attribute 10 сохранены как у старого клиента: backend config
пока не отдаёт эти caps. Нельзя назвать этот старый контракт полностью server-driven.
Equipment JSON не содержит save/session ID: невидимую смену при одинаковых видимых
данных frontend обнаружить не может; окончательная ownership/context проверка на сервере.
Unknown-outcome lock находится в памяти открытой панели. Reload его не сохраняет
и не доказывает, что первая заявка не выполнилась; слепой повтор покупки не предлагается.
Ответ success означает заявку в очереди, не доказанный эффект модом.

## Проверки checkpoint

| Проверка | Результат |
|---|---|
| Полный новый frontend suite | 321 passed, 2 explicit live skips, exit 0 |
| Typecheck | exit 0 |
| Build + check-build | exit 0: 6 входов, helper first, CSP, одинаковые парные HTML, независимые графы |
| Два real HTTP теста мини-игр после rebase | 2/2, exit 0: 6 побед сапёра и полный морской бой, свежая temp DB |
| Red/green controls | 13 core/wiring + 14 equipment + 8 collector mutations, все exit 1 → exact restore → green |
| Неизменность защищённых областей | Git diff legacy/backend/mod/OBS/frozen ZIP пуст |
| Браузер/телефон/318 px/Hosted Test | НЕ проверены |

**Exact-head CI:** [run 37060498062](https://github.com/Shedoy23/shedstream/actions/runs/37060498062),
попытка 2 — success. Frontend и manager-core прошли сразу; первый backend gate
упал в неизменённом `test_skillgames_api.py`. Локально воспроизведён SQLite lock
в async-тесте heartbeat. [Причина, оба исхода и неприменённое предложение](PANEL_CI_FLAKE_2026-10-03.md).
Зелёный повтор не означает, что эта тестовая нестабильность устранена.

Frontend CI явно устанавливает Python 3.12 + PyYAML 6.0.3 для проверки канонического
UI-usage validator; это test-only зависимость, сервер или БД для npm test не запускаются.
Команды: `npm --prefix frontend-next test`, `npm --prefix frontend-next run build`,
`LOCAL_TEST_BASE_URL=http://127.0.0.1:<port> npm --prefix frontend-next run test:live`.
Локальный сервер и HTTP-тесты в облаке выполняются одним shell из-за изоляции loopback.

## Вес первого мобильного входа

`panel-mobile.html` + весь статический import graph: **114 632 bytes raw / 32 980
bytes gzip-9**. Метод ровно `gzip -9 -c <file>` отдельно для каждого файла,
`node frontend-next/scripts/measure-build.mjs frontend-next/dist panel-mobile.html`.
[Перечень файлов и сумм](evidence/panel-2026-10-03/first-checkpoint-sizes.json).
Внешний Twitch Helper, API bodies/headers и sourcemaps в initial transfer не включены.

Это частичный новый panel вход, поэтому его размер нельзя выдавать за уменьшение
всей прежней панели. ≤200 КБ gzip application target выполняется; CDN gzip и
правило Twitch <3 s реально не измерены. `minify:false`, `cssMinify:false`,
`sourcemap:true`, оригинальные читаемые Preact sources и MIT notices сохранены.

## Что требует живой проверки

Облачный браузер отверг loopback как `ERR_BLOCKED_BY_CLIENT`; обхода не было.
Проверка доступной desktop-среды также не дала онлайн-машины для UI QA.
Нужны глаза на 318 px, portrait/landscape, тексты/длинные каталоги, реальные
подтверждения и клавиатуру/тач; затем отдельно разрешённый Twitch Hosted Test.
Ни jsdom, ни зелёный GitHub CI не заменяют этот оставшийся пункт плана.
