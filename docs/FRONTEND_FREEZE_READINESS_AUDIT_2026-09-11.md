# ShedLink — аудит готовности frontend freeze / Twitch Review

**Дата:** 2026-09-11  
**Режим:** read-only аудит; код, конфигурация, ZIP-кандидат, Dev Console и production не изменялись.  
**Ветка:** `codex/public-release-readiness`

## Вердикт

**Итог: НЕ ГОТОВ к объявлению frontend freeze и отправке в Twitch Review.**

Сам frontend-кандидат `0.0.5` статически согласован, воспроизводим и проходит доступные автоматические проверки. Однако готовность к Review нельзя подтвердить до закрытия трёх P1-гейтов:

1. Не подтверждено, что в Twitch Hosted Test загружен именно проверенный архив с MD5 `059806841c3b84790af97c1056c4c3f5`; последняя документированная Dev Console-проверка относится к предыдущему архиву.
2. Freeze ещё не зафиксирован организационно: нет тега/неизменяемой точки `0.0.5`, а production deploy-lock frontend выключен (`$FrontendReviewOpen = $false`).
3. Найденная во время аудита гонка платной заявки исправлена в текущем локальном HEAD и закрыта тестами, но deployment исправления на production не подтверждён. До этого нельзя гарантировать принцип «эффект или возврат, но не оба» в среде Review.

Дополнительно отсутствует отдельный контрактный тест именно против замороженного артефакта `0.0.5`: существующий compatibility-gate закрепляет `0.0.1`, а остальные тесты проверяют текущее дерево. Это недостаточно для безопасного развития backend после freeze.

### Проверенные точки

| Объект | Значение / статус |
|---|---|
| HEAD в начале аудита | `8a0d9080400ac1abae2b1c01843fed93a78eeaba` |
| HEAD после внешних изменений во время аудита | `c23bcb8` (`0050f18` — исправление гонок; `1693e1f` — тестируемые проходы sweepers) |
| Рабочее дерево перед созданием отчёта | чистое |
| ZIP-кандидат | `dist/shedlink-0.0.5.zip`, 249294 байт |
| SHA-256 ZIP | `6f7e115bfd8bdabbd254a4c1f42cf730961d56f06da0523161d3a54ab43da253` |
| MD5 ZIP | `059806841c3b84790af97c1056c4c3f5` |
| Неизменяемая копия | `dist/releases/shedlink-0.0.5-hosted-20260910-6f7e115b.zip`, байт-в-байт совпадает |
| Public web `https://shedoy23.ru/extension.html` | HTTP 200; проверенные frontend-файлы совпали с локальным деревом по MD5 |
| Public `/dev/extension.html` | HTTP 404 — документированный `/dev`-маршрут не доступен |
| Twitch Hosted Test / CDN | **UNCHECKED**: нет доступа к Dev Console и нет подтверждения MD5 текущего ZIP |
| Production backend revision | **UNCHECKED**: публичный health не раскрывает проверяемый commit |

Во время аудита ветка была изменена извне. На исходном `8a0d908` дефект гонки воспроизводился детерминированно; на финальном `c23bcb8` frontend и ZIP не изменились, backend-suite стал зелёным 97/97. Выводы ниже явно разделяют эти состояния.

## Метод и ограничения

Проверены репозиторий, candidate ZIP, release-документы, публичные URL, frontend-код, backend authority/refund paths, автоматические тесты и локальные мобильные viewport 320×640 и 375×667. Требования Twitch сверены с официальной документацией 2026-09-11.

CodeGraph был недоступен: все структурные запросы возвращали `database is locked`. Поэтому аудит выполнен целевым чтением файлов, запуском тестов и исполняемыми воспроизведениями. Это ограничение не скрывает ни один из указанных ниже **UNCHECKED** live-сценариев.

Не выполнялись и не имитировались как «проверенные»: вход в Twitch Dev Console, загрузка ZIP, реальный Hosted Test, submit в Review, реальный Twitch identity consent/token refresh, iOS/Android Twitch app, многопользовательский live-нагрузочный сценарий, реальные моды/игры и production DB failover/restart.

## Находки по приоритетам

### P0

Не найдено.

### P1 — блокируют Review

#### P1-1. Точный ZIP в Hosted Test не подтверждён

- **Где:** Twitch Dev Console → версия `0.0.5` → Hosted Test.
- **Сценарий:** ревьюер открывает Hosted Test, но CDN обслуживает предыдущую загрузку, а локально проверялся новый архив.
- **Ожидание:** отображаемый в Dev Console MD5 равен `059806841c3b84790af97c1056c4c3f5`, обе поверхности используют новый cache-bust `?v=202609101017`, версия в UI — `v0.0.5`.
- **Факт:** локальный ZIP и immutable-copy совпадают; `verify-candidate.py` зелёный. Но release record требует ручной загрузки и сверки MD5, а последняя зафиксированная Hosted Test-сверка относится к архиву `513ff...`, MD5 `34bad42f...` от 2026-09-09.
- **Доказательство:** `dist/shedlink-0.0.5.zip`; `Расширение/docs/RELEASE_RECORD.md`; `Расширение/docs/HOSTED_TEST_TRANSPORT_CHECKLIST.md`.
- **Исправление:** владелец загружает именно проверенный ZIP в Dev Console, сверяет MD5, открывает desktop/mobile Hosted Test и записывает результат в release record.
- **Блокирует Review:** да.

#### P1-2. Гонка платной заявки существовала на исходном HEAD; локально исправлена, production не подтверждён

- **Где:** `Расширение/backend/main.py`, `database.py`, adapters ShedColony/Bannerlord/RimWorld.
- **Сценарий, подтверждённый на `8a0d908`:** TTL-sweeper выбирает старую `queued`; игра между выборкой и возвратом переводит её в `dispatched` или `acked`; adapter не перечитывает допустимый статус и возвращает 200, после чего строка становится `failed`. Результат — эффект и деньги одновременно. Сценарий воспроизведён для всех трёх модулей и обоих статусов.
- **Смежные подтверждённые гонки:** poll мог отдать игре строку, которую sweeper уже refund'нул; dispatched-sweeper мог перетереть `acked` обратно в `queued`.
- **Ожидание:** единственный исход платной заявки; статус-проверка и действие — в одной транзакции.
- **Факт на финальном HEAD:** `refund_still_due()` проверяет статус в транзакции возврата; poll перечитывает и захватывает строки под одной write-lock; requeue использует `WHERE status='dispatched'`. `test_module_action_races.py` детерминированно закрывает три класса гонок. Полный suite — 97/97.
- **Доказательство:** `Расширение/backend/modules/_base.py:173`; adapters `rimworld/_adapter.py:93`, `shedcolony/_adapter.py:403`, `bannerlord/_adapter.py:759`; `database.py:4521`; `main.py:2001,2087`; commit `0050f18`.
- **Исправление:** кодовая часть уже внесена извне во время аудита. Осталось штатно доставить backend на production и выполнить post-deploy contract/race smoke; frontend ZIP при этом менять не требуется.
- **Блокирует Review:** да, пока revision production не подтверждена.

#### P1-3. Freeze-контур не закрыт и нет контракта для immutable `0.0.5`

- **Где:** git tags, `scripts/deploy.ps1:93`, backend compatibility tests.
- **Сценарий:** после начала Review frontend случайно меняется либо backend эволюционирует против текущего дерева, а не против уже загруженного CDN-артефакта.
- **Ожидание:** неизменяемый идентификатор кандидата, включённый deploy-lock и CI/test fixture, читающий контракт `0.0.5`.
- **Факт:** immutable ZIP-копия есть, но тега `submit/0.0.5` нет; `$FrontendReviewOpen = $false`; комментарий lock всё ещё описывает старый Review `0.0.2`. `test_frontend_001_compat.py` защищает только `0.0.1`.
- **Доказательство:** `git tag --list`; `scripts/deploy.ps1:93-107`; `Расширение/backend/tests/test_frontend_001_compat.py`.
- **Исправление:** непосредственно перед submit зафиксировать тег/commit/hash кандидата, включить deploy-lock, добавить контрактный тест/fixture `0.0.5` без изменения содержимого ZIP.
- **Блокирует Review:** да для объявления freeze; контрактный тест допустимо добавить только в backend/tests.

### P2 — существенный риск, но не самостоятельный hard blocker

#### P2-1. На узком mobile viewport навигация становится неочевидной и имеет малые touch targets

- **Где:** `extension.html:62-66`, `mobile.html:62-66`, `viewer.css:1473`.
- **Сценарий:** при ширине 320/375 px подписи вкладок скрыты, остаются только emoji; у этих кнопок нет `aria-label`/`title`.
- **Факт:** горизонтального overflow нет; контент и раскрытие шансов доступны кликом. Но вкладки имеют высоту около 35 px, кнопка закрытия — около 25×20 px, а смысл emoji не задан доступным именем.
- **Исправление:** в следующей frontend-версии добавить доступные имена и увеличить touch targets; изменение текущего ZIP сейчас сбросит проверку Hosted Test и потребует нового кандидата.
- **Блокирует Review:** нет само по себе; повышает риск замечания «not intuitive/mobile usability».

#### P2-2. Документированный `/dev`-маршрут расходится с публичной средой

- **Где:** public web routing и release-документация.
- **Факт:** `https://shedoy23.ru/dev/extension.html` отдавал 404; `https://shedoy23.ru/extension.html` — 200 и совпал с локальными frontend-файлами. Корневая распакованная оболочка без injected meta показывает метку `dev`, тогда как ZIP корректно содержит `v0.0.5`.
- **Риск:** оператор может проверить не ту поверхность и ошибочно считать `/dev` независимой средой.
- **Исправление:** либо восстановить маршрут, либо исправить runbook/release record и явно назвать public root preview.
- **Блокирует Review:** нет, если Hosted Test ZIP отдельно подтверждён.

#### P2-3. Live-матрица перед Review пока не выполнена

- **Где:** `HOSTED_TEST_TRANSPORT_CHECKLIST.md`, `INGAME_CHECKLIST_TRACK_B.md`, `REVIEWER_WALKTHROUGH.md`.
- **Не проверено:** anonymous → identity share → authorized; реальный refresh/expiry JWT; Twitch mobile portrait/landscape; suspend/resume; длинные тексты/пустые/error-состояния; одновременные пользователи и каналы; real save/restart/offline; game refusal/no-op; падение мода в критических окнах; все игровые каталоги и модалки; Config page в Dev Console.
- **Ожидание:** каждый пункт имеет PASS/FAIL, устройство/канал, время и evidence.
- **Блокирует Review:** чеклист целиком — да как release-gate; отдельный сценарий может быть отложен только явным решением владельца с риском.

### P3 — неблокирующие улучшения

- Mobile ZIP укладывается в лимит Twitch 1 MB: распакованные assets около 911 KB. Запас небольшой (~89 KB), поэтому новые assets легко нарушат лимит.
- Warning `lint_consistency.py` о недоступной game assembly означает, что policy catalog проверен не полностью; для текущего frontend ZIP это не ошибка, но перед изменением игрового каталога нужен доступ к сборке.
- Текст deploy-lock устарел и ссылается на версии `0.0.3/0.0.4`; его стоит актуализировать при включении freeze.

## Артефакт и доставка

`verify-candidate.py --version 0.0.5` подтвердил:

- 24 файла архива совпадают с frontend tree;
- различие HTML только ожидаемое: injected `<meta name="shedlink-version" content="0.0.5">`;
- в обеих оболочках одинаковый cache-bust `?v=202609101017`;
- release journal описывает именно этот архив;
- ZIP содержит 25 entries с `VERSION`, без `.exe/.dll/.jar/.db/.env/.map/.pdb`;
- не найдено `iframe`, inline `<script>` или `eval`;
- внешние URL ограничены ожидаемыми Twitch/ShedLink/статическими namespace.

Публичные `viewer.js`, `shop.js`, `viewer.css`, `extension.html`, `mobile.html` на `shedoy23.ru` совпали с локальным деревом по MD5. Это доказывает состояние public preview, но **не** состояние Twitch CDN/Hosted Test.

## Auth, identity, JWT и состояние UI

Статическая и автоматическая проверка подтверждает:

- `Twitch.ext.onAuthorized` обновляет token при каждом вызове (`viewer.js:386`), а не использует token навсегда;
- неизвестная identity приводит к запросу share identity, а отказ оставляет повторную попытку доступной;
- backend `/api/user/resolve-twitch-token` проверяет подпись/expiry JWT и извлекает signed `user_id`/`channel_id`; переданный клиентом opaque id не становится источником authority;
- login-map переживает restart (`test_login_map_survives_restart.py`);
- при потере auth баланс/доход становятся неизвестными (`—`), а не ложным нулём (`viewer.js:594`);
- `_stateSeq` отбрасывает поздний ответ старого запроса после нового auth/state (`viewer.js:1065`);
- no-store и принудительное обновление stats покрыты тестами.

`test-viewer-auth-recovery.mjs`: 4/4 PASS. Девять frontend smoke/unit scripts — PASS. Реальные token expiry/refresh, anonymous consent в Twitch и мобильное восстановление — **UNCHECKED**.

## Платные действия и server authority

### Общий контракт

Frontend отправляет intent; backend владеет ценой, доступностью, tenant/channel context, лимитами, каталогом, отказом, charge/refund и терминальным статусом. `expected_price` у прогрессивных RimWorld-покупок защищает согласие пользователя на цену; старый клиент без поля остаётся совместимым по отдельному test gate.

Универсальный ожидаемый жизненный цикл:

`queued → dispatched → acked` **или** `queued/dispatched → failed + один refund`.

Нельзя считать корректным `acked → queued`, выдачу `failed` игре, двойной charge/refund либо refund после эффекта. Текущий локальный HEAD имеет детерминированные race tests для этих инвариантов.

### Матрица модулей

| Группа | Автопокрытие | Итог | Live |
|---|---|---|---|
| RimWorld | charge atomic, double click, offline/stream gate, abandoned commands, refund/refund counter, tenant/channel isolation, transport, catalog, price consent, race suite | локально PASS | **UNCHECKED** в реальной игре |
| Bannerlord | buy action, authority contracts, target spoof, child limits, refusal coverage, race suite | локально PASS | **UNCHECKED** |
| ShedColony | money, catalog/item catalog, empty roster, special refund, race suite | локально PASS | **UNCHECKED** |
| Cases / open-all | single/open-all, hourly cases, odds disclosure | локально PASS | **UNCHECKED** в Hosted Test |
| Quests / rewards | atomic quest reward, engagement/watchtime/session gates | локально PASS | **UNCHECKED** multi-user live |
| TTS | approval/moderation/refund on reject | локально PASS | **UNCHECKED** реальный playback/moderation |
| Pets | UI layout + documented global/cross-channel exception | локально PASS | **UNCHECKED** live; исключение должно остаться явным |

Full backend suite на исходном HEAD был 96/97: `test_module_action_races.py` падал до assertions из-за отсутствия вынесенных функций и отдельно выполненное воспроизведение показывало реальный refund-after-take. На финальном HEAD — **97/97, exit 0 у каждого**.

## Mobile UI

Локально проверены viewport 320×640 и 375×667:

- горизонтального overflow нет (`scrollWidth == viewport width`);
- основные карточки доступны вертикальным scroll;
- раскрытие валюты/вероятностей работает тапом без hover;
- layout не ломается на 320 px.

Ограничения: это browser preview без Twitch chrome, реального Helper auth, safe-area, soft keyboard и игровых данных. Поэтому mobile modal/catalog/error/empty states и landscape остаются **UNCHECKED**.

## Twitch Review — сверка требований

Проверено по официальным страницам Twitch 2026-09-11:

- [Extension Life Cycle](https://dev.twitch.tv/docs/extensions/life-cycle/): Review идёт из Hosted Test/CDN; изменение assets во время Review требует возврата в Local Test, новой загрузки и повторной отправки; нужны рабочий review channel, walkthrough и changelog.
- [Guidelines and Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/): extension должна загружаться, быть понятной, работать с активной игрой/конфигурацией; mobile initial load — до 1 MB и должен укладываться в mobile viewport; контент и награды должны быть точными и допустимыми.
- [Building Extensions](https://dev.twitch.tv/docs/extensions/building/): mobile frontend тестируется отдельно; EBS проверяет JWT; `onAuthorized` вызывается снова при refresh, использовать надо последний token.
- [Extensions Reference](https://dev.twitch.tv/docs/extensions/reference/): `onAuthorized` — источник свежего token/opaque user identity; mobile context может отличаться.
- [Submission Best Practices](https://dev.twitch.tv/docs/extensions/submission-best-practices/): подробный walkthrough, изолированный changelog, требования к игре/приложению и согласованное live-окно уменьшают риск отклонения.

Статически ShedLink согласуется с CSP-профилем: нет iframe/inline scripts/eval, EBS и внешние endpoints HTTPS. Крустики и игровые награды не заявлены как деньги/обмениваемая ценность; кейсы раскрывают шансы, contest rules и prize descriptions присутствуют. Фактические Dev Console metadata, allowlists, review channel, screenshots и reviewer instructions — **UNCHECKED**.

## Что можно менять после freeze

### Обычно безопасно без новой frontend-версии

- backend-only исправления, сохраняющие существующие endpoints, методы, auth и JSON shape;
- добавление необязательных полей;
- server-owned цены, лимиты, каталоги, refusal texts и availability, если текущий клиент корректно обрабатывает `0`, `null`, missing/unknown и прежние значения;
- observability, migrations, race/atomicity fixes и тесты;
- документация вне ZIP.

Каждое такое изменение всё равно должно пройти контрактный тест против **точного `0.0.5`** и smoke в Hosted Test.

### Требует новой frontend-версии и повторного Twitch Review/проверки

- любое изменение HTML/JS/CSS/assets или cache-bust в ZIP;
- новый UI, тексты/раскрытия, navigation, mobile layout, auth flow;
- смена CDN/EBS origins, CSP-relevant ресурсов или путей;
- удаление/переименование endpoint/JSON field, изменение типа/семантики, обязательный новый request field;
- backend-изменение, которое текущий `0.0.5` не может корректно отобразить или отказоустойчиво пережить.

## Rollback и эксплуатационная модель

- **Frontend:** immutable archive существует и позволяет воспроизвести candidate. Однако после submit Twitch assets фактически immutable; мгновенная «подмена» ZIP не является rollback-планом. Для изменения нужна новая версия/цикл. До submit rollback — вернуться из Review/Hosted Test, загрузить выбранный проверенный archive и заново сверить MD5.
- **Backend:** можно откатывать независимо только на revision, совместимую с frozen `0.0.5`. Нужны идентификатор deployed commit, DB-migration compatibility и post-rollback smoke. В текущем аудите это не подтверждено.
- **Сигнал остановки:** несовпадение MD5, неизвестный backend revision, failure race/contract suite, неверная валюта/цена, paid no-op без refund, двойной effect/refund, cross-tenant leak, JWT acceptance failure или mobile overflow/blank screen.

## Обязательный pre-submit gate

1. Развернуть backend с исправлением не ниже `0050f18`; записать production commit и health evidence.
2. Запустить 97/97 suite и отдельный `test_module_action_races.py` на release revision.
3. Добавить и прогнать compatibility fixture для неизменяемого `0.0.5`.
4. Загрузить `dist/shedlink-0.0.5.zip` в Dev Console и сверить MD5 `059806841c3b84790af97c1056c4c3f5`.
5. Выполнить Hosted Test transport + desktop/mobile + in-game Track B, включая auth expiry, offline/refund, restart/save и concurrency.
6. Проверить Dev Console metadata, review channel/allowlist, config, walkthrough, changelog, privacy/terms и reviewer access.
7. Зафиксировать тег/commit/hash кандидата и включить frontend deploy-lock.
8. Только после PASS всех пунктов объявлять freeze и нажимать Submit for Review.

## Итоговая классификация

### Подтверждённые дефекты

- На исходном `8a0d908`: три гонки жизненного цикла платной заявки, включая запрошенный `queued → selected → dispatched/acked → refund/failed`; исправлены локально в `0050f18`, тесты зелёные.
- Public `/dev/extension.html` возвращает 404 вопреки рабочей документационной модели `/dev`.
- Mobile tab navigation при 320/375 px скрывает подписи без альтернативных accessible names и использует малые touch targets.

### Неподтверждённые риски

- production может ещё не содержать race fix;
- Hosted Test может обслуживать предыдущий ZIP;
- backend после freeze может сломать `0.0.5`, поскольку нет отдельного artifact-level contract gate;
- небольшой запас до mobile 1 MB.

### Не проверено

- Twitch Dev Console/Hosted Test/CDN и реальный review channel;
- deployed backend commit;
- live Twitch auth/token expiry/mobile app;
- реальные игровые эффекты, отказ/no-op/refund, save/restart/offline и concurrency;
- все authenticated/error/empty/long-text mobile states;
- production rollback rehearsal.

### Неблокирующие улучшения

- accessibility/touch targets mobile navigation;
- актуализация `/dev` и deploy-lock документации;
- увеличение запаса mobile bundle;
- полный catalog lint с доступной game assembly.

**Заключение:** содержимое `shedlink-0.0.5.zip` можно сохранить как кандидат без новых frontend-правок. Следующий безопасный шаг — не менять ZIP, а подтвердить backend fix на production, закрепить artifact-level contract, загрузить и сверить точный ZIP в Hosted Test, пройти live-матрицу и только затем формально включить freeze.
