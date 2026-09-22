# Wounded fallback and Auto Equip Companions inspection

Owner authorized sending troops when the hero cannot fight personally, and
requested inspection (not integration) of Auto Equip Companions.

## Wounded hero

Native MenuHelper.EncounterAttackCondition disables attack on Hero.IsWounded;
use this rather than a duplicated 20 percent rule. EncounterOrderAttackCondition
still enforces healthy troops, morale and other native restrictions. Its
consequence initializes simulation and opens the map scoreboard.

Fallback is only Apply + current encounter + wounded hero + unavailable attack
+ available str_order_attack. It covers field/village and existing supported
operation attack paths. Prisoner/loot authorization is recorded before starting.
Only a simulation started by this session is confirmed through the native
scoreboard ExecuteQuitAction when IsSimulation/IsOver/ShowScoreboard are true,
without a modal window. This releases simulation sources and invokes OnFinished,
not an early/manual EndBattleSimulation. Repeated polls cannot confirm twice.
Existing preparation logic avoids new expeditions while the hero is wounded.

Regression 05a5803: 358 pass / 2 fail before implementation; completed code also
tests modal blocking and native send-troops refusal. Live combat remains untested.

## Auto Equip Companions

Installed Steam Workshop item 3457590233, version v1.4.8.2. Read local
SubModule.xml, readme.txt, game_settings.json, LICENSE and decompiled DLL to
D:/shedlink-build/AutoEquipCompanions.decompiled.cs. MIT license (Matthew Saari).
No third-party files or settings changed, no implementation copied into autopilot.

Entry: inventory-close listener -> OnExecuteCompleteTransactions ->
AutoEquipModel.AutoEquipCompanions. Also has a manual inventory button.
Enumerates heroes in the main party, including the player if their per-character
toggle allows it; per-slot settings also apply. Uses BattleEquipment, not civilian.
Candidates come from the main party inventory, excluding locked item IDs while
CanAutoEquipLockedItems=false. It does not automatically buy gear.

Current UseTemplates=false means default slot policy:
- Armor: sum of modified head/body/arm/leg armor.
- Weapons: strictly higher EquipmentElement.ItemValue, preserving effective
  item type of the current slot. Empty weapon slots have no matching type and
  are not filled. Relevant-skill difficulty is checked; mounted compatibility
  and couchable-lance behavior are preserved where the template checks them.
- Shields: default shield template uses value; the actual default weapon slot
  uses SameTypeWeaponTemplate, also value.
- Mounts: value, sufficient riding skill, mount type constraints.
- Harness: modified mount body armor, compatible mount family.
Only strict score improvement replaces an eligible current item. TransferCommand
through InventoryLogic moves gear between inventory and hero, rather than
creating equipment. Processing heroes in roster order is not a global optimizer.

Templates (infantry/cavalry/horse archer/bow/crossbow captain) exist but are
disabled in installed settings. BastardSwordsAreOneHanded=true; debug dumps off.
Per-character save settings were not decoded, so actual enabled heroes/slots in
the owner's save are not verified. Inventory-close interoperability with the
autopilot's loot screen must be checked live before adding a duplicate equip pass.
