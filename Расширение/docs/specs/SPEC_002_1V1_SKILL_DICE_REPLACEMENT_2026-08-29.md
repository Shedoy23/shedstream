# SPEC 0.0.2: «Повтори сигнал» / Signal Relay

**2026-08-29 · DESIGN ONLY — no code until Twitch replies**

**Job:** replace Dice with one quick, low-strain, genuinely skill-based 1v1 game on the existing seasonal-MMR surface.

## 0. Decision

Build **Signal Relay**, a simultaneous memory/accuracy duel using four large buttons. Both players see the **same** short symbol sequence, then reproduce it. Sequences grow each round. More correct progress wins. Exact equality advances to fixed harder rounds; equality at the safety cap is a **draw with zero MMR**.

No roll, wager, paid entry, random winner, prize draw, client-decided result, or chance tiebreak.

Why this T2 candidate:

- lower physical/reflex strain and latency sensitivity than Green Light/Catch the Light;
- faster/simpler on Twitch mobile than Codebreaker;
- one thumb, four large targets, no knowledge/language test;
- distinct from retained RPS and tic-tac-toe;
- server can decide solely from accuracy, never client time.

Sources: `audits/MECHANICAL_BUTTON_GAMES_2026-08-26.md`, `audits/CORE_STANDALONE_IDEAS_CONSOLIDATED_2026-08-26.md`, `audits/AUDIT_002_CONSOLIDATED_2026-08-29.md` §1 B2/§2. Dice failed because random 2d6 accrued prize-bearing ELO; Signal Relay MMR accrues only from skill wins.

## 1. Player promise

> Watch one signal. Repeat it better than your opponent. The same challenge is shown to both players.

- **Entry:** free; no 💎, Bits, 💰, item, or other stake.
- **Length:** target 25–45s; hard cap 60s.
- **Controls:** four large buttons with redundant color + shape/icon labels.
- **Skill:** short-term memory, concentration, input accuracy.
- **Spectator read:** two progress meters on the same sequence; no odds or rolling animation.

## 2. Match flow

### 2.1 Queue and ready

1. Player selects **Play Signal Relay**.
2. Server enters free matchmaking, using rating band where practical.
3. Pair receives opponent name, connection preflight, and 10s Ready prompt.
4. Failure to ready cancels without match/MMR.
5. Both ready → server creates immutable `match_id`, player nonces, challenge plan.

First-time players complete one unranked three-symbol tutorial: watch → wait for **YOUR TURN** → repeat. It carries no MMR/reward.

### 2.2 Ranked stages

| Stage | Length | Reveal | Input allowance | Purpose |
|---|---:|---:|---:|---|
| 1 | 4 | 550ms on + 200ms gap | 2.0s/tap | accessible opening |
| 2 | 6 | 500ms + 180ms | 1.8s/tap | main comparison |
| 3 | 8 | 450ms + 160ms | 1.6s/tap | separation |

Each stage:

1. server puts both in `REVEAL` and releases the same sequence step-by-step;
2. buttons remain disabled during reveal;
3. server opens `INPUT` after reveal;
4. each tap sends `{match_id, stage, input_index, symbol, nonce}`;
5. server validates next expected symbol and returns only progress/end state;
6. wrong symbol, duplicate index, or expired generous deadline ends that player's stage;
7. opponent inputs remain hidden until both finish, preventing copying/tactical stopping.

### 2.3 Score and exact ties

Score is:

```text
(stages_completed, total_correct_prefix_symbols)
```

Compare first field, then second. **Time is not scored.** Example: completing stages 1–2 plus five correct symbols in stage 3 gives `(2,15)`.

Exact tie after stage 3 → shared stage 4 (length 10), then stage 5 (length 12). Still equal → `draw_exact_tie`, zero MMR to both. Never coin-flip, randomize, or use faster network as tiebreak.

## 3. Shared challenge and accessibility

Server derives one plan before play:

```text
challenge_seed = HMAC(server_secret, match_id || season_id || rules_version)
```

- Identical symbol at every position for both players.
- Difficulty constraints: max two identical symbols consecutively; all four symbols appear in each base stage; schedule fixed by rules version.
- Future sequence is not sent wholesale; symbols release one reveal event at a time.
- Persist seed commitment/rules version; optionally reveal seed after match.

The seed selects a **shared test**, not a winner or value. It cannot favor either player.

Accessibility:

- color + icon/shape + stable position; never color alone;
- optional audio/vibration supplements visual signal;
- large one-thumb targets; no rapid multi-touch;
- reduced motion uses high-contrast state changes at identical cadence;
- generous deadlines; correctness, not speed, scores;
- ranked presentation settings never alter sequence, deadline, or scoring.

## 4. Server authority, timing, anti-cheat

State machine:

```text
QUEUED → READY → REVEAL_n → INPUT_n → RESOLVE_n
       → (NEXT | TIEBREAK | COMPLETE | DRAW | VOID)
```

Client renders state/submits button identities. It never submits time, correctness, score, winner, or MMR.

- Server monotonic clock owns input windows; client clock ignored.
- Timing only determines arrival inside a generous window; it never ranks correct players.
- Bad connection fails preflight rather than silently becoming a loss.
- Rotate nonce each stage; require exact next input index.
- Reject reveal-time, duplicate, skipped, stale/future, and post-close inputs.
- Rate-limit impossible cadence; suspicion triggers review, not an opaque/random winner.
- Persist append-only sequence commitment, transitions, inputs/rejections, disconnects, result, MMR transaction id.
- MMR transaction is idempotent and applies once after terminal server result.

Browser automation cannot be eliminated, but client result forgery, replay, or future-sequence extraction is non-authoritative.

### Disconnects

| Event | Result |
|---|---|
| Before both ready | cancel, no MMR |
| Server/service failure | void, no MMR |
| Both disconnect | void, no MMR |
| One disconnects before any input | one short reconnect grace, then void initially |
| One leaves after ranked input | forfeit after grace; opponent wins |

Initial rollout should void ambiguous infrastructure failures, not manufacture a “skill” win from network luck. Forfeit must be narrow, published, and evidenced.

## 5. Seasonal MMR integration

Replace the dice result producer; reuse ladder UI/lifecycle.

Allowed terminal rating inputs:

- `skill_win/loss`: server comparison of accuracy score;
- `forfeit_win/loss`: only under published disconnect rule;
- `draw_exact_tie`: zero delta;
- `void`: zero delta/no match count.

Prohibited inputs: roll totals, seed value, reveal timing, client score, participation alone, spend/stake, pet/guild boosts, balance, paid status.

Invariant:

```text
MMR changes only from a validated head-to-head skill result.
Standing deterministically follows those MMR changes.
No random event awards rating, eligibility, standing, or tiebreak advantage.
```

- Free entry; no purchase changes window, sequence, scoring, or matchmaking.
- Win/loss feeds existing rating formula; exact tie/void = zero.
- Published ladder tiebreak recommendation: higher MMR → more skill wins → fewer matches to reach it → shared rank; never draw lots.
- **Do not migrate Dice ELO.** It came from random 2d6 and would contaminate the skill ladder. Start a new discipline/season or reset explicitly.
- Dice history may remain labelled `Dice (retired)` but cannot determine rank/seed/reward eligibility.

### Rewards and rules

Jim T4-C is authoritative for final reward wording. Preserve:

- in-app rules, dates, eligibility, ranking/tiebreak formula, prizes;
- organizer/sponsor disclosure and “Apple is not a sponsor” (Apple 5.3.2);
- no consideration, wager, pooled pot, paid advantage, or random selection;
- seasonal standing derives only from recorded skill wins/published MMR math.

Safest default is deterministic non-transferable status (title/badge/pennant). If Scope B keeps existing disclosed top-three 💎 amounts, Jim must explicitly approve that exact skill-contest model/rules before code/submission; this spec does not silently change the prize.

## 6. Reviewer-facing skill argument

> Signal Relay is a free head-to-head memory game. Both players see the identical sequence under identical rules and reproduce it with four buttons. The server validates every input; whoever accurately reproduces more wins. The shared sequence defines the common puzzle and cannot favor either player. Speed is not scored. Exact ties receive additional identical sequences or a draw with no rating change. There is no stake, random winner, chance-based rating gain, purchasable advantage, or prize draw. Seasonal standing changes only from server-verified skill wins.

This fixes audit blocker B2: Dice ELO accrued from random rolls; Signal Relay MMR accrues only from demonstrated memory/accuracy.

## 7. Compliance properties

### Twitch §5.3 / reviewer posture

- free entry; no wager, buy-in, transfer, or cash-out;
- no Bits for entry, advantage, or eligibility;
- no random outcome-for-value or casino/dice/roll/odds presentation;
- no paid modifier; any future 💎 cosmetics exact/noncompetitive;
- UI says **memory game**, **match**, **rating**, **season**, not bet/lucky/gamble.

### Apple 4.7

- generated sequence is a common challenge, not a reward draw;
- no randomized item, rarity, reveal, or value;
- no purchase affects challenge/outcome.

### Apple 5.3.2

- official rules shown before ranked entry and linked from ladder;
- rules state organizer, eligibility, dates, winning method, deterministic tie policy, prizes, and “Apple is not a sponsor”;
- prize disclosed beforehand and awarded from published skill standing, never chance.

## 8. Later build acceptance criteria

1. Both clients receive identical revealed symbols.
2. Client cannot submit time, score, result, or MMR.
3. Replay/skip/duplicate cannot advance score.
4. Wrong symbol deterministically ends that player's stage.
5. Equal play runs fixed harder stages; cap equality draws/zero MMR.
6. Time never breaks score tie.
7. Dice history/rating cannot seed this ladder.
8. Only validated skill result/narrow forfeit changes rating; draw/void do not.
9. Failure/disconnect cannot fabricate win or double MMR.
10. Controls work without color and with reduced motion.
11. Entry remains free; no paid gameplay modifier.
12. In-app rules match Jim's approved reward contract.

## 9. Owner questions

1. **Reward:** retain disclosed top-three 💎 only if Jim approves the skill-contest rules, or use status-only title/badge (safest)?
2. **Reset:** confirm clean Signal Relay rating with no Dice-ELO migration (recommended).
3. **Length:** 3 base + max 2 tie stages (recommended), or longer?
4. **Disconnect:** void ambiguous early disconnects (recommended), or every post-ready disconnect forfeits?
5. **Theme/name:** neutral `Signal Relay / Повтори сигнал` (recommended), or ShedLink-specific non-casino skin?

None blocks design handoff. Reward language waits for Jim T4-C; implementation waits for Twitch.
