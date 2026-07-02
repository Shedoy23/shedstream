# Core-mechanics audit — 2026-07-02

Adversarial audit of core-platform mechanics (12 mechanics, 45 agents, each finding
independently verified by a skeptic). Baseline: standalone tests all green
(test_multi_tenant_isolation 1335, test_pubsub 31, test_eventsub 34, db-pool). Happy
paths work; below are edge/exploit/crash findings the tests don't cover.

**28 confirmed, 5 refuted (false alarms filtered).** Severity: 5 HIGH, 5 MEDIUM, 18 LOW.

## ✅ Fixed (commit be09da3, 2026-07-02)
- **Attendance streak exploit** — `/api/viewer/attendance` trusted client `minutes` →
  crafted `minutes=15` claimed reward without watching. Now server-time gated (m89
  `first_seen_at`, claim only after ≥15 real min). + rate-limit.
- **Duels ELO wipe** — `check_season_end` missing `game_type` filter reset ELO for ALL
  games on rollover. Now game_type-scoped. `routes/duel.py`.
- **Pet shop preview** — `list_pet_catalog` omitted `png_path` → gift-box instead of
  skin. `database.py`.
- **TicTacToe text** — "3×3 grid" → "4×4 grid". `frontend/tictactoe.js`.

## ⏳ Skipped (re-verified NOT a bug)
- marriage-accept deletes all incoming proposals to the now-married user — correct
  cleanup (they can't be accepted anyway); the audit's "fix" would leave stale rows.

## ✅ Fixed — ATOMICITY class (commit 82ae1df, 2026-07-02)
Recurring root cause: `add_points`/`remove_points` each open their OWN db connection,
so they can't be atomic with the surrounding state change. If a crash/DB-error hits
the exact window → money debited without effect, or reward double-awarded. **Fixed**
via new `Database.add_points_tx(conn,...)` / `remove_points_tx(conn,...)` (operate on
the caller's connection, no own commit) so the charge joins the same `BEGIN IMMEDIATE`
transaction as the state change. All 7 sites converted; proven by atomicity test
(rollback undoes both) + full suite 1335/1335. Was **7 instances:**
- `routes/duel.py:171` — season prize payout not atomic with season-finish mark → double-award on crash (HIGH)
- `routes/marriage.py:125` — divorce debit + state-change in separate connections → money lost on crash (HIGH)
- `routes/tts.py:123` — debit then INSERT tts row separately → 5000💎 lost if INSERT fails (HIGH)
- `main.py:1448` — viewership-milestone streak: dedup INSERT commits before add_points (MEDIUM)
- `routes/dice.py:257` — dice season prize payout non-atomic → double-pay on crash (MEDIUM)
- `routes/promo.py:71` — promo use recorded but reward not delivered if add_points fails (MEDIUM)
- `routes/tts.py:86` — TTS cooldown TOCTOU: two concurrent submits both pass the check (MEDIUM)

**Fix pattern:** perform the points UPDATE (`UPDATE viewers SET points=points-? WHERE
points>=?`, check rowcount) inline in the SAME `BEGIN IMMEDIATE` transaction as the
state change — don't call add_points/remove_points across a boundary. → candidate for
a CLAUDE.md gotcha ("charge + effect must share one transaction").

## 🟡 Pending — LOW (hardening / cosmetic, opportunistic)
- IDOR/oracle: `marriage.py:74` marriage_status reads path-username (read-only leak);
  `database.py:1379` open_case not_owner-vs-not_found cross-tenant existence oracle;
  `tts.py:179` audio endpoint defaults to DEFAULT_CHANNEL_ID when channel_id omitted.
- Thin-front hardcoded balances (same class as Bannerlord thin-front): `guilds.js`
  GUILD_CREATE_COST/MIN_CONTRIBUTE; `viewer.js:2092` TTS_COST/TTS_MAX_LEN.
- Cosmetic/harmless: `duels.js:179` extra username field (ignored server-side);
  `guilds.js:190` join button shown to existing members; `rps.py:450` stale ELO in
  poll response; `tictactoe.py:496` double UPDATE on non-finished move; `viewer.py:333`
  no rate-limit (now added); quest idempotency edges (`bot_core.py:944/970` — grant_case
  without trigger_key, completed_at committed before reward); `database.py:3063`
  leave_guild SELECT+DELETE race; `bot_core.py:1223` get_viewer_detailed_stats calls
  db methods without channel_id (dead method).

## Not fixed here = not urgent
Everything pending is either low-probability (crash-window) or low-severity. No open
exploit remains after be09da3 (the attendance one was the only free-currency hole).
