# Аудит game connectors: статические ограничения содержимого

Дата: 2026-09-28. Только исходники копии 0.0.6. Изменены исключительно эти артефакты аудита. JSON — основной реестр, приоритет относительно game-as-source-of-truth, не оценка безопасности релиза.

## Что уже берётся из игры

- Bannerlord EquipmentShopBehavior.Tick: MBObjectManager ItemObject -> Sellable -> Describe -> module.catalog_update; behavior подключён в BannerlordLinkModule.cs:415. Catalog живой, но это каталог магазина экипировки, не всех вещей. Party inventory отдельно пропускает неизвестные категории. NotMerchandise не удаляется из owned ledger; отсутствующие предметы модов остаются с unavailable=true (EquipmentShopBehavior.cs:182-191).
- HeroStateSync перечисляет все SkillObject и CharacterAttribute. AddFocus/AddAttribute используют runtime registry. AddSkillXp адресный resolver ограничен DefaultSkills; классовый random pool является авторской политикой. ModifyAttribute legacy resolver ограничен DefaultCharacterAttributes, но backend отклоняет эту команду — не считать живой viewer проблемой.
- RecruitTroops основной путь берёт culture.BasicTroop/EliteBasicTroop, не vanilla troop IDs. Проблема только fallback с tier<=1 и угадыванием элиты по wage.
- EnactPolicy разрешает runtime PolicyObject по ID. В BannerlordLink/src поиск не нашёл publisher PolicyObject catalog. Это scoped отрицательный результат; parent должен связать его с доказанным fixed list frontend.
- RimLinkGameComponent.cs:39-106 строит и отправляет ShopManager/EventManager каталоги при init; ручные пути также есть в RimLinkMod.cs. DefDatabase охватывает загруженные defs модов. Trait degrees, GeneDef, XenotypeDef и skills пешки уже динамические.
- RimWorld EquipItem использует GenStuff.DefaultStuffFor, а не жёстко Steel/Cloth; конфликты одежды проверяются ApparelUtility.CanWearTogether по телу реальной пешки. Нельзя записывать историческую подмену материала или generic одежду как непроверенный текущий дефект.

## Самые важные цепочки

1. Полный registry -> фильтр магазина -> отсутствие записи вообще. Отделить display catalog, доступность покупки, возможность экипировки и владение.
2. Runtime skill state -> fixed DefaultSkills resolver адресного XP. AddFocus/AddAttribute уже динамические. Random XP pool и классовые веса — авторский баланс, не автоматически ошибочная игровая истина.
3. Выбранная культура -> отсутствует Wanderer -> случайная другая культура. Для creation нужен catalog availability, а не только список культур.
4. RimWorld recipe -> только hediff ID -> первый рецепт -> первая fixed body part -> AddHediff. Сам рецепт и worker semantics не следуют в запросе. Модовые операции нельзя обещать без адаптации.
5. IncidentDef -> label dedup -> новый mod ID исчезает. Dedup должен опираться на стабильную идентичность.
6. Event tier T4/T5 -> payload points4000/6000 -> FireIncident clamp3000. Safety cap не следует снимать; нужно выровнять объявленное и исполненное.

## Уточнения второго прохода

- Возраст 18 доказан только в Marry/MakeBaby/FamilyHandlers. AdoptHero уже читает AgeModel.HeroComesOfAge, но оставляет maxAge35. Не утверждать, что весь мод игнорирует AgeModel.
- IsAnomalyEvent в CommandFactory — **неактивный helper**: поиск по всей RimLink/Source дал только определение, без вызовов. MOD-041 исключён из списка активных блокировок.
- Реальная дополнительная эвристика находится в EventCommands.cs:274-301: имя ID Join/Trader выбирает allied humanlike faction; ThreatBig или имя worker Raid — hostile humanlike; ShipPart/Siege/Crash/Raid — spawnCenter. Это граница поддержки custom workers, даже при динамическом ID. TryExecute результат возвращается корректно; наличие heuristic не доказывает наблюдённый игровой сбой.
- Не найден численный Take лимит каталога в просмотренных builders. Не приписывать backend/frontend caps коннектору. Усечение отдельных tooltip до120 символов есть, но общий desc часто сохранён отдельно.
- В просмотренных item payloads нет общего контракта изображения/icon asset из игры. Это schema gap, не доказательство неправильного локального icon path. Передавать пути игровых файлов в веб нельзя считать решением экспорта assets.
- HeroBuildPolicy содержит собственные 4 специализации, powers, cooldown/duration; это платформенная механика. Не удалять её под лозунгом «всё должен сообщить vanilla Bannerlord». Нужна единая декларация этой механики и её связи с runtime предметами.
- Старые SetClass/EquipItem/UpgradeGear/Reequip handlers зарегистрированы рядом с новым free-build/shop. Регистрация доказана; внешняя достижимость зависит от backend, проверяется parent. Echo set_culture/set_faction тоже зарегистрированы, но их нельзя рекламировать как реализованные capabilities.

## Проверки для будущей реализации

- Новая модовая культура с Wanderer / без Wanderer: точный выбор либо объяснённый отказ, никогда молчаливая замена.
- Новый SkillObject и CharacterAttribute: snapshot, кнопка, dispatch, game resolution, результат относятся к одному ID.
- Вещь знакомого типа, неизвестного типа, NotMerchandise, дорогая, без рецепта, отсутствующая после удаления мода: видимость и возможность покупки проверяются отдельно.
- RimWorld alien body с тремя одинаковыми конечностями, несколько рецептов одного hediff, recipe с несколькими допустимыми частями, custom worker: нельзя подменять точную цель left/right.
- Два incident с одним label и разными ID; T4/T5 effective threat; unknown category без ложного утверждения «лёгкий».
- Смена игры/сейва/модпака и изменение исследований: catalog session/version и availability freshness.

## Границы доказательства

## Поправки после cross-layer проверки parent

- MOD-012 переведён в INFO/legacy_inactive: routes/bannerlord.py:2084-2092 явно отклоняет player.modify_attribute. Динамический рабочий путь — hero.add_attribute. Регистрация старого handler не доказывает viewer доступность.
- MOD-011 снижен до P2/adapter_constraint: DefaultSkills ограничивает именно адресный XP resolver; авторские random/class weights не объявляются ошибкой. Backend 2009-2023 разрешает optional skill_key; daily reward595-603 намеренно random.
- MOD-018 переведён в P3/fallback: backend2870-2877 блокирует set_class/upgrade/reequip при equipment session; player.equip_item исключён из покупаемых937-944. Старые пути нельзя считать активным обходом новой модели.
- MOD-027 снижен до P3: исключение Baseliner и custom-save xenotypes является явной областью магазина; это не само по себе баг. Полнота display каталога и продаваемость — разные требования.

## Окончательные границы

Финальный cross-review: MOD-022 снижен до P2. Tech-era фильтр активен, но research_unlocked не найден как потребляемое поле frontend/backend; не доказана надпись «исследовано» или UI отказ на основе этого поля. MOD-039 — INFO/platform_policy_ok: полный description сохранён и уже показан раскрытием shop.js163-179, усечение касается краткого tooltip. MOD-024: ручной PriceSettings.PairedImplants override не исправляет экспорт is_paired — ShopManager185 считает отдельно по Human, BuildCatalogWithPrices370-372 заменяет только цену; Prices.IsPaired вызывается в UI настроек RimLinkMod328.

MOD-019 дополнительно переведён в INFO/legacy_inactive: set_culture/set_faction сняты из manifest114; respawn отсутствует в покупаемых, viewer route3312 проверяет этот список. EchoHandler33-38 возвращает отказ и PostFailed, не ложный успех. Это риск будущего наивного discovery, не текущая оплачиваемая кнопка.

Cross-layer контрпример: EquipmentShopPolicy.PublicTier сейчас зажимает native tier в1..6. Проба backend payload tier7 демонстрирует future-contract ограничение, но не доказывает исчезновение текущего модового предмета: текущий producer отправит6. MOD-005 описывает именно схлопывание отображаемого тира и собственную level policy.

Второй проход по дополнительным файлам добавил MOD-043..048: caravan template fallback, workshop fuzzy identity, vassal template/age fallback, property ownership по имени вместо stable registry, отсутствие session envelope у RW catalogs и группу нормальных продуктовых политик.

Дополнительные проверенные исключения:

- TrainTroopsHandler98-119 использует текущие UpgradeTargets, выбирает same-culture предпочтительно и random branch. Нет vanilla troop whitelist. Tier costs и elite multiplier — собственная цена свиты.
- SummonHeroHandler1058-1067: free-build ветка определяет mount по фактической BattleEquipment, только legacy использует MountedClasses. Нельзя считать этот список причиной спешивания любого нового билда. Retinue684-685 разрешается runtime CharacterObject; missing IDs пропускаются, это уже предмет отдельной reconciliation проверки.
- EquipItemHandler270-322 содержит старые random categories/tier>=4, но player.equip_item закрыт viewer gate; не добавлен как новый активный дефект.
- TournamentMission210-238 получает filler через runtime CultureObject.BasicTroop/EliteBasicTroop всех культур, а не vanilla список. Fixed reward/handicap — own policy.
- PriceSettings содержит overrides/enabled по defName, настраиваемые category multipliers и defaults; неизвестная category получает multiplier1. Это допустимый pricing policy fallback, не подмена игровых свойств. Маркер RimLink_ViewerIdentity — наш собственный сохраняемый HediffComp, не vanilla hardcode.
- Caravan/Workshop snapshot читает реальное имущество. Комментарии о ratio150:1/100:1 сами по себе не подтверждают текущую backend конвертацию и не включены как факт экономики. Найденная проблема этой группы — name-based identity при наличии stable registry.


Проверялись релевантные фрагменты, а не полная построчная вычитка всего src. Нет сборки, проверки DLL, production, игры или установленных модов. Native API semantics не декомпилировались. Приоритеты — планирование миграции; не утверждение что каждый случай уже проявился у зрителя. CodeGraph заблокирован по проверке parent; использовались поиск литералов и чтение исходников. Backend/frontend/autopilot в этой части не менялись и не аудировались.
