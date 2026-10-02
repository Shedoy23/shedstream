# Preact: доказательства ядра панели и развития героя

Локальная кандидатная ветка `feature/panel-preact`. Это ограниченный перенос
подэкрана **развития героя** и совместного host для снаряжения, не всего Hero tab
и не всей панели. Старый frontend, backend, моды и OBS не менялись.
Публикация и деплой этим документом не подтверждаются.

## Откуда взяты ответы и старое поведение

`frontend-next/test/panel-fixtures/generate-responses.py` создаёт отдельную
временную SQLite с полной схемой/миграциями и вызывает настоящие handlers.
На 02.10 генератор сохранил 40 ответов: Bannerlord config/hero/classes/build/
buffs/actions/equipment, а также настоящие `viewer_stats`, `get_user_level`,
`list_duels`, успешный/неавторизованный UI telemetry handler и настоящую форму role refusal. Последние три ответа
success-tail больше не заменены сокращёнными выдуманными объектами.

Входное состояние репрезентативное из существующих backend-тестов и полей
сериализатора мода, не выгрузка живой игры. Изменённые цены, неизвестный отказ, caps и отдельные отказные/гонковые состояния в UI-тестах — явно заданные
изменения fixture для проверки клиента, не заявление о такой текущей экономике
или конкретном ответе сервера в production. Настоящая форма role refusal используется
как forward-compatibility edge: текущие development actions не role-gated.

Повтор генератора из корня (локальный путь нужен импортируемому RimWorld config):

```sh
RIMWORLD_PRICES_PATH=/tmp/preact-local-unused-prices.json PYTHONDONTWRITEBYTECODE=1 \
  /tmp/preact-backend-venv/bin/python frontend-next/test/panel-fixtures/generate-responses.py .
```

`panel-legacy-harness.ts` читает script order из неизменённого `extension.html`
и выполняет все 23 локальных исходника в настоящем jsdom/VM. Старые renderers
создают реальные кнопки/select; тесты кликают DOM и отправляют настоящий change.
`DOMContentLoaded`/Twitch auth startup не запускаются. В выбранном host нет
посторонних daily/tournament/battle/shop/status хостов. Никакие старые mutation
handlers не заменены. Все незаданные fetch маршруты являются ошибкой, включая
ошибку, проглоченную старым catch.

Сравниваются полные упорядоченные traces: method, pathname, query, JSON body,
JWT, Content-Type, cache. Нормализован только случайный client_action_id;
регистры, amount, price, строки ID, имена полей не нормализованы. Порядок ключей
объекта JSON не является отдельным wire-контрактом.

## Проверенные границы

- Все 18 focus и 6 attribute controls, 7 backend classes, 4 specialization и
  3 starter choices; реальные PascalCase атрибуты из lowercase DB
- Общий stats → level + duels tail; hero immediate read и delayed 3500 ms tail
- Current, unavailable, pending, in_battle, syncing, claimed, отсутствующий и
  погибший герой; caps, законный ноль, изменённые цены, отказы/кулдауны
- Реальный PanelApp вместе с EquipmentView: switch на inventory загружает сразу;
  8s polling inventory идёт только на активной вкладке; phase 8s/2.5s не
  сбрасывается при смене вкладки посреди периода; hidden document останавливает
  reads, show сохраняет следующий штатный tick без лишних немедленных GET
- Для обоих смонтированных экранов explicit Hero Refresh вызывает
  hero → equipment → build, даже когда equipment скрыт; success delayed tail
  вызывает hero → build → equipment. Это отличается от periodic visibility gate
- Editor DOM, search, caret и focus переживают same-user token refresh;
  новая identity получает новый subtree и чистый editor
- Pending/cooldown revision, медленный и обратный порядок GET, старое action
  completion другой identity и readonly during auth verification

В parity-режиме host scheduling ограничен выбранными экранами: настоящий старый
`_bindBnrInnerTabs` используется целиком; selected-host intervals воспроизводят
его 8s active-inventory condition и 2.5s buffs, без посторонних pollers. Это не
доказательство полного module startup или всей панели.

## Исправленные ошибки и намеренные безопасные отличия

1. Два разных spec/kit клика в одном кадре раньше проходили per-choice lock.
   Теперь controller синхронно держит общий build-family lock, как BnrBuilds.
2. Переключение tabs сначала перезапускало интервалы. Ref активной вкладки
   сохраняет исходную фазу, а effect меняется только при readiness/lifecycle.
3. Потерянный ответ/20s timeout мог снять lock и разрешить новую покупку с новым
   client_action_id. Теперь `HttpPanelTransport` сохраняет uncertainty для
   channel+opaque viewer. Все новые mutations этой личности в данном transport
   заблокированы; видимые кнопки тоже. Reads/manual refresh продолжают работать.
   Отдельная identity не блокируется, возврат к прежней сохраняет блок.
   Определённый server refusal можно повторить. Автоматического POST/retry нет.
   Сообщение говорит, что первая заявка могла дойти до сервера.
   **Ограничение:** lock находится в памяти этой открытой панели, не переживает
   reload/new transport. Reload не доказывает, что первая заявка не выполнилась,
   и не является рекомендацией повторить покупку. Авторазблокировки после GET нет:
   текущий API не даёт надёжного протокола определения исхода первой заявки.
4. Missing/malformed цены намеренно fail-closed вместо старых fallback prices.
   Повторный Refresh восстанавливает config/classes; failed build read убирает
   устаревшие choices, не подсовывая legacy picker.
5. Action ID сохраняет legacy fallback Date/random при отсутствии randomUUID.
   Локальная ошибка генерации ID/JSON до fetch не считается принятой заявкой
   и не блокирует дальнейшие действия; оба случая показаны red→green.
6. Revision barriers не дают GET, начатому до action acknowledgement, стереть
   новый local pending/cooldown. Backend остаётся экономическим авторитетом.

## Red/green evidence

Фиксы начинались с failing DOM/controller tests и отдельных test-коммитов.
10 controlled mutations отдельно сломали: attribute case, focus amount,
class ID, specialization field, starter field, family lock, pending barrier,
cooldown barrier, response ordering, unknown-result transport block. Все дали
exit 1 с named assertion; каждый исходник восстановлен из собственной копии,
затем core suite exit 0. Никакого git-checkout поверх чужих правок не было.

Главные проверяемые файлы:

- `test/panel-core.test.tsx`
- `test/panel-development-parity.test.tsx`
- `test/panel-app-lifecycle.test.tsx`
- `test/panel-legacy-harness.test.ts`

Точный общий aggregate, вес сборки и независимые equipment mutation results
фиксируются в итоговом отчёте панели после совместного build.

Браузерный visual/318 px, настоящее Twitch Hosted Test, реальные телефоны и
эффект заявки внутри игры здесь не доказаны. Облачный browser loopback был
запрещён; повторной попытки обходным браузером не было.

## Счётчики намерений в настоящем host

Отдельный `PanelUsage` подключён через lifecycle controller и entrypoint.
Используется прежний collector contract: 30 секунд, keepalive, до двух повторов
одного batch через 60 секунд, 5s timeout, token/identity clear, та же allowlist и
лимиты событий. Это не 15s collector мини-игр. В событиях нет action data,
цен, item/owned ID, имён и координат.

Настоящий PanelApp считает только видимое authenticated core/bannerlord
exposure, реальные смены hero/inventory и попытки в общем dispatcher. Exact-choice
повтор, остановленный shared lock, считается попыткой, как раньше; build-family
блокируется выше этого dispatcher и не создаёт второго события. Poll/render
не считаются кликами. Telemetry errors/hung request не задерживают покупку.

Все 23 неизменённых старых скрипта, реальные tab/buttons и новый host сравниваются
полным trace вплоть до 30s/90s batch, hidden flush и последующих pollers. Случайный
batch_id, как и action ID, нормализуется; содержимое, количество и порядок событий
сохраняются. Отдельно проверяется настоящий backend `validate_batch`.

Найден и исправлен дефект самого контролируемого старого clock: interval при
повторном планировании должен получать новый порядок timer task. Постоянная
сортировка по исходному handle неверно ставила его перед давно запланированным
one-shot timeout с тем же deadline. Теперь оба clock используют порядок
повторного планирования; сами deadlines 30s/2.5s и traces не подменены.
