# Bannerlord diplomacy save failure, 2026-09-21

## Evidence and cause

`C:\ProgramData\Mount and Blade II Bannerlord\logs\rgl_log_2536.txt`,
15:21:45 through 15:29:00: `SaveContext Error: Could not find type definition
of type: BannerlordLink.Actions.ViewerDeclareWarDecision`. Save-as `123` fails
the same way. The log was buffered while the game ran and appeared after exit.

The current worktree already introduced custom war/peace decision subclasses.
They are stored in native `Kingdom.UnresolvedDecisions`, but neither runtime
type had a SaveSystem registration. Existing native base-class registrations
do not cover subclasses. No disk-space or slot-name change fixes this defect.

## Fix

Public, automatically discovered `BannerlordLinkSaveableTypeDefiner` registers
war as `194210001` and peace as `194210002`. These are permanent save IDs;
do not renumber/reuse. Added explicit `TaleWorlds.SaveSystem` assembly reference.
Native inherited fields and the sponsoring clan's voting override remain intact.
No campaign objects, pending votes, or existing saves are deleted or rewritten.

## Validation

`DiplomacySaveHarness` uses installed game assemblies and real
`SaveManager.Save`/`Load` with `InMemDriver`, without starting a native campaign.
Initial current DLL: exit 1 with the exact missing-type error for both decisions.
Previous installed DLL (rollback below): exit 1 with both missing-type errors.
Fixed local and installed DLL: exit 0, six checks: two runtime-type round trips,
two inherited bool/int field round trips (2 war / 6 peace fields), two proposer
stance checks after load. Release build: 0 warnings, 0 errors.

The fixture uses uninitialized decisions with null campaign references; full
campaign save/load, non-null proposer/target graphs and live play remain unverified.

Run from the worktree:

```powershell
dotnet build BannerlordLink/src/BannerlordLink.csproj -c Release
dotnet build BannerlordLink/tests/DiplomacySaveHarness -c Release
& BannerlordLink/tests/DiplomacySaveHarness/bin/Release/net472/DiplomacySaveHarness.exe BannerlordLink/bin/Win64_Shipping_Client/BannerlordLink.dll 'X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord'
```

## Installation and remaining check

During final verification no game/launcher/watchdog process remained. The game
folder already contained the fixed DLL (copied outside this task's tool calls).
Local and installed SHA-256:
`370925D88B2D7EB76956A6B46171C073B87DF4FEB446A64CB03144B3F6278668`.
Installed path:
`X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Shedoy23.BannerlordLink\bin\Win64_Shipping_Client\BannerlordLink.dll`.
Rollback beside it: `BannerlordLink.dll.rollback-2026-09-21-881FFBCF`, SHA-256
`F4946A5C0BBBAA21FE74E8E4A0C59AFD5A95E510F2246E60840E28FF3805302A`.

User check after restart: load campaign, create pending war/peace proposals,
save to a new slot, reload; confirm native pending decisions remain. This task
does not claim that test passed. Save backups from before investigation remain
at `D:\Bannerlord-save-backups\20260921-152837`.

The diplomacy subclasses predated this fix as uncommitted changes in this shared
worktree; this task does not claim authorship or commit unrelated pending edits.
CodeGraph remained unavailable (uninitialized MCP / locked CLI database).
Documentation search for SaveableTypeDefiner had no existing entry.
