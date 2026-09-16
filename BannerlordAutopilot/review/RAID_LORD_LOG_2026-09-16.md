# Live raid/lord triage, 16 September, 22:37–22:51

## Correction after owner authorization

Native MapEvent initialization explicitly assigns the nearest village to a
FieldBattle (CampaignSystem decompilation around 111594–111620). The settlement
being non-null therefore does not imply a raid/siege. Field-battle eligibility
now permits a village only with IsFieldBattle; naval/fortress/raid exclusions
remain. Combat dialogue uses the same eligibility instead of random choices
for that encounter. This also enables the existing F11 mission-attachment path.

PollRaid permits all four already-handled terminal raid menus after encounter
teardown, while still requiring the session's recorded raid. Native raid-end
Continue uses ExitToLast (or army_wait for a follower), not a direct battle exit.

Red regression commit 5fe6920: 349 pass / 5 fail (exit 5): two terminal menus,
village field battle, F11 resume and fixed combat dialogue. After correction:
354/354, BattleMission 22/22, actual game contract 421/421; build 0 warnings/errors.
These are local tests and native API/source evidence; live replay is still pending.

Original diagnostic record follows (before code changes).

Inspected live log `C:/Users/Edward/Documents/Mount and Blade II Bannerlord/Logs/autopilot_20260916.txt`.
Installed DLL MD5 remains 55B9AE163133BABA456FF5302F8E235A (61e4549).
No code or DLL changes made in this inspection.

## Raid end

22:45:38: `raiding_village_end` clicked after the village battle. At 22:45:48
the watchdog sees MapState, Stop, Hold and
`village_raid_ended_leaded_by_someone_else [continue]`. No operation click for
continue is recorded. At 22:45:54 time resumes; the log does not identify who
closed that window. Preparation checks before/after report under 70% healthy.
Thus this was an interrupted raid for recovery, not proof of completed looting.

Code defect in PollRaid: the settlement-mismatch guard admits two terminal
menus but excludes village_raid_ended_leaded_by_someone_else, even though the
switch below handles it. If EncounterPlace is cleared on exit, that case is
unreachable. Exact EncounterPlace value is not logged at the stall.

## Lord battle at village

22:49:42/49: generic random dialogue selects lord_meet_player_response1 and 545.
22:49:52: encounter at Glenlithrig, Derthert party, battle present.
22:49:53: PollRaid clicks attack and a mission opens. Unlike earlier battles,
no `battle autopilot added` or formation-control log follows.
22:51:03: explicit UI enable attempt rejected: battle outside prototype scope.
There is no intervening Disable/F12 log; do not call this a proven mode shutdown.

Code coverage gap: field-battle eligibility requires MapEventSettlement == null;
operation eligibility for the raid target requires IsRaid. A lord field battle
at a village can fall between these predicates even though PollRaid authorizes
attack. Actual MapEvent type/flags at mission initialization are not logged, so
the specific failing predicate remains to be reproduced. Generic random dialogue
also took this encounter instead of the intended lord combat chain.

Next correction: terminal raid menus after encounter teardown; consistent
eligibility for lord encounters at the owned raid target, including dialogue and
mission attachment. Add red regressions and validate against native battle types
before widening eligibility. No live fix claimed.
