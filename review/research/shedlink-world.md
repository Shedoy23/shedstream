# ShedLink: мир, династия, владения — фактическая инвентаризация

База: `C:/Users/Edward/Desktop/work/.claude/worktrees/bannerlord-crash-analysis-a34de4`, ветка `claude/poststream-2026-09-22`, HEAD `0cdf6338`. Только чтение исходников. CodeGraph заблокирован, использованы прицельные чтения/поиск. Ни живой игры, ни доказательства установленной версии этот документ не представляет. Строки ниже относятся к этой базе. Старые комментарии проверялись по исполняемому телу, а не принимались за статус.

## Общий путь и владение состоянием

`viewer-bannerlord.js` вызывает `_bannerlordBuyAction`; `routes/bannerlord.py:1722,1792,2803,3354` проверяет пользователя, mirror-состояние/ограничения, цену и ставит `module_actions`; `ActionRegistry.cs:29-122` регистрирует реальные обработчики; `MainThreadDispatcher` исполняет на game thread; `ActionFeedback` подтверждает результат/отказ. `HeroStateSync.cs:144-263` строит полный снимок Hero (gold, alive, prisoner, clan, kingdom, family, skills, attributes, heirs, vassals, kingdom readiness); `_adapter.py:1159` принимает state update с контролем свежести и пишет зеркало. Состояние мира живёт в движке/сейве; backend хранит зеркало, платформенную оплату, заявки и некоторые собственные каталоги/прогрессию.

`HeroIdentityBehavior.cs:56-65` сохраняет StringId→username и iteration через `IDataStore.SyncData`; `MainCampaignBehavior.cs:61-102` подписывает HeroKilled, HeroLevelledUp, load/session, MapEventEnded, DailyTickHero, Tick, HeroComesOfAge; `:639,684,811` публикует property/full hero snapshots, поэтому система не ограничивается присутствием зрителя в чате/сцене. Из этого не следует, что все offline/replay крайние случаи проверены в игре.

## Семья и жизнь

**Уже есть:** NPC-брак/развод, беременность и настоящие children, родители/сиблинги/генеалогия, взрослые наследники, имя/внешность/reset skills ребёнка, договорённость о браке детей двух зрителей, выбор автоматического наследника при смерти, новый герой при отсутствии наследника, история имущества.

UI: `viewer-bannerlord.js:2843` `loadBannerlordHeirs`, `:2877` `loadBannerlordFamily`, `:3065-3139` имя/respec/bodycode/предложение брака; `:4530,4591` профиль/дерево семьи, `:5186` создание нового wanderer после смерти. Backend: `routes/bannerlord_family.py:56-156` own/public children и proposals; `:183-346` propose/respond/cancel (ownership, pending/expiry), принятие ставит `hero.activate_marriage`; `routes/bannerlord.py:161` heirs.

`MarryHandler.cs:88-150` берёт реальных живых NPC: противоположный пол, взрослый, unmarried, не viewer/MainHero/prisoner/fugitive; fallback-tier ослабляет возраст<50/не лидер/клан. Выбор случайный через MBRandom, не выбор конкретного NPC. `:158-226` charge game gold, взаимные Spouse, cleanup governor/party, перевод NPC в clan, native MarriageModel relation. `MakeBabyHandler.cs:55-151` проверяет alive/age/spouse/лимит детей/pregnancy, списывает game gold, вызывает `MakePregnantAction.Apply`, наблюдает IsPregnant и синхронизирует; рождение далее ведёт vanilla PregnancyCampaignBehavior.

`FamilyHandlers.cs:60-157` ActivateMarriage разрешает Hero by stable ID, проверяет alive/age/unmarried, задаёт взаимный `Spouse`, шлёт `hero.marriage_activated`. Это минимальное связывание: тело не выполняет полный vanilla clan/banner housekeeping и не проверяет все marriage-model условия. Не описывать как полностью нативную дипломатическую свадьбу. `:164-327` child rename/bodyprops/respec — реальные handlers, а не только форма.

## Смерть, преемственность, наследство

`MainCampaignBehavior.cs:234-268` смерть → player.died; `_adapter.py:1329-1513` отмечает dead, увеличивает iteration, берёт первый alive nonactivated heir по came_of_age, заранее помечает activated, собирает workshop/caravan/fief mirror, пишет inheritance_log и ставит hero.activate_heir. Важно: выбранный сервером наследник ещё проверяется игрой, но выбор/отметка/журнал до подтверждения; это завершённый путь реализации, не доказательство безотказного восстановления при любых гонках.

`ActivateHeirHandler.cs:78-217`: resolve real Hero, жив ли; rename+identity; heal; player.linked + player.respawned + полный state/equipment; **личный сундук умершего наследуется** через `EquipmentShopBehavior.InheritStash`, надетое уходит со старым героем; workshop reclaim и transfer existing caravan ownership. `:228-319` использует `ChangeOwnerOfWorkshopAction.ApplyByBankruptcy`, `CaravanPartyComponent.TransferCaravanOwnership`. Workshop совпадение settlement/type с fallback; чужое viewer-имущество защищает guard. Уничтоженные караваны не воскрешаются. Клан/владения наследуются через native dynastic logic, handler не принуждает смену clan или владения каждым fief. `viewer-bannerlord.js:1763` показывает inheritance-log, route `bannerlord.py:3719`.

**Не повторять устаревшее «зрители бессмертны»:** `BannerlordLinkModule.cs:308-322` в skip-list campaign immortality patch; `AdoptedHeroDeathPatch.cs` содержит старое большое описание, но `Mission_OnAgentRemoved_Patch.HeroBattleImmortality=false`. Активный `ViewerBattleMortalityPatch.cs:17-35` — postfix `DefaultPartyHealingModel.GetSurvivalChance`, 0.0002 смерти за knockdown, гарантированное survival сохраняется, RNG остаётся движку. Конь protected отдельно. Это death consequence с династией, уже не простое BLT reborn.

## Кланы, вассалы, королевства

UI `viewer-bannerlord.js:4734,4779,4894,4982` create/join/leave clan/kingdom. Handlers `CreateClanHandler.cs:50-181`, Join/LeaveClan, Join/LeaveKingdom реальны и возвращают события; adapter `:2099-2226` обновляет зеркало. У героя настоящий Clan/Kingdom, не фиктивная browser guild.

`CreateKingdomHandler.cs:45-68` вычисляет сторонников восстания: личные вассалы или relationship≥50, в старом kingdom; `:100-210` требует 2 сторонников при восстании, допускает landless kingdom, защищает текущий бой, вызывает `KingdomManager.CreateKingdom`; `:216-253` переводит сторонников native defection path с сохранением их владений, выдаёт стартовый бюджет/влияние, charge и event. Это конкретная глубокая механика, которую нельзя предлагать как отсутствующую.

`VassalHandlers.cs:46-233` выделяет взрослого подходящего ребёнка в новый `Clan.CreateClan`, назначает лидера/дом/kingdom и регистрирует связь. `:265-488` **recruit_vassal_clan создаёт нового NPC из template (`HeroCreator.CreateSpecialHero:377`) и клан**, не нанимает выбранного существующего wanderer-компаньона и не управляет набором companion roles. `:500-540` rename. `VassalAutoFollowBehavior.cs:91-115` сейвит отношения вассал/master и денежные baselines; `:205-237` follows master's kingdom; `HeroStateSync.cs:197-201,259` даёт полные heirs/vassals snapshots; backend `routes/bannerlord_vassals.py:62-136` reconcile, `:171-218` eligible heirs, UI `:1833-2003`. Не путать вассала с party companion.

## Clan upgrade tree уже существует

`routes/bannerlord.py:3445-3500` выдаёт каталог own/locked/requires; `:3547-3681` проверяет prerequisite и ordered bulk chain, очередь `hero.buy_clan_upgrades`; `BuyClanUpgradesHandler.cs:13-54` charge game gold и durable purchased event; `_adapter.py:1999` записывает owned после события. `viewer-bannerlord.js:4161` tree, `:4252` bulk binding, `:4306` UI.

`ClanUpgradesBehavior.cs:94-113` game save owned JSON, `:133-157` restore to backend, `:173-220` fetch owned/effects, daily tick renown/influence. **Комментарий в шапке «статические бонусы follow-up» устарел:** `Models/BLUpgradeModels.cs:34-83` оборачивает предыдущую PartySpeedModel, solo/army bonuses; `:88-111` PartySizeLimitModel, `:148-163` ClanTierModel party limit. Retinue capacity bonus применяется backend `bannerlord.py:1874`. Поэтому prerequisite trees, bulk and native model upgrade effects не являются пустым gap. Контент/effects собственного дерева пока от backend, ownership зеркалится save; это граница для game-as-source-of-truth.

## Дипломатия и коллективная политика

UI `viewer-bannerlord.js:2384` kingdom-state, политика/мир/выкуп/налог; backend `bannerlord_diplomacy.py:54,232,358,430,513`; game `DiplomacyHandlers.cs`: `EnactPolicyHandler:24` runtime PolicyObject и decision path; `MakePeaceHandler:140`; `ProposeWarHandler:360` и `ProposePeaceHandler:429` отправляют native kingdom decisions; `ViewerDeclareWarDecision:330` / `ViewerMakePeaceDecision:343` custom support computation; `PayRansomHandler:496`; `SetKingdomTaxHandler:563`. Это не отсутствие взаимодействий viewer↔viewer: политика, общие войны и семейные предложения уже связывают игроков.

`KingdomTaxBehavior.cs:55-75` DailyTickClan + save налоговой ставки и last gold; `:99-142` положительный delta дохода clan leader → `GiveGoldAction.ApplyBetweenCharacters` king (не platform points). Это собственная налоговая логика, не generic «kingdom upgrade tree».

## Parties, armies, orders и стратегический мир

`CreatePartyHandler.cs:63-222`: live Hero, prisoner/state/clan/party/WarPartyLimit проверки; снимает Governor, `MobilePartyHelper.SpawnLordParty`, ChangePartyLeader, ActualClan, добавляет retinue roster, starter food/horses, position и плату. Mirror backend `bannerlord.py:2396`, `_adapter.py:2228`; UI обычные management blocks.

`ArmyHandlers.cs:38-185`: реальная kingdom army через `Kingdom.CreateArmy`; candidates через `ArmyManagementCalculationModel.CanLordCreateArmy`; временный influence buffer компенсирует native call cost; checks лидер/kingdom/mercenary/current battle; реиспользует активный party order и выбирает армейский тип siege/raid/defend. `DisbandArmyHandler:201` реальный роспуск. **Комментарий «cohesion later» устарел:** `PartyOrderBehavior.cs:409-430` hourly top-up до100 уже есть.

`viewer-bannerlord.js:2083-2340` приказы, backend `routes/bannerlord_party_orders.py`, `PartyOrderHandlers.cs:63-220` runtime Settlement resolution, hostility gate, SetMoveBesiege/Defend/Raid/GoTo/Patrol; recruit автоматический. `PartyOrderBehavior.cs:83-139` HourlyTick + SyncData, `:268-400` expiry/completed/reissue; `:517-588` маршрут пополнения и native найм. Существуют persisting 7-game-day orders, не одноразовый запрос с потерей на следующем тике.

## Workshops, caravans, fiefs

UI `viewer-bannerlord.js:1270,1381` мастерские; `:1569,1673` караваны; `:1493` феоды. Backend routes `bannerlord_workshops.py`, `bannerlord_caravans.py`, `bannerlord_fiefs.py`, mirrored properties snapshot `_adapter.py:1750`, callbacks `:2721-2850`. Game handlers WorkshopHandlers buy/sell (`:37,303`) и CaravanHandlers (`:33,293`) создают/передают/продают настоящие engine entities. Daily sync behaviors считают profit/ownership; CaravanTracker отправляет durable profit/destroyed. Реальная инфраструктура, не wishlist.

`FiefTributeSyncBehavior.cs:39-119` оценивает native model tax/tariff income; `:123` ownership snapshot. Backend `bannerlord_fiefs.py:159-201` **только статистика динаров**, add_points отсутствует, native экономика даёт Hero.Gold; `:98-109` tribute boost немедленно отказывает, код ниже мёртв. Шапка файла обещает passive points ошибочно. Не предлагать «возврат passive platform farming» как необусловленное улучшение.

**Не установлено наличие:** viewer-facing назначения Scout/Surgeon/Engineer/Quartermaster/Governor, каталога настоящих hired wanderers и их индивидуального gear/XP/UI; отдельного fief building upgrade tree/kingdom upgrade tree. Основание шире отсутствия слова: просмотрены полный ActionRegistry, соответствующие frontend management blocks, семейные/property routes и реальные handlers; имеющиеся Governor API в CreateParty/Marry/LeaveClan — снятие чужой роли при перемещении, а не назначение companion. Нативный game AI может иметь такие роли, это не управляемая viewer-механика.

## Предварительные выводы для сравнения (не roadmap)

Сравнивать только разницу глубины. «Добавить семью/наследников/вассалов/кланы/постоянные приказы/prerequisite upgrades/наследство сундука» уже не новое. Возможные предметы проверки BLT: roster нескольких именованных companions, назначение party roles, local property upgrades, kingdom-specific prerequisites, выбор наследника/завещание и более богатая biography. Они остаются гипотезами до прочтения BLT. У нас уже особенно развито существование в campaign world, viewer family negotiation и dynasty/property continuity. Не называем его лучше BLT до сравнения.
