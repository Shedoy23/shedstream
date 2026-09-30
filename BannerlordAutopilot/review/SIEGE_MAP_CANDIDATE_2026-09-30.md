# Siege frontier + standalone map probe: prepared candidate, 2026-09-30

Status: validated locally and staged; NOT INSTALLED. Game, launcher settings, saves and existing Link module were not changed. Installation requires the parent's separate confirmation that the game is closed. No push or main merge.

## Integrated source

Fresh remote main: `7e382b1ca648a2719206f5ba2bec680ca557ca4f`. Independent clone `C:\Users\Edward\Documents\Codex\2026-09-30\task-4\siege-map-integration`, branch `integrate/siege-frontier-map-probe-20260930`. Compiled source: `e1c584512e0194279cf595524caa56f3fe65b276`.

Original commits: siege red tests `12d4cc824d618f78e874cad39eb37e876c34f3f0`, siege fix `912de90a0c208b5c1f5ac17e9d3d7f1eae5ad3b8`, standalone probe `d51202cc3b02302a137a6e4d14c794b6d5a4e28c`. Cherry-picks `e80e87a`, `4f055b2`, `e1c5845`; only STATUS/DEFERRED prepend entries conflicted and both entries were retained. No production code conflicts.

Autopilot ranking and final eligibility share `OffensiveSiegeRejection`: current war through actual MapFaction, valid fortress, not raided, and an already besieged target must have an eligible allied camp. Own/friendly/neutral/nonattackable targets do not consume the three-closer-enemies quota. Radius 100, strict-distance ties, any-valid-home and no-home fallback policies are preserved. Geographic diagnostics include target/homefief/distance/eligiblecloser/reason. See [focused change review](SIEGE_ENEMY_FRONTIER_2026-09-30.md).

Probe remains an independent `Shedoy23.MapExportProbe` module, DefaultModule=false, depending on Native/SandBoxCore/Sandbox. Module IDs and dependencies match the installed module set without collision. It does not automatically capture. Manual command: `shedmap_probe.capture confirm-after-stream`. No existing BannerlordLink DLL is included.

## Drift and backups

Remote main Autopilot source/SubModule.xml match installed source `8874c1bc`. Installed DLL/PDB exactly match the prior deployment manifest and were read into staging backups with shared read, then hash verified. Installed DLL/PDB and Link DLL were checked again after the build: unchanged.

Backup Autopilot DLL SHA256: `8A35C0AD8610583006AE40C03833808316B6C1B9AA01934BDD4031020DB94B0A`.
Backup Autopilot PDB SHA256: `898B629F050DF6BAF51952D9CB1E50579E6BB8CD845CDD287DD62DC44DA04FE0`.
Unchanged Link DLL SHA256: `1561AF9C87BA0B53869C726735168EFF2CD5C8C9B51DDD48A54459A82AF28F4F`.
Full destinations, sizes, hashes and rollback instructions: [rollback manifest](../evidence/siege-map-candidate-20260930/rollback-manifest.json).

## Targeted validation

Inspected project/build targets: no auto-deploy; output is isolated staging, engine references have Private=false. Directory.Build imports disabled. Builds use one MSBuild node, BuildInParallel=false, shared compilation disabled and no package sources. A staging-only netstandard reference target supplies the installed net472 facade; no project source changes were needed for the environment.

- Actual Autopilot net472 Release: exit 0, 0 warnings, 0 errors, 7.94 seconds.
- ContractCheck net472 Release: exit 0, 0 warnings, 0 errors; actual installed engine reflection contract 512/512, exit 0.
- Combined source focused frontier/SiegeReliability/Conquest/CampaignCommitment regressions: 232 OK / 0 FAIL, exit 0.
- Standalone probe direct Roslyn net472/x64, parallel disabled, warnings-as-errors: exit 0. DLL hash matches the original independently validated probe candidate.
- No full heavy suite, no game launch, no native rendering call, no live capture. Probe export and corrected siege decisions still need runtime observation after restart.

Logs and manifests: `BannerlordAutopilot/evidence/siege-map-candidate-20260930/`. Build orchestration script/config and staging reference target are retained outside the repository in the package evidence/build inputs.

## Exact installation payload

Package: `C:\Users\Edward\Documents\Codex\2026-09-30\task-4\staging-siege-map-20260930`.
Only these four files under payload are intended for the game's Modules directory:

| Action | Relative path | SHA256 |
| --- | --- | --- |
| Replace | Shedoy23.BannerlordAutopilot/bin/Win64_Shipping_Client/BannerlordAutopilot.dll | 6360E79A68CCA000A1258B23BED5477BF0B003BEC8D7D04530D7F6F4D3DD2078 |
| Replace | Shedoy23.BannerlordAutopilot/bin/Win64_Shipping_Client/BannerlordAutopilot.pdb | C8BD08961789B27ECA3D064AC8F6EF2FF38A4379FAD555A2C889123756FE0DC3 |
| Add | Shedoy23.MapExportProbe/SubModule.xml | 484C6C6F782FF0AAFAE5A12DBA501A8144445CBE3A0BA5744EA58AC21DE0AEE4 |
| Add | Shedoy23.MapExportProbe/bin/Win64_Shipping_Client/ShedLink.MapExportProbe.dll | 1A6572682EFCBD2A821743D5762D627E45B91DBA233C3768A4C7180E52E4A193 |

[Candidate manifest](../evidence/siege-map-candidate-20260930/candidate-manifest.json). The final handoff commit adds documentation/evidence only; compiled source SHA remains e1c5845.

## After the game is confirmed closed

1. Recheck installed DLL/PDB against rollback hashes, payload hashes against candidate manifest, and that probe folder/ID remains absent. Stop replacement on unexplained drift.
2. Copy only the four whitelisted payload files to the matching Modules paths. Verify destination hashes. Retain exact backups; never copy the entire module tree or an old Link DLL.
3. To load the manual probe on the next start, explicitly enable `ShedLink Map Export Probe (manual, experimental)` in the launcher after Sandbox; this setting has not been changed during preparation. Preserve existing enabled mods/order. Capture remains a separate manual step after the stream.
4. After restart, verify startup contract=512 and inspect a real siege selection/geographic rejection. After the stream, if requested, run the manual capture and inspect its JSON/PNG. Native rendering/export success is not yet established.
5. Rollback after the game is closed: restore only the two backed-up Autopilot files; disable the probe if enabled and remove only its added files. Preserve existing Link, saves and other modules.
