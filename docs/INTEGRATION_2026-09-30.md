# Local integration candidate, 30 September 2026

This is an isolated local candidate, not an installation or production report.

## Inputs and location

- Branch: `integration/shedlink-pets-20260930`.
- Checkout: `C:/Users/Edward/Documents/Codex/2026-09-30/task/shedstream-integration`.
- Current source basis: `586fbffad3eeadb9ed183e64c320a3bed449d00e`, branch `claude/poststream-2026-09-22`, checkout `C:/Users/Edward/Desktop/work/.claude/worktrees/bannerlord-crash-analysis-a34de4`.
- Pet head: `d4ef67e0aeb493f28a416e7c2ceb8f83b914a6a9`, branch `codex/public-release-readiness`, checkout `C:/Users/Edward/Desktop/work/.claude/worktrees/codex-public-release`.
- Common ancestor: `5dc8a5bd17857046600d1f5f7b83959aaf106f3d`; the pet line contributes 16 unique commits.
- Original repository has distinct remotes: `origin=https://github.com/Shedoy23/shedstream.git`, `afterlait=https://github.com/Shedoy23/AfterLait.git`. No original remotes or worktrees were changed.
- Read-only remote recheck: active published head `b92deb45d06daf24781b2dcbe92040201379d40e`; published main `a380ad7b72eec79889ae99d7fb5d5886c3aa31d3`. The local basis includes 20 newer unpublished commits.

## Reconciliation decisions

Both migration identities are retained. `M129.reforge_rights` and `M129.pet_companions` are different ledger keys, as are `M130.clan_catalog_truth` and `M130.pet_fantasy`. They must not replace each other based on numeric prefixes. Main also retains M131/M132; pets retain `M133.pet_legacy_common`.

The merge keeps the current database implementation and adds shared pet pricing; keeps the configurable final-summary timeout in the overlay; adds pet renderers/assets and preserves both histories in STATUS/DEFERRED. The pet line's already committed stream-director source and historical evidence are included, with no installation or live execution.

The current source's four reviewed dirty documentation/evidence files record the earlier 27 September autopilot installation. Generated harness sources were excluded. Of 94 backed-up dirty/new files: 4 included, 33 already present by full-content or reverse-patch comparison, 57 deferred. [The complete per-file ledger](INTEGRATION_DIRTY_LEDGER_2026-09-30.json) gives source path, backup path, SHA256, decision and reason for every file. Deferred files remain available in the backup; this is not a claim that their behavior is obsolete.

Separate saved lines, deliberately not merged: retinue experiment `459c092e1c958f50bd078680345b91f6586227a4`; Manager `b7afa0fe61ada486ebf6f747823c4d37a9ef3da9`; AfterLait mobile/compliance `aa9e28ea7c9e5d1e6f829d8d835c862b9ccb14b2`; agents/hive documentation `4fc95bc3da38899abedfad8aa4fa8dc30bb74c74`; independent 0.0.6 repository `a7e432fb17aefb820b834de78aa396501e20eeac`; RBM `e84a12237d65b339dc5a89bf80856d06193feca9`. Deferred dirty groups include panel/access/promo changes, viewer-presence proposals, older overlapping mod implementations, agent-loop work, and summon-placement prototypes. Source stash `35f74dfd0a7af99554c486e90cec1ea30e06c602` is preserved in the bundle.

## CI and future frontend

`backend/requirements-test.txt` declares `httpx==0.28.1` and includes runtime requirements; CI installs this file. The failing ASGI API test previously imported an undeclared test dependency.

Both future viewer shells now use one cache stamp for their nine viewer modules. The lifecycle check was retained unchanged and passed after the source correction. The Twitch review archive was not rebuilt or edited: SHA256 `6f8e07f56b7d6a0b4f628a2731d81686a47b77dd8b7cfcc912dd1f8af3f90672`. Both frozen-client ZIP fixtures and the tracked RimLink ZIP are byte-identical to the basis. A source-to-submitted-ZIP equality check is expected to show drift for future shell sources; it must not trigger replacement of the submitted package.

## Backup evidence

Backup directory: `C:/Users/Edward/Documents/Codex/2026-09-30/task/integration-backup-20260930`.

Four independently verified bundles preserve the shared repository, 0.0.6, RBM and the separate bandit diagnostic repository. The 94 dirty/new files were copied and SHA256-checked against their originals, including binary content when present. The integration clone was restored from the shared-repository bundle. Embedded 0.0.6 is bundled separately; the untracked generated decompiler tree is outside integration scope and explicitly recorded as skipped.

- `shedstream.bundle`: 100354477 bytes; SHA256 `ef2fcf00bb487f09310e5a96971cb470d5d8ad0e76596b0d0878bddf228e38c4`.
- `manifest.json`: SHA256 `62c48bb9a31d0dc67d42f5489716f97a745e203ae0f4ae9462578e4789c2a237`.
- External proof: `integration-backup-proof.json`; before/after snapshots: `audit-integration-start.json`, `audit-integration-end.json` in the task directory.

Original worktree HEADs/statuses, all local branch records, remotes and the bytes of all backed-up files were rechecked unchanged after integration.

## Validation and limits

Environment: Windows, Python 3.11, isolated virtualenv and synthetic SQLite data. Python/Node external connections were blocked; browser pet checks used mocked API responses and external-request interception. No production database, deployment, real Twitch/OBS operation or game installation was used.

- Canonical standalone backend suite: 136 tests. First pass: 133 successful; three failed because of audit-wrapper URI handling, differing synthetic DB paths, and an extra seeded channel. Those wrapper issues were corrected; all three individually returned exit 0. The suite was not represented as one uninterrupted green run. Logs: `integration-backend-suite.txt`, `integration-retests.json` and associated retest logs in the task directory.
- New migration reconciliation test: fresh schema, main-only upgrade, pet-only upgrade; both M129/M130 identities, 14 active skins, prior ownership/equipment/balance preserved, real purchase debited once, repeat migrations retain inventory and audit history. A mutation suppressing M129.pet_companions fails the test as intended.
- API no-store, lifecycle, frozen-client compatibility and all three existing pet purchase tests pass.
- Browser: 12 living pets plus legacy; all animation states, directions, bounds, resizing, reduced motion, live skin changes, missing image and profile fallback. Both retained six-pet renderers pass using `--legacy-render` (with and without `--fantasy`). The old-renderer script without that flag attempts to seek the replaced CSS animation and is not the living-renderer test.
- Pet animation/scene tests and stream-director mock unit tests pass. Backend compile, 31 frontend JS syntax checks, installation catalog validation/rejection tests and documentation duplication checks pass.
- Consistency lint passes with one expected warning: the game assembly is unavailable for policy-catalog inspection. C# binaries were not rebuilt: this merge changes no C# runtime code relative to the fresh basis.

Before adopting as main: review this candidate and the explicit deferred ledger, then run the normal Linux/Python 3.12 CI on the exact candidate SHA after separately authorizing publication. Main and the original working copies remain untouched. A future deployment additionally needs an explicit read-only reconciliation of the then-current installation/database; historical production notes alone do not prove its current state.
