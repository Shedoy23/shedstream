# Источники, история и границы лицензий

Исследование 28.09.2026. Это записи о проверенных исходниках; DLL сторонних проектов не запускались и не устанавливались. В ShedLink не переносились классы, алгоритмические реализации, configs или assets BLT. Внешние checkout находятся в `D:/shedlink-build/`, вне дерева продукта.

## Зафиксированные версии

| Источник | Ревизия | Что исследуется |
|---|---|---|
| ShedLink, `claude/poststream-2026-09-22` | `0cdf6338db7bd1b5f5d9ab7e43b2b8b8efb31e30` | Рабочее дерево `bannerlord-crash-analysis-a34de4`; исходные изменения документации и Generated.cs harness сохранены. Runtime baseline снят отдельно |
| billw2012/Bannerlord-Twitch | `f989f5602f648c9c24f1d95a9364fa7a11676e31` | Исходный BLT/AdoptAHero/BLTBuffet, история 624 достижимых коммитов |
| Randomchair22/Bannerlord-Twitch | `83b264f85774489c84c5682c73df3ef92915f39e` | Современная ветка, 1386 достижимых коммитов; main содержит изменения новее некоторых тегов |
| MesmerTurn/BLT-5.4.x-Warsails-Reforged | `dee0d1735f44b336a77986025ec1f863ea05e26f` | Текущий master, 36 коммитов; не идентичен тегу 5.4.6 |
| MesmerTurn, `v5.4.6-1.3.15` | `713b99ad2a0f11acfa35c09a7d50fe5cc7d85e74` | Контроль исторической версии; анализ изменений относительно master, без подмены общего checkout |
| MesmerTurn/MakeBltGreatAgain | `5197130e8a1755b452755194b50e65e75998cf98` | Отдельный extension; исторический duplicate в полном форке не входил в explicit Compile list и затем удалён |
| TOR Realm Guide | HTML SHA256 `55048f0e1e252dfdd3021a3c7ab87b1052a859da447c99cde9047da4d7ec1f24` | Скачан напрямую по URL после ошибки web reader. Публичный guide не привязан к commit развёрнутого кода |

Число коммитов означает доступную историю, **не** построчное прочтение всех изменений. Читались тематические истории и выбранные добавления/удаления. Списки файлов и тематические журналы лежат рядом. В `repositories.json` записаны пути, remote и refs.

## Лицензии: проверенные заявления и разрешённые способы использования

| Репозиторий / модуль | Наблюдаемое основание | Категория для этого исследования |
|---|---|---|
| billw BLT core / AdoptAHero / Buffet / Configure | Корневой [LICENSE](https://github.com/billw2012/Bannerlord-Twitch/blob/f989f5602f648c9c24f1d95a9364fa7a11676e31/LICENSE) — LGPL-2.1 | **REFERENCE IMPLEMENTATION**; **CODE REUSE POSSIBLE** лишь с исполнением применимых условий, не как безусловное разрешение вставить класс в ShedLink |
| Randomchair22, те же модули и добавления в репозитории | Корневой [LICENSE](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/LICENSE) — LGPL-2.1 | **REFERENCE IMPLEMENTATION**; потенциальное прямое использование требует сохранения notices и соблюдения лицензии производного/связанного результата |
| Mesmer full fork, BLT-derived modules | [README:74–76](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/README.md#L74-L76) отсылает к исходной лицензии billw; отдельного LICENSE в проверенном дереве нет | **REFERENCE IMPLEMENTATION**; не объявлять весь форк MIT. Для reuse отдельных добавлений надо установить происхождение файла и сохранить upstream обязанности |
| Standalone MakeBltGreatAgain | [README:100–102](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/5197130e8a1755b452755194b50e65e75998cf98/README.md#L100-L102) заявляет MIT, полного LICENSE/notice для модуля в дереве не найдено | **REFERENCE IMPLEMENTATION**, **CODE REUSE POSSIBLE** потенциально после восстановления полного MIT notice и проверки происхождения конкретного фрагмента. README не снимает лицензию заимствованного BLT-кода |
| TOR guide, modpack configs, class/item content, Warhammer assets | Публичная страница; лицензия на перенос текста/config/assets не установлена | **IDEA ONLY**. Не копировать контент/таблицы баланса/графику. Не считать лицензию кода BLT лицензией на TOR assets |
| BUTR SaveSystem | [ButterLibLicense.txt](https://github.com/billw2012/Bannerlord-Twitch/blob/f989f5602f648c9c24f1d95a9364fa7a11676e31/BannerlordTwitch/BannerlordTwitch/SaveSystem/ButterLibLicense.txt) содержит MIT notice Copyright 2020 BUTR Team | Отдельное происхождение SaveSystem, не MIT для всего BLT |
| JetBrains annotations / третьи библиотеки | В отдельных исходниках есть собственные license headers | Отдельная provenance; не расширять их MIT header на игровой модуль целиком |

Идея механики, поведение и используемый публичный API описываются собственными словами. Копирование реализации, даже с переименованием переменных, не становится независимой реализацией. Собственное повторение поведения через архитектуру ShedLink здесь предпочтительно и соответствует правилам репозитория.

LGPL допускает использование при условиях; это не «запрет на чтение» и не MIT. Для распространения модифицированной библиотеки и связанных результатов имеют значение исходники соответствующих изменений, notices и предусмотренная лицензией возможность модификации/перелинковки. Конкретный вариант распространения нужно оценивать отдельно. Основание: [официальный текст LGPL 2.1, §§2,4,6](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.en.html). В исследовании прямого reuse нет.

## История, которую нельзя выдать за текущую функцию

1. **Mesmer class upgrade tree.** Коммит `d6f0626` добавлял `ClassProgressionTree`, nodes с required kills и допустимыми следующими классами, `UpgradeClass` action. Прочитан файл из родителя отката. [693e0bd](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/commit/693e0bdf4b5813b6019c2d2b12ca24ec04b05d4f) удалил 334 строки/7 файлов. Это исторический пример prerequisite tree, не готовая текущая специализация, которую ShedLink «отстаёт» реализовать.
2. **MBGA composable power rewrite.** [cbf8553](https://github.com/MesmerTurn/MakeBltGreatAgain/commit/cbf8553) добавлял composable DoT/Aura/Self-Buff. Текущий [5197130](https://github.com/MesmerTurn/MakeBltGreatAgain/commit/5197130e8a1755b452755194b50e65e75998cf98) — его revert. Наличие старого README/commit не доказывает текущую доступность. При этом отдельные группы powers существуют в базовом BLT независимо от этого отката.
3. **Wanderer self-progression.** Исторический MBGA `352bb4c` содержит реальную реализацию, не только design document; subsequent [df04587](https://github.com/MesmerTurn/MakeBltGreatAgain/commit/df04587) урезал standalone extension. Полный Mesmer fork и standalone надо рассматривать отдельно; подробнее в сравнении world.
4. **Полный source tree Mesmer.** [698eac7](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/commit/698eac7b353731c551b04fe36d07c914afd27a52) добавляет ранее не отслеживаемую полную исходную структуру. До него отсутствие файла в истории не означает отсутствие механики в распространявшемся бинарнике.
5. **Phoenix Rebirth / Auto Pickup.** README MBGA сообщает об удалении ненадёжных powers. Текущий поиск и история доступного source не устанавливают полноценную старую рабочую реализацию Phoenix. Поэтому это свидетельство документации об исключении, не рекомендация переносить resurrection.

## TOR: полезные гипотезы, а не доказательство публичного кода

[Guide](https://generaleddy.neocities.org/TOR-Realm-Guide) показывает связку личного героя, карьеры спутников, персональных вещей и владений. Ценны earned-only вершины развития спутников, защита их профильного оружия от случайной замены, выбор строя охраны, а также информирование о следующем milestone. Это направления сравнения поведения; конкретные thresholds и race locks — настройки модпака.

Его gear prestige 7–9 нельзя смешивать с публичным Mesmer reset-prestige. Описанные ingredient enchanting и companion tier9 не подтверждены как тот же implementation в исследованных refs. В публичном `EnchantItem.cs:46–95` виден случайный modifier экипированного предмета за gold, что не равно системе ингредиентов из guide. Всё, что не связано с BLT-интеракциями, включая устройство магии TOR, исключено из аудита.

## Проверка Bannerlord API

Использована доступная локальная декомпиляция `D:/shedlink-build/bl-decomp/TaleWorlds.CampaignSystem.decompiled.cs`. У неё generic AssemblyVersion 1.0.0.0; она не доказывает совместимость любой версии Bannerlord.

Подтверждены public сигнатуры `BuildingHelper.ChangeCurrentBuildingQueue` (5737), `Hero.SetBirthDay` (35052), `MobileParty.SetPartyScout/Quartermaster/Engineer/Surgeon` (101850–101877), `HeroDeveloper.AddSkillXp` (156231). Это проверка конкретных API, не полный аудит транзитивных эффектов, native safety или бинарной совместимости. Игровой прогон/сборка будущих адаптаций здесь не выполнялись.
