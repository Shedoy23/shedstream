# Кузница Preact: паритет и безопасность, 03.10.2026

## Результат

Существующая кузница в инвентаре перенесена целиком в отдельную Preact-панель.
Runtime **c00bf91196820d8a7478ab59bd35a79555e6fb39** прошёл независимый обзор;
финальные тесты и обновлённые handler-fixtures **04a011e48f53221f95b9bb8e33706d54bd2ace88**:
**937 unit/DOM passed + 2 explicit live skips**. Два HTTP-теста выполнены отдельно:
**2/2 exit 0**. Последующий portable cashier probe не меняет runtime или Vitest cases.
Кузница отдельно: **54 теста**, ещё **6 независимых edge probes**, **16 мутаций**,
каждая exit 1 с поломкой и exit 0 после точного восстановления собственных байтов.
[Машинное подтверждение и хеши логов](evidence/panel-forge-2026-10-03/verification.json).

Это локальный кандидат, не весь оставшийся интерфейс. Настоящий турнир не перенесён.
Ни публикации новых panel-коммитов, ни merge, deploy, Twitch submission/release не было.

## Что повторяет старую панель

- Раскрываемая секция «Кузница (трофеи)» внутри инвентаря, изначально закрыта;
  раскрытие сохраняется при переходах, переписывании заголовка героя и обычных polls.
- Десять прежних позиций: weapon0–weapon3, head, body, leg, gloves, cape, horse.
  Пустые слоты, тир, все старые labels качества, следующая ступень, максимум,
  обозначение щита и цена из отдельного `config.reforge_price`.
- Девять кнопок базового сценария проверены поимённо: все позиции кроме weapon3,
  который в реальном handler-fixture уже legendary. Horse сохраняет старую кнопку;
  если у вещи нет улучшений, настоящий сервер отказывает до списания.
  Horseharness сервер поддерживает, но в старых десяти UI-позициях его нет.
- Тексты определённых отказов сервера показываются без подмены; числовой ноль цены
  остаётся допустим. Новых покупок `hero.smith_item`/`hero.equip_trophy` не добавлено.
- POST `/api/bannerlord/action`: `action_type=hero.reforge_quality`, data содержит
  только `slot` и свежий `client_action_id`. Цена, item_id и modifier клиентом не назначаются.
- Успех: общий balance → level/duels, через 3500 мс hero/build/equipment и отдельный
  старый forge-хвост с ещё одним hero GET. При определённом отказе только локальный
  hero GET через 3500 мс. Проверен весь trace до 30 секунд с обычным polling,
  JWT, Content-Type, cache, query и usage. Нормализуются только случайные client IDs.
- Отдельного платного подтверждения или нового forge polling не появилось.
  Usage считает открытие секции и действие без данных покупки.

Oracle исполняет неизменённые 23 старых scripts и настоящие DOM controls.
Сравнивается выбранный host со всеми его reads/tails; это не заявление о полном
паритете ещё не перенесённой общей оболочки и всех модулей.

## Намеренные безопасные отличия

1. Новый принятый предмет/quality перерисовывается даже при прежнем заголовке героя.
   Сохранённый callback не покупает по уже изменённой вещи/цене до нового рендера.
   Смерть/отсутствие героя, скрытый инвентарь и ошибка hero read закрывают покупки.
2. Один слот защищён от синхронного двойного клика; разные слоты независимы.
   Неизвестный исход POST блокирует новые покупки, не повторяется автоматически
   и сохраняется при обновлении JWT того же зрителя. Старые JWT/viewer continuations
   не делают отложенные reads под новой личностью.
3. Некорректная/отсутствующая цена не заменяется fallback. Появилась узкая кнопка
   «Обновить цену кузницы», которая перечитывает только config и сохраняет disclosure.
4. Принятый `my-hero` ещё может показывать вещь A, когда новый `equipment-shop`
   уже сообщил B, другое quality или отсутствие вещи. Только спорный forge-слот
   блокируется с «Данные вещи обновляются» до согласования принятых источников.
   Магазин и согласованные слоты не блокируются. Повтор старого hero, ошибка или
   неполный inventory, обновление JWT не стирают наблюдение. Старый ответ другого
   героя/зрителя не снимает текущий запрет. Сравниваются item_id и quality; tier
   намеренно исключён: endpoints используют нумерацию от 0 и от 1.

### Почему нужна последняя защита

[Реальная временная касса](evidence/panel-forge-2026-10-03/cashier-proof.json):
сначала принят `my-hero` с fine helmet_A; затем inventory изменён на helmet_B,
и equipment-shop уже отдаёт B. Slot-only POST head списывает 20000💎
(100000 → 80000) и ставит в очередь `_reforge.item_id=helmet_B`.
Свежий my-hero тоже возвращает B: это **устаревшее клиентское наблюдение во времени**,
а не неисправность двух свежих ответов сервера. Все деньги/аккаунты тестовые.
Старый DOM oracle продолжает отправлять такой запрос, новый блокирует.

Защита ограничена тем, что клиент уже увидел. DTO не содержит save/session ID;
невидимую одинаковую смену или изменение после GET перед POST фронт атомарно
не обнаружит. Окончательные target/charge/queue/game проверки остаются серверу/моду.

## Данные и воспроизведение

`frontend-next/test/panel-fixtures/forge-tournament-responses.json` содержит **61**
запись настоящих route/adapter handlers на временной SQLite с полными migrations.
Это формы ответов и seeded состояния, не запись реального эфира.
В generator `require_jwt_user` подменён: это не HTTP/JWT/игровое доказательство.
Девять source SHA-256 сверены; backend/mod/legacy не изменены.
Poor/inferior quality_rank исправлены с синтетических -2/-1 на реальные mod values
0/0 и fixture регенерирован. Следующая ступень по-прежнему rank1.
Название fixture также содержит tournament-ответы для исследования; ни наличие
JSON, ни отдельный synthetic `tournament.html` не означает перенос реального турнира.

```sh
npm --prefix frontend-next ci
npm --prefix frontend-next test -- --maxWorkers=2
npm --prefix frontend-next run build
npm run test:frontend && npm run lint:js && npm run globals:selftest
python scripts/lint_consistency.py
# Python окружение с requirements-test и pyflakes:
python frontend-next/test/panel-fixtures/generate-forge-tournament-responses.py
python frontend-next/test/panel-fixtures/probe-forge-target-mismatch.py /tmp/forge-proof.json
# Только в своей чистой копии: script намеренно ломает и восстанавливает файлы.
python frontend-next/scripts/check-forge-mutations.py /tmp/forge-mutation-evidence
node frontend-next/scripts/measure-build.mjs frontend-next/dist panel-mobile.html
```

54 forge tests — `panel-forge-{parity,safety,observation}.test.tsx`.
Полные логи в [папке доказательств](evidence/panel-forge-2026-10-03).
Исходные red: отсутствие quote retry и шесть наблюдаемых target-regressions.
Первая диагностическая мутация alive-guard выжила, потому что другой guard уже
блокировал несовпадающее equipment. Тест исправлен согласованным исходным inventory
и явной проверкой enabled; после этого все 16 cases убиты. Этот диагностический
survivor сохранён, не выдан за pass. Мутации выполнялись в отдельном worktree;
основной checkout не содержал сломанного runtime. На окончательных fixture/tests
полный suite повторён. Проверка type/build и независимый review привязаны к тому же
runtime; более поздние изменения — только tests/probes и этот отчёт.

## Вес и непроверенные границы

`panel-mobile.html` + его статический import graph: **230996 raw / 60804 gzip-9 bytes**.
Карты, внешний Twitch Helper, API bodies/headers сюда не входят; gzip посчитан
локально для каждого файла. minify:false, cssMinify:false, sourcemaps и notices сохранены.
Это не измерение CDN или подтверждение Twitch <3 секунд.

Браузерная игра/318 px, настоящий телефон, Twitch Hosted Test, реальный Twitch login,
производственная нагрузка и применение кузницы в игре **не проверены**.
Cloud loopback был denied, обхода не было. Desktop ранее подтверждён offline.
Нужны разрешённый браузерный проход и отдельно согласованный Hosted Test.
Malformed truthy hero flags/нестандартные quality types остаются robustness-границей:
настоящие handlers сейчас отдают корректные типы, новый серверный баг не утверждается.
