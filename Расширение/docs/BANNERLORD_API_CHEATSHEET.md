# Bannerlord API Cheatsheet (для BannerlordLink)

**Что это:** слой быстрой ориентации по Bannerlord modding API (v1.3.15.x, net472),
организованный **по задачам**. Для каждой задачи: `TaleWorlds`-API → как делает BLT
(файл) → как у нас в `BannerlordLink` (файл) → ⚠ готча.

**Когда мало — копай глубже:** `docs/BLT_RC22_REFERENCE.md` (88 КБ, разбор BLT
по файлам). Сам сорс BLT: `reference/BLT_RC22/BannerlordTwitch/` (262 `.cs`, gitignored).

**Лицензия:** BLT — LGPL clean-room. Здесь только описания API + короткие идиомы +
ссылки на файлы. Тела классов BLT НЕ копировать.

Сокращения путей: `BLT/…` = `reference/BLT_RC22/BannerlordTwitch/BLTAdoptAHero/…`;
`Ours/…` = `BannerlordLink/src/…`.

---

## 1. Агенты, Миссии и Бой (`TaleWorlds.MountAndBlade`)

### Заспавнить агента в миссию
`Mission.Current.SpawnTroop(IAgentOriginBase origin, bool isPlayerSide, bool hasFormation, bool spawnWithHorse, bool isReinforcement, int formationTroopCount, int formationTroopIndex, bool isAlarmed, bool wieldInitialWeapons, bool forceDismounted, Vec3? initialPosition, Vec2? initialDirection)` → `Agent`. origin = `new PartyAgentOrigin(PartyBase party, CharacterObject troop)`.
- BLT: `BLT/Behaviors/BLTSummonBehavior.cs` `SpawnAgent` (`formationTroopCount:1`). Ours: `Ours/Actions/SummonHeroHandler.cs:350` (герой), `:588` (свита).
- ⚠ `initialPosition:null` → engine reinforcement zone (канон, безопасно). Не-null поз требует `isReinforcement:false`. **Турнирные/арена-миссии не имеют reinforcement zone** → SpawnTroop кидает "Nullable object must have a value" (детектить сканом `Mission.MissionBehaviors` на "Tournament").

### Плавный вход после спавна
`agent.FadeIn(); agent.MountAgent?.FadeIn();`
- BLT: `BLTSummonBehavior.cs` сразу после SpawnTroop. Ours: `SummonHeroHandler.cs:404`.

### Принудительно задать сторону/команду
`agent.SetTeam(Team, bool sync)`; команды `Mission.PlayerTeam` / `Mission.PlayerEnemyTeam`.
- BLT: `BLT/Actions/SummonHero.cs` форсит SetTeam пост-спавн. Ours: `SummonHeroHandler.cs:388`.
- ⚠ Движок может проигнорить `isPlayerSide` и назначить команду по `origin.party.MapFaction` — всегда явный SetTeam.

### Переименовать агента (лейбл)
`Agent.Name` read-only → писать приватное поле `_name` (TextObject) через reflection.
- BLT: `BLTSummonBehavior.cs` `AccessTools.Field(typeof(Agent),"_name")`. Ours: `SummonHeroHandler.cs:807` (кандидаты `_name`/`<Name>k__BackingField`).

### Конный/пеший + формация
`FormationClass` enum; `Mission.Mode`, `Mission.IsSiegeBattle`, `IsNavalBattle`. Преференс формации: `Campaign.Current.SetPlayerFormationPreference(CharacterObject, FormationClass)`.
- BLT: `BLTSummonBehavior.cs` `ShouldBeMounted` (false в Stealth/siege/naval); SetPlayerFormationPreference. Ours: `SummonHeroHandler.cs:904` `ShouldUseMount`, `:248` formation pref.
- ⚠ Без SetPlayerFormationPreference лучник-герой падает в дефолтную Infantry-формацию.

### Маунт ↔ всадник
`agent.HasMount`, `agent.MountAgent`, `agent.RiderAgent`, `agent.IsMount`; `CharacterObject.HasMount()`.
- BLT: charge-урон редиректит `attacker.IsMount ? attacker.RiderAgent`. Ours: `Ours/Patches/DamageHookPatch.cs:84` тот же редирект.

### Detach агента из формации (соло-контроль)
Реализовать `IDetachment`; `formation.JoinDetachment(d)`, `formation.DetachUnit(agent,bool)`, `agent.SetScriptedPosition(ref WorldPosition, false, AIScriptedFrameFlags)`.
- BLT: `BLT/Behaviors/BLTHeroDetachmentBehavior.cs` `Detach` (formation-detachment). Ours: `Behaviors/HeroDetachmentBehavior.cs` — **agent-scripted** (`SetScriptedPosition`, НЕ formation: TeamAI перебивал ордера формаций), команды через `hero.detach_*`. См. §8.
- ⚠ `BLTHeroDetachmentBehavior.cs:579` — если `FormationFileIndex == -1` (агент не позиционирован), `DetachUnit` крашит на `_units2D[bad,bad]`; гардить индексы ≥0.

### Lifecycle-хуки MissionBehavior
override `OnAgentBuild(Agent,Banner)`, `OnAgentCreated`, `OnAgentRemoved(Agent victim, Agent affector, AgentState, KillingBlow)`, `OnAgentDeleted`, `OnMissionTick(float dt)`, `OnAgentHit`.
- BLT: `BLT/Behaviors/BLTHeroPowersMissionBehavior.cs`. Ours: `Ours/Behaviors/PowersMissionBehavior.cs:50,60,233` (`: MissionLogic`).
- ⚠ `Agent.State` неопределён после delete (handle переиспользуется) — **кэшировать в OnAgentRemoved**. Копировать коллекции перед итерацией в тике — агенты гибнут mid-tick.

### Хукнуть/изменить боевой урон
Harmony Prefix на `Mission.RegisterBlow(Agent attacker, Agent victim, GameEntity realHitEntity, ref Blow b, ref AttackCollisionData collisionData, in MissionWeapon, ref CombatLogData)`. Менять `b.InflictedDamage/BaseMagnitude/AbsorbedByArmor` **+ зеркалить в `collisionData`**.
- BLT: `BLTHeroPowersMissionBehavior.cs` RegisterBlow Prefix. Ours: `DamageHookPatch.cs:61`.
- ⚠ Harmony биндит args по имени — `attacker/victim/b/collisionData` должны совпадать. Не зеркалишь `b.*` в `collisionData.*` → движок игнорит правки. Клампить NaN/Inf/negatives.

### Нанести ручной урон / контр-удар
`agent.RegisterBlow(Blow blow, AttackCollisionData cd)`. Blow: `new Blow(victimIndex){ InflictedDamage, DamageType, DamageCalculated=true, BoneIndex=Monster.ThoraxLookDirectionBoneIndex, GlobalPosition, Direction, BlowFlag=BlowFlags.NoSound }`; cd = `default(AttackCollisionData)`.
- BLT: `BLT/Helpers/AgentHelpers.cs` `CreateCollisionDataFromBlow`. Ours: `DamageHookPatch.cs:459` (reflect AoE), `PowersMissionBehavior.cs:169` (DoT).
- ⚠ **Не реентрить RegisterBlow внутри его же Prefix с общим `ref cd`** → коррупт engine state → нативный краш. Откладывать в OnMissionTick со свежим `default` cd + ThreadLocal guard. `BlowFlags.NoSound` спасает от FMOD-handle exhaustion в сустейн-циклах.

### Здоровье / хил / позиция агента
`agent.Health`, `.HealthLimit`, `.BaseHealthLimit` (settable float); `.Position` (Vec3), `.LookDirection`, `.IsActive()`, `.IsHuman`.
- BLT: `BLTSummonBehavior.cs` скейлит свите `BaseHealthLimit/HealthLimit/Health`. Ours: `SummonHeroHandler.cs:415` хил до HealthLimit; lifesteal `DamageHookPatch.cs:239`.
- ⚠ Мутация `BaseHealthLimit` **после** спавна крашила нативно на 1.3.15 (`SummonHeroHandler.cs:618` — отключено). Ставить при/во время спавна.

### Снять агента / детект исчерпанной стороны
`Agent.AgentState` (`Active/Routed/Unconscious/Killed/Deleted`); kill→survive: в OnAgentRemoved Prefix выставить `agentState = AgentState.Unconscious`. Reinforcement-гейт: Postfix `MissionAgentSpawnLogic.IsSideDepleted(BattleSideEnum, ref bool __result)`.
- BLT: anti-permadeath (`BLT_RC22_REFERENCE.md:695`). Ours: `Ours/Patches/SiegeRetreatFix.cs`, `IsSideDepletedPatch.cs`, `AdoptedHeroDeathPatch.cs`.
- ⚠ `BattleSideEnum`(Attacker/Defender) ≠ player/enemy; маппить через `team.Side`. `Unconscious` ≠ `Killed` для kill-credit.

---

## 2. Кампания, Герой и Общество (`TaleWorlds.CampaignSystem`)

### Доступ к Hero и CharacterObject
`Hero.CharacterObject` ↔ `CharacterObject.HeroObject`/`.IsHero`; `Hero.MainHero`, `Hero.AllAliveHeroes`, `hero.Clan/IsAlive/IsFemale/Age/HitPoints`.
- BLT: lookup по chat-имени `Hero.AllAliveHeroes.FirstOrDefault(...)`. Ours: `Ours/Actions/HeroLookup.cs` `FindByUsername` (префикс `[BLink] name`); `Behaviors/HeroIdentityBehavior.cs` (StringId→username).
- ⚠ `Hero.Name.ToString()` — локализованный текст, снять `{=key}`. **Наши герои — бесклановые wanderer'ы**, `hero.Clan` часто null.

### Выдать/снять Hero.Gold
`GiveGoldAction.ApplyBetweenCharacters(Hero giver, Hero receiver, int amount, bool disableNotification=false)`. null на стороне = mint (giver=null) / burn (receiver=null). Прямо: `hero.Gold`.
- BLT: своя viewer-валюта `ChangeHeroGold`, не `Hero.Gold`. Ours: `GiveGoldHandler.cs:65` (mint); сток `GiveGoldAction.ApplyBetweenCharacters(hero, null, cost, true)`.
- ⚠ 💰 `Hero.Gold` (динары) ≠ 💎 backend-крустики. Не путать.

### Скиллы — set/добавить XP
`hero.HeroDeveloper.SetInitialSkillLevel(SkillObject,int)` (hard set), `.AddSkillXp(SkillObject, float, bool isAffectedByFocusFactor=true)`, `.DevelopCharacterStats()` (применить сейчас). Read: `hero.GetSkillValue(skill)`; список `DefaultSkills.*`.
- BLT: `AddSkillXp` → сразу `DevelopCharacterStats()`. Ours: `AddSkillXpHandler.cs:224` (XP + clamp soft-cap), `SetClassHandler.cs:344` (per-class).
- ⚠ XP режется focus-фактором, если не `isAffectedByFocusFactor:false`; 0 фокуса → ~0 прироста. Wanderer ОБЯЗАН иметь ≥1 скилл (иначе edge-кейсы).

### Атрибуты и фокус
`hero.HeroDeveloper.AddAttribute(CharacterAttribute, int, bool checkUnspentPoints=false)`, `.AddFocus(SkillObject, int, bool=false)`. Read: `hero.GetAttributeValue(attr)` (cap 10), focus cap 5.
- BLT: пасс `checkUnspentPoints:false` чтобы обойти экономику очков. Ours: `AddAttributeHandler.cs:135`, `AddFocusHandler.cs:149`.
- ⚠ Клампить `amount = Min(amt, 10-current)` ПЕРЕД AddAttribute — over-cap может нативно крашнуть.

### CampaignBehaviorBase — события и персист
subclass `CampaignBehaviorBase` → override `RegisterEvents()` + `SyncData(IDataStore)`. События: `CampaignEvents.{DailyTickHeroEvent,HeroKilledEvent,HourlyTickEvent,OnSessionLaunchedEvent}.AddNonSerializedListener(this, handler)`. Регистрация: `CampaignGameStarter.AddBehavior` в `OnGameStart`.
- BLT: `BLT/Behaviors/BLTHeirBehavior.cs`; персист dict через `SyncDataAsJson`. Ours: `Ours/Behaviors/MainCampaignBehavior.cs` (SyncData stateless — мы храним на backend).
- ⚠ `HeroKilledEvent(victim, killer, KillCharacterActionDetail detail, bool show)`. Hero нельзя реконструировать из JSON — Hero-рефы только через engine `SyncData`.

### Брак и супруг
`hero.Spouse` (set на ОБЕИХ сторонах), `hero.ExSpouses`. Есть `MarriageAction`, но BLT/мы его **обходим**.
- BLT: `BLT/Actions/FamilyManagement.cs` — `h1.Spouse=h2; h2.Spouse=h1; h1.Clan=h2.Clan; UpdateHomeSettlement()`. НЕ MarriageAction. Ours: `MarryHandler.cs:152` (`hero.Spouse=npc`), divorce `=null`.
- ⚠ Ставить супруга на обоих + согласовать кланы/партию, иначе десинк world state.

### Дети и беременность — ⚠ КРАШ бесклановых
`MakePregnantAction.Apply(Hero mother)` (только female). Дети появятся в `hero.Children` через ~36 дней (ванильный `PregnancyCampaignBehavior`). Ванила: `DefaultPregnancyModel.GetDailyChanceOfPregnancyForHero(Hero)`.
- BLT: `FamilyManagement.cs` — female→`Apply(hero)` else `Apply(hero.Spouse)`; лимит 3. Ours: `MakeBabyHandler.cs:93` (лимит 5 alive).
- ⚠ **CRITICAL:** замужний **бесклановый** female-герой крашит ванильный daily-tick — `GetDailyChanceOfPregnancyForHero` дерефит `hero.Clan` без null-гарда → NRE → процесс умирает. Наши вьюхи бесклановые by design, но женятся. Фикс: `Ours/Patches/PregnancyModelPatch.cs` — Prefix → `chance=0` (skip original) при `hero==null||hero.Clan==null` + Finalizer глотает прочий NRE. (Плюс фронт+backend гейтят брак за clan.)

### Создание/членство клана
`Clan.CreateClan(stringId)` → `.ChangeClanName`, `.Culture`, `.Banner=Banner.CreateRandomBanner()`, `.AddRenown`, `.SetInitialHomeSettlement`, `.SetLeader(hero)` → `CampaignEventDispatcher.Instance.OnClanCreated(clan,false)`. Join = `hero.Clan = clan`. Лидер: `ChangeClanLeaderAction.ApplyWith[out]SelectedNewLeader`. Occupation: `hero.SetNewOccupation(Occupation.Lord/Wanderer)`.
- BLT: `BLT/Actions/ClanManagement.cs` (full create; leave → Wanderer + `Clan=null`). Ours: `CreateClanHandler.cs:120`, `LeaveClanHandler.cs:101`.
- ⚠ Новому клану нужен home settlement, иначе позже throw. Лидера ставить ДО `OnClanCreated`.

### Королевство и политики
join `ChangeKingdomAction.ApplyByJoinToKingdom(clan, kingdom)`, merc `ApplyByJoinFactionAsMercenary`, leave `ApplyByLeaveKingdom(clan, byOwnDecision)`. Политики: `kingdom.AddPolicy(PolicyObject)` / `RemovePolicy`. Read: `clan.Kingdom`, `kingdom.RulingClan/Fiefs/IsAtWarWith`.
- BLT: `BLT/Actions/KingdomManagement.cs` (оборачивает move в static-флаг try/finally чтобы обойти свои же защитные патчи). Ours: `JoinKingdomHandler.cs:101`, `LeaveKingdomHandler.cs:63`, `KingdomTaxBehavior.cs`.
- ⚠ После join без фиефов: `ConsiderAndUpdateHomeSettlement()` + per-hero `UpdateHomeSettlement()`, иначе home null.

### MobileParty (отряд на карте)
`MobilePartyHelper.SpawnLordParty(hero, Vec2 pos, float radius)` или `CreateNewClanMobileParty(hero, clan)`; затем `party.MemberRoster.AddToCounts(CharacterObject, n)`. Лимит: `clan.WarPartyComponents.Count < clan.CommanderLimit`.
- BLT: `ClanManagement.cs` / `BLT/Actions/PartyManagement.cs` (`SpawnLordParty` у `settlement.GatePosition`). Ours: `CreatePartyHandler.cs:166` (+ retinue add + `BootstrapPartyLoot`).
- ⚠ Settlement спавна не должен быть null (`SettlementHelper.GetBestSettlementToSpawnAround`). Гардить: герой не в партии / не в player-клане.

### Поселения / фиефы
`Settlement.All`, `s.IsTown/IsCastle/IsVillage/IsHideout`, `s.GatePosition`, `s.Village.VillageType.Productions`; `clan.Fiefs`, `town.Prosperity/Loyalty`. Owner: `ChangeOwnerOfSettlementAction.ApplyByDefault`. Governor: `ChangeGovernorAction.Apply(town, hero)`.
- BLT: `ClanManagement` HandleFiefs / HandleGovern. Ours: `FiefTributeSyncBehavior.cs`, `WorkshopProfitSyncBehavior.cs`, `MainCampaignBehavior.PushSettlementsCatalog`.
- ⚠ Свободный ввод имён поселений → промахи lookup; пушим живой каталог на фронт (dropdown).

### CampaignTime
`CampaignTime.Now`, `.Days(n)/.Hours(n)`, `CampaignTime.HoursInDay`; `(date - Now).ToDays`, `time.ElapsedDaysUntilNow`.
- BLT: party-loot range `2f * Campaign.Current.EstimatedAverageLordPartySpeed * CampaignTime.HoursInDay`. Ours: тот же идиом в `CreatePartyHandler.BootstrapPartyLoot`; prisoner-days `CaptivityStartTime.ElapsedDaysUntilNow`.
- ⚠ `CampaignTime` — struct (ticks), не сравнивать с реальным `DateTime`.

### Смерть, наследник, преемственность
`KillCharacterAction.ApplyByXxx(..., KillCharacterActionDetail)`. Наследник авто: `CampaignEvents.HeroComesOfAgeEvent` (age 18). Resolve по id: `MBObjectManager.Instance.GetObject<Hero>(stringId)`.
- BLT: `BLT/Behaviors/BLTHeirBehavior.cs` (авто-регистрация первого взрослого ребёнка; death-prevention → Unconscious). Ours: `MainCampaignBehavior.OnHeroComesOfAge`, `ActivateHeirHandler.cs` (rename heir→`[BLink] user`, re-claim workshops `ChangeOwnerOfWorkshopAction` + caravans `CaravanPartyComponent.TransferCaravanOwnership`), `Patches/AdoptedHeroDeathPatch.cs`.
- ⚠ Наследник может быть GC'нут/мёртв до активации — null-чек `GetObject<Hero>` + fallback-событие. `Hero.StringId` стабилен через `SetName` → ключи identity-словаря переживают rename.

---

## 3. Предметы и Экипировка (`TaleWorlds.Core` / `ObjectSystem`)

### Типы предметов
`ItemObject.ItemTypeEnum`: `OneHandedWeapon, TwoHandedWeapon, Polearm, Bow, Crossbow, Arrows, Bolts, Thrown, Shield, Horse, HorseHarness, HeadArmor, BodyArmor, LegArmor, HandArmor, Cape, Banner, Invalid`. Read: `item.ItemType`.
- ⚠ `ChestArmor` существует, но **ванилой не используется** — items не найдутся; для торса брать `BodyArmor`.

### Перечислить / отфильтровать предметы
`MBObjectManager.Instance.GetObjectTypeList<ItemObject>()` → все загруженные items. Фильтр: `!item.NotMerchandise`, `item.ItemType==…`, `item.Culture`.
- BLT: `BLT/Actions/EquipHero.cs` `FindRandomTieredEquipment` (LINQ); `CanUseItem` гейтит по skill≥Difficulty + gender-флагам. Ours: `UpgradeGearHandler.FindTieredItem` / `SetClassHandler.FindTieredItem` (`.Where(!NotMerchandise)`).
- ⚠ Возвращает и non-merchandise/template-мусор — всегда фильтровать. Турнирные mounts — NotMerchandise → BLT для коней пасует `AllowNonMerchandise`.

### Слот экипировки — read/set
`hero.BattleEquipment[EquipmentIndex]` (get/set `EquipmentElement`). `EquipmentIndex`: `Weapon0..3, Head, Body, Leg, Gloves, Cape, Horse, HorseHarness`. Очистка: `= EquipmentElement.Invalid`.
- BLT: `EquipHero.cs` `[index] = new EquipmentElement(item)`. Ours: `UpgradeGearHandler.ApplyGearLoadout` (+ снимает коня пешим: `Horse = EquipmentElement.Invalid`).
- ⚠ Правки write-through; **только off-mission** (`Mission.Current != null` → движок юзает stale equipment на живом Agent → null-deref). Оба хендлера гардят.
- ⚠ `EquipmentElement` — struct; чекать `.IsEmpty` / `.Item == null`, не `null`.

### Итерация слотов
`Equipment.Yield{Equipment,Weapon,FilledEquipment,FilledArmor}Slots()` → `(EquipmentElement element, EquipmentIndex index)`.
- BLT: `EquipHero.cs` `RemoveAllEquipment` / dedup-seed. Ours: ручной `for(int s=0;s<4;s++)` (без Yield).

### Armor: слот↔тип
5 пар: Head/HeadArmor, Body/BodyArmor, Leg/LegArmor, Gloves/HandArmor, Cape/Cape.
- BLT: `BLT/Helpers/SkillGroup.cs` `ArmorIndexType`. Ours: `UpgradeGearHandler.ArmorSlots`.
- ⚠ Слотов брони 5 — отдельного "arm" нет; arm-броня сидит на Body/Gloves.

### Случайный предмет около тира (nearest-tier)
`(int)item.Tier` (enum `ItemTiers.Tier1..6`, **0-based**), `item.Tierf` (float).
- BLT: `SelectRandomItemNearestTier` — `GroupBy(Tier).OrderBy(100*abs(target-t)+t).SelectRandom()`. Ours: `PickNearestTier` (тот же ключ `100*Math.Abs(engineTier-g.Key)+g.Key`).
- ⚠ **T6 ammo не существует** (ванила ~макс T4) → наивный "exact или random" давал T1-стрелы; nearest-tier берёт T4. Это и был задокументированный фикс.
- ⚠ Off-by-one ВЕЗДЕ: UI показывает 1–6, вся `item.Tier`-математика 0–5. `engineTier = userTier - 1`.

### Сохранить крафт/именное (ItemModifier)
`EquipmentElement.ItemModifier` (null или ItemModifier); `new EquipmentElement(item, modifier)`.
- BLT: keep если `Tier > targetTier` (приз) или registered custom. Ours: `ShouldReplaceSlot` → false если `ItemModifier != null` (крафт/именное) ИЛИ `Tier > engineTier` (приз); пустой слот всегда заполняем.
- ⚠ Modifier'ы персистят через save только если `MBObjectManager.RegisterObject(modifier)`.

### Прочитать модифицированные статы
armor: `element.GetModifiedHeadArmor/BodyArmor/ArmArmor/LegArmor()`; weapon: `w.GetModifiedSwingDamage(...modifier)`; mount: `modifier.ModifyMountSpeed/Charge/HitPoints(base)`.
- BLT: `BLT/Actions/ItemStats.cs`. Ours: не реализовано (нет команды inspect).
- ⚠ Базовый `item.ArmorComponent.HeadArmor` игнорит modifier — для реального значения брать `GetModified*` у EquipmentElement.

### Боевой конь vs вьючное / конь vs верблюд
`item.HasHorseComponent`, `item.HorseComponent.IsMount` (rideable), `.Monster.FamilyType` (int: human=0,horse=1,camel=2,…), `.Speed/.Maneuver/.ChargeDamage`.
- BLT: фильтр `HorseComponent?.IsMount==true && Monster.FamilyType == (int)horse|camel`; барду матчит `horseType == ArmorComponent?.FamilyType`. Ours: **только строковая эвристика** `StringId.Contains("camel")` (фрагильно).
- ⚠ **Наш фильтр хуже BLT** (см. §7 Gaps): мулы (`!IsMount`/`IsPackAnimal`) у нас НЕ исключаются → пеший с маунт-классом может получить мула; барда не матчится по семье → верблюд может получить конскую барду.

### Дедуп оружия по слотам
`item.StringId`; пара ammo `ItemObject.GetAmmoTypeForItemType(item.Type)`.
- BLT: HashSet `currentlyEquippedItemIds`, no-dup → lower-tier → allow-dup fallback; авто 2× ammo для ranged. Ours: `usedWeaponIds` HashSet + `FindTieredItem` excludeIds первым проходом, full-pool fallback.
- ⚠ Дубль как last-resort — намеренно (berserk=2×2H, assassin=2×1H); не хард-фейлить на пустом deduped-пуле.

### Полный flow upgrade/equip
- BLT: `EquipHero.UpgradeEquipment(hero, targetTier, classDef, replaceSameTier)` — **вайпает все слоты**, заполняет оружие+2×ammo+щит+всю броню+коня+барду+civilian; `targetTier = GetEquipmentTier + (Reequip?0:1)`. Ours: `ApplyGearLoadout(hero, classKey, engineTier)` (общий upgrade+reequip) → `GiveGoldAction(...,cost)` → `HeroStateSync.Push` + `EquipmentSync.PushAll`.
- ⚠ Разница: BLT вайпает-потом-заполняет (теряет worn не-modifier гир); мы редактируем in-place через `ShouldReplaceSlot` (сохраняем worn higher-tier/modifier, не реролля их).

---

## 4. Harmony-патчинг и crash-protection

### Пропустить оригинал
`[HarmonyPrefix] static bool Prefix(... ref T __result)` → `return false` скип, `true` выполнить. Set `__result` до `return false`.
- BLT: `BLT/Behaviors/HarmonyPatches.cs` (`...Prefix(ref int __result)`). Ours: `PregnancyModelPatch.cs` (clanless → `__result=0f; return false`).
- ⚠ void-prefix не может скипнуть; нужен `bool` return.

### Прочитать/изменить результат
`[HarmonyPostfix] static void Postfix(ref T __result)`.
- BLT: `HarmonyPatches.cs` (iterate `____markers`). Ours: `IsSideDepletedPatch.cs` (флипает `ref bool __result`), `TournamentParticipantsPatch.cs` (refill `ref List`).
- ⚠ Early-out до скана агентов — postfix на каждый вызов (hot path).

### Defensive finalizer (глотать КОНКРЕТНОЕ исключение)
`[HarmonyFinalizer] static Exception Finalizer(Exception __exception, ...)` → `return null` глотает, `return __exception` ре-кидает.
- BLT: `HarmonyPatches.cs` (finalizer возвращает null безусловно). Ours: `BannerCampaignBehaviorPatch.cs` (глотает ТОЛЬКО `InvalidCastException` на DailyTickHero), `PregnancyModelPatch.cs` (ТОЛЬКО `NullReferenceException`).
- ⚠ **MUST `return __exception` для не-целевых типов** — глотать всё = прятать реальные баги. Finalizer бежит даже когда оригинал кинул.

### Prefix-dodge + finalizer-catch (belt-and-suspenders)
- Ours: `PregnancyModelPatch.cs` — prefix ловит `hero.Clan==null`, finalizer ловит глубже (`hero.Spouse.Clan==null`).

### Менять ref-struct аргументы
`static void Prefix(Agent attacker, ref Blow b, ref AttackCollisionData collisionData)` — **имена параметров обязаны совпадать** (Harmony биндит по имени).
- Ours: `DamageHookPatch.cs` (мутирует `b`/`collisionData`, зеркалит каждую запись).
- ⚠ Дрейф имени параметра на ренейме TaleWorlds → тихий `default(Blow)`. Мод логирует "processed N blows" для детекта сломанного биндинга.

### Version-safe резолв цели (TargetMethods yield)
`static IEnumerable<MethodBase> TargetMethods()` на `[HarmonyPatch]`-классе; `yield return method` или `yield break` (skip).
- Ours: все reflection-патчи (`BannerCampaignBehaviorPatch`, `PregnancyModelPatch`, `IsSideDepletedPatch`, `CleavePatch`) — `yield break` на null type/method + лог.
- ⚠ `return null` из `TargetMethod()` (singular) бубблит HarmonyException через PatchAll; `yield break` из `TargetMethods()` (plural) скипает чисто. **Юзать plural.**

### Reflection-резолв
`AccessTools.TypeByName(fqn)`, `AccessTools.Method(type,name,Type[])`, `AccessTools.Field`, `AccessTools.PropertyGetter`.
- BLT: `AccessTools.Field(typeof(Mission),"_missilesDictionary")`. Ours: `PregnancyModelPatch.SafeResolveType` (try/catch → null).
- ⚠ **Резолвить в static-поле, НЕ inline в `[HarmonyPatch]`-атрибуте** — кидающий static cctor JIT-убивает весь DLL до `OnSubModuleLoad` (лог пустой, юзер видит native 0xC0000005).

### Приватные поля/инстанс/args
`___fieldName` (triple-underscore + ведущий `_` поля → `____playerKingdom` для `_playerKingdom`), `__instance`, `__args[]`.
- BLT: `Prefix(ref bool __result, Kingdom ____playerKingdom)`. Ours: `TournamentParticipantsPatch.Postfix(TournamentBehavior __instance)`.

### Resilient PatchAll + kill-switch
`harmony.CreateClassProcessor(type).Patch()` per `[HarmonyPatch]`-тип (вместо одного `PatchAll()`).
- BLT: просто `harmony.PatchAll()`. Ours: `BannerlordLinkModule.cs` — итерит `asm.GetTypes()`, скип через `SKIP_PATCH_NAMES` HashSet, патчит каждый в try/catch, считает ok/failed/skipped.
- ⚠ Ванильный `PatchAll` **аборт ВСЕХ оставшихся патчей** если у одного TargetMethod кинул → один сломанный патч молча отключал всё (баг, ради которого это сделано).
- ⚠ `CreateClassProcessor` чтит `Prepare()==false` и считает это успешным no-op (не failure) — хорошо для нашего ok/failed-тэлли. Но `Prepare()=>false` всё равно `ok++`, так что count неоднозначен для диагностики «отключён ли патч»; только `skipped` (через SKIP_NAMES) инкрементит skipped-счётчик.

### Транспайлер
`[HarmonyTranspiler]` + `CodeMatcher` — **не используется** ни BLT, ни нами; оба на prefix/postfix/finalizer.

---

## 5. Crash hall-of-fame (повторяющиеся грабли)

| Краш | Причина | Защита |
|---|---|---|
| **Pregnancy NPE** на daily-tick | замужний бесклановый герой → `GetDailyChanceOfPregnancyForHero` дерефит null `Clan` | `PregnancyModelPatch.cs` prefix+finalizer; гейт брака за clan (front+back) |
| **InvalidCast** на daily-tick | ванильный `BannerCampaignBehavior.DailyTickHero` на edge-кейс героях | `BannerCampaignBehaviorPatch.cs` finalizer (только InvalidCast) |
| **Native 0xC0000005, лог пустой** | throwing static cctor в `[HarmonyPatch]`-классе убивает DLL до load | резолв типов в `SafeResolveType` (try/catch), не inline |
| **"Nullable must have a value"** на SpawnTroop | турнир/арена-миссия без reinforcement zone | детект "Tournament" в `Mission.MissionBehaviors`, форс-dismount/skip |
| **Native crash** в RegisterBlow | реентри RegisterBlow в своём Prefix с общим `ref cd` | откладывать в OnMissionTick, свежий `default` cd, ThreadLocal guard |
| **Native crash** | мутация `BaseHealthLimit` после спавна (1.3.15) | ставить только при спавне |
| **Off-by-one** гир | `item.Tier` 0-based, UI 1-based | `engineTier = userTier - 1` |
| **PatchAll отрубил всё** | один сломанный TargetMethod аборт всего PatchAll | resilient per-type CreateClassProcessor + SKIP_PATCH_NAMES |
| stale equipment / null-deref | правка `BattleEquipment` во время Mission | гейт `Mission.Current != null` |
| **DetachUnit crash** | агент с `FormationFileIndex == -1` | гардить индексы ≥0 |
| detach «behavior null» в hideout | static `Instance` обнулён `OnEndMission`'ом наложенной миссии | резолв `Mission.Current.GetMissionBehavior<T>()` + гард `ReferenceEquals(_instance,this)` (§8) |
| соло-команда не двигает агента | `DisableScriptedMovement`+`SetTargetFormationIndex` → под стоящей формацией | вести через `SetScriptedPosition`(цель)+re-issue; игрока (`Controller==Player`) не скриптить (§8) |
| shield_break «не работает» | `ChangeWeaponHitPoints(0)` ломает щит лишь в ударе | инстант — `agent.DropItem(shieldSlot)` (§8) |
| город/замок не дают трибьют | diff `Town.Gold` (казна ≠ доход, ≤0) | `SettlementTaxModel.CalculateTownTax` / `ClanFinanceModel.CalculateVillageIncome` (§8) |
| stale game-state на новом сейве | инкрементальный UPSERT-only sync копит данные | reconcile-on-connect (`heroes_snapshot`→DELETE по owner) + save-switch wipe по `UniqueGameId` (§8) |

---

## 6. Файловый индекс (BLT ↔ наш по теме)

| Тема | BLT (`reference/BLT_RC22/.../BLTAdoptAHero/`) | Наш (`BannerlordLink/src/`) |
|---|---|---|
| Спавн в миссию | `Behaviors/BLTSummonBehavior.cs`, `Actions/SummonHero.cs` | `Actions/SummonHeroHandler.cs` |
| Powers/combat-хуки | `Behaviors/BLTHeroPowersMissionBehavior.cs`, `Helpers/AgentHelpers.cs` | `Patches/DamageHookPatch.cs`, `Behaviors/PowersMissionBehavior.cs` |
| Detachment | `Behaviors/BLTHeroDetachmentBehavior.cs` | `Actions/DetachmentHandlers.cs`, `Behaviors/HeroDetachmentBehavior.cs` |
| Экипировка/тиры | `Actions/EquipHero.cs`, `Actions/ItemStats.cs`, `Helpers/SkillGroup.cs` | `Actions/UpgradeGearHandler.cs`, `Actions/SetClassHandler.cs` |
| Семья/брак/дети | `Actions/FamilyManagement.cs`, `Behaviors/BLTHeirBehavior.cs` | `Actions/MarryHandler.cs`, `MakeBabyHandler.cs`, `ActivateHeirHandler.cs` |
| Клан/королевство | `Actions/ClanManagement.cs`, `Actions/KingdomManagement.cs` | `Actions/CreateClanHandler.cs`, `Join/LeaveKingdomHandler.cs` |
| Отряд на карте | `Actions/PartyManagement.cs` | `Actions/CreatePartyHandler.cs` |
| Скиллы/атрибуты/фокус | `Actions/SkillXP.cs`, `AttributePoints.cs`, `FocusPoints.cs` | `Actions/AddSkillXpHandler.cs`, `AddAttributeHandler.cs`, `AddFocusHandler.cs` |
| Harmony-патчи | `Behaviors/HarmonyPatches.cs` | `BannerlordLinkModule.cs` (PatchAll), `Patches/*.cs` |
| Crash-protection | death-prevention в `HarmonyPatches.cs` | `Patches/{PregnancyModelPatch,BannerCampaignBehaviorPatch,AdoptedHeroDeathPatch}.cs` |

---

## 7. Расхождения с BLT (бэклог улучшений)

1. ✅ **Фильтр маунта — исправлено 2026-05-31** (Finding A). `FindTieredItem` в обоих
   хендлерах теперь отсекает мулов/вьючных: `HorseComponent.IsRideable && !IsPackAnimal`
   (с fallback). Камель/конь пока по имени (`StringId.Contains("camel")`) — версионно-
   устойчиво для ванилы; полный BLT-вариант (`Monster.FamilyType` + барда по
   `ArmorComponent.FamilyType`) — опциональный дальнейший рефайн.
2. ✅ **Гендер-гейт — добавлен 2026-05-31** (BLT `CanUseItem` gender-часть): `GearGenderOk`
   режет `ItemFlags.NotUsableByFemale/Male` под пол героя (с fallback). **Skill-гейт
   намеренно НЕ делаем** — у свежего героя skill < Difficulty высокотировой шмотки →
   отфильтровал бы нужный класс-гир (skill бустится классом отдельно).
3. **Нет item-inspection** (модифицированные статы через `GetModified*`) — у BLT есть в
   `ItemStats.cs`. Это отдельная фича (команда/UI), не «улучшение существующего».

---

## 8. Сессия 2026-06-01 — добытые API + готчи (live-debug)

Накоплено при починке боевых команд, дохода фьефов и stale-данных. Сверено с
движком/BLT **в бою** (live-лог), не теоретически.

### Резолв MissionBehavior — `GetMissionBehavior<T>()` > статик-синглтон
`Mission.Current?.GetMissionBehavior<T>()` → behavior текущей миссии.
- Ours: `HeroDetachmentBehavior.Instance` резолвит через `Mission.Current.GetMissionBehavior` (static-поле как fallback).
- ⚠ **Готча (реальный баг):** static `Instance` (set в `OnBehaviorInitialize`, null в `OnEndMission`) **затирается `OnEndMission`'ом ВЛОЖЕННОЙ/наложенной миссии** — особенно **hideout** (Stealth + sub-миссии): новая init'ит (Instance=B), старая end'ит (Instance=null) пока B жив → команды видят `null` («behavior null»). Фикс: резолв из `Mission.Current` + гард `if (ReferenceEquals(_instance, this)) _instance = null` в OnEndMission.

### Скриптинг ОДИНОЧНОГО агента (соло-команды в бою)
`agent.SetScriptedPosition(ref WorldPosition pos, false, Agent.AIScriptedFrameFlags.NeverSlowDown)` — вести агента в точку (перебивает формацию для ЭТОГО агента); `agent.SetAutomaticTargetSelection(true)` — авто-атака в упор; `agent.DisableScriptedMovement()`/`DisableScriptedCombatMovement()` — вернуть AI-контроль.
- Ours: `HeroDetachmentBehavior` — Hold = SetScriptedPosition(текущая поз); Charge = SetScriptedPosition(ближайший враг) + re-issue 0.5с; Attach = DisableScriptedMovement.
- ⚠ **`SetTargetFormationIndex` сам по себе НЕ двигает агента** (был баг charge: `DisableScriptedMovement`+`SetTargetFormationIndex` → агент возвращался под СТОЯЩУЮ формацию и стоял). Двигает именно `SetScriptedPosition`.
- ⚠ Игрока скриптить нельзя: `agent.Controller == Agent.ControllerType.Player` / `agent == Agent.Main` → ручное управление перебивает скрипт. Детектить и пропускать.

### Выбить оружие/щит — `DropItem`
`agent.DropItem(EquipmentIndex)` — роняет предмет слота (надёжно, любой слот). Детект щита: `weapon.Item.ItemType == ItemObject.ItemTypeEnum.Shield`.
- BLT: `Helpers/AgentHelpers.cs` / BLTBuffet `CharacterEffect` `agent.DropItem(index)` для disarm. Ours: `ActivatePowerHandler` disarm_burst + shield_break.
- ⚠ **`agent.ChangeWeaponHitPoints(idx, 0)` ломает щит ТОЛЬКО во время удара** (BLT ставит вместе с `collisionData.IsShieldBroken=true` в хите). Инстант-AoE без удара → HP=0, но щит НЕ пропадает = «не работает». Мгновенно — `DropItem`.
- ⚠ `weapon.CurrentUsageItem` может быть `null` у несвыбранного щита → детект по `WeaponClass` промахивается; брать `Item.ItemType`.

### Доход владельца фьефа (НЕ `Town.Gold`!)
город/замок: `Campaign.Current.Models.SettlementTaxModel.CalculateTownTax(town, false).ResultNumber`; деревня: `Campaign.Current.Models.ClanFinanceModel.CalculateVillageIncome(clan, village, false)`.
- BLT: `Actions/ClanManagement.cs:826` / `CampaignInfo.cs:414` (та же связка для дохода клана). Ours: `FiefTributeSyncBehavior` — дневной доход напрямую, без diff/снапшота.
- ⚠ **`Town.Gold` = казна ГОРОДА, не доход владельца** и скачет ≤0. diff Town.Gold → города/замки НИКОГДА не давали трибьют (были невидимы в «Моих владениях»). `Village.Hearth` — прокси роста, тоже не доход.

### Anti-stale game-state — reconcile-on-connect
Мод = источник правды; backend-кэш валиден пока мод онлайн (`_last_seen` обновляется на любой event + STALE_THRESHOLD → онлайн-бейдж).
- Ours: `MainCampaignBehavior.PushSessionStart` шлёт `heroes_snapshot` (живые `[BLink]` usernames сейва) на `OnGameLoadFinished`+`OnSessionLaunched`; backend `_on_heroes_snapshot` DELETE'ит rows для usernames НЕ в снапшоте (heroes+skills+attrs+equip+class по `username`; fiefs+workshops+caravans по `owner_username`). Save-switch (`Campaign.Current.UniqueGameId` ≠ записанного) → wipe всего game-state.
- ⚠ **Инкрементальный sync (UPSERT-only) копит stale между сейвами** — на новом сейве висели старые fiefs/workshops/caravans. Лечится reconcile'ом по владельцу (мод говорит «кто существует» → backend удаляет остальных), НЕ накоплением.

---

*Собрано 2026-05-31 из `reference/BLT_RC22/` (262 .cs) + `docs/BLT_RC22_REFERENCE.md` (88 КБ) + `BannerlordLink/src/`. Глубже — в `BLT_RC22_REFERENCE.md` (по файлам). Дополнено 2026-06-01 (§8 — live-debug: detach / доход фьефов / anti-stale).*
