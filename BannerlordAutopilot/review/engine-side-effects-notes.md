# Проверка подписчиков AiHourlyTick (локальная DLL 1.4.8)

Полная декомпиляция ilspycmd 10.0.1.8346: `engine-side-effects/`. Все номера ниже относятся к ней. Игра не запускалась. Выводы относятся к штатной CampaignSystem.dll; модифицированные модели и подписчики других модов не покрыты.

## Установленные факты

1. В DLL восемь регистраций AiHourlyTickEvent, не семь. Пропущен AiVisitSettlementBehavior:77; SandBoxManager:122 устанавливает это поведение. Другие семь: AiArmyMemberBehavior:18, AiEngagePartyBehavior:16, AiLandBanditPatrollingBehavior:11, AiMilitaryBehavior:27, AIMoveToNearestLandBehavior:15, AiPatrollingBehavior:27, PatrolPartiesCampaignBehavior:45.
2. Буквальные утверждения №2/3 опровергаются изменениями чужих кешей. AiMilitaryBehavior:519 -> PartyThinkParams.Initialization:54-77 -> перебор MapFaction.Heroes -> Party.EstimatedStrength -> PartyBase:422-431 -> UpdateEstimatedStrengthCaches:857-860 записывает _cachedEstimatedStrength и _lastEstimatedStrengthVersionNo. Через CalculateEstimatedCurrentStrength:884-896 -> DefaultMilitaryPowerModel.GetPowerOfParty:96-120 -> Hero.PowerModifier:729-738 возможна запись чужого _powerModifier. Воспроизведение по коду: F10, герой-вассал, другие партии своей фракции, хотя бы у одной устарел strength cache. Это кеши, НЕ доказательство изменения приказов, ресурсов или порчи кампании. Цена: низкая техническая; средняя для достоверности заявления «ничего не меняем».
3. Дополнительный путь к чужим кешам: AiMilitaryBehavior:522 -> DefaultArmyManagementCalculationModel.CanLordCreateArmy:119-200 -> foreign party.EstimatedStrength:156, GetCustomStrength:184 -> тот же power model. Не нужен для пункта 2, поскольку Initialization вызывается раньше независимо от возможности собрать армию. AiEngagePartyBehavior:111,125 также читает силы чужих партий.
4. AiVisitSettlementBehavior:184-185,200 изменяет общий рабочий список _settlementsNavigationData (Clear/Fill/Sort); AiMilitaryBehavior:271-298 изменяет _checkedNeighbors. Само по себе это повторно используемая рабочая память, а не обнаруженная ошибка кампании.

## Проверенные подозрения, которые не подтвердились

- CanLordCreateArmy не создает армию и не снимает влияние. GetInfluenceBudgetWhileCreatingArmy:308-311 только возвращает Influence * 0.7; результат в :125 даже не используется. PossibleArmyMembers остается списком-кандидатом. Реальное создание армии находится в AiPartyThinkBehavior после выбора, не в исследованных подписчиках.
- DefaultArmyManagementCalculationModel:74 party.LeaderHero.RandomFloat НЕ потребляет глобальный RNG: RandomOwnerExtensions:53-65 использует сохраненный Hero.RandomValue (Hero:775 auto-property). Seeded random в DefaultTargetScoreCalculatingModel и AiVisitSettlementBehavior не следует называть потреблением общего RNG без доказательства реализации MBRandom.
- Прямой MBRandom.RandomFloat в AiLandBanditPatrollingBehavior:38 и AiVisitSettlementBehavior:546 относится к bandit-only веткам; MainParty как LordParty туда не проходит. Не найден подтвержденный путь потребления глобального RNG для штатного MainParty в исследованных цепочках.
- DoNotChangeBehavior в AiMilitaryBehavior:499 выставляется только лидеру существующей армии, ожидающей участников (:493-499). При Army == null недостижим.
- WillGatherAnArmy=true в AiMilitaryBehavior:536 выставляется только для ArmyTypes.Besieger; соответствующий AiBehavior в :142 — BesiegeSettlement. AiPatrollingBehavior:244 явно ставит willGatherArmy:false. PatrolAroundPoint+WillGatherArmy не найден как достижимый штатный результат. Нельзя выдавать поддержку такого случая в AiPartyThinkBehavior за достижимый баг автопилота в stock игре.

## Покрытие и пределы

Тела всех восьми подписчиков просмотрены. Для MainParty на свободной суше AiArmyMemberBehavior возвращается при Army==null (:39); AiLandBanditPatrollingBehavior — при !IsBandit (:21); PatrolPartiesCampaignBehavior — при !IsPatrolParty (:429); AIMoveToNearestLandBehavior — при !IsCurrentlyAtSea (:20). Четыре остальных проходят к расчетам. Углубленно разобраны army model, PartyThinkParams, силы партий/героев, RandomOwnerExtensions, основные target score и navigation helpers. Это не машинно доказанная чистота полного транзитивного замыкания каждого метода, особенно native map scene и заменяемых моделей. Не подтверждено ни создание армии, ни трата ресурсов, ни выдача чужих приказов из штатного сбора оценок.

CampaignEventDispatcher:1224-1230 вызывает все event receivers, CampaignEvents:2103 рассылает событие. Сторонний receiver/model вправе иметь побочные эффекты; отсутствие Harmony у данного мода не ограничивает их. Это граница гарантии, не установленный дефект соседнего мода.
