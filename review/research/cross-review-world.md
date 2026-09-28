# Независимая проверка combat notes (world investigator)

2026-09-28. Проверены `blt-combat.md`, `shedlink-combat.md` против исполняемых тел source. Только чтение runtime; этот файл единственная запись проверки. Пины те же, что в исходных notes. Живой сцены/сборки нет.

## Подтверждено с уточнениями

1. **Guard действительно управляет принадлежащей герою свитой.** MBGA5197130 `source/MakeBltGreatAgain.cs:630-725` GuardCommand добавляет Hero в activeGuards; tick694–719 берёт `GuardSummonAccess.GetRetinueAgents(hero)` и ведёт именно эти Agent к heroAgent. Helpers754–773 читают оба свойства Retinue/Retinue2 и поле Agent. Mesmer BLTSummonBehavior.cs:39-40 содержит эти реальные list-properties. `SubModule.xml:29` подключает BLTGuardModule, source500–504 добавляет GuardMissionBehavior в combat mission. Это не спутано с follow своего героя и не только непривязанный класс.

2. **НО guard off НЕ восстанавливает AI.** MBGA source682–687 `DeactivateGuard` только удаляет Hero из HashSet и пишет log. Не зовёт DisableScriptedMovement/SetAutomaticTargetSelection для свиты. Отмена прекращает новые приказы, но обещать мгновенное штатное управление после off нельзя. Это дополнительная конкретная caveat к уже указанной в combat notes опасности scripted target. Нельзя копировать lifecycle буквально.

3. **Нет formation presets в текущем GuardCommand.** Единственный специальный аргумент `off`, любой иной включает guard. TOR `line/shield/loose` действительно GUIDE_ONLY. Наличие Native Formation API не доказывает эту функцию.

4. **FollowHero — отдельный реально достижимый путь.** MBGA145–190 выбирает второго viewer Hero, запрещает self, deployment и явно другой Team, вызывает FormationBehavior.ActivateFollowHero. Это командование своим героем рядом с другим, не приказ свите охранять другого зрителя. Guard и Follow можно рассматривать как две комбинации над существующей системой, не считать обе независимыми новыми подсистемами.

5. **Reflection caveat точнее:** комментарий MBGA `CurrentAgent jest Property` неверен для Mesmer `HeroSummonState.CurrentAgent` (поле на строке36). GetProperty промахивается, но GetHeroAgent имеет fallback поиска Mission.Agents, поэтому это **не доказанная поломка guard**. Combat note формулировку «читает Current.HeroSummonStates» лучше уточнить: helper775–782 отражённо вызывает Mission.GetMissionBehavior<T>() и instance.GetHeroSummonState(hero), затем Retinue/Retinue2. Сам вывод о dependency на внутренний BLT тип верен.

6. **Duel не требует согласия и не изолирует участников.** MBGA1512–1736 проверяет живые агенты/разные Team, HasActiveDuel только для атакующего, словарь attacker→target; target может быть целью многих. StartDuel1660 командует только атакующим; target сохраняет обычный AI. DuelMoveAndFight1720 допускает ближайших других врагов по дороге. Combat notes правильно классифицируют как pursuit/target order поверх существующего PvP. Уточнение: guard — `Team != Team`, не универсальная `IsEnemyOf`, так что «любая межкомандная ситуация означает врага» не гарантировано в нестандартных сценах. Объявление defeated не доказывает, что дуэлянт нанёс последний удар.

7. **ShedLink уже умеет PvP, поэтому назвать отсутствие duel отсутствием PvP было бы ошибкой.** Прочитан SummonHero/side lock и текущий registry; dedicated consent duel action не найден среди реальных handler registrations. Истинная mutual challenge + 1v1 fairness была бы собственной новой механикой, не переносом доказанного BLT поведения.

## Tournament: реальный gap, но не полная уравниловка

8. В трёх активных ShedLink источниках `TournamentMissionBehavior`, `TournamentQueueBehavior`, `TournamentParticipantsPatch` нет собственного выбора/normalization MatchEquipment или custom bracket/loadout preset. Есть roster injection, награды, winners anti-snowball. `TournamentMissionBehavior.cs:50-96` **классово-различающий** HP penalty для прошлых победителей (0.65–0.85 + fallback0.75), не только единые25%. Это уже их собственный баланс; не описывать как отсутствующий.

9. Mesmer `BLTTournamentMissionBehavior.cs:304-341` branches Default/ClassLoadout/CulturalUnified, `:590-595` реально Harmony AddRandomClothes prefix пропускает native method при собственном equipment handling. `ApplyNormalizedArmor:259-282` nearest tier и культура, `BuildUnifiedLoadout:380+` одна оружейная семья на раунд. Эти пути действительно реализованы, не просто enum/config.

10. **Формулировка «progression-independent competitive event» слишком сильная.** Одинаковый tier/weapon family не уравнивает фактические damage/armor между предметами разных культур/modpack; навыки, атрибуты, perks, HP и активные powers могут сохранять преимущество. ClassLoadout специально различает экипировку/коня по классу. Корректно: «уменьшает зависимость результата от постоянного gear, даёт явно заданный формат». Для полной нормализации нужен отдельный перечень нормализуемых характеристик и powers policy. BLT ActivePowerGroup.CanActivate имеет config DisablePowersInTournaments; сам режим CulturalUnified этот флаг не доказывает включённым.

## Powers: novelty правильно ограничена

11. ShedLink new-build `HeroBuildPolicy.cs:27-79`: seven families, weapon equipped/wielded/hit match, native skill ranks50/150, shared cooldown, passive specialization. `ActivatePowerHandler.cs:115-140` применяется только если build!=null и power!=heal_burst; старые герои без build идут legacy paths. Combat notes правильно не обещают всем новым героям весь legacy switch. Отдельно heal остаётся исключением к выбранной weapon power, поэтому выражение «ровно одна способность вообще» было бы неверно.

12. RC22 `PowerGroupItemBase.cs:18-32` Requirements.All(IsMet); ActivePowerGroup66–124 берет несколько unlocked power definitions, checks/activates их, PassivePowerGroup устанавливает handlers. Реальная добавочная глубина — **несколько компонентов с разными criteria**, не «наконец появятся ограничения abilities». Старые BLT требования основаны на IAchievementRequirement (включая statistic/class-specific), а не доказанный произвольный JSON-rule engine. Нельзя обещать полную универсальность любого предиката без дополнительного дизайна.

13. Это не зависит от reverted MBGA cbf8553. Имена групп/требований найдены в актуальном RC/Mesmer core. При этом наличие эффекта в конфиг-классе не доказывает, что он назначен конкретному playable class в TOR preset. Классификация capability-level B допустима, конкретные TOR способности требуют конфигурации.

## Дополнение training и проверка собственных заметок

14. Own-world pass подтвердил: ShedLink TrainTroopsHandler63–181 — разовая замена retinue slot metadata/событий, PartyOrderBehavior517–588 — найм по маршруту. Не persistent budget для нативного roster. Provisional C в combat summary лучше заменить на **B: углубление существующего управления войском**, чтобы не получилось «training отсутствует». Source evidence передан основному агенту.

15. Проверены смысловые якоря собственных world notes: ManageFief RC/Mesmer215 реально вызывает BuildingHelper.ChangeCurrentBuildingQueue, бюджет258–284 меняет Hero.Gold; public engine methods5722/5737 действительно в текущем local decomp. Губернатор в ManageFief пуст, но PartyManagement465–493 действительно назначает самого viewer Hero. Wanderer исторический source352bb4c, актуальный5197130 удалён; repository origin MesmerTurn/MakeBltGreatAgain подтверждён. URL Rejuvenate исправлен до github.com. Heir note правильно предупреждает о null после присваивания, это source risk без теста. Не найдены основания отменить эти world выводы.

## Итог challenge pass

Основные combat gaps выдержали проверку. Для сводного отчёта обязательны 4 уточнения: guard off не возвращает AI; cultural tournament preset не гарантирует равенство stats; duel — принудительное преследование без consent/изоляции; training — расширение существующего, а не новая отсутствующая система. Прямой перенос reference-реализаций не рекомендован.
