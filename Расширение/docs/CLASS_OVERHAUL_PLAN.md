# Class Overhaul Plan — 12 distinct classes (2026-06-17)

**Status:** Phase 0 ✅ verified in-game. Phase 1 ✅ BUILT + DEPLOYED to prod (2026-06-18) — 12-class roster, in-game verification pending. Phase 2 (full power rebalance of all 12) + Phase 3 (picker icons/order) = spec below.

### Phase 1 — implementation notes (2026-06-18, deployed)
- **12 classes** in `ClassLoadout.Classes` (C#): weapon-by-WeaponClass + armor weight-band + skip-slots + mount. Both formation maps updated (`SummonHeroHandler.ResolveFormationClass` + `RecruitTroopsHandler._classToFormation`) + `MountedClasses`.
- **`m80_class_overhaul`** (wired in main.py): reseeds `bannerlord_classes` → 12 (FK-safe order: catalog → remap → deprecate), remaps removed keys in `bannerlord_hero_class` (heavy_archer→archer, heavy_crossbow→crossbow, psycho→berserk, cavalry→lancer, camel_cavalry→lancer, camel_archer→horse_archer), soft-deprecates the 6 old rows, seeds **baseline** powers for the 5 new classes (existing power_keys only).
- **Camel classes folded** (→lancer/horse_archer); revisit as a culture skin later. `Config.UseCamel` kept (reserved) → harmless CS0649 warning.
- **Phase 2 TODO:** full power rebalance of ALL 12 per the §B numbers (the 5 new currently have baseline bundles, the 7 kept retain pre-overhaul powers).
- Verified: mod compiles, lint OK, m80 runtime test green (12 active / 6 deprecated / remap psycho→berserk keeps level / 5×6 power rows). Frontend picker is backend-driven → 12 show automatically.

### Phase 0 — implementation notes (2026-06-18)
- New engine capability lives in **`BannerlordLink/src/Actions/ClassLoadout.cs`** — the SINGLE source of truth for class→loadout (`Slot{Type,Wc}` + `ArmorBand` + `SkipArmorSlots` + mount) and the tier/WeaponClass/weight-aware `FindTieredItem`/`PickNearestTier`.
- **Found + fixed: equip logic was DUPLICATED** across `SetClassHandler` (set_class) and `UpgradeGearHandler.ApplyGearLoadout` (upgrade_gear + reequip_gear). Only set_class was class-aware → `reequip`/`upgrade` re-rolled generic gear and undid the class look. Both now call `ClassLoadout`. **Phase 1 edits the 12 loadouts in ONE C# place** (ClassLoadout.Classes) + the M15 Python seed.
- **THIRD place class identity lives = class→FormationClass map** (`SummonHeroHandler.ResolveFormationClass` + `RecruitTroopsHandler`). New class keys (legionnaire/spearman/maul/skirmisher/lancer) must be added there too in Phase 1, else they default-formation.
- **Modifier/reforge preservation (M8) interacts with class weapon type:** a viewer's reforged (ItemModifier) weapon is KEPT across class change even if its WeaponClass ≠ the class's (e.g. @shedoy23's reforged 2H *sword* stays on berserk instead of an axe). Open design Q: class-type-overrides-reforge vs keep-investment (current). Clean proof = test on a hero with no reforged gear.

---
**Goal:** 12 viewer classes that FEEL distinct, differentiated on 3 axes — **weapon (WeaponClass)** + **armor (weight/material)** + **powers (passives/actives)**.

All power MECHANICS already exist (read by `PowerCache`/`DamageHookPatch`/`ActivatePowerHandler`/`PowersMissionBehavior`). This overhaul is **data** (loadouts + power seeds) + **one new engine capability** (equip filter by WeaponClass + armor material). No new power code.

Numbers below are **first pass** — balance is felt in play, tune on stream. All values are L1 / L2 / L3 (per class level). Base: every [BLink] hero gets HP ×2.5; `hp_multiplier` stacks on that. Heavier armor = slower (offset by `athletic_skill_boost`). Weapon FLAGS (cleave, crush-through, dismount, anti-shield) come from the chosen WeaponClass itself — not from powers.

---

## A. Engine changes (Phase 0 — the enabler)

`BannerlordLink/src/Actions/SetClassHandler.cs`:
1. `FindTieredItem(...)` — add optional `WeaponClass? wc` param; when set, filter the pool by `i.PrimaryWeapon?.WeaponClass == wc`. (Pool stays by `ItemType`; `wc` narrows it.)
2. `ClassConfig` — change `Slots` from `ItemTypeEnum[]` to a struct array `(ItemTypeEnum type, WeaponClass? wc)[]`; add field `ArmorBand Armor` (None / Light / Medium / Heavy) — a **weight band**, not a hard material; add optional `SkipArmorSlots` set (default empty = fill all 5 armor slots) for partial-armor identities — e.g. berserk skips Head (no helmet) + uses the lightest cloth Body. Skipped slots are set to `EquipmentElement.Invalid`.
3. Armor equip (currently fixed, lines ~270-288) → class-aware by **weight band within the requested tier** (NOT a hard material lock). Keep `PickNearestTier` driving the tier (so **gear_tier still raises armor value for every armored class**), then within the nearest-tier group pick by weight: Heavy = heaviest available, Medium = mid, Light = lightest. Preserves gear-tier progression AND the relative heavy/light feel at every tier.
   - **Why not a hard `MaterialType` lock:** plate clusters at high tiers, leather/cloth at low tiers → a locked class would get near-identical armor at gear_tier 1 vs 6 (armor upgrade dies for that class). **Confirm the pool's tier×material/weight distribution in-game during Phase 0** (mod logs the actual BodyArmor pool) before finalizing the band picker.
   - **§B armor labels = weight bands:** Plate→Heavy, Chainmail→Medium, Leather→Light, None→no armor. `None` (berserk) is the only class with no armor-tier scaling — intentional glass fantasy (his gear_tier buys a better axe); switchable to Light if armor-upgrade-meaning is wanted for him.
4. Verify `ApplyClassSkillBoosts` maps **throwing** + **athletics** skills (not just 1h/2h/polearm/bow/crossbow/riding) — add if missing.
5. Mirror the new fields in the backend seed (`m15`-style) for the catalog/UI.

Reference enums (TaleWorlds.Core): `WeaponClass` { Dagger, OneHandedSword, TwoHandedSword, OneHandedAxe, TwoHandedAxe, Mace, TwoHandedMace, OneHandedPolearm, TwoHandedPolearm, LowGripPolearm, Bow, Crossbow, Javelin, ThrowingAxe, ThrowingKnife, SmallShield, LargeShield, … }. `ArmorComponent.MaterialType` { None, Cloth, Leather, Chainmail, Plate }.

---

## B. The 12 classes — full spec

Power keys reused as-is (already implemented): passives `hp_multiplier, damage_reduction_pct, stagger_immunity_pct, ignore_armor_pct, lifesteal_pct, move_speed_pct, body_scale, *_skill_boost`; actives `rage, cleave, explosive_arrows, lifesteal_burst, ironskin_toggle, retribution_toggle, shield_break_burst, heal_burst, berserker_charge, poison_dot`. `heal_burst` is available to everyone (engine default).

### INFANTRY

**`tank` — 🛡 Латник** (Plate · slow immovable wall)
- Loadout: [OneHandedWeapon/Mace, Shield/LargeShield, —, —]. Armor: **Plate**. Foot.
- Passives: hp_multiplier 1.6/1.9/2.2 · damage_reduction_pct 12/20/30 · stagger_immunity_pct 50/70/85 · ignore_armor_pct 10/18/25 · athletic_skill_boost 20/40/60 (offset plate) · one_handed_skill_boost 15/30/50 · body_scale 1.10/1.12/1.15
- Actives: ironskin_toggle 35/55/75 · shield_break_burst 6/8/10
- Feel: takes everything, hits slow, breaks shields. Mace crush-through.

**`berserk` — 🪓 Берсерк** (barechested · glass cleaver)
- Loadout: [TwoHandedWeapon/TwoHandedAxe, TwoHandedWeapon/TwoHandedAxe, —, —]. Foot.
- Armor: **Light, partial** — Head EMPTY (no helmet), Body = lightest cloth tunic (~0 armor, the "pants+shirt" look, NOT a breastplate), Leg + Gloves = Light (tier-scaling). Cape optional/Light. → head & torso unarmored (true glass, takes full headshots/body hits), least weight = fastest, yet gear_tier still upgrades boots/gloves/tunic so the upgrade isn't dead.
- Passives: hp_multiplier 0.85/1.00/1.10 · two_handed_skill_boost 30/60/90 · ignore_armor_pct 20/35/45 · lifesteal_pct 6/11/16 · move_speed_pct 12/18/24 · damage_reduction_pct 3/6/10 · stagger_immunity_pct 25/40/55
- Actives: rage 1.5/1.7/1.9 · cleave 0.40/0.50/0.60 · lifesteal_burst 30/45/60
- Feel: mows crowds (2H-axe cleave), dies if focused. Fast (no armor).

**`legionnaire`* — ⚔ Легионер** (Mail · reliable line)
- Loadout: [OneHandedWeapon/OneHandedSword, Shield, Thrown/Javelin, —]. Armor: **Chainmail**. Foot.
- Passives: hp_multiplier 1.2/1.35/1.5 · one_handed_skill_boost 20/40/60 · throwing_skill_boost 15/30/50 · damage_reduction_pct 6/10/14 · stagger_immunity_pct 20/35/50 · athletic_skill_boost 10/20/35
- Actives: rage 1.3/1.45/1.6 · shield_break_burst 5/7/9
- Feel: throw javelin → shield up → trade. Versatile, no glaring weakness, no peak.

**`assassin` — 🗡 Убийца** (Leather, small · fast bleeder)
- Loadout: [OneHandedWeapon/Dagger, Thrown/ThrowingKnife, —, —]. Armor: **Leather**. Foot.
- Passives: hp_multiplier 0.80/0.90/1.00 · one_handed_skill_boost 25/50/80 · throwing_skill_boost 20/40/65 · lifesteal_pct 10/18/26 · move_speed_pct 14/20/26 · body_scale 0.92/0.90/0.88 · damage_reduction_pct 4/8/12
- Actives: lifesteal_burst 35/50/65 · poison_dot 8/13/19 · berserker_charge 50/70/100
- Feel: fastest, slippery (small), sustains via lifesteal, frail.

**`spearman`* — 🔱 Копейщик** (Mail · anti-cavalry)
- Loadout: [Polearm/TwoHandedPolearm(spear), Shield, —, —]. Armor: **Chainmail**. Foot.
- Passives: hp_multiplier 1.1/1.3/1.5 · polearm_skill_boost 20/45/70 · damage_reduction_pct 6/12/18 · stagger_immunity_pct 25/45/65 · athletic_skill_boost 10/20/35
- Actives: ironskin_toggle 25/40/55 · heal_burst
- Feel: reach + brace; the spear's CanDismount flag wrecks cavalry. Holds the line.

**`maul`* — 🔨 Сокрушитель** (Mail/half-plate · anti-armor crusher)
- Loadout: [TwoHandedWeapon/TwoHandedMace, —, —, —]. Armor: **Chainmail**. Foot.
- Passives: hp_multiplier 1.2/1.4/1.6 · two_handed_skill_boost 25/50/80 · ignore_armor_pct 25/40/55 (blunt — its niche) · stagger_immunity_pct 30/50/70 · damage_reduction_pct 6/12/18 · athletic_skill_boost 8/16/28
- Actives: shield_break_burst 8/10/12 · rage 1.3/1.5/1.7
- Feel: 2H-mace cleave + crush-through-blocks + knockdown; counter-pick vs Латник/shields (blunt beats armor where cut fails).

### RANGED (foot)

**`archer` — 🏹 Лучник** (Leather · kite + AoE)
- Loadout: [Bow, Arrows, Arrows, OneHandedWeapon/Dagger]. Armor: **Leather**. Foot.
- Passives: hp_multiplier 0.95/1.05/1.15 · bow_skill_boost 25/50/75 · damage_reduction_pct 6/10/14 · stagger_immunity_pct 10/15/20 (survive a melee reach) · move_speed_pct 10/15/20 · lifesteal_pct 5/8/12
- Actives: explosive_arrows 60/90/120
- Feel: kite, AoE volleys, fragile. Battle order «Издали/Перестрелка» fits.

**`crossbow` — 🎯 Арбалетчик** (Mail · armor-pen siege shot)
- Loadout: [Crossbow, Bolts, Bolts, OneHandedWeapon]. Armor: **Chainmail**. Foot.
- Passives: hp_multiplier 1.1/1.25/1.4 · crossbow_skill_boost 25/55/85 · ignore_armor_pct 15/25/35 (bolt pen) · damage_reduction_pct 6/10/14 · stagger_immunity_pct 10/15/20
- Actives: explosive_arrows 65/95/125
- Feel: slow heavy hitter, punches armor; tankier than archer.

**`skirmisher`* — 🪃 Застрельщик** (Leather · javelin barrage)
- Loadout: [Thrown/Javelin, Thrown/Javelin, Shield/SmallShield, OneHandedWeapon]. Armor: **Leather**. Foot.
- Passives: hp_multiplier 1.0/1.15/1.30 · throwing_skill_boost 25/50/75 · move_speed_pct 12/18/24 · damage_reduction_pct 5/9/14 · stagger_immunity_pct 15/25/35 · one_handed_skill_boost 10/20/35
- Actives: explosive_arrows 50/75/100 (triggers on thrown missile hits too) · heal_burst
- Feel: javelin barrage at mid-range (pierces shields), then 1H+shield in melee. Counter shield-walls.

### CAVALRY

**`knight` — 🏇 Рыцарь** (Plate · devastating heavy charge)
- Loadout: [Polearm/OneHandedPolearm(lance), OneHandedWeapon, Shield/LargeShield, —]. Armor: **Plate**. **Horse**.
- Passives: hp_multiplier 1.6/1.85/2.1 · polearm_skill_boost 20/45/65 · one_handed_skill_boost 15/30/50 · riding_skill_boost 20/40/65 · damage_reduction_pct 8/14/22 · stagger_immunity_pct 30/50/68 · athletic_skill_boost 10/20/35
- Actives: ironskin_toggle 30/45/60 · heal_burst
- Feel: couch-lance charge (dismount flag), heavy, slower to reposition.

**`lancer`* — 🐴 Улан** (Mail · nimble hit-and-run)
- Loadout: [Polearm/OneHandedPolearm(lance), Thrown/Javelin, OneHandedWeapon, —]. Armor: **Chainmail**. **Horse**.
- Passives: hp_multiplier 1.2/1.4/1.6 · polearm_skill_boost 20/40/65 · throwing_skill_boost 15/30/50 · riding_skill_boost 25/50/75 (faster) · damage_reduction_pct 6/12/18 · move_speed_pct 8/14/20
- Actives: explosive_arrows 45/70/95 (javelin throw) · heal_burst
- Feel: charge → throw javelins → wheel away. Lighter/faster than Рыцарь.

**`horse_archer` — 🐎 Конный лучник** (Leather · mobile harasser)
- Loadout: [Bow, Arrows, OneHandedWeapon, Arrows]. Armor: **Leather**. **Horse**.
- Passives: hp_multiplier 1.0/1.10/1.15 · bow_skill_boost 20/40/65 · riding_skill_boost 20/40/65 · lifesteal_pct 6/12/19 · damage_reduction_pct 4/7/10
- Actives: explosive_arrows 44/70/96 · heal_burst
- Feel: kite on horseback; battle order «Набег» fits.

`*` = new class key (5): legionnaire, spearman, maul, skirmisher, lancer. The other 7 reuse existing keys (ref stability) with revised loadout/name/powers.

---

## C. Class-key strategy + viewer remapping

- **Keep 7 existing keys** (revised content): tank, berserk, archer, crossbow, assassin, knight, horse_archer. (Rename only the display NAME column.)
- **Add 5 new keys:** legionnaire, spearman, maul, skirmisher, lancer.
- **Remove 6 keys → remap existing `bannerlord_hero_class` rows** (so no viewer's class breaks):
  - heavy_archer → archer · heavy_crossbow → crossbow · psycho → berserk · cavalry → lancer · camel_cavalry → lancer · camel_archer → horse_archer
  - (Camel variants = horse skin; revisit later as a culture flag.)

---

## D. Build phases (each = a focused session; owner in the loop between)

| Phase | Work | Files | Gate (in-game) |
|---|---|---|---|
| **0. Engine + 1 proof** | WeaponClass filter + class-aware armor + ClassConfig struct; build **berserk** end-to-end (2×2H-axe, no armor) | `SetClassHandler.cs` (+mod rebuild) | berserk equips axes, no armor, no crash → ✅ only then proceed |
| **1. 12 loadouts** | all 12 in C# `_classes` + migration reseed `bannerlord_classes` (new fields) + **key remap** migration on `bannerlord_hero_class` | `SetClassHandler.cs`, `mNN_classes_v2.py`, `main.py` | catalog=12; each class equips the right weapon class + armor |
| **2. Powers** | migration reseed `bannerlord_class_powers` per the numbers above | `mNN_powers_v2.py`, `main.py` | local migration test (like m78/m79) + spot-check values |
| **3. Frontend + deploy + balance** | class-picker shows 12 (icons/desc/role groups: пехота/стрелки/конница); deploy backend→mod→frontend; in-game pass per class | `viewer-bannerlord.js` (+ `viewer.js` labels) | each class: equip ok, feels distinct, no crash on tick/save-load |

Deploy order each phase: backend (migrations) → mod (`-Mod`, GAME CLOSED) → frontend (`-Frontend`). Mod features verified only in-game (no auto-test) — iterate on stream.

---

## E. Risks / rules

- **C# `_classes` ↔ Python seed MUST stay in sync** (project file rule) — edit both together.
- **equip-without-Mission + NPC/clan edge-cases** = the crash class hit repeatedly this period → dense in-game test each phase (esp. set_class outside battle).
- **Migration: never edit an applied migration**; add new (m-numbered, wired in `main.py`, idempotent). Key-remap migration must be idempotent + only touch rows with removed keys.
- **Refactor, not bloat** — 12 revised replace 13 (feature-in/feature-out satisfied).
- **Compliance/BLT:** gameplay + TaleWorlds API only — non-issue.
- Numbers are a first pass; expect 1-2 stream balance iterations after Phase 3.
