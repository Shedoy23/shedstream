# BLT combat depth vs ShedLink — source findings

Исследование 2026-09-28, без изменения runtime. ShedLink baseline и сквозные цепочки: [shedlink-combat.md](shedlink-combat.md), HEAD `0cdf6338`. Ни один BLT-мод здесь не собирался/не запускался; «реализовано» означает исполняемый код с traced entrypoint, не доказанное поведение DLL у TOR-стримера.

## Pinned sources

- B = billw2012/Bannerlord-Twitch `f989f5602f648c9c24f1d95a9364fa7a11676e31`, локально D:/shedlink-build/billw2012.
- R = Randomchair22/Bannerlord-Twitch `83b264f85774489c84c5682c73df3ef92915f39e`, D:/shedlink-build/blt-research-randomchair22.
- M = MesmerTurn/BLT-5.4.x-Warsails-Reforged `dee0d1735f44b336a77986025ec1f863ea05e26f`, D:/shedlink-build/blt-research-mesmerturn. Это default HEAD, не tag5.4.6.
- G = MesmerTurn/MakeBltGreatAgain `5197130e8a1755b452755194b50e65e75998cf98`, D:/shedlink-build/blt-research-mbga; ниже G:path означает source/MakeBltGreatAgain.cs.
- TOR guide text: parent snapshot D:/shedlink-build/blt-research-20260928/tor-guide.txt. Guide evidence отдельно от code evidence.

## Summary classifications

| Mechanic | ShedLink equivalent | Class/gap | Value / difficulty |
|---|---|---|---|
| Basic/elite retinue, upgrades, first-summon troops, loss roll | Already exists | A, no wholesale port | Already done |
| Separate second retinue roster + clearing slots | One mixed basic/elite slot list | B, independent composition/replacement | Medium / medium; avoid more agents for its own sake |
| Guard own hero with retinue | Hero-only detach commands | B, troop-aware guard/follow | High / medium native risk |
| Follow another allied viewer/streamer | Attach to native AI; no chosen ally target in inspected actions | B, cooperative tactical order | High / medium |
| Hold/charge/siege detachment | Existing plus skirmish/raid and contextual siege orders | A/D; ShedLink broader command set than inspected M core | No port |
| Duel command | Enemy-side summons and tournament PvP | B, explicit targeted pursuit; G is not mutual 1v1 arena | Medium / medium |
| Retreat command | No viewer retreat action in inspected registry/UI | B, withdraw tactical choice | Medium / medium; G implementation has caveats |
| Repeated summon cooldown scaling | Fixed ally30s/enemy45s plus same-battle side lock | B, escalation per battle | Optional / small-medium, design choice |
| Compound powers with per-effect unlock criteria | Single chosen weapon power, skill50/150 ranks and specialization | B, richer combinations and conditional progression | High / high; catalogs first |
| Class career kills/battles scale power properties | Weapon skill ranks | B, alternate class mastery progression | Medium-high / medium-high |
| Ally heal aura / reactive low-HP effects | Self-heal, damage/lifesteal/poison/AoE already | B, cooperative or reactive roles | Medium / medium-high |
| Kill streaks, contribution rewards | Existing personal/retinue XP/heal, milestones and damage ledger | A/D, no flat kill-reward transplant | Already deep |
| Tournament equipment/format presets | Native tournament + viewer queue/rewards/HP anti-snowball | B, equalized/cultural class/unified loadouts, varied bracket | High / medium-high |
| Daily party training fund with tier cap and clan spillover | Immediate abstract retinue training; party recruit orders | B, persistent campaign training investment | Medium / medium |
| TOR guard line/shield/loose, half-investment retinue refund | Not in inspected public guard/retinue implementation | GUIDE_ONLY, cannot claim public code proven | Idea candidate only |

## Retinue depth and defects in reference implementation

R stores two lists `HeroData.Retinue` and `.Retinue2` with TroopType/Level: [campaign behavior](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Behaviors/BLTAdoptAHeroCampaignBehavior.cs#L36). Primary and secondary each have separate size/cost/troop-pool settings, UpgradeRetinue/UpgradeRetinue2, game gold and actual UpgradeTargets (`:1197-1458`,`:1482-1767`). Options include own culture, basic/elite, bandit/militia pools. State serialized via ScopedJsonSync HeroData2 (`:328-471`) with referenced game objects maintained. Native APIs CharacterObject.UpgradeTargets, Hero/CultureObject, troop roster, Mission.SpawnTroop; no need backend to reconstruct upgrade chains.

[Retinue2 command](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Actions/Retinue2.cs#L51) has `clear <index>`, `clear all`, and upgrade N/all (`:51-110`). In this source clear deletes entries; no half-cost refund in this command. TOR guide says half investment refunded (text`:569`), which must remain GUIDE_ONLY unless its exact version is obtained.

Important quality caveat: R [BLTSummonBehavior:353](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Behaviors/BLTSummonBehavior.cs#L353) spawns the second list then inserts its Agent into `existingHero.Retinue`, while secondary casualty lookup reads `.Retinue2` (`:157,207`). M repeats same pattern at `BLTAdoptAHero/Behaviors/BLTSummonBehavior.cs:352`. Thus separate persistent roster is real, but distinct casualty attribution is suspicious; no live test done. Do not sell this as a polished implementation.

Meaningful ShedLink adaptation is roster groups/roles and replaceable slots, not automatically doubling troop count. It depends on fixing game ownership of retinue and authoritative full snapshots (see ShedLink casualty/save caveat). Backend stores projection, frontend shows groups and game-supplied replace/upgrade options; migration/save version likely for group identity; medium save risk, high if reusing existing index-only slot semantics. Keep independent implementation.

## Guard/follow/orders

G [GuardCommand + GuardMissionBehavior:630-725](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/5197130e8a1755b452755194b50e65e75998cf98/source/MakeBltGreatAgain.cs#L630): active battle, deployment complete, owner summoned; guard on/off; mission-local set of Heroes, every0.5s gets owned retinue agents and follows/fights within3m. Reflection bridge reads BLTSummonBehavior.Current.HeroSummonStates and Retinue/Retinue2 (`:729-774`). It is reflection into BLT internals, not required Bannerlord API. ShedLink already has its own RetinueRegistry; don't reproduce that dependency.

G [FollowCombat:224-260](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/5197130e8a1755b452755194b50e65e75998cf98/source/MakeBltGreatAgain.cs#L224): nearest hostile proximity within9m gives native AI back via SetAutomaticTargetSelection/DisableScriptedMovement; otherwise SetScriptedPosition toward owner. Native Agent and WorldPosition APIs; transient mission state, no save schema required for simple guard mode. Caveat: logic only sets position when far; semantics near target and releasing old scripted targets require our own testing.

G [FormationFollowHeroCommand:145-199](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/5197130e8a1755b452755194b50e65e75998cf98/source/MakeBltGreatAgain.cs#L145): choose another viewer's present hero, reject self/enemy/deployment, follow within configurable distance. Streamer follow at`:113-142`. Viewer cooperation becomes tangible (archer accompanies tank) without new economic system. Existing ShedLink detach UI/action transport can expose selected allied entity; game validates current Agent/Team. Backend authorization/transport, frontend target picker, no DB migration necessary unless persistent preference/history. Difficulty medium; native navigation/performance risks more important than save risk. Release target if dead/unspawned/mission changes.

M [BLTHeroDetachmentBehavior:13-85](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/Behaviors/BLTHeroDetachmentBehavior.cs#L13) uses IDetachment, Formation.JoinDetachment/DetachUnit and AddAgentAtSlotIndex. ShedLink deliberately uses own per-agent scripted movement, already offers hold/charge/skirmish/raid/walls/gate. BLT framework wholesale is not an improvement; borrow target/follow affordance only. Do not regress native formation safety.

TOR guard line/shield/loose (`tor-guide.txt:499-502`) not matched by current G GuardCommand (only recognizes off, every other arg turns generic guard on). Treat formation presets as guide-described extension, not public G proven implementation.

## Duel and retreat semantics

G [DuelCommand:1512-1640](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/5197130e8a1755b452755194b50e65e75998cf98/source/MakeBltGreatAgain.cs#L1512) validates both living agents, opposite sides, battle/deployment, one target per attacker. It **does not ask target acceptance** and explicitly allows many attackers against one target. `DuelMissionBehavior:1641+` stores attacker→target, retargets every1.5s, releases when either disappears, announces outcome. This is named enemy pursuit in a normal battle, not isolated fair duel with consent/stakes. ShedLink enemy summon already enables PvP; useful delta is explicit target order. If product wants actual duel agreement, that is new design, not verified BLT capability. Backend target identity/action plumbing; UI pick enemy; mission-only state no save migration. Medium native risk and potential harassment design choice.

G [RetreatCommand/behavior:509-620](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/5197130e8a1755b452755194b50e65e75998cf98/source/MakeBltGreatAgain.cs#L509): every0.5s find nearest enemy, disable auto targeting, scripted position30m away. Off can call `agent.Formation.SetMovementOrder(Charge)`—may affect whole formation, so do not copy. No evidence this performs native safe escape/despawn/result settlement. Adaptation should state desired choice (preserve wounded hero vs contribution), then use verified native retreat path and payout semantics. Not a small cosmetic button despite tiny command.

## Summon cooldown scaling

Original B already has TimesSummoned/mission-local cooldown (`BannerlordTwitch/BLTAdoptAHero/Behaviors/BLTSummonBehavior.cs:35-44,104-113`). R [GlobalCommonConfig:738-739](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/GlobalConfigs/GlobalCommonConfig.cs#L738) computes `base * multiplier ^ max(0,n-1)`, defaults20s/1.1 (`:215-230`). R summon state uses game mission time `:49-54` and increments TimesSummoned `:126`; retinue only first time. This is a genuine small delta versus fixed ShedLink summon cooldown. Value conditional: limits repeated returns in same battle; can also punish losing viewers. Put count/deadline and availability in game snapshot; backend own short anti-spam remains. No persistent schema needed if per mission, frontend already cooldown component, implementation small-medium including reconnection identity and result handling. Not automatically preferred balance.

## Powers: composition is the valuable difference, not another poison button

Original B already has `PowerGroupItemBase.Requirements` as `IAchievementRequirement` list with all(IsMet). R [ActivePowerGroup](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Powers/Core/ActivePowerGroup.cs#L43) holds many effect IDs; GetUnlockedPowers and CanActivate check each effect; Activate starts each unlocked effect (`:66-124`). [PowerGroupItemBase:18-32](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Powers/Core/PowerGroupItemBase.cs#L18) binds per-effect unlock predicates. PassivePowerGroup`:57-80` installs effect handlers when hero joins battle. This is already current longstanding BLT, **distinct from reverted MBGA generalized DoT/Aura refactor**.

R `Behaviors/PowerHandler.cs:19-110` routes AgentBuild, damage, melee/missile, killed, slow tick, mission over and model callbacks to registered effects. BLTHeroPowersMissionBehavior wraps engine events; native/hook surfaces include Mission.RegisterBlow, OnAgentBuild/OnAgentRemoved, AgentDrivenProperties and damage models. Definition config serializes IDs/settings; active handlers ephemeral mission state. Read-only code reference, not code reuse recommendation.

ShedLink already enforces selected/wielded weapon and ranks by native skill, plus passives; BLT delta is ability containing multiple effect components with **different game-reported unlock conditions**, not basic ability requirements. Suggest game-side definitions/conditions and explanation payload, frontend generic unlocked/locked rows. Backend should not evaluate Bannerlord skill/kill/build eligibility. Requires new game capability catalog, save-versioned selected ability if needed, frontend multi-effect card, medium/high migration risk if changing old classes. High complexity, do after ownership contract.

G [PowerProgression.GetTier:5733-5764](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/5197130e8a1755b452755194b50e65e75998cf98/source/MakeBltGreatAgain.cs#L5733) reads class-specific total kills OR battles to unlock tiers, supports infinite steps; ScaleInt/ScaleFloat use per-property configured curves (`:5770-5814`); manual Harmony prefix clones unlocked passive definitions (`:5890-5925`) to avoid mutating shared settings. A meaningful career progression option over ShedLink weapon-skill ranks, but open-ended linear scaling may destroy endgame balance. Prefer milestones with bounded choices; persistent source should be game class/hero career stats, backend display. Parent stats audit decides how much infrastructure already exists.

G [HealAuraPower:2322-2406](https://github.com/MesmerTurn/MakeBltGreatAgain/blob/5197130e8a1755b452755194b50e65e75998cf98/source/MakeBltGreatAgain.cs#L2322) does actual nearby allied health restoration, with radius, tick frequency, max affected agents and cleanup. APIs Mission.GetNearbyAgents, Agent.IsFriendOf/Health/HealthLimit, handler slow tick. Valuable cooperative role built on existing powers. G has reactive low-HP Berserk/LastStand (`:2079-2270`), useful optional trigger model rather than new global system; require exact no-op/cooldown and effect ownership semantics in independent implementation.

Reference warning: current G BuffAura description says damage+armor but `ApplyBuff:2852-2862` maps damage to SwingSpeedMultiplier and armor to ArmorHead; inverse modifier cleanup `:2867+`. Cannot report exact team damage/full-body armor as implemented. Commit cbf8553 attempted real Aura Buff/Debuff and composable DoT/Aura/SelfBuff; HEAD5197130 is its explicit revert. History is idea evidence only, not current code claim.

## Tournament depth beyond existing ShedLink

R `GlobalTournamentConfig:75-85` normalize armor, `:103-293` configurable/random round layouts. Actual R BLTTournamentMissionBehavior`:135-241` changes equipment; [BLTTournamentBetMissionBehavior:257-265](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Behaviors/BLTTournamentBetMissionBehavior.cs#L257) replaces round definitions, Harmony CreateTournamentTree. Randomized equipment can bias toward participants' class skills and includes unarmed (`BLTTournamentMissionBehavior:156-193`). Anti-snowball also uses configurable skill debuffs; ShedLink already has recent-winner HP penalty, so this is an alternative balancing method, not absent anti-snowball.

M [GlobalTournamentConfig:20-25,100-116](https://github.com/MesmerTurn/BLT-5.4.x-Warsails-Reforged/blob/dee0d1735f44b336a77986025ec1f863ea05e26f/BLTAdoptAHero/GlobalConfigs/GlobalTournamentConfig.cs#L100) adds **ClassLoadout** and **CulturalUnified**. Actual `BLTTournamentMissionBehavior:231-390`: one shared randomly selected weapon family per round, each fighter gets own-culture item nearest selected tier; armor own culture→host culture→any fallback; class loadout uses class slot definitions. Gives progression-independent competitive event while preserving cultural identity. This is stronger adaptation candidate than another reward multiplier.

Implementation knowledge: TournamentParticipant.MatchEquipment, ItemObject runtime pool, TournamentBehavior.Rounds, TournamentRound construction; Harmony patches for native tournament equipment/tree hooks, version sensitive. Persist only chosen tournament rules if desired, mission equipment temporary, never overwrite permanent equipment ledger. Backend can expose rules/state, frontend a preset explanation; migration optional rules persistence, save risk low if transient but native conflict risk medium-high with overhaul tournaments. Don't copy vanilla StringId fallback weapon (`empire_sword_1_t2_blunt`) into platform.

Existing ShedLink already has queue save/reload, free registration, winners/consolation XP, native item prize, overlay/prediction and winner history. Retain its free predictions; BLT betting path is not recommended adaptation.

## Daily training fund

R [PartyManagement:635-668](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Actions/PartyManagement.cs#L635) exposes status/cancel/refund/invest. [TrainingBehavior:34-68](https://github.com/Randomchair22/Bannerlord-Twitch/blob/83b264f85774489c84c5682c73df3ef92915f39e/BannerlordTwitch/BLTAdoptAHero/Behaviors/TrainingBehavior.cs#L34) DailyTickHero + SyncData funds/tiers; `:144-183` upgrades leader party, once tier cap reached spends on eligible clan party; `:254-300` actual PartyTroopUpgradeModel.GetGoldCostForUpgrade and runtime UpgradeTargets/MemberRoster. This is a finite resource sink shaping household armies over campaign days, distinct from ShedLink instant retinue.train.

Do not assume native upgrade prerequisites are fully obeyed because model cost is called: requires separate review of `PickBestUpgradeTarget`/roster mutation semantics. Adapt using game models/events and game-owned fund; backend payment request only; frontend status/cancel/cap; save schema and finite balance persistent, medium complexity and save risk. World inventory independently confirmed the current ShedLink party-order route recruits troops but has no equivalent saved training fund; classify B extension of existing retinue/party progression.

## History/provenance evidence and recommendation limits

- R history Retinue2 introduced `51fef45` (2025-12-14), clear all `cfe93ce` (2026-03-11); current public implementation inspected, not inferred README.
- B history `e6d6d8c` (2022-11-17) forced summon stats without breaking streaks; cooldown and first-summon retinue already upstream. They are old shared infrastructure, not uniquely superior new fork mechanics.
- G historical composable refactor `cbf8553` (2026-07-18) explicitly reverted by current5197130 same day. Do not conflate with longstanding ActivePowerGroup or with guide's newer privately configured behavior.
- M root tree added `698eac7` (2026-07-10); history has native summon/banner safety fix `4d665de` (2026-07-17). Broad claims of save/native crash safety unsupported.

Top combat adaptations after source comparison: (1) targeted ally follow + troop guard atop existing orders; (2) tournament loadout/format presets; (3) deeper game-owned power milestones/effect groups; (4) daily army training fund; (5) explicit enemy target as tactical order, not falsely marketed duel. Secondary retinue is lower priority than making the existing retinue commandable and authoritative. Small candidates: game-reported summon escalation, retinue replace/clear with explicit refund policy, visible power requirement breakdown, tournament rules preview. No implementation roadmap or code change made by this subaudit; parent consolidates dependencies and license provenance.
