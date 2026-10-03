> ИСТОРИЧЕСКАЯ инвентаризация базы b2064f4. Текущая сверка кнопок: [RECONCILIATION](PANEL_FULL_PORT_RECONCILIATION_2026-10-03.md), результаты: [COVERAGE](PANEL_FULL_PORT_COVERAGE_2026-10-03.md).

# Инвентаризация игровых действий для полного порта панели

Снимок кода: `feature/panel-preact-full` на `b2064f4`. Это сверка старых модулей
`Расширение/frontend/{viewer-rimworld.js,pawn.js,xenotype.js,viewer-shedcolony.js}`
с `frontend-next/src/panel`. Рассматриваются кнопки, отправляющие игровые действия;
чисто локальные вкладки, фильтры и закрытие модальных окон перечислены ниже.

## Вывод

В `frontend-next/src/panel/main.tsx:1-19` создаётся `PanelApp` с Bannerlord
Equipment, combat и party. Вызовы панели направлены на `/api/bannerlord/*`;
в коде панели нет `/api/rimworld/*`, `/api/shedcolony/*`, RimWorld или Shedcolony.
Поэтому порт этих двух игр ещё не начат в выбранном Preact-панеле.

При этом серверные контракты обеих игр уже есть в старом backend: RimWorld в
`Расширение/backend/rimworld.py`, Shedcolony в
`Расширение/backend/routes/shedcolony.py`. В рассмотренных действиях не найден
блокер вида «на сервере нет ручки». Основная работа — интерфейс, state, формы,
цены и вызовы из нового клиента. Старый сервер должен оставаться источником
денег, каталогов и допустимых значений.

## RimWorld: действия и запросы

Старый модуль запускает игровые опросы только после выбора `active_module`;
при старте запрашивает статус, конфиг, колонистов, пешку, магазин и события
(`viewer-rimworld.js:80-101`). `X-Twitch-JWT` передаётся в приватные запросы.

| Действие/кнопка | Запрос и payload | Цена / серверное ограничение | Покрытие `frontend-next` |
|---|---|---|---|
| Запрос Twitch ID | `Twitch.ext.actions.requestIdShare()`; HTTP нет (`viewer-rimworld.js:109-139`) | Разблокирует идентификацию Twitch | Нет |
| Купить событие RimWorld | `GET /api/rimworld/events`, затем `POST /api/rimworld/trigger-event` `{username,event_id}` (`viewer-rimworld.js:148-159,238-283`) | `cost` приходит в каталоге событий. UI ставит общий 5-минутный cooldown (`EVENT_COOLDOWN_MS`), сервер остаётся решающим | Нет |
| Удалить черту | `POST /api/rimworld/remove-trait` `{username,trait_def,degree}` (`viewer-rimworld.js:286-310`; кнопка в `pawn.js`) | **300** очков (`TRAIT_REMOVE_COST`) | Нет |
| Купить черту | `POST /api/rimworld/buy-trait` `{username,trait_def,degree,expected_price?}` (`viewer-rimworld.js:322-349`; UI каталога загружается legacy shop) | Цена динамическая из server catalog/progressive pricing; отправленная цена проверяется сервером, не служит источником списания | Нет |
| Купить ген | `POST /api/rimworld/buy-gene` `{username,def_name,expected_price?}` (`viewer-rimworld.js:352-377`) | Динамическая progressive price; `expected_price` защищает от изменения цены между показом и нажатием | Нет |
| Удалить ген | `POST /api/rimworld/remove-gene` `{username,def_name,label}` (`viewer-rimworld.js:380-416`; кнопка в `pawn.js`) | **3000** очков (`GENE_REMOVE_COST`) | Нет |
| Создать пешку | `POST /api/rimworld/create-pawn` `{username,pawn_name}` после подтверждения (`pawn.js:540-565`) | **200** очков; сервер проверяет баланс и ставит команду в очередь | Нет |
| Лечить пешку | `GET /api/rimworld/heal-cooldown/{username}`, затем подтверждение и `POST /api/rimworld/heal-pawn` `{username}` (`pawn.js:455-532`) | **150** очков; cooldown **15 минут**; сервер проверяет cooldown/баланс | Нет |
| Воскресить свою пешку | `POST /api/rimworld/resurrect-pawn` `{username}` после подтверждения (`pawn.js:568-591`) | **500** очков | Нет |
| Выбрать ксенотип | `GET /api/rimworld/catalog?category=xenotype&username=...`, `POST /api/rimworld/buy-item` `{username,item_def,def_name}` (`xenotype.js:40-44,122-153`) | Каталожная цена конкретного ксенотипа; смена заменяет текущие ксеногены. Сервер требует позицию в `shop_catalog` и списывает catalog price | Нет |
| Купить нейротренер | `GET /api/rimworld/catalog?category=neurotrainer&username=...`, затем `POST /api/rimworld/train-skill` `{username,item_def}` (`xenotype.js:177-187,215-238`) | Цена нейротренера из каталога; cooldown UI 3 секунды на item, сервер — истина по цене/каталогу | Нет |
| Поднять страсть навыка | `GET /api/rimworld/pawn-skills/{username}`, затем `POST /api/rimworld/buy-passion` `{username,skill_def,passion}` (`xenotype.js:257-261,325-343`) | `upgrade_price` приходит с сервера; только следующий уровень страсти 0→1→2, ограничения навыка проверяет backend | Нет |
| Сбросить страсть навыка | `POST /api/rimworld/reset-passion` `{username,skill_def}` после подтверждения (`xenotype.js:346-369`) | `reset_price` приходит в ответе списка навыков; backend проверяет цену/пешку/навык | Нет |

Информационные запросы без покупки: `GET /api/rimworld/status`,
`/api/rimworld/config`, `/api/rimworld/colonists`, `/api/rimworld/my-pawn/{username}`,
`/api/rimworld/catalog`, `/api/rimworld/pawn-skills/{username}` и
`/api/rimworld/heal-cooldown/{username}`. Серверные цены фиксированных кнопок заданы
в `Расширение/backend/rimworld.py:66-74` и отдаются через
`/api/rimworld/config` (`:2939-2964`): spawn 200, heal 150, resurrect 500,
trait removal 300, gene removal 3000. Предметные цены берутся не из UI, а из
канального `shop_catalog`; сервер фильтрует по категории/наличию товара и сверяет
динамические цены (`:1720-1810,1814-1885`). События получают цену из синхронизируемого
каталога событий (`:2675-2757`).

## Shedcolony: действия и запросы

Старый модуль раз в 5 секунд делает `GET /api/shedcolony/my-colonist` и
`GET /api/shedcolony/capacity`; до отображения кнопок получает
`GET /api/shedcolony/config` (`viewer-shedcolony.js:769-816`). Конфиг содержит
`action_prices` и разрешённые каталоги. Все покупки проходят через
`ShedLink.buyAction('shedcolony', type, data, ...)`: POST
`/api/shedcolony/action`, JWT и `{action_type,data:{...client_action_id}}`
(`viewer-shedcolony.js:319-335`; `viewer-actions.js:120-140`). Сервер игнорирует
клиентскую цену, подставляет `_ACTION_PRICES`, сам резолвит `citizen_id` зрителя,
списывает и ставит действие в очередь (`routes/shedcolony.py:96-137,355-378`).

| Кнопки/действия | Payload `data` | Цена (server `_ACTION_PRICES`) | Ограничения и источник |
|---|---|---:|---|
| Создать колониста `colonist.spawn` | `{}` | 1000 | Один активный колонист на зрителя; повторная pending-заявка блокируется (`shedcolony.py:380-419`) |
| Назначить работу `colonist.assign_job` | `{job}` | 300 | Свободные места отображаются из capacity; backend проверяет job allowlist (`:232-245,410-420`) |
| Дать дом `colonist.assign_home` | `{}` | 200 | Свободные койки показываются из capacity; цель остаётся за модом |
| Прокачать выбранный навык `colonist.add_xp` | `{skill}` | 400 | Сервер фиксирует **1000 XP** (`shedcolony.py:257-258,406-410`) |
| Выполнить просьбу `colonist.fulfill_request` | `{request_id?}` | 100 | Токен выбранной просьбы валидируется; без него мод закроет верхнюю открытую просьбу (`:247-250,429-438`) |
| Покормить / вылечить болезнь / исцелить / снять траур | `colonist.feed`, `.cure_disease`, `.heal`, `.clear_mourn`; `{}` | 75 / 100 / 100 / 50 | Кнопки сереют, если snapshot показывает полный голод/HP или отсутствие болезни (`viewer-shedcolony.js:404-416`) |
| Поднять настроение `colonist.happiness_boost` | `{}` | 400 | На своём колонисте; цена сервера |
| Выдать еду/предмет `colonist.give_item` | `{item}` | 200 | Каталог `item_catalog.give_item`; allowlist и проверка наличия в сборке (`shedcolony.py:155-207,441-449`) |
| Сменить пол / телепортировать | `colonist.set_gender`, `colonist.teleport`; `{}` | 200 / 150 | Только свой citizen; смена — переключатель, направление не задаётся |
| Броня: кожа / железо / алмаз / незерит | `colonist.equip_leather`, `.equip_iron`, `.equip_diamond`, `.equip_netherite`; `{}` | 500 / 1500 / 3000 / 4000 | Свой колонист |
| Инструменты / оружие / щит | `colonist.give_tools`, `.equip_weapon`, `.give_shield`; `{}` | 2500 / 2500 / 1000 | Инструменты только при назначенной работе; оружие/щит только для guard jobs (UI gate) |
| Боевой приказ / отступление гвардейца | `colonist.set_guard_task` `{task:'guard'|'patrol'}`; `colonist.set_guard_retreat` `{retreat:boolean}` | 500 / 300 | Сервер принимает только guard/patrol, без follow (`:463-470`) |
| Фестиваль / гость / квест / шпионы | `colony.festival`, `.spawn_visitor`, `.quest_unlock`, `.spy_boost`; `{}` | 3000 / 2000 / 2000 / 1500 | Шпионы — только во время рейда; для гостя нужна таверна (подсказки UI) |
| Снабдить колонию | `colony.supply` `{item}` | 1000 | Только базовые материалы из `item_catalog.supply`, без ценных ресурсов (`:164-180,440-449`) |
| Закрепить неснижаемый запас | `colony.set_minimum_stock` `{item,qty}` | 75000 | Каталог `min_stock`; количество **1–16 стаков**; нужен склад (`:184-214,440-450`) |
| Разгрести заказы здания | `colony.clear_backlog` `{building: 'x,y,z'}` | 50000 | Выбирается позиция из `capacity.targets.buildings`; backend проверяет только формат BlockPos (`:216-220,451-455`) |
| Начать / мгновенно закончить исследование | `colony.start_research` / `.finish_research` `{branch,research}` | 75000 / 37500 | Списки `available` / `in_progress` приходят из `capacity.targets.researches`; backend проверяет формат ID (`:221-224,456-462`) |
| Авто-режим работы | `colonist.auto_work` `{}` | 1000 | UI предлагает только farmer/lumberjack/shepherd/composter |
| Улучшить здание | `colony.upgrade_building` `{building:'x,y,z'}` | 50000 | Только если streamer online и target в `targets.upgradable`; одна незанятая цель (`viewer-shedcolony.js:448-461`) |

Все цены и список endpoint-конфигурации находятся в `routes/shedcolony.py:96-214`
и отдаются `/api/shedcolony/config` (`:580-634`). Каталоги `give_item`, `supply`,
`min_stock` совпадают с серверными allowlist и фильтруются по сборке стримера.
UI резервные цены/каталоги — только fallback при недоступности config
(`viewer-shedcolony.js:19-81,804-825`).

Локальные, не списывающие игровые действия: выбор трёх вкладок «Колонист / Экипировка /
Колония», открытие/закрытие аккордеонов, поиск событий/ксенотипов/нейротренеров,
закрытие модальных окон и выбор значений в формах. Переходы сами по себе HTTP не
вызывают; игровые GET перечислены у polling и перед действием.

## Риски устаревших слотов и снимков

- Слоты работ, кровати и цели колонии приходят снимком раз в 5 секунд; кнопка может
  быть нажата после изменения игры и до следующего опроса. При смене данных React-порт
  должен считать snapshot устаревшим и блокировать отправку до обновления. Старый UI
  уже переносит значения select между рендерами (`_selVals`, `:682-701`), поэтому
  выбор навыка/работы может сохраниться даже после нового снимка, если такое значение
  осталось в выпадающем списке.
- `capacity.stale` становится true, если heartbeat старше 60 секунд, и старый UI
  отключает все покупки (`viewer-shedcolony.js:637-657`). Это защита от вечной очереди,
  её нельзя потерять при переносе.
- Сервер надёжно подставляет `citizen_id` из JWT-зрителя для всех `colonist.*`
  (`shedcolony.py:373-378`): клиент не выбирает слот/чужого колониста. Для backlog и
  upgrade сервер проверяет синтаксис координаты, но не свежесть цели; mod должен
  разрешить координату на момент исполнения и отказать, если цель исчезла/изменилась.
  Для исследований аналогично: проверяется формат, доступность проверяет мод.
- RimWorld показывает динамические каталоги и цены. В Preact переносить надо пару
  catalog→покупка без локальной цены. Особенно сохранить `expected_price` у черт/генов:
  старые фронты шлют сумму, которую показывали, чтобы сервер отклонил устаревшую цену
  (`viewer-rimworld.js:338-347,364-373`). Сервер остаётся владельцем цены.
- В RimWorld фиксированные покупки отдельными ручками пока не несут
  `client_action_id` (общее замечание в `viewer-actions.js:5-7`). Не переносить их
  механически через Shedcolony action API: сначала сверить их текущую идемпотентность,
  cooldown и очереди в `rimworld.py`.

## Проверенные пробелы

1. **Нет новых game views:** в `frontend-next/src/panel/main.tsx:1-19` переданы только
   Bannerlord-вьюхи; `PanelApp.tsx` не содержит выбора RimWorld/Shedcolony.
2. **Нет новых game transports:** `frontend-next/src/panel/controller.ts` вызывает
   только `/api/bannerlord/*` (например `:132,146,171,194-202`), а
   `transport.ts:34-61` отправляет action на `/api/bannerlord/action`.
3. **Backend blocker: не найден.** Для зафиксированных выше действий есть старые
   действующие endpoint handlers и server-side catalog/price/validation. В новом
   клиенте требуется новый UI/controller contract; изменение backend по этому
   сравнению не обосновано. Повторная проверка backend понадобится только если
   будущий UI требует данные, которых нет в перечисленных ответах или action payloads.

## Что перенести первым

1. Добавить к Preact явный выбор активной игры/панели и lifecycle polling по
   `active_module`; не опрашивать неактивную игру.
2. Сначала перенести read models и цены: RimWorld config/catalog/pawn/events;
   Shedcolony config + colonist + capacity/targets и stale gate.
3. Завести типизированные action-контракты по таблицам и сохранить точные legacy
   payloads. Shedcolony — общий `client_action_id` и deferred-result тосты; RimWorld —
   текущие endpoint-specific тела и подтверждения для списывающих действий.
4. В новом Shedcolony view тестировать устаревшие jobs/beds/requests/building/research
   targets: отображённый target может исчезнуть между GET и POST. Не считать
   фронтенд-гейтинг заменой server/mod-проверке.
