# Compliance review — Tug-of-War

**Reviewer:** Jim  
**Date:** 2026-08-26  
**Verdict:** **PASS-WITH-CHANGES**

## Independent read

The core mechanic is not gambling: entry is free, the player performs a visible action, team position is computed by a deterministic formula, and no stake or pool is created. Rope/team/tap imagery is ordinary competition rather than casino presentation.

However, the current spec attaches 💎 specifically to the winning team. That creates a mobile reviewer-visible chain of **choose a side → collective outcome partly outside one viewer’s control → receive currency if that side wins**. It is not legally equivalent to a wager because there is no consideration/stake, but it is unnecessarily close to prediction/betting presentation—especially after this exact extension was flagged under Twitch 3.5. The compliant mobile MVP should separate participation currency from outcome: fixed equal participation 💎 for every qualified participant; winning team receives badge/status only.

Official references checked on 2026-08-26:

- Twitch Extensions rule 3.5 requires mobile compliance with Apple §4.7: https://dev.twitch.tv/docs/extensions/guidelines-and-policies/
- Twitch permits exchange for loyalty-based points under commerce rule 5.2, while its Bits rules prohibit paid contest entry and wagering (useful policy analogy even though 💎 are not Bits): same policy page, §§5–6.
- Apple treats HTML5/JS mini-games as software governed by its guidelines (§4.7), and contests require developer sponsorship plus in-app official rules stating Apple is not involved (§5.3.1–5.3.2): https://developer.apple.com/app-store/review/guidelines/
- Apple’s current age-rating definitions allow frequent contests at 13+, while gambling/frequent simulated gambling escalates higher: https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions

## Required changes before build

### Blockers

1. **Remove outcome-contingent 💎.** Award the same fixed participation amount to every qualified participant, regardless of team result. Winner badge/title and top-contributor mention may remain status-only and nontransferable. Do not call participation points a consolation prize.
2. **No chance fallback anywhere.** Team selection must remain voluntary; never randomize/auto-assign teams. A tie that survives sudden death must resolve as a draw with no winning-side status, or by a published deterministic metric. Never coin-flip, randomly select a winner, or award a random participant.
3. **Publish official rules in the mobile Extension before joining.** Include sponsor/developer identity; “no purchase/payment necessary”; eligibility; round/season dates and UTC/time zone; exact scoring, decay and normalization; minimum qualifying participation; tie/disconnect rules; exact status/participation rewards; disqualification/anti-abuse; privacy/public-name behavior; and that Apple is not a sponsor or involved. State Twitch is not the sponsor as a prudent additional clarification.
4. **Make normalization deterministic, bounded and auditable.** Use one published server formula with fixed-point/integer arithmetic. Freeze the team-size basis at the end of the join window (or publish an equally deterministic alternative); do not silently change past tap value as viewers switch/join. Team choice must lock when contribution begins.

### Should

1. Rename reward language to **“fixed participation credit”** and outcome language to **“team result/status”**. Avoid “bet”, “stake”, “odds”, “pot”, “jackpot”, “payout”, “win currency”, “double”, “risk”, and casino celebration patterns.
2. Set a disclosed qualification floor (for example, at least X effective taps over Y seconds) so opening the panel/one tap cannot farm participation rewards. The floor must be identical and deterministic.
3. Keep top-3 recognition status-only. Rank by a disclosed effective-contribution metric after decay; show the formula/help link. Do not attach 💎 to rank.
4. Validate broadcaster-provided team names with length/content constraints, give the broadcaster reset/remove controls, and ensure published names are attributable/moderatable under Twitch user-content rules.
5. Display a concise currency disclosure near the first reward mention: 💎 are earned loyalty points, non-purchasable (under the current model), nontransferable, noncashable, have no monetary value; participation is free; exact credit is stated before joining. No odds disclosure is needed because there must be no odds.

### Nice

1. Prefer “round complete / team result” visuals over showers of gems, spinning counters, near-miss rope snaps, or urgent “one more tap to win rewards” copy.
2. Provide reduced-motion mode and accessible tap targets; cap useful taps so accessibility/autoclick speed is not decisive.
3. Show a post-round contribution breakdown (effective taps, decay, frozen team factor) so users can reproduce why the rope ended where it did.

## Answers to spec §13

### 1. Does team-size normalization read as fair balance?

Yes, if disclosed, deterministic and frozen/reproducible. It reads as manipulation if weights change invisibly during the round or past contributions are retroactively revalued. Freeze team counts at join close, publish the multiplier and cap, lock side choice after the first effective tap, and calculate server-side using fixed-point integers.

### 2. Do fixed 💎 for winners read as a prize for outcome?

Yes. It is a contest prize, not a wager in the strict sense because entry is free and nothing is risked. But the viewer cannot individually control the aggregate team outcome, so the mobile presentation resembles a free side-prediction with currency attached. After the existing 3.5 flag, that is too much review ambiguity for little product value.

### 3. Are season status prizes enough, or must round 💎 go?

For the conservative mobile MVP, round **winner-only 💎 must go**. Keep equal fixed participation 💎 for qualified players, and use winner badges/titles/Hall-of-Fame status for round and season outcomes. Status contests still need official rules under Apple §5.3.1–5.3.2.

### 4. Hidden gambling read?

The hidden risks are: voluntary team choice becoming a de facto free prediction; a random/opaque tiebreak; random auto-assignment; live normalization that users cannot reproduce; gem bursts/payout language; winner currency multiplied by streaks; paid cosmetics that also increase contribution; top-contributor currency; and any future 💎 entry/boost that affects outcome or eligibility. Explicitly prohibit each in acceptance tests.

## General policy and engineering invariants

### Multi-tenant isolation

The design is feasible but every primary/unique/foreign key and query must include `channel_id`: rounds, team definitions, memberships, tap aggregates, award ledger and seasonal standings. A bare `round_id` generated per channel is unsafe unless globally unique; safest logical identities are `(channel_id, round_id, user_id)`. Overlay subscriptions and broadcaster start/stop must also be channel-scoped.

### Reward atomicity and idempotency

There is no charge path in the compliant MVP, which simplifies atomicity. Resolution must use a single-winner state transition (`active → resolving → resolved`) plus an award ledger with a unique `(channel_id, round_id, user_id, reward_kind)` constraint. Insert ledger row and add fixed points in the same DB transaction; retries become no-ops. Snapshot/finalize effective contributions before awards. Bulk awarding can create a SQLite write lock, but it is manageable with one short transaction or deterministic batches backed by the unique ledger. Never compute rewards from mutable live counters after resolution.

## Acceptance-test summary

- Free entry and no balance check/deduction.
- Equal fixed participation 💎 irrespective of winning/losing side.
- Winner/top-contributor/season rewards are status-only.
- No random team assignment, random tiebreak, random reward, or random multiplier.
- Formula, qualification, tie rules and exact reward visible before join.
- Official rules accessible in mobile UI; Apple non-sponsor statement present.
- No casino/betting/payout/odds/pot language or near-miss animation.
- Channel isolation and idempotent single award proven under concurrent resolution/retry.
