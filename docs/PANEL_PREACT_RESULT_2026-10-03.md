# Панель Preact: результат ночной работы 03.10.2026

## Первый проверенный checkpoint: развитие героя, снаряжение, счётчики

Кандидат `0d57d3e0c9330d7d37f6a36144ed3f39d712908d`, tree
`995023f51759ff2c2787c9477db3205b5c879100`, находится в `feature/panel-preact`.
Ветка продолжает **опубликованную** `feature/skillgames-preact` (`ccd1489`),
а не старую несведённую поставку. Все 38 промежуточных red/green шагов сохранены;
после переноса на опубликованную историю frontend каждого шага побайтно совпал.
[Карта локальных доказательств](evidence/panel-2026-10-03/local-proof-map.json).

Это первый законченный срез. Следующий по согласованному плану — боевые действия.
Ни весь Hero tab, ни вся старая панель пока не называются перенесёнными.
Старые `Расширение/frontend/*`, backend, моды, OBS и frozen ZIP не менялись.
Новой выкладки, слияния и подачи в Twitch нет.

## Покрытие экранов

| Экран/область | Переписан | Паритет запросов | Отличия и оставшиеся границы |
|---|---|---|---|
| Развитие героя | Да: 18 focus, 6 attributes, 7 классов, 4 специализации, 3 starter choices | Да, все реальные DOM controls, full tails | Не весь Hero: создание/возрождение, семья, пол, retinue/daily вне этого среза |
| Магазин и инвентарь | Да: покупка, прямая покупка с заменой, equip/unequip/discard, фильтры, страницы, слоты | Да, реальные старые/новые подтверждения и все поля котировки | Legacy-equipment fallback вне этой карточки не переносился |
| Общий host двух экранов | Да | Да: входы вкладок, повторный вход, фаза polls, hidden explicit refresh, token/identity lifecycle | Полный startup остальных модулей не заявлен |
| Счётчики UI | Да, прежние server events | Да: реальные PanelApp traces + неизменённый collector/server validator | Только осмысленные intent/exposure events; no click scraping |
| Обновление баланса после действия | Общий transport tail | Да: stats → level + duels | Это не перенос всего самостоятельного экрана баланса/статистики |
| Боевые действия | Следующий этап; контракты исследованы | Ещё не заявлен | 8 приказов, стойки, призывы и способности предстоят |
| Отряд/армия, дипломатия/королевство, кузница, турниры | Нет | Нет | Остаток согласованного порядка |
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
