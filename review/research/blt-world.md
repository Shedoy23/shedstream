# BLT world / dynasty / companions: comparison evidence

Сопоставление с `shedlink-world.md`. Пины: billw `f989f5602f648c9c24f1d95a9364fa7a11676e31`; RC22 `83b264f85774489c84c5682c73df3ef92915f39e`; Mesmer `dee0d1735f44b336a77986025ec1f863ea05e26f`; MBGA `5197130e8a1755b452755194b50e65e75998cf98`. RC22/billw prefix `BannerlordTwitch/BLTAdoptAHero/`; Mesmer prefix `BLTAdoptAHero/`. Ссылки пинованы; source review не означает live gameplay proof. Лицензии сводит главный отчёт; для выводов здесь рекомендуем независимую реализацию идеи и чтение API, не перенос кода.

## Сводка

| BLT | ShedLink | Класс / реальная разница | Ценность / сложность |
|---|---|---|---|
| ManageFief native projects/daily/budget | Fief ownership + tribute readout | B: управление реальным строительством, без нового дерева искусственных бонусов | высокая / средняя |
| Fief/Kingdom upgrade scopes | Clan upgrade tree + prerequisites/bulk/native model bonuses | B: несколько prerequisite IDs, kingdom/fief scope, influence cost, liege→vassal effects | высокая / высокая |
| Capital | Kingdom/fiefs/rebellion | C: столица, transfer delay/cooldown, потеря территории, capital-only upgrade | средняя / высокая |
| Explicit heir | Auto oldest eligible child + stash/property succession | B: назначить наследника заранее, sibling/spouse eligibility | высокая / средняя |
| Family command | Family tree + child management + viewer proposals | A; ShedLink UI удобнее, но BLT имеет grandchildren traversal | не дублировать |
| MBGA historical wanderers | Vassals/heirs/retinue, не companion roster | C, HISTORICAL: real extra Heroes, own gear/kills/battles/tier/power | высокая / высокая |
| Companion party roles | No viewer assignment | C hypothesis from native API, НЕ подтверждённая BLT full system |
| Self-govern | Existing governor-removal housekeeping only | B: viewer hero can become governor | средняя / средняя |
| Treaty/NAP/alliance/offers | War/peace/policy voting, taxes/ransom, rebellion | B: договоры с expiry и согласованием / союзники | высокая / очень высокая |
| Army roster controls | Create/disband + sticky orders/cohesion | B: call/join/kick/reassign/leave, not 'add army' | средняя / высокая |
| Training fund | One-off retinue bulk upgrade, party recruit route | B: persistent daily actual-party roster training budget/maxTier | высокая / средняя-высокая |
| Reborn / Rejuvenate | Actual death→heir→dynasty | E by default: full reborn/age reset reduces meaning of dynastic loop | низкая without product choice |

## 1. Native fief construction — наиболее конкретный небольшой gap

[RC22 ManageFief](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Actions/ManageFief.cs#L38), [Mesmer counterpart](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/Actions/ManageFief.cs#L38): checks clan leader/no mission/fiefs; `FiefInfo:100` reads Town.Buildings, BuildingsInProgress, wall, governor, construction and BoostBuildingProcess. `Project:151-222` chooses actual town Buildings and calls `BuildingHelper.ChangeCurrentBuildingQueue`, `ChangeDefaultBuilding`. `ChangeGold:258-284` adjusts real construction budget and Hero.Gold delta. Governor stub in ManageFief is empty — don't present that stub as implemented. Separate PartyManagement govern exists below.

ShedLink `FiefTributeSyncBehavior` + `bannerlord_fiefs.py` + frontend1493 expose owner/tax history, not building projects. Useful extension: see native available projects and order queue, fund construction. Game supplies ID/name/progress/availability; backend just delivery and identity. Native save already stores Buildings and boost; own migration optional for cached snapshot, not native building persistence. FE generic progress/entity/actions; BE action registration, cached state; moderate save risk when using native helpers, no new custom class save definitions. Current local engine decomp confirms public methods at `TaleWorlds.CampaignSystem.decompiled.cs:5722,5737`; **BoostBuildingProcessWithGold:5812 hardcodes Hero.MainHero** so don't invoke it blindly for viewer — validate viewer Gold and target budget together in game. BLT's fuzzy names are not desirable; use stable IDs.

## 2. Upgrade depth beyond existing clan tree

[UpgradeDefinitions:60-81](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/Actions/UpgradeDefinitions.cs#L60) supports comma-separated multiple prerequisites (all), coastal/capital gates, removable flag; FiefUpgrade152–285, ClanUpgrade327–597, KingdomUpgrade674+. [UpgradeAction501–557](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/Actions/UpgradeAction.cs#L501) builds prerequisite chains. Kingdom purchase1008–1075 requires ruler, gold+influence, persists each bought chain node, reports partial chain stop. RC22 has equivalent RequiredUpgradeIDs70 and fief/clan/kingdom catalog system, not unique Mesmer invention.

[UpgradeBehavior15–62](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/Behaviors/UpgradeBehavior.cs#L15) stores per-settlement/clan/kingdom purchased IDs + fractional troop accumulation via SyncData. Actual effects are not just schema: `:497-524` own versus liege ApplyToVassals, `:670+` adds capital effects. `BLTSettlementUpgradeBehavior.cs:25-123` DailyTickSettlement mutates prosperity/loyalty/security/food/militia, native max checks, tax gold and village hearth. `Models/BLTUpgradeModels.cs` integrates party/model bonuses. Daily troop/garrison spawns are a strong economic policy change and shouldn't be silently imported.

ShedLink already has own/locked tree, prerequisite, bulk purchase, daily renown/influence, wrapped PartySize/Speed/ClanTierModel, save restore. Delta is additional scopes, multiple dependencies and meaningful regional/collective effects, not basic tree. Suggested architecture: owned_entity or organization capability with game-defined upgrade catalog and game-side eligibility/payment. Backend stores correlation/history; migration likely for game snapshot keyed by entity, not duplicate engine simulation. FE generic upgrade tree reusable. Save risk moderate/high depending schema; high complexity. Do after stable catalog/ID/session contracts, not before.

## 3. Capital: new but optional specialization

[CapitalBehavior.cs:39](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/Capital/CapitalBehavior.cs#L39) SyncData dictionaries capital/by-clan, transfer target/previous/end day, cooldown/restoration and capital upgrades. DailyTick54 handles transfer/cooldown/capital loss120; SetCapital205, transfer222; separate capital-only purchases256; getters321+ feed UpgradeBehavior. A capital is consequently a strategic commitment with transfer delay and conquest consequence, not only a badge. ShedLink lacks this owned-property specialization while already having native kingdoms/fiefs. Worth considering only after property capability and deliberate policy for loss; custom game persistence required, BE/FE mirror + actions, medium migration need and higher save-compat burden.

## 4. Named companion: present in history, removed from current MBGA

Do not call current MBGA companion implementation based on retained documentation. [Removal df04587](https://github.com/MesmerTurn/MakeBltGreatAgain/commit/df04587c7c183497a12eb47e4ed0a8c24bfb99c9) says entire Wanderer system removed to reduce scope/naval death crash surface. Current5197130 source has no WandererRecord/BLTWandererBehavior definitions, although comments and old design/plan retain names.

Actual implemented [352bb4c source](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/352bb4c90a59a915c69b7ade34fcb4723500fe85/source/MakeBltGreatAgain.cs#L6460):
- WandererRecord6460–6468: owner name, real HeroStringId, one persistent rolled power, kills, battles, Tier1–8.
- BLTWandererBehavior6501–6590: JSON metadata `BLTWanderersJson` in SyncData; Hero/gear/skills remain native save. Stable Hero resolution, multiple records per owner.
- WandererCommand6795–6946: hire real **new Hero from wanderer template**, NOT hire selected existing tavern NPC; list/fire/name/equip/info/skills. Gear action equips owner's matching custom item directly into BattleEquipment/CivilianEquipment (not a demonstrated ownership-transfer transaction). Weapon slot fallback Weapon0; do not copy this simplistic equipment UX.
- WandererSpawnMissionBehavior6949+: owner-agent→companions spawn mapping; death handling7034/7094 has battle death chance and conditional permanent death; mission-end7156–7175 assigns individual kills/battles and recomputes tier; UpgradeWandererEquipment7331–7355 chooses same ItemType at own tier. WandererTierCalculator7699 and PowerScaling7728 scale powers by own achievement.
- Behavior uses real HeroCreator.CreateSpecialHero, native roster/equipment, mission callbacks and several combat hooks. This is viable API reference, not reliable release guarantee; removal reason deserves explicit note.

**TOR guide gap:** T1–9, earned-only8/9, matching-skill gear guards and noble promotion do NOT match this T1–8 historical implementation. Keep those GUIDE-ONLY until exact source provided. Mesmer commit698eac7 restored duplicate source before a8bc344 removed duplicate; file history does not make it active current module. No demonstration of full Scout/Surgeon/Engineer/Quartermaster role controls here.

Adaptation: related_entities roster of true Heroes, game-owned stats and persistent personal progression, viewer decides tactical/loadout roles; no duplicate Hero simulation in backend. Needs game persistence, entities/action contract, FE entity card+inventory/skills, BE routing/cache, likely mirror migration, high save/missions complexity. A compelling extension to existing retinue and dynasty, but intentionally independent implementation, not resurrection of removed MBGA code.

## 5. Roles: separate native possibility from BLT evidence

[PartyManagement465–493](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Actions/PartyManagement.cs#L465) `HandleGovern` actually assigns **viewer hero himself** to clan fief. Removes previous party/governor, TeleportHeroAction, ChangeGovernorAction.Apply. Mesmer same. ShedLink uses RemoveGovernor while marrying/creating party/leaving clan but has no exposed assignment action in examined registry/UI. This is B property/hero-role depth, not proof BLT supports managing many hired companion roles.

Current native decomp has public `MobileParty.SetPartyScout`, `SetPartyQuartermaster`, `SetPartyEngineer`, `SetPartySurgeon` at101850–101877. Therefore these are technically grounded **independent adaptation hypotheses**; validate occupancy, membership, concurrent party changes, and native model effects before design. Governor/party leader/caravan leader differ in ownership/lifecycle and should not be collapsed into an unchecked generic role setter.

## 6. Heir designation versus actual dynasty

[HeirCommand102–177](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/Actions/HeirCommand.cs#L102) chooses/replaces designated heir from adult clan children/siblings and (named choice) spouse; `BLTHeirBehavior.cs:95-98` ScopedJsonSync HeirData. ShedLink already auto-activates oldest mirror heir and transfers stash/property. Delta: explicit player choice before death and broader eligible family, not adding succession itself. Game should publish eligible choices from native family rules, save chosen StringId, revalidate alive/clan at death; backend must not select based only on stale cache. Existing heir UI/action queue/state snapshot can host it; moderate BE+FE+game work, migration optional if game metadata and mirror field used, moderate save risk.

Reliability caveat: Mesmer HeirCommand sets `heirHero=null` in activation branch then references heirHero.Clan around199–202. This is a source-level null-dereference risk, no runtime reproduction here. Do not describe BLT heir activation as fully proven just because selection is richer.

Original [billw AdoptAHero95–106](https://github.com/billw2012/Bannerlord-Twitch/blob/f989f5602f648c9c24f1d95a9364fa7a11676e31/BannerlordTwitch/BLTAdoptAHero/Actions/AdoptAHero.cs#L95) has fractional inheritance of spent gold and limited custom items, calls InheritCustomItems457/InheritGold477. Mesmer behavior656 sums ancestral spent+current gold;997 transfers custom items. That's abstract BLT economy legacy, distinct from native children/property/stash lineage. Do not replace richer ShedLink dynasty with a percentage rebate merely to claim parity.

FamilyManagement RC/Mesmer already does spouse/children/parents/rename/looks/skills/marry; grandchildren command393 is small additional browsing depth. ShedLink persisted proposal expiry/acceptance and visible tree are already analogous and stronger UI; proposals in Mesmer FamilyManagement591 are runtime dictionary, not by itself durable consent workflow.

## 7. Reborn / rejuvenate are product alternatives, not automatic upgrades

[MBGA Reborn6245–6348](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/5197130e8a1755b452755194b50e65e75998cf98/source/MakeBltGreatAgain.cs#L6245) creates fresh Hero for fallen player, initializes, optionally invokes fork-only CloneHeroData by reflection, rejoins clan and regenerates equipment via reflection. On DLL without CloneHeroData, copying silently skips; success text still says remembering everything. Даже с Mesmer CloneHeroData (`BLTAdoptAHeroCampaignBehavior.cs:673–693`) копируются только BLT ledger/retinues/class/prestige/items/achievement stats: native skills/focus/attributes не перенесены, вопреки комментарию MBGA. Main lesson is avoid reviving a corpse object with invalid native lifecycle, not preserve all progress unconditionally.

[Rejuvenate.cs:59-100](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/Actions/Rejuvenate.cs#L59) advances BirthDay by configured years (never below18), optionally spouse. E for current intended death/heir loop unless user explicitly wants immortality/age control. Native API trivial; game-design cost substantial.

## 8. Diplomacy and army depth

[BLTTreatyData:9-124](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/Diplomacy/BLTTreatyData.cs#L9): truce, NAP, alliance, timed tribute, call-to-war proposal. Factions resolve Kingdom or landed independent Clan by stable ID; tribute remains kingdom-only. `BLTTreatyManager.cs:182-230` saves treaty/proposal lists, not merely chat text. `BLTDiplomacyBehavior.cs:32-40` subscribes MakePeace/WarDeclared/ClanChanged/KingdomDestroyed/DailyTick; `Behaviors/HarmonyPatches.cs:586,595` intercepts MakePeaceAction.ApplyInternal to prevent/reroute vanilla peace. `IndependentsOverhaul/BLTClanDiplomacyBehavior.cs:92-102,233-341,396` adds landless independent clan alliances/acceptance/call-to-war.

ShedLink already war/peace votes, kingdom tax, ransom, policy, rebellion, vassal following. Delta agreements + negotiated alliance/expiry, not basic politics. Very high scope/risk because third-party AI/faction patches and native events interact; keep idea, don't transfer broad peace blocking. Need game-owned treaty state (where custom), FE offers/entity relations, BE authentication/consent delivery; migrations for mirror/history probable. High save and compatibility risk. Base game may evolve its diplomacy APIs: this audit does not certify old fork hooks safe for installed engine.

`PartyManagement.cs:1038-1055` army status/disband/leave/reassign/view/create/takeover/call/join/kick/garrison/release/allowAI/allowBLT/threat/orders; examine each before implementation. ShedLink native CreateArmy/disband + persistent orders/recruit/cohesion already exist. Candidate additions with smaller purpose: explicit join/leave/call invited viewer party and expose current roster, not independent armies at all costs. RC/Mesmer also use older `GetMobilePartiesToCallToArmy` (Mesmer1461), while current ShedLink1.4.8 uses `CanLordCreateArmy(... out candidates)`. This is concrete version drift.

## 9. Training fund

Combat audit found RC22 `TrainingBehavior` save budget/maxTier + DailyTickHero + PartyTroopUpgradeModel/native MemberRoster and spill to clan parties. ShedLink `TrainTroopsHandler.cs:63-181` is one-off **retinue slot JSON** upgrade, uses UpgradeTargets but own price, posts retinue_changed and HeroProfile save; no native MemberRoster training or persistent budget. `PartyOrderBehavior.cs:517-588` handles automatic recruitment route, not training. Class B to existing troop progression: player funds ongoing native training with chosen ceiling; useful sink and fewer repeated clicks. Need game budget save, UI budget/limits/status and delivery; backend mirror only, no daily training simulation. The exact BLT training source details are in companion combat notes; not a claim that ShedLink has no training.

## Useful small adaptations supported here

1. Select next native building/daily project and construction budget for existing fief.
2. Designate eligible heir explicitly rather than oldest mirror child; show fallback if dies.
3. Multi-prerequisite AND requirement and preview complete upgrade cost; existing tree already supports single chain/bulk.
4. Self-govern action with explicit loss of field-party leadership choice.
5. Clan/army roster details and individual join/leave choices (verify native safe APIs).
6. Additional grandchildren view using existing family entity display; avoid declaring a new dynasty subsystem.

These are research conclusions, not approved roadmap. Deep companions and treaties demand their own specification. No BLT code/assets/config copied into ShedLink.
