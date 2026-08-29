# AUDIT 002 — Consolidated: what the project lacks + the path to an "ideal 0.0.2"

**Date:** 2026-08-29 · **Orchestrated by:** god (Michael) · **Origin:** owner ask (use the Twitch-reply wait to audit gaps + design the ideal 0.0.2).

Four independent, read-only audits, one dimension each. No code changed anywhere.

| Dim | Owner | Source doc |
|---|---|---|
| Compliance-readiness | Jim (Codex) | `AUDIT_002_COMPLIANCE_JIM_2026-08-28.md` |
| Product / mechanics | Pam | `AUDIT_002_PRODUCT_PAM_2026-08-28.md` |
| Engineering hygiene | Oscar | `AUDIT_002_HYGIENE_OSCAR_2026-08-28.md` |
| UX / polish | Dwight | `AUDIT_002_UX_DWIGHT_2026-08-28.md` |

---

## 0. The one structural fact that reframes the whole 0.0.2 plan

**`extension.html` and `mobile.html` are IDENTICAL today** (Jim, machine-checked: `data-action` sets match exactly, `<script src>` sets match exactly). The T1 "gate a compliant subset on mobile" plan assumed the shells could differ — **that divergence mechanism does not exist yet**, and every blocker below currently stands on **desktop too**.

Consequence — for 0.0.2 we pick ONE of:
- **(A) Build the divergence mechanism first**, then hide flagged mechanics on the mobile shell only (desktop keeps them). More moving parts + a new compliance test to keep the shells honest.
- **(B) De-gamble / fix on BOTH shells (one truth).** Simpler, no divergence machinery, no "two versions drift apart" risk. Recommended for most blockers.

---

## 1. Compliance (Jim) — the gate to submission

Rules re-fetched 2026-08-29 from dev.twitch.tv + developer.apple.com.

### BLOCKERS — chance-for-value (fail the Apple 4.7 loot-box read)
| # | Mechanic | Evidence | Note |
|---|---|---|---|
| B1 | **Cases** — drop tier decides VALUE, 1 000💎…500 000💎 = **500× spread rolled by RNG** | `bot_core.py:1119,1165-1168,55-60`; `config.py:507-512` | OK under Twitch §5.3 (no money value), fails Apple 4.7 |
| B2 | **Dice season prize (NEW)** — ELO accrues from **random 2d6 rolls**, top-3 by ELO get 300K/200K/100K crustics, prize amounts **printed on screen** | `dice.py:66-77,59-60,283-306`; `duels.js:100-122` | Breaks the "seasonal prizes are the safe remainder" assumption — true for tic-tac-toe/RPS, **FALSE for dice: the ladder itself is random** |
| B3 | Paid **random skill XP** | `viewer-bannerlord.js:4043-4061`; `bannerlord.py:1926-1940`; `AddSkillXpHandler.cs:84-150` | confirms 26.08 |
| B4 | **Random equipment** — block header literally reads "🎁 Случайный товар", 1 000 000💰 tags | `viewer-bannerlord.js:3727-3760`; `EquipItemHandler.cs:105-190` | reads as a loot box **faster than the cases do**; "dinars≠crustics" defence fails — `4035-4041` sells dinars for crustics on the same screen |
| B5 | Paid **random NPC marriage** | `viewer-bannerlord.js:4484-4489`; `bannerlord.py:2029-2048`; `MarryHandler.cs:88-165` | confirms 26.08 |

### RISK-HIGH (both NEW)
- **B6 Tournament trophy generator is ALIVE.** UI promises "победитель получает 50 000💰 + XP + приз" (`viewer-bannerlord.js:1005`); `_adapter.py:2231-2240` → `generate_prize_item()` → `bannerlord_custom_items.py:176-193` rolls rarity 50/30/15/5 **and** rolls stats. On 29.07 the smithed-item odds disclosure was deleted from both shells because "the mechanic died" — **the forge died, the generator did not.** Breaks our own claim "the only random element is the case tier." **Mitigation:** the item is never rendered — `GET /api/bannerlord/custom-items` is called nowhere in `frontend/`.
- **R1 NO official contest rules anywhere** (machine-checked: zero hits for rules/правила конкурса/sponsor/sweepstake in `frontend/*.html|*.js`) — yet `duels.js:100-122` announces season end + 3 prize places + ELO gate, and the tournament announces prizes. **Apple 5.3.2 requires official rules PRESENTED IN THE APP + "Apple is not a sponsor."** A separate rejection ground from 3.5 nobody has named — costs a **static text block, no code.**

### Other NEW
- **R2** No age-gate exists and we cannot build one (Apple 4.7.5 puts the mechanism on the HOST) → the only lever is not exceeding 13+ content. **Do NOT propose an age gate to the platform.**
- **R3** Tic-tac-toe timeout auto-move picks a **random cell** (`tictactoe.py:180-198`) in a prize-bearing match — small, but we called it pure skill.

### 💡 Biggest UNUSED argument (free, strong)
**The extension uses NO Bits at all** (machine-checked: no `useBits`/`onBitsTransaction` in either shell). Twitch §6.2.3/6.2.4/6.2.5 — gambling-for-reward, random loot boxes, contest entry — are **ALL scoped to Bits.** A checkable fact, stronger than the "virtual currency with no monetary value" reasoning, and it was **not in the sent letter.**

### Letter status
No correction needed — "no entry cost / no stake" was TRUE (tournament is free; the 1000💎 premise is dead). BUT "the only payouts are seasonal leaderboard prizes" needs the **dice nuance (B2)**, and "the only random element is the case tier" **breaks unless B6 is closed.**

### Keep RPS (Jim recommends, objects to hiding)
`rps.py:53` declares `_rng` and never uses it — pure PvP simultaneous choice, **zero system randomness.** A verifiable argument for the reviewer.

### CLEAN & verified
No transfer/donate/cash-out; disclosed case odds 70/25/4/1 match `bot_core.py` exactly; cases genuinely unbuyable; lexicon clean; RimWorld/shedcolony manifests have no random actions; the packager ships only `extension.html`+`mobile.html`+`config.html`, so the marketing `index.html` (with its "Boosty" line) never reaches Twitch.

---

## 2. Product / mechanics (Pam) — what's missing as a game

- **P0** No closed, module-independent engagement loop / consumer → weak return motivation.
- **P0** Dice removal leaves a quick-play hole (decision: 1v1 skill + existing seasonal MMR; exact mechanic parked pending Twitch; Tug-of-War rejected). ⚠️ Note the collision with Jim B2 — the seasonal-MMR reward is only safe if the ladder is **skill, not random**.
- **P0** `active_clicks`/`mouse_moves` are DROPPED while passive presence earns **25💎/min** → the economy literally teaches idling.
- **P1** Guild treasury/skills, pets, family/marriage store state but **lack consumers** ("state without a consumer").
- **P1** Cases removal lacks a deterministic collection cadence to replace the reward rhythm.
- **P1** Identity fragmented; no standalone streamer-session format that composes the systems.
- **P2** Quick games are islands; sinks buy stored state more than consequences.
- **N=1 caveat:** zeros do not prove non-use; social mechanics need multi-viewer validation.

---

## 3. Engineering hygiene (Oscar) — what's rotted

- **CRITICAL** CI masks ALL backend test failures (`continue-on-error` + `|| true`) and skips the canonical standalone runner → **60 Python tests are non-blocking / decorative in CI.**
- **HIGH** Workstation has no runnable Python (`py` exit 112) → no live green evidence could be produced (env limitation to fix or note).
- **HIGH** Operational failures (e.g. OAuth refresh) still rely on log/manual preflight; `/health` can stay green while broken.
- **HIGH** Shipped-artifact ↔ source provenance is not blocking/reproducible; **submitted frontend differs from HEAD by 18 files (+2369/−1317)**; Bannerlord not built in CI.
- **MEDIUM** Migration/schema + points-ledger-trigger drift lacks blocking upgrade assertions.
- **MEDIUM** No dependency/secret/static-security gate.
- **LOW** Three-tier backups **work** (offsite is NOT a gap), but failure/freshness shares the alerting blind spot.

---

## 4. UX / polish (Dwight)

- **P0** `viewer-bannerlord.js:43-105` maps async `recent_refunds` reasons through a **frozen JS dictionary** → every unknown backend/mod reason collapses to generic "Действие не удалось" → **thin-front violation, drives re-clicks.**
- **P1** `_bannerlordBuyAction` doesn't forward the deferred `successMessage` opts → paid+ASYNC actions (create_vassal_clan etc.) lack a guaranteed "заявка принята, исход позже" toast → viewer re-clicks & overpays (the "объявление войны 4 раза" class).
- **P1** Hardcoded mutable prices/limits in the frozen frontend: TTS 5000/200, RimWorld pawn 200 + trait removal 300, marriage proposal 100, detachment 10/30, plus Bannerlord price fallbacks → frozen UI can show/disable on stale values.
- **P2** `BNR_POWER_META` + workshop catalog frozen → description drift (documented in-code); streak next-reward computed locally.
- **PASS** Shell markup at parity; ordinary HTTP refusals already render arbitrary `result.message`; shared paid path has single-flight/idempotency/balance refresh; war/peace confirmations exist.

---

## 5. Cross-dimension synthesis — the real punch list

Two themes recur across dimensions:
1. **"State without a consumer"** (Pam P0/P1) — the core game accrues value nothing spends, and the economy rewards idling.
2. **"Frozen frontend as a single point of drift"** — Dwight's hardcoded prices + refund dict, Oscar's 18-file shipped-vs-HEAD gap, and the fact both shells are identical (Jim §0) are the same weakness: the thin-front rule isn't enforced and there's no gate keeping shipped == source == compliant.

### MUST-FIX before any 0.0.2 submission (cheap, no feature loss)
- **M1** Add **official contest-rules text** in-app (Apple 5.3.2) — static block, no code. (Jim R1)
- **M2** **Close B6** — stop the tournament from advertising/generating a random-stat trophy (drop the generator call or fix the prize to deterministic). Restores "only random element is X" truthfully. (Jim B6)
- **M3** Lead the reviewer reply with the **"no Bits" argument** (Jim) + the dice-prize nuance (B2). Free, strongest lever.
- **M4** Fix **Oscar CRITICAL** (CI stops masking test failures) — independent of the review, dangerous to leave. (Oscar)

### DE-GAMBLE set (real work; keeps features per 26.08 "by choice, not hide")
- Cases (B1), dice ladder (B2), skill XP (B3), equipment (B4), marriage (B5) → deterministic **choice** instead of RNG, OR hidden from the submitted build.

### PRODUCT / POLISH (can land after 0.0.2 ships)
- Consume `active_clicks` / add a consumer loop (Pam P0); refund-reason + async toasts + prices-from-backend (Dwight P0/P1); provenance + alerting gates (Oscar).

---

## 6. The decision for the owner

Submission is gated on the Twitch reviewer's reply anyway, so there is time to design well. Three scopes:

- **Scope A — Minimal safe-pass.** M1–M4 + **hide** cases/dice/3 Bannerlord random-paid from the submitted build (don't redesign). Keep RPS + tic-tac-toe. Fastest to approval; removes features; leaves the product gaps open.
- **Scope B — Best compliant product (recommended).** M1–M4 + **de-gamble-by-choice** (cases/dice-ladder/marriage/skill/equipment become deterministic choice) + the 1v1 skill dice-replacement on a **skill** ladder. Keeps the game rich; costs a build + one review cycle to prove the model.
- **Scope C — B + product/hygiene hardening.** Everything in B plus fix the idle-rewarding economy + a consumer loop + the frozen-front/provenance gates. The "ideal" in full; the most work.

**god recommendation:** **Scope B for the submission, but do M4 (CI test-masking) now** — it's independent of the review and dangerous. Defer the deep economy redesign (C) to after 0.0.2 ships. This gets the strongest honest submission without over-committing engineering before the reviewer confirms the model.

**Also settled by the audit:** keep RPS (verifiable zero-RNG); do NOT propose an age gate (host's job); no letter correction, just the two nuances above.
