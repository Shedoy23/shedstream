# Independent challenge pass: world proposals and combat/progression overlap

Reviewed 2026-09-28. Exact ShedLink baseline0cdf6338 unchanged by this researcher; no runtime/test modifications. Read other notes as hypotheses, then re-opened actual source. No live-game proof.

## 1. Named companions: gap survives, but scope must stay exact

Attempted refutations: existing heir picker, vassal recruitment, wanderer adoption, CompanionOf native handling.

- ShedLink `VassalHandlers.cs:340-414` recruits **new lord** from culture template (fallback Wanderer occupation), `HeroCreator.CreateSpecialHero`, then new Clan and leadership. This is already real named persistent NPC agency. Consequently wording «ShedLink lacks persistent NPC associates» is false. Gap is a **roster of subordinate companion Heroes per viewer with own equipment/progression and tactical participation**, rather than another clan leader.
- Existing `AdoptHeroHandler.cs:108-183` creates viewer's own wanderer; not hiring extra companions. `LeaveClanHandler.cs:183-199` RemoveCompanionAction is lifecycle cleanup for viewer hero, not management UI.
- ActionRegistry full action registration, viewer family/vassal blocks, backend vassal routes contain no companion-roster hire/equip/roles actions. `BLUpgradeModels.cs:155` forwards native companion limit; it does not expose companion management.
- Independently read historical G `352bb4c90a59a915c69b7ade34fcb4723500fe85:source/MakeBltGreatAgain.cs:6795-6893`. Command definitely creates a **fresh** Hero from wanderer template, charges BLT gold, stores owner record, rolls power, supports list/fire/name/equip. It does not recruit a chosen pre-existing tavern NPC. Equipment writes same owner's custom item into companion equipment, without demonstrated removal from owner's list: do not describe robust exclusive item custody.
- Confirmed removal commit `df04587c7c183497a12eb47e4ed0a8c24bfb99c9`: entire Wanderer system removed for scope and naval-death crash surface. Current G HEAD5197130 is not the companion source. Historical status mandatory. Full Scout/Surgeon/Engineer/Quartermaster management remains native-API adaptation hypothesis, not BLT feature proven by companion code.

Verdict: C for distinct roster capability, or B extension of related entities; high value, high complexity. Neither vas­sals nor heirs should be reimplemented. Phrase «named/hired companions» with explicit distinction from selecting an existing tavern wanderer.

## 2. Heir choice: hidden UI does not refute gap

- `viewer-bannerlord.js:1972-2004` has `bnr-vas-heir-pick`, but emits **hero.create_vassal_clan**, not successor designation. Label alone could have created false positive.
- `:2838-2868` heirs panel only lists names. `:5185-5221` death button emits **hero.create**, new wanderer; not switching to a selected heir.
- `_adapter.py:1364-1378` chooses first eligible row `ORDER BY came_of_age_at ASC LIMIT 1` and marks activated; no selected-heir condition. `routes/bannerlord.py:160-193` list endpoint; actual ActivateHeirHandler registered for backend automatic death path, not sold viewer selection.
- M `Actions/HeirCommand.cs:102-177` selection/replacement resolves adult children/siblings, named choice also spouse from adoptedHero.Clan.Heroes. M `Behaviors/BLTHeirBehavior.cs:35-98` saves chosen pair and removes designation if heir dies; also auto-default on coming of age. Command reachability via ActionManager.RegisterAll (ICommandHandler reflection) rather than mere existence of class.
- Independently confirmed activation bug hazard: `HeirCommand.cs:180-202` assigns `newHero=heirHero`, then `heirHero=null`, later reads heirHero.Clan/calls leadership action with null. Therefore richer **designation** is established; safe activation is not.

Verdict B: player choice before death, with game-defined eligibility and native ID, on top of existing much deeper dynasty/inheritance. Not «add heirs» and not copy BLT activation. Minor wording: “oldest” here literally earliest recorded came_of_age_at; not full proof of actual age ordering after all snapshot/recovery cases.

## 3. Native fief projects: strongest concrete small gap, constrained by ownership

- Re-read ShedLink `routes/bannerlord_fiefs.py:51-109`: projection of tribute/identity, old tribute_boost immediately rejects; no project queue/current/default fields. Full ActionRegistry lacks project operation. Existing Workshop/Caravan purchase paths concern different entity types; clan upgrades are own effects, not native Town.Buildings queue.
- R `Actions/ManageFief.cs:38-96` checks adopted clan leader/no Mission/fiefs and dispatches projects/gold/info. `Project:151-221` reads Town.Buildings, runtime match, calls BuildingHelper.ChangeCurrentBuildingQueue and ChangeDefaultBuilding; `ChangeGold:258-282` sets budget to requested amount and charges/refunds delta against Hero.Gold. Governor switch commented and method empty. Not a full governor system.
- R parser accesses splitArgs[1] without length check and name match can produce null fief. Do not import chat parser; stable entity IDs + game validation are straightforward improvement.
- Independently verified native decomp `TaleWorlds.CampaignSystem.decompiled.cs:5722-5750`: **public** ChangeDefaultBuilding toggles actual town flags; ChangeCurrentBuildingQueue clears/enqueues actual Building objects and rejects/asserts daily project in normal queue. Caller still must validate ownership, current town membership and valid project level; public helper is not authorization.
- Native `:5812-5823` BoostBuildingProcessWithGold charges/refunds **Hero.MainHero**. Critical adaptation trap confirmed: blindly calling helper for viewer would debit streamer. Use correct viewer-owned game gold action + target Town.BoostBuildingProcess with effect validation; preserve native projects separately from platform economy.

Verdict B: expose existing engine feature, no synthetic fief bonus tree required. Game-owned catalog/progress/queue is aligned with user request. Native save handles Town fields, backend snapshot migration optional; don't promise zero save risk simply because public API exists.

## 4. Achievements/streak overlap check

`blt-progression.md` had not yet appeared during this pass. Checked actual predicates and ShedLink implementation directly:

- ShedLink `routes/bannerlord_achievements.py:34-93` contains13 achievements and `:99-168` stat increments/maxima/unlock loop, keyed channel+username. Therefore «add achievements» is duplicate; richer hero/class career scope is legitimate possible delta.
- R `Achievements/AchievementDef.cs:44,83` all requirements; `StatisticTotalRequirement.cs:47-53,80-89` compares stat against constant **or another statistic**, operators>,>=,<,<=; `StatisticClassSpecificRequirement` adds class scope. More expressive condition system than one threshold is genuine. Reuse those ideas as game-side predicate reporting, not backend rebuilding game rules.
- ShedLink already has KillStreak (`KillRewardBehavior.cs:369,800`), survives death within battle. `AwardContribMilestones:1125-1160` uses kills/damage/surviving absorbed damage; grants XP, legacyGold diagnostic only and actual gold=0 there. BattlePayoutPolicy handles actual gold. TOR strict “without dying” is alternative balance, not a missing streak system. Combat inventory amended to remove stale-comment ambiguity.

## Notes maintenance

`blt-combat.md` has one Powers heading, no duplicate section. Training classification updated from provisional C to B after world investigator confirmed PartyOrder recruits but no stored training fund. Native upgrade prerequisite caveat retained. Only researcher-owned notes edited.
