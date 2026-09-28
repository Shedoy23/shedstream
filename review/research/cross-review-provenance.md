# Независимая проверка provenance/history и companion versions

Проверены `provenance-history.md`, companion/reborn части `blt-world.md`, current tracked license/readme trees и соответствующие historical git objects. Сторонние DLL не запускались; это факты исходников, не юридическое заключение.

## Исправить / уточнить

1. **Reborn не восстанавливает native skills даже при наличии CloneHeroData.** В current standalone MBGA `source/MakeBltGreatAgain.cs:6291–6292` только первому skill задаётся1, если он0; `:6304–6306` optional reflection вызывает CloneHeroData. В Mesmer `BLTAdoptAHero/Behaviors/BLTAdoptAHeroCampaignBehavior.cs:673–693` метод переносит BLT ledger gold/spent, retinue1/2, tier/equipment class/class, prestige, customItems, AchievementStats. Native HeroDeveloper skills/focus/attributes не переносит. Комментарий MBGA6300 обещает skills, success6337 — everything; это не следует из реализации. Текущий blt-world верно описывает optional missing-method path, но стоит добавить это ограничение и для полного форка. RC22 tree не имеет определения CloneHeroData.

2. **Фраза «встроенный MBGA в полном форке» может создать ложное впечатление current inclusion.** Текущий Mesmer `git ls-files '*MakeBlt*' '*Wander*'` не содержит тех companion source. `a8bc344e00248069442a4979ecd3b9576ecdefa9` удалил imported `BLTAdoptAHero/MakeBltGreatAgain.cs` (5718строк), а historical `a8bc344^:BLTAdoptAHero/BLTAdoptAHero.csproj` не включал его в explicit Compile list. Поэтому лучше написать «standalone module; исторический duplicate полного форка не был частью его сборки». В blt-world это различие уже корректно разъяснено ниже, но source-version table стоит согласовать.

3. **Дополнить конкретный third-party notice в лицензиях.** У billw есть `BannerlordTwitch/BannerlordTwitch/SaveSystem/ButterLibLicense.txt`; RC22 обе папки SaveSystem и Util/SaveSystem; Mesmer `BannerlordTwitch/SaveSystem` и `Util/SaveSystem`. Файл содержит полный MIT текст, Copyright2020 BUTR Team. Это отдельный notice для SaveSystem provenance, не MIT-лицензия всего BLT. Строка про JetBrains/third-party headers в отчёте верна, но BUTR более конкретен для обсуждаемого ScopedJsonSync/save.

## Подтверждено без возражений

- Корневые LICENSE billw `f989f56` и RC22 `83b264f` буквально LGPL Version2.1; README обоих отдельно заявляют source-sharing binary-change rule. Это не MIT.
- В current Mesmer `dee0d17` нет tracked root LICENSE; README74–76 различает BannerlordTwitch original license и MakeBltGreatAgain MIT. Отчёт правильно не распространяет MIT на весь fullfork.
- Standalone MBGA `5197130` README100–102 заявляет MIT; `git ls-files` не находит LICENSE/COPYING/NOTICE. Формулировка «потенциальный reuse после установления notices/provenance» корректно условная; не превратить её в подтверждённое blanket разрешение на весь файл.
- History `693e0bd` действительно удаляет class progression tree/UpgradeClass:7files,334deletions. Не текущая функция.
- History `df04587c7c183497a12eb47e4ed0a8c24bfb99c9` прямо описывает removal entire Wanderer system + Prestige и причины scope/naval-death crash. Historical `352bb4c` действительно определяет WandererRecord, BLTWandererBehavior, WandererCommand, HeroCreator.CreateSpecialHero, WandererTierCalculator. Это не только retained design-doc.
- Текущее дерево MBGA не содержит этих companion definitions; упоминание GetWandererTemplates внутри Reborn не означает companion subsystem.
- Hire historical WandererCommand создаёт нового Hero из template. Формулировка blt-world «не выбранный существующий tavern NPC» верна.
- TOR-specific tier9/ingredients не выданы за public-code proof; full item provenance в сравнении progression не приписана BLT без полей/events.
- Full-source import698eac7 нельзя использовать как дату возникновения всех механик или отсутствие старого бинарного поведения.

Никакие файлы исходных проектов или других исследователей не изменялись. Два существенных уточнения отправлены родительскому агенту сразу.
