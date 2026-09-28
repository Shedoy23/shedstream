# Frontend — аудит hardcode 0.0.6

Дата: 2026-09-28. Read-only. Реестр: [frontend.json](frontend.json).

40 групп: 12 P1, 20 P2, 6 P3, 2 INFO. Число групп не является числом багов: adapter constraints, fallback и platform_policy_ok различаются.

## Главное

Критический путь не ограничивается каталогами культур/законов. Даже если мод пришлёт новый навык или характеристику вещи, текущий frontend может их отбросить. Свита блокируется по T5/T6, progression предполагает пределы 5/10, анатомия RimWorld сведена к left/right, MineColonies возможности выводятся из имени профессии.

Новый магазин Bannerlord уже динамически получает items и категории, tiers, can_manage/can_buy и reasons. Названия категорий имеют fallback на ID. Это хороший задел: не требуется заново создавать каталог frontend. Но stats фильтруются по statNames; owned slots фиксированы. RimWorld traits/genes/xenotypes/предметы тоже не являются локальным списком вещей. Нужен аудит producer, а не ложное утверждение «все вещи hardcoded во фронте».

## Воспроизведение

`node version-0.0.6/hardcode-audit/frontend-probe.cjs` запускает выделенный из текущего исходника реальный renderer в Node vm с минимальным DOM mock. Проверяет неизвестный skill, пределы focus/attribute и потерю неизвестного stat вещи. Сохранённый probe исполнен: exit 0, четыре ожидаемых дефекта воспроизведены. Это не браузер, Twitch или живая игра. Проверки ожидают текущую проблему, поэтому exit 0 означает воспроизведённый дефект, а не исправленную систему. Результат — frontend-probe-results.json.

Предварительный ручной probe: ModMagic level 99 не появился, зато показан отсутствующий vanilla OneHanded; focus=6 и Vigor=11 бросили RangeError. Первый временный extraction прочитал неверный marker и получил ReferenceError; исправленный extraction ищет marker после начала блока. В сохранённом probe есть проверка присутствия renderer.

## Покрытие и границы

- Глубокие целевые проходы: viewer-bannerlord.js, viewer-bannerlord-builds.js, viewer-bannerlord-equipment.js, viewer-bannerlord-ui-config.js, viewer-shedcolony.js, viewer-rimworld.js, pawn.js, shop.js, xenotype.js.
- Оболочки: extension.html и mobile.html (подключения scripts, игровые разделы, фильтры, legacy modal). Дефекты JS действуют на обе.
- Shared: viewer-registry.js, viewer-actions.js и игровые места viewer.js. Registry полезен для lifecycle, но не discovery capabilities.
- config.js: настройка подключения/питомцев платформы; игровых списков культур/вещей/навыков не выявлено.
- family.js: семья платформы через /api/marriage, не семейное дерево Bannerlord. Не переносить в game truth.
- cases.js, pets.js, guilds.js, duels.js, tictactoe.js: targeted review platform ownership. Их собственные правила/каталоги не автоматически игровые дефекты.
- dice.js, tugofwar.js, voting.js, realtime.js, pet-layout/stage/assets и legal/index: обзор назначения и literal keyword scan; полный semantic аудит этих platform/visual файлов не заявлен.
- overlay.html: просмотрены Bannerlord summoned/power event sections; отдельно найдены power metadata copies. Полный визуальный аудит overlay не проводился.
- admin/admin.html: targeted read игровых API/страницы RimWorld; dashboard module selector закрыт тремя играми. Остальные admin политики вне game-content frontend задачи.
- Исторический docs/MOD_COMPAT_AUDIT.md прочитан после docs-search; устаревшие line/prod утверждения оттуда не используются как доказательства текущего дерева.

## Реестр

### FE-001 — Культуры создания героя: закрытый список шести ванильных культур

P1; game_truth; active.

Список доступных культур и описания рождаются в JS, не в каталоге активной кампании.

Последствие: Модовая культура отсутствует в выборе; удалённая ванильная остаётся предложенной.

Источник истины: BannerLink: культуры реальной кампании с can_create/reason и подходящим шаблоном героя.

Изменение: Передавать culture_id, label, description и доступность. Случайный выбор оформить отдельной игровой возможностью.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:5128-5136` — CULTURES из 6 литералов становится кнопками
- `Расширение/frontend/viewer-bannerlord.js:5168-5173` — Выбранный key уходит в hero.create

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-002 — Законы: 12 ID и ручные описания эффектов

P1; game_truth; active.

Полученные из игры активные законы не служат каталогом доступных политик; каталог и эффекты написаны вручную.

Последствие: Законы модов нельзя выбрать; изменения эффектов не отражаются, удалённые политики остаются.

Источник истины: PolicyObject и модели активной кампании; допустимые enact/repeal действия для конкретного героя.

Изменение: Передавать полный каталог с игровыми описаниями и per-action availability. Не вычислять эффекты в JS.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:2356-2381` — _BNR_POLICIES с ID, именами и числовыми эффектами
- `Расширение/frontend/viewer-bannerlord.js:2434-2467` — Список действий строится из _BNR_POLICIES, текущие enacted/pending только помечают строки

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-003 — Мастерские: ванильный закрытый список WorkshopType

P1; game_truth; active.

Города динамические, типы мастерских остаются ручными, включая engine-specific wood_WorkshopType.

Последствие: Новые производства не видны; старые переименованные типы ведут к отказам.

Источник истины: BannerLink: зарегистрированные WorkshopType, существующие/доступные производства в выбранном городе.

Изменение: Каталог типов и условия покупки передавать из игры отдельно от платформенной платы.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:1256-1268` — 11 ID _BNR_WORKSHOP_TYPES
- `Расширение/frontend/viewer-bannerlord.js:1422-1431` — Радиокнопки из локального массива
- `Расширение/frontend/viewer-bannerlord.js:1447-1450` — Города уже отдельно читаются из engine catalog

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-004 — Навыки и атрибуты Bannerlord: лишние теряются, отсутствующие выдумываются

P1; game_truth; active.

Обход серверного массива подменён обходом ванильной карты.

Последствие: Новый навык/атрибут не рисуется; удалённый появляется с 0 и кнопкой покупки. Даже label известного skill игнорируется.

Источник истины: Game state/schema: skill_id,label,attribute_id,current_value,focus,actions.

Изменение: Итерировать полученные entries и отношения. Unknown entries показывать с label/ID, а не отбрасывать.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:1093-1119` — Шесть атрибутов, 18 навыков, жёсткая карта skill→attribute
- `Расширение/frontend/viewer-bannerlord.js:1151-1159` — Lookup по реальным skills, но отсутствующий key заменяется level:0/focus:0
- `Расширение/frontend/viewer-bannerlord.js:1191-1202` — Рендер идёт по BNR_ATTRIBUTES и BNR_ATTR_TO_SKILLS

Проверка: Изолированное исполнение текущего loadBannerlordProgression в Node vm с mock DOM: payload skills=[{skill_key:'ModMagic',label:'Mod Magic',level:99,focus:1}] дал renders=true, showsModSkill=false, showsVanillaOneHanded=true. HTML реального renderer; не browser/game.

### FE-005 — Пределы focus=5 и attributes=10 способны сломать рендер

P1; game_truth; active.

Лимиты записаны в расчёте звёздочек, запрете кнопок и текстах.

Последствие: При focus=6 либо attribute=11 String.repeat получает -1 и бросает RangeError; модовый расширенный предел также блокируется UI.

Источник истины: Игра: max_focus,max_value,next_upgrade,can_upgrade,cost.

Изменение: Использовать предел и доступность из снимка; отдельно ограничить число декоративных значков безопасным UI-пределом.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:1157-1165` — repeat(5-focus), maxed>=5
- `Расширение/frontend/viewer-bannerlord.js:1191-1200` — repeat(10-val), maxed>=10
- `Расширение/frontend/viewer-bannerlord.js:5608` — loadBannerlordProgression вызывается из загрузки героя

Проверка: Изолированное исполнение текущего loadBannerlordProgression в Node vm с mock DOM: OneHanded focus=6 и Vigor=11 оба дали RangeError Invalid count value: -1. Дополнительно exact expressions repeat(5-6)/repeat(10-11) дают тот же результат. Первый harness extraction ошибся ранним marker (ReferenceError), исправлен поиском marker после начала блока. Не full browser/game и не утверждение о текущем сохранении.

### FE-006 — Свита: конец ветки выводится из T5/T6, а не из UpgradeTargets

P1; game_truth; active.

JS дублирует предположение о максимальном ванильном тире.

Последствие: Модовый T5 с дальнейшей веткой может быть объявлен maxed; низкотирный конечный юнит, наоборот, доступен для бесполезной заявки.

Источник истины: Игра: available_upgrades,can_upgrade,next_troop/cost для каждого слота.

Изменение: Вернуть из игры quote тренировки/найма и результат доступности; не выводить конец ветки по tier.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:3935-3946` — Тренировка пропускает tier>=5 basic / >=6 elite
- `Расширение/frontend/viewer-bannerlord.js:3980-3985` — basicAllMax/eliteAllMax по числу тира
- `Расширение/frontend/viewer-bannerlord.js:4012-4019` — Результат запрещает кнопки найма/тренировки
- `Расширение/frontend/viewer-bannerlord.js:4067-4073` — Обработчики тоже возвращаются при локальном disabled

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-007 — Свита: расчёт цены и доступности покупки в JS

P2; duplicated_platform_policy; active.

Даже после загрузки серверных цен алгоритм quote остаётся во фронте; fallback таблица и 3× тоже живут здесь.

Последствие: Разные правила upgrade/частичных тренировок/модовых веток дают неверный запрет либо неверную ожидаемую сумму.

Источник истины: Game action quote для Hero.Gold; платформенные надбавки из backend.

Изменение: Отдавать стоимость применимого набора операций и can_afford. Цены платформы не объявлять игровым фактом.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:3923-3933` — Таблица стоимости + elite multiplier и min tier
- `Расширение/frontend/viewer-bannerlord.js:3940-3945` — Сумма тренировок вычисляется локально
- `Расширение/frontend/viewer-bannerlord.js:3987-3991` — Расчёт используется для нехватки золота
- `Расширение/frontend/viewer-bannerlord.js:861-864` — Ценовая таблица гидрируется с backend

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-008 — Кузница: фиксированная лестница качества

P1; game_truth; active.

Игра может иметь другую группу модификаторов, но frontend назначает следующий результат самостоятельно.

Последствие: Модовое качество не отображается или ему обещается неверная ступень; legendary всегда блокируется.

Источник истины: BannerLink: текущий ItemModifier label и конкретный следующий допустимый modifier/эффекты, can_reforge/reason.

Изменение: Показать игровой preview результата. Не рассчитывать next quality по фиксированной строке.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:3836-3856` — Качества и переход fine→masterwork→legendary; unknown→fine
- `Расширение/frontend/viewer-bannerlord.js:4385-4394` — nextQ определяет кнопку и обещание
- `Расширение/frontend/viewer-bannerlord.js:5541-5547` — Кузница видна независимо от legacy-equipment

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-009 — Слоты экипировки и кузницы зашиты двумя разными списками

P2; adapter_constraint; active.

Новый item catalog не означает динамическую схему слотов; кузница и инвентарь имеют разные списки.

Последствие: Новый слот нельзя выбрать в owned UI. Сбруя не представлена в кузнице даже если game handler поддержит её.

Источник истины: Игра/адаптер: schema equipment slots и per-slot actions.

Изменение: Отдельный список слотов из game contract; наличие операции reforge определять по item actions. Native набор слотов допустим как версия адаптера, не как универсальная платформа.

Доказательства:

- `Расширение/frontend/viewer-bannerlord-equipment.js:3-4` — 11 slotNames для нового инвентаря
- `Расширение/frontend/viewer-bannerlord-equipment.js:170` — Owned UI итерирует Object.keys(slotNames)
- `Расширение/frontend/viewer-bannerlord.js:4362-4373` — В кузнице 10 слотов; horseharness отсутствует

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-010 — Новый магазин вещей отбрасывает неизвестные характеристики

P1; game_truth; active.

Предметы динамические, но данные о них ограничены набором JS-метрик.

Последствие: Модовый damage/resistance/effect не отображается, даже если backend его передал; нули/отрицательные бонусы исчезают.

Источник истины: Игра: stats entries с label,value,unit,format,comparison_direction; descriptions для нечисловых свойств.

Изменение: Рендерить безопасные типизированные неизвестные поля, подробности не обрезать молча. Краткую карточку и полный просмотр разделить.

Доказательства:

- `Расширение/frontend/viewer-bannerlord-equipment.js:9-12` — Whitelist statNames
- `Расширение/frontend/viewer-bannerlord-equipment.js:39-54` — stats и numericStats отфильтровывают ключи без statNames
- `Расширение/frontend/viewer-bannerlord-equipment.js:57-66` — Сравнение тоже только для известных ключей, >0, первые 8

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-011 — Сравнение экипировки всегда считает больше лучше, кроме веса

P2; game_truth; active.

Смысл улучшения определяется именем weight; других правил метрики нет.

Последствие: Модовая стоимость/штраф/время может получить неверную зелёную оценку; отсутствие baseline считается нулём.

Источник истины: Schema каждой игровой метрики: higher/lower/neutral, comparable и единицы.

Изменение: Сравнивать только сопоставимые значения, направление брать из metadata; без него показывать нейтральную дельту.

Доказательства:

- `Расширение/frontend/viewer-bannerlord-equipment.js:57-66` — usefulDelta = key === weight ? -delta : delta

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-012 — Legacy equipment renderer: фиксированная типизация и набор статов

P3; adapter_constraint; fallback.

Запасной рендер использует старую схему и эвристику щита.

Последствие: При деградации API новые характеристики/типы исчезают, тип вещи может быть угадан неверно.

Источник истины: Item category/subtype и stats schema из адаптера.

Изменение: Либо общий data-driven renderer, либо явно versioned совместимый fallback без выдуманных сведений.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:3872-3904` — Списки weapon/armor/horse и специальные наборы stat
- `Расширение/frontend/viewer-bannerlord.js:917-920` — Щит угадывается по наличию hp+body
- `Расширение/frontend/viewer-bannerlord.js:5529-5532` — Legacy блок скрывается при equipment_shop_ready
- `Расширение/frontend/viewer-bannerlord-equipment.js:278-282` — При ошибке нового магазина legacy снова показывается

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-013 — Новая система build: пороги 50/150 и смысл сил остались в JS

P2; game_truth; active.

Список возможностей приходит из игры, но числовая интерпретация value и следующий порог выводятся локально.

Последствие: Ребаланс силы или новая формула оставит неверную подпись и следующий unlock.

Источник истины: Build snapshot: effect descriptors и next_threshold/next_rank.

Изменение: Использовать уже переданные description и добавить structured effects; убрать дублирование формул.

Доказательства:

- `Расширение/frontend/viewer-bannerlord-builds.js:13-24` — strength switch: rage, cleave, shield_break etc
- `Расширение/frontend/viewer-bannerlord-builds.js:83-92` — Отображение rank/skill и следующий порог 50/150

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-014 — Приказы героя: возможность выводится из класса/оружия

P2; game_truth; active.

Ни legacy, ни новый build не передают прямую доступность detach_raid/detach_skirmish.

Последствие: Новый дальнобойный тип либо отдельное правило игры не откроет приказ; наличие power availability не равно availability приказа.

Источник истины: Игра: available_actions для конкретного героя/отряда и причины.

Изменение: Не выводить возможность одной операции из возможности другой; game-side предикаты сохранить authoritative.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:3230-3237` — Списки cavalry/ranged классов и BnrBuilds.detachment
- `Расширение/frontend/viewer-bannerlord-builds.js:145-149` — ranged означает weapon_type bow/crossbow + available
- `Расширение/frontend/viewer-bannerlord.js:3238-3250` — По этому результату кнопка существует или отсутствует

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-015 — Карта приказов отряда и фильтрация целей по vanilla типам

P2; game_truth; active.

Цели из игры, но допустимость цели для приказа пересчитывает JS.

Последствие: Модовые отношения/типы поселений могут дать неверный список; новый поддержанный адаптером приказ не появится.

Источник истины: Game-side action descriptors + eligible targets.

Изменение: Передавать targets по action_id; поддерживать известные безопасные input types для generic picker.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:2206-2213` — 6 локальных вариантов приказов
- `Расширение/frontend/viewer-bannerlord.js:2218-2228` — Siege excludes village, raid only village, defend/patrol only own

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-016 — Стойки боя являются контрактом собственного мода, но не discoverable

P3; adapter_constraint; active.

Собственная механика BannerLink описана в UI фиксированными вариантами.

Последствие: Добавление/отключение стойки требует frontend release, хотя это не vanilla content ID.

Источник истины: BannerLink: supported stance options и описание эффектов.

Изменение: Оставить стабильные action IDs; список вариантов/availability получать из capability. Не считать сам факт авторских stance ID ошибкой.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:3325-3346` — defensive/balanced/aggressive и hero.set_combat_stance

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-017 — Династия: общий запрет по clan leader вместо возможностей механик

P2; game_truth; active.

Фронтенд группирует разные game rules в один gate и трактует наличие любого clan party как запрет создать отряд.

Последствие: Изменения правил кампании/модов не отражаются; интерфейс может запретить доступное действие.

Источник истины: Игра: capability/action availability отдельно для workshops,party,fiefs,kingdom,etc.

Изменение: Навигацию показывать по capability; actions disable по серверной/game причине, а не единому is_leader.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:5459-5477` — Вкладка династии закрывается для !isClanLeader
- `Расширение/frontend/viewer-bannerlord.js:5480-5499` — Сразу несколько разных механик живут за одним gate
- `Расширение/frontend/viewer-bannerlord.js:4748-4757` — Создать отряд лишь если у клана вообще нет parties

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-018 — Дети и вассалы: лимиты по 5 дублируются во фронте

P2; duplicated_platform_policy; active.

Лимиты авторской механики зашиты независимо от backend/mod; другие условия семьи также вручную соединяются.

Последствие: После изменения server/game policy UI продолжает ограничивать или ошибочно разрешать заявку.

Источник истины: Authoritative policy ownership (backend либо мод) + resolved availability от игры.

Изменение: Передать max_count/current_count/actions, отделить лимит продукта от native условий возраста/брака.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:1880-1896` — Вассалы <5/max 5
- `Расширение/frontend/viewer-bannerlord.js:4599-4609` — canMakeBaby aliveChildren<5, цена отдельно гидрируется

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-019 — Тексты старых сил и OBS имеют свои копии

P2; duplicated_platform_policy; fallback.

Legacy силы используют локальные смысловые описания; OBS имеет отдельные labels.

Последствие: Ребаланс BannerLink не обновляет эти утверждения. Сам OBS активен независимо от legacy build. Более существенно: legacy current_powers с неизвестным key отбрасывается. HUD/OBS имеют fallback raw key и не исчезают.

Источник истины: Power metadata из адаптера/серверного каталога, duration/value из события.

Изменение: Отдать label/description/effects в payload и применять общий безопасный renderer; style/icon fallback допустим.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:152-175` — BNR_POWER_LABELS с +50HP/45с и описаниями
- `Расширение/frontend/viewer-bannerlord.js:3603-3607` — Новый build renderer обходит legacy active powers
- `Расширение/frontend/overlay.html:1273-1289` — Отдельная BNR_POWER_META, комментарий о второй копии
- `Расширение/frontend/viewer-bannerlord.js:3635-3637` — Неизвестный power_key вообще отбрасывается legacy renderer

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-020 — Цены и пресеты: fallback является второй истиной

P2; duplicated_platform_policy; fallback.

При ошибке/задержке config отображаются цены, лимиты и конверсии вшитой версии.

Последствие: Зритель может увидеть цену старого ZIP; это не доказательство неверного списания backend.

Источник истины: Backend economy policy с version/quote, без обязательного получения цены из игры.

Изменение: До подтверждённого quote показывать unknown/disabled; last-known показывать как устаревшее. Платформенная цена вправе оставаться backend-owned.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:851-873` — Гидратация конфига и catch сохраняющий defaults
- `Расширение/frontend/viewer-bannerlord.js:890-901` — Price/gold helpers возвращают fallback
- `Расширение/frontend/viewer-bannerlord.js:4089-4097` — Пресеты gold/XP
- `Расширение/frontend/viewer-rimworld.js:18-37` — Отдельные prices defaults/config

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-021 — Дипломатия: локальные 300 секунд вместо server cooldown

P2; duplicated_platform_policy; active.

Даже при общей системе cooldown дипломатия хранит отдельное числовое правило.

Последствие: Ребаланс кулдауна/другая сессия дают неверную доступность кнопок.

Источник истины: Backend cooldown remaining/expires_at для action_id.

Изменение: Использовать общий cooldown contract; клиентская защита double click остаётся локальной.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:2383` — _bnrDiploCd local timestamps
- `Расширение/frontend/viewer-bannerlord.js:2528-2531` — _DIPLO_CD=300
- `Расширение/frontend/viewer-bannerlord.js:2538-2547` — Disabled кнопки войны/мира по local remainder

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-022 — RimWorld: hediff классифицируется по имени и severity

P1; game_truth; active.

UI угадывает медицинскую семантику из локализованного текста и величины severity.

Последствие: Модовая болезнь с малой severity попадёт в импланты; иной язык/название ломает группировку, severity не всегда процент.

Источник истины: RimLink: kind,is_implant,is_injury,severity display/range,description из HediffDef/класса.

Изменение: Передавать тип/метрики явно. При unknown показывать нейтральный hediff, не объявлять имплантом.

Доказательства:

- `Расширение/frontend/pawn.js:359-366` — Имплант = подстроки имплант/протез/биони/архо/нано/synth или severity<=0.01
- `Расширение/frontend/pawn.js:410-415` — Тип раны по русским подстрокам, severity приводится к 0..1

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-023 — RimWorld: имплантация ограничена человеческой парой left/right

P1; adapter_constraint; active.

Ни body-part instance IDs, ни число доступных конечностей из игры не участвуют в выборе.

Последствие: Модовая анатомия с дополнительными руками/глазами либо неоднозначными парными частями не имеет точного выбора.

Источник истины: Игра: список допустимых BodyPartRecord targets со стабильными session IDs,label,occupied/replacement.

Изменение: Заменить boolean paired на конкретные targets; окончательная совместимость импланта проверяется игрой.

Доказательства:

- `Расширение/frontend/shop.js:248-273` — is_paired ведёт к occupiedLeft/Right
- `Расширение/frontend/shop.js:286-307` — Ровно две кнопки и part_hint left/right
- `Расширение/frontend/pawn.js:304-352` — Локальный словарь человеческих частей тела с text fallback

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-024 — RimWorld: шкала навыка 20 и passion 0→1→2

P2; game_truth; active.

Игра передаёт навыки и цены, но максимумы/переходы остаются ванильными.

Последствие: Сборка с extended skills/passions отображается неполно или блокируется клиентом.

Источник истины: RimLink: skill max/display range и возможные passion transitions.

Изменение: Разделить visual progress и game limit; получить next action из игры, не вычислять passion+1.

Доказательства:

- `Расширение/frontend/pawn.js:132-146` — Passion icon только 1/2, уровень делится на 20
- `Расширение/frontend/xenotype.js:269-281` — Следующий passion считается +1, после 2 кнопки нет

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-025 — RimWorld: локальная локализация переопределяет game labels

P3; game_truth; active.

Для известных defName клиент предпочитает ручное имя игровому label.

Последствие: Мод заменяющий смысл/название vanilla skill не отражается; неизвестный skill при этом не теряется (есть fallback).

Источник истины: Game label как основной источник; curated localization только если label отсутствует.

Изменение: Поменять приоритет источников и сохранять fallback, не удалять поддержку неизвестного.

Доказательства:

- `Расширение/frontend/viewer-rimworld.js:418-436` — SKILL_LABELS_RU[def] прежде skill.label
- `Расширение/frontend/pawn.js:136-137` — Карточка вызывает localizeSkill

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-026 — RimWorld: здоровье определяется эвристикой масштаба

P2; adapter_constraint; active.

Контракт единиц заменён угадыванием по значению.

Последствие: Значение 1 двусмысленно (1% или 100%); fractional значение >1 от модового масштаба ошибочно прочтётся как проценты.

Источник истины: Версионированное health current/max либо explicit normalized_percent из адаптера.

Изменение: Одна documented единица; legacy conversion отделить по schema_version.

Доказательства:

- `Расширение/frontend/pawn.js:80-83` — health>1 значит процент, иначе fraction*100
- `Расширение/frontend/pawn.js:105-110` — Полученное значение прямо становится процентом и шириной

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-027 — RimWorld: события используют локальный 5-минутный cooldown

P2; duplicated_platform_policy; active.

События из server catalog, но время блокировки вычисляется по константе клиента.

Последствие: Ребаланс серверных правил остаётся невидим CDN-клиенту; новый сеанс теряет local clock.

Источник истины: Backend event-specific cooldown contract.

Изменение: Применять remaining/expires_at из API, как уже делается для heal cooldown.

Доказательства:

- `Расширение/frontend/viewer-rimworld.js:202-216` — Disabled по EVENT_COOLDOWN_MS и _cmdCooldowns
- `Расширение/frontend/viewer-rimworld.js:230-246` — Константа 5*60*1000 и local cooldown helpers

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-028 — RimWorld: категории UI и маршрутизация покупки закрыты

P2; adapter_constraint; active.

Новый item внутри известного типа отображается, но новая операция/категория не discoverable.

Последствие: Новая категория видна только в All либо отправлена по общему buy-item без специфичного выбора; это ограничение контракта, не запрет всех модовых вещей.

Источник истины: Catalog category metadata + action descriptor/parameter schema.

Изменение: Строить фильтры из фактического каталога; использовать ограниченный registry renderer/actions по типам, unknown action не выполнять вслепую.

Доказательства:

- `Расширение/frontend/extension.html:343-350` — Ручные filter buttons apparel/weapon/implant/trait/gene
- `Расширение/frontend/shop.js:118-140` — Типовые подписи с fallback на raw type
- `Расширение/frontend/shop.js:228-237` — Покупка routed по item.type
- `Расширение/frontend/shop.js:33-34` — neurotrainer/xenotype исключены в отдельные UI

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-029 — ShedColony: список 11 навыков отбрасывает новые

P1; game_truth; active.

Полученный sk используется только lookup для известных ключей.

Последствие: Новый навык исчезает и из просмотра, и из прокачки.

Источник истины: Мод Minecraft: skills entries labels,current и доступность прокачки.

Изменение: Итерировать реальное состояние/каталог, использовать ID без локального whitelist.

Доказательства:

- `Расширение/frontend/viewer-shedcolony.js:155-161` — SC_SKILLS список
- `Расширение/frontend/viewer-shedcolony.js:433-435` — XP select из списка
- `Расширение/frontend/viewer-shedcolony.js:501-509` — State skills обходятся через SC_SKILLS

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-030 — ShedColony: guard/auto-work решается whitelist профессий

P1; game_truth; active.

Назначения идут из capacity, а набор возможностей определяется именем job.

Последствие: Новая гвардейская профессия либо модовая автоматизация не получает кнопок.

Источник истины: Мод: job capabilities и action availability.

Изменение: Передавать can_equip_weapon/can_guard_task/can_auto_work и описание текущего automation.

Доказательства:

- `Расширение/frontend/viewer-shedcolony.js:65-69` — 4 job keys auto-work
- `Расширение/frontend/viewer-shedcolony.js:402-406` — guard whitelist knight/ranger/archer/druid
- `Расширение/frontend/viewer-shedcolony.js:539-558` — Все guard controls скрыты для других jobs

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-031 — ShedColony: сытость=60 и health fallback=20

P2; game_truth; active.

Максимум сытости не является данными; неизвестный HP max считается 20.

Последствие: При модовом пределе 100 feed отключится в 60; при отсутствующем max_hp неверный gate.

Источник истины: Мод: needs current/max и can_feed/can_heal.

Изменение: Не подменять отсутствие authoritative maxima ванильной истиной, показывать unknown.

Доказательства:

- `Расширение/frontend/viewer-shedcolony.js:380-384` — HP max fallback20, saturation bar max60
- `Расширение/frontend/viewer-shedcolony.js:420-426` — Feed запрещён при saturation>=60, heal по fallback20

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-032 — ShedColony: каталоги Minecraft предметов имеют активный fallback

P2; game_truth; fallback.

Основной список берётся с backend, но при недоступном config используется копия vanilla.

Последствие: Клиент может предложить отсутствующий предмет. Успешная hydration не доказывает полноту game registry: это задача producer.

Источник истины: Мод: реальные registered items + permissions политики продукта; backend выдаёт validated catalog.

Изменение: Fail closed для покупаемых unknown catalog entries либо last-known с version/freshness. Не утверждать, что штатный путь всегда hardcoded в JS.

Доказательства:

- `Расширение/frontend/viewer-shedcolony.js:73-79` — min stock vanilla IDs
- `Расширение/frontend/viewer-shedcolony.js:100-116` — supply/give_item vanilla IDs
- `Расширение/frontend/viewer-shedcolony.js:814-821` — Успех config заменяет, catch сохраняет
- `Расширение/frontend/viewer-shedcolony.js:824-828` — refresh начинается также до hydrate завершения

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-033 — ShedColony: фиксированные комплекты брони вместо каталога вещей

P2; adapter_constraint; active.

UI оперирует авторскими fixed-kit actions, а не предметами реального мира.

Последствие: Модовые материалы/оружие нельзя выбрать без новой интеграционной механики; название/состав обещаний дублирует мод.

Источник истины: Game capabilities: kits catalog или item catalog с применимостью на colonist.

Изменение: Сохранить kits как допустимый продукт, но их список/состав передавать из мода. Для цели любые вещи потребуется отдельная capability.

Доказательства:

- `Расширение/frontend/viewer-shedcolony.js:38-55` — equip_leather/iron/diamond/netherite action IDs
- `Расширение/frontend/viewer-shedcolony.js:520-533` — 4 кнопки брони и фиксированное описание tool kit
- `Расширение/frontend/viewer-shedcolony.js:542-546` — Обещание лучший меч+лук

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-034 — ShedColony: локальные названия профессий/зданий теряют namespace

P3; game_truth; active.

Игра задаёт IDs, но подпись lookup по common registry path.

Последствие: Модовый namespace:builder может стать обычным Строителем; новые названия остаются ID.

Источник истины: Game display_name для каждой сущности с namespace-preserving ID.

Изменение: Использовать label от игры, локальные словари лишь как fallback для старого payload.

Доказательства:

- `Расширение/frontend/viewer-shedcolony.js:83-98` — SC_BUILDING_LABELS
- `Расширение/frontend/viewer-shedcolony.js:163-179` — SC_JOB_LABELS
- `Расширение/frontend/viewer-shedcolony.js:195-207` — Сначала отделяется base после двоеточия
- `Расширение/frontend/viewer-shedcolony.js:637-638` — Upgrade picker использует _buildingLabel(type)

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-035 — Все три UI знают список собственных действий; discovery ещё нет

P2; adapter_constraint; active.

Registry устраняет if по игре при переключении, но не описывает capabilities/state/actions.

Последствие: Четвёртая игра или новая механика требует нового JS/HTML; game manifest сам не создаёт UI.

Источник истины: Capability manifest с безопасными component types и action descriptors, adapter extension registry.

Изменение: Generic by default поверх текущего registry. Это архитектурный предел, не требование присылать executable UI с сервера.

Доказательства:

- `Расширение/frontend/viewer-registry.js:39-50` — Регистрация игры только root/title/start/stop
- `Расширение/frontend/extension.html:224-307` — Отдельные оболочки Bannerlord/RimWorld/ShedColony
- `Расширение/frontend/viewer-shedcolony.js:25-63` — SC table известных действий
- `Расширение/frontend/viewer-bannerlord-ui-config.js:4-9` — Лишь четыре существующих UI sections

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-036 — Платформенные мини-игры/питомцы/гильдии не обязаны читать игру

INFO; platform_policy_ok; active.

Эти литералы относятся к продукту ShedLink, не к состоянию Bannerlord/RimWorld.

Последствие: Их перенос в game catalog был бы ошибкой ownership; проверять только дрейф platform policy между backend/frontend.

Источник истины: Backend ShedLink для баланса/каталога; локальный renderer для визуальных правил.

Изменение: Не включать в очередь game-truth migration лишь по наличию констант.

Доказательства:

- `Расширение/frontend/guilds.js:36-41` — Guild skills config от платформы
- `Расширение/frontend/pets.js:238-242` — Питомцы платформенного каталога
- `Расширение/frontend/tictactoe.js:16-21` — Собственная игра 4×4
- `Расширение/frontend/duels.js:246-247` — Собственные RPS варианты

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-037 — Мёртвый create-colonist modal и неиспользуемый BNR_SKILLS не считать активным каталогом

INFO; legacy_inactive; inactive.

Литералы существуют, но отдельно от реальных активных controls.

Последствие: Завышение аудита: активный дефект навыков находится в BNR_ATTR_TO_SKILLS, не в самой BNR_SKILLS.

Источник истины: Удаление/документация legacy при будущей чистке.

Изменение: Не выдавать эти строки за активную покупку. Реальную прогрессию рассматривать в FE-004/005.

Доказательства:

- `Расширение/frontend/extension.html:590-598` — Legacy modal с комментарием о мёртвом входе
- `Расширение/frontend/viewer-bannerlord.js:1088-1092` — BNR_SKILLS declaration без runtime consumer в текущем frontend
- `Расширение/frontend/viewer.js:113-115` — create-colonist-btn лишь вызывает closeModal

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-038 — Стримерский выбор модулей фиксирован тремя кнопками

P3; adapter_constraint; active.

Даже когда модуль зарегистрирован в backend, панель управления не discoverable.

Последствие: Для четвёртой игры нужно менять dashboard.

Источник истины: Backend module registry с installed/available/enabled metadata.

Изменение: Строить список модулей из registry, безопасно рендерить label/id; это не список игровых предметов.

Доказательства:

- `Расширение/backend/templates/streamer_dashboard.html:274-283` — Кнопки bannerlord/rimworld/shedcolony и массив для переключения

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-039 — ShedColony: параметры действий и enum guard task статичны

P3; adapter_constraint; active.

Форма параметров повторяет контракт реализации, но не является schema-driven.

Последствие: Новый допустимый режим не появляется; отсутствие skill selection silently выбирает Strength.

Источник истины: Action input schemas enum/options/min/max/default, выданные адаптером.

Изменение: Постепенно перевести существующие controls на typed action schema; UI defaults должны быть явными.

Доказательства:

- `Расширение/frontend/viewer-shedcolony.js:80-81` — MIN_STOCK_QTYS 1,2,4,8,16
- `Расширение/frontend/viewer-shedcolony.js:548-556` — Guard task guard/patrol и retreat on/off
- `Расширение/frontend/viewer-shedcolony.js:707-718` — Ручная сборка payload per kind; XP fallback Strength

Проверка: Статический анализ текущей копии: декларация и вызывающий путь прочитаны; в игре и браузере не проверено.

### FE-040 — Bannerlord: новые причины отказа теряются в локальном словаре

P2; duplicated_platform_policy; active.

Игровая причина отказа кодируется набором известных клиенту строк; неизвестная теряет подробность.

Последствие: Мод/новый backend передаст новую причину, старый Twitch ZIP покажет Действие не удалось вместо конкретного объяснения.

Источник истины: Game result.reason_code + безопасный human-readable message из backend localization/game metadata.

Изменение: Предпочитать серверный message с escape, локальный словарь оставить fallback. Причина не должна определять право выполнения на клиенте.

Доказательства:

- `Расширение/frontend/viewer-bannerlord.js:49-95` — BNR_REFUSE_REASON_RU, unknown→Действие не удалось
- `Расширение/frontend/viewer-bannerlord.js:100-105` — recent_refunds.reason преобразуется только через локальный словарь
- `Расширение/frontend/viewer-bannerlord.js:5039` — Вызов notification из /my-hero

Проверка: Статический путь /my-hero→_bnrNotifyRefunds→_bnrRefuseReasonRu подтверждён; live refusal не выполнялся.

## Ограничения

- Read-only анализ копии 0.0.6; активность означает достижимый путь текущего source, не подтверждение production/игрового сеанса.
- CodeGraph недоступен (parent сообщил database locked). Использован targeted rg/read; структурное полное покрытие не заявляется.
- Просмотрены игровые JS, обе HTML оболочки, shared registry/actions, OBS игровые ветки, relevant admin/dashboard sections. Platform-only файлы проверены преимущественно targeted keyword pass; pet-assets/render assets не подвергались полному semantic review.
- Producer/backend/mod implementation в этом подотчёте не аудировались полностью. desired_source указывает владельца истины, а не гарантирует наличие соответствующего API уже сейчас.
- Runtime доказательства ограничены изолированным progression renderer в Node vm и expression checks. Browser, Twitch CDN, production, game DLL, live game не затрагивались.
- Каждая finding — семейство мест, а не подсчёт всех literals. INFO/adapter constraints/fallback не являются подтверждёнными дефектами текущей vanilla игры.
- Новый магазин Bannerlord уже получает items/tiers/categories и availability с сервера; RimWorld catalog/traits/genes/xenotypes тоже dynamic. Дефекты полноты upstream каталога требуется оценивать в моде и backend.
- Исторический docs/MOD_COMPAT_AUDIT.md найден через docs-search и прочитан для контекста, но его старые выводы о production не использованы как текущие факты.


## Дополнение воспроизведения FE-010

Текущие stats()/numericStats() извлечены из viewer-bannerlord-equipment.js: swing_dmg=25 отображён, mod_magic_damage=50 отброшен и из текста, и из comparison data. frontend-probe.cjs завершился exit 0; четыре assertions подтверждают текущие дефекты, а не исправление.

## Перекрёстная проверка кузницы и отказов

FE-008: кнопка viewer-bannerlord.js:4417 отправляет hero.reforge_quality. routes/bannerlord.py:974–980 явно отличает его от retired hero.smith_item/equip_trophy; ActionRegistry.cs:71 регистрирует ReforgeQualityHandler. Активную перековку нельзя смешивать с удалённой продажей кузнечных трофеев.

FE-040: recent_refunds payload (routes/bannerlord.py:1537–1541) не содержит отдельного human message; текущий toast берёт reason в локальный словарь и теряет неизвестную причину. Общая система notices/API может независимо объяснить отказ; вывод не распространяется на все каналы уведомлений.
