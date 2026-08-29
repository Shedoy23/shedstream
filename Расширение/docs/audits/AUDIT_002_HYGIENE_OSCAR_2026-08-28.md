# Engineering-hygiene gap audit for an ideal 0.0.2

**Date:** 2026-08-28

**Scope:** tests, monitoring, backups, migrations/schema, shipped artifacts, security posture. Read-only inspection; ranked by release risk.

## Executive result

The repository has good local safety tools and 60 standalone Python tests, but the release evidence chain is not enforceable end to end. The largest gap is that CI cannot fail on backend tests. This workstation also has no runnable Python, so there is no fresh compile/lint/test verdict. Backups are **not a gap**: RUNBOOK.md §4 «Бэкапы и восстановление» records three working tiers, including offsite pull and restore verification.

> **Correction, 2026-08-29:** the “no runnable Python” conclusion was a PowerShell launcher/PATH false negative. Running the canonical suite through Git Bash `python` proved 63/63 standalone Python and JavaScript tests green. The CI masking finding remained valid and was fixed separately.

## Ranked gaps

### 1. CRITICAL — CI masks every backend-test failure

**What breaks if ignored:** code can merge and look release-ready while standalone tests fail, hang, or never run. The canonical runner judges scripts by exit code and timeout; CI invokes `pytest` and guarantees success with `continue-on-error: true` plus `|| true`.

**Cheap first step:** run `python scripts/run-backend-tests.py` in CI, remove both failure masks, and make its exit code blocking after one clean CI run.

**Evidence:** `.github/workflows/ci.yml:48-59`; `scripts/run-backend-tests.py:41-74`; **60** `Расширение/backend/tests/test_*.py` files. RUNBOOK.md:594-609 says the runner and exit codes are authoritative.

### 2. HIGH — No fresh executable release verdict is possible on the owner's workstation

**What breaks if ignored:** 0.0.2 can be tagged/packaged without proof that Python compiles, consistency invariants pass, or backend tests exit cleanly. This is an unverified build, not a source-test failure.

**Cheap first step:** restore a pinned Python 3.12 environment and add a bootstrap/preflight gate with an actionable error when Python/dependencies are absent; rerun compile, lint, and the standalone runner.

**Evidence (2026-08-28):** `python` is not recognized. `py -0p` printed `No installed Pythons found!`; `py -m compileall -q .` and `py scripts/lint_consistency.py` returned exit **112**. The same missing Python 3.11 path prevents `mempalace` launch.

### 3. HIGH — Production failures rely on a human noticing logs or running preflight

**What breaks if ignored:** critical background functions can remain broken while `/health` stays 200. OAuth refresh already failed 448 times for three weeks without a visible alert; the same class can silently stop rewards, EventSub, backup verification, or loops.

**Cheap first step:** send one deduplicated owner-visible alert for failed OAuth refresh, failed/stale backup verification, loop death, and repeated 5xx, including last-success times. Use the existing Telegram/dashboard path.

**Evidence:** RUNBOOK.md:708-731 documents the 448 failures and says visible alerting is “ещё не сделано”; `Расширение/backend/routes/streamer.py:1102,1189` still prints refresh failures. `/health` is a lightweight DB check (`main.py:355-360`); `scripts/preflight.ps1` is manual. `tests/test_background_loops_survive.py:14` says a loop can stop while `/health` remains 200.

### 4. HIGH — Shipped-artifact/source provenance is not a blocking reproducible gate

**What breaks if ignored:** submitted/installed ZIP, DLL, or EXE can differ from reviewed source, and audits can inspect the wrong code. The submitted frontend is intentionally pinned while HEAD moved substantially; Bannerlord is not built in CI.

**Cheap first step:** generate a release manifest containing commit/tag, deterministic file list, SHA-256 for every artifact, and verifier output; retain it beside the exact Twitch ZIP and signed packages. Require rebuild or verified byte-match before submission.

**Evidence:** `git diff --stat submit/0.0.2..HEAD -- Расширение/frontend` reports **18 files, 2,369 insertions, 1,317 deletions**. RUNBOOK.md:288-300 pins the submitted archive; RUNBOOK.md:1188-1207 warns audit archives have described stale code. `.github/workflows/ci.yml:61-63` does not build BannerlordLink. `dist/releases/` contains many historical/diagnostic packages.

### 5. MEDIUM — Migration correctness depends on conventions and a local lint that was not run

**What breaks if ignored:** source, migration, and production schemas can diverge; a migration recreating `viewers` can remove points-ledger triggers and make financial reconciliation incomplete.

**Cheap first step:** add a blocking fresh-install plus upgrade-from-snapshot migration CI job and assert required triggers/tables/columns. Add the proposed rule that any `CREATE TABLE viewers` migration must restore ledger triggers.

**Evidence:** RUNBOOK.md:764-766 records code↔migration drift. DEFERRED.md:285-293 says `trg_points_ledger_*` may not survive recreation of `viewers` and proposes an unimplemented guard. The migration-wiring lint could not execute (exit 112). Migration tests exist, but finding 1 makes backend tests non-blocking.

### 6. MEDIUM — No automated dependency, secret, or static-security gate

**What breaks if ignored:** vulnerable dependencies, committed credentials, or reintroduced insecure patterns can ship while compile/consistency checks pass. The April audit is historical evidence, not continuous enforcement.

**Cheap first step:** add blocking `pip-audit`, reviewed `npm audit --omit=dev`, and a secret scanner such as gitleaks; retain targeted regression tests for fixed critical classes.

**Evidence:** `.github/workflows/ci.yml` has no dependency audit, secret scan, CodeQL/Bandit/Semgrep equivalent, SBOM, or Dependabot configuration. `Расширение/docs/SECURITY_AUDIT_2026-04-30.md` predates this audit by four months and originally recorded 13 critical and 9 high findings.

### 7. LOW — Working backups share the alerting blind spot

**What breaks if ignored:** a future failed pull or restore verification can remain unnoticed until recovery. This is **not** a missing-backup/offsite finding.

**Cheap first step:** expose last successful pull, last restorable verification, and backup age in the owner-visible health summary from finding 3.

**Evidence:** RUNBOOK.md:134-188 documents three working tiers and automated restore verification after offsite pull. Results go to `pull-backup.log`; no repository evidence shows an alert consumer for stale/failed results.

## Checks attempted

| Check | Result | Interpretation |
|---|---:|---|
| `python -m compileall -q .` | could not start | No Python command; not a source verdict |
| `py -m compileall -q .` | exit 112 | No installed Python |
| `python scripts/lint_consistency.py` | could not start | No lint verdict |
| `py scripts/lint_consistency.py` | exit 112 | No lint verdict |
| standalone `tests/test_*.py` | not runnable | 60 files present; no Python runtime |

## Explicit non-findings

- Backups are DONE in three tiers; offsite is present and intentionally pulled to the owner's PC.
- Frontend HEAD differing from `submit/0.0.2` is intentional during review. The gap is provenance/enforcement, not the drift itself.
- Old security-audit items are not re-reported as current vulnerabilities without re-verification.
