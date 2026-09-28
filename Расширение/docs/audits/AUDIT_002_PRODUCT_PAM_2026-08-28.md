# Audit 0.0.2 — PRODUCT / MECHANICS

**Pam · 2026-08-28 · design audit only, no feature spec**

Sources reused: `OVERVIEW.md`, `ROADMAP.md`, `Расширение/docs/CONTEXT*.md`, `AUDIT_REGISTER_0.0.2.md`, `TWITCH_REVIEW_0.0.2_REJECTION.md`, `audits/CORE_STANDALONE_IDEAS_CONSOLIDATED_2026-08-26.md`. The requested `python scripts/docs-search.py ...` was attempted first; no Python interpreter is usable, so its documented corpus was searched with `rg`.

Constraints: production is N=1, so zero metrics do not prove non-use. 💎 crustiki are core-only participation points; 💰 dinars are Bannerlord in-game gold. They must not be conflated.

## 1. Current-state mechanics map

| Surface/system | Viewer-facing mechanics | Product role | Limit |
|---|---|---|---|
| Desktop panel | 💎 earning; quests/promo/stats; pets; guilds; family; voting; TTS; tic-tac-toe, dice, RPS/duels; cases; game panes | Main hub | Parallel tabs accrue/display state but rarely reinforce one another. |
| Mobile panel | Compact Games/Rewards: tic-tac-toe, 2d6 dice, duels/RPS, cases | Fast action/review surface | Dice is the clearest game and the removal target; dice+cases removal leaves a play/reward hole. |
| OBS overlay | Fighter cards, TTS, active-viewer pets | Public recognition | Presentation, not a pet/gameplay loop. |
| Streamer controls | Channel/config, votes/events, pet toggle, module state | Enable/moderate | No core activity format with start, common goal and resolution. |
| Core backend | 💎 ledger; attendance/watch; quests; pets/guilds/family; votes/TTS; minigame ratings/seasons | Persistent standalone substrate | Pays passive open-panel presence (25/min); frontend sends `active_clicks`/`mouse_moves`, backend drops them. |
| Bannerlord | Adopt hero; culture/class; 13 classes/powers; combat, economy, progression, dynasty; state echo; 💎 platform actions vs 💰 world upgrades | Best realization of persistent identity | Strong loop requires a live game/module. |
| RimWorld | Viewer pawn, genes/skills/xenotypes, purchases | Potential second world | Effectively disabled; waits for Module API migration. |
| Pets | Cross-channel pet, cosmetics/equip, overlay | Portable identity/collection | State without consumer: no care, growth, agency, objective or contribution. |
| Guilds | Create/join, treasury, skills/upgrades, rank | Social/group accumulation | Working treasury grows without a meaningful outcome that consumes it. |
| Family | Proposal/marriage relationship state | Social bond | No meaningful recurring consequence or shared decision. |
| Quick games | Tic-tac-toe, dice, RPS/duels, some ELO/season framing | Immediate action | Dice removal hole; others are islands, not a mastery path. |
| Cases/rewards | Surprise/collection/reward cadence | Dopamine and sink | Review blocker; no deterministic collection replacement yet. |
| Voting/TTS | Stream steering and deterministic expression | Strongest core-native action | Episodic and broadcaster-dependent; does not bind persistent systems. |

Current core loop:

```text
open/watch/chat → earn 💎 mostly passively → spend/store in isolated mechanics
→ pet/guild/family/rating state grows → little shared objective or next-session payoff
```

Bannerlord closes identity → hero action → changed world → future-stream continuity. Core does not close independently.

## 2. Prioritized product gaps

### P0 — MISSING: one core engagement loop that closes

**Evidence:** `ROADMAP.md` promises persistent identity → character → progression → actions/relationships → continuity. T2 diagnoses pets, guild treasury and marriage as “state without a consumer.” `OVERVIEW.md` places the strongest realization inside Bannerlord.

**Impact:** the extension reads as a menu, not a game. It can create a first action but weakly answers “why return next stream?”, threatening Second Session Rate/returning viewers.

### P0 — MISSING: shipped dice replacement for immediate play

**Evidence:** the rejection doc records prominent mobile 2d6 and the conservative removal path. T2 explicitly reserves “Replace DICE / quick 1v1 thrill.” T2/tasks ledger records the owner's current decision: replacement must be a 1v1 skill game on the existing seasonal-MMR model; Tug of War is a rejected alternative, and the exact mechanic remains parked until Twitch replies.

**Impact:** removal deletes the clearest fast, legible 1v1 action. A selected design is not viewer value; Games remains thin until a skill replacement ships.

### P0 — WEAK/BROKEN: active input is collected then discarded

**Evidence:** T2 records frontend `active_clicks`/`mouse_moves` dropped by backend alongside passive 25 💎/min. The roadmap measures real viewer action, actions/stream and return.

**Impact:** economy teaches idling and cannot distinguish engagement from unattended presence or power activity progression.

### P1 — DEAD: guild accumulation lacks a coordinating outcome

**Evidence:** `AUDIT_REGISTER_0.0.2.md` verifies creation, treasury accounting and skill upgrades on live data—this is not technical breakage. T2 says treasury fills with nothing meaningful to spend on.

**Impact:** cooperation becomes bookkeeping; recruiting and repeat visits lack shared payoff.

### P1 — DEAD: pets are ownership/cosmetics without agency

**Evidence:** `OVERVIEW.md`/`CONTEXT_PETS_V3.md` document cross-channel ownership, equip and overlay; MVP intentionally avoided utility; T2 identifies no consumer.

**Impact:** once equipped, the pet asks little and changes little. The most portable identity asset cannot carry a habit.

### P1 — DEAD/WEAK: family state does not change play

**Evidence:** marriage exists (with legacy passive-income history), but T2 says it has no meaningful effect.

**Impact:** it creates a one-time social moment, not recurring cooperation, expression or progress.

### P1 — MISSING: deterministic collection cadence after cases

**Evidence:** review/audit docs put cases/odds/random reveal in the blocker set. Independent T2 work converges on visible albums/passports, exact paths and transparent tracks.

**Impact:** removal alone deletes collect-complete-return rhythm and a 💎 sink; cosmetics/pets lose discovery and completion framing.

### P1 — WEAK: identity is fragmented across tabs

**Evidence:** profile, pet, guild, family, quests and ratings exist without one outcome composing them. Bannerlord makes class, powers, gear, relationships and actions facets of one hero.

**Impact:** users accumulate several identities rather than build one legible identity; features compete instead of compounding.

### P1 — MISSING: standalone streamer session format

**Evidence:** votes/TTS are episodic, pets are presentation, strongest loop is integration-led. T2 boss/expedition/channel-goal directions all identify start → shared progress → resolution without a module.

**Impact:** without Bannerlord, a streamer cannot simply announce “tonight we do X in ShedLink”; repeat usage depends on another game.

### P2 — WEAK: quick games are islands, not mastery

**Evidence:** separate tic-tac-toe/dice/RPS and ratings exist; T2 proposes a status circuit to unify skill play.

**Impact:** matches do not advance a broader journey or connect to identity/community state.

### P2 — WEAK: core sinks lack meaningful choices

**Evidence:** 💎 funds actions/cosmetics and guild/pet spend works, yet T2 diagnoses accumulating state. 💰 correctly remains Bannerlord-only.

**Impact:** spend often buys more stored/displayed state, not consequence. More prices without consumers deepen the gap.

### P2 — EVIDENCE GAP: social mechanics cannot be judged at N=1

**Evidence:** guilds, duels, votes and leaderboards require 2+ users.

**Impact:** zero/low metrics cannot separate bad demand from untestable multiplayer. Validate with multiple users or mechanics valuable solo that compound socially.

### P3 — MISSING: second usable world for cross-game promise

**Evidence:** Bannerlord is live flagship, RimWorld disabled, ShedColony early; roadmap gates more integrations behind retention.

**Impact:** cross-world identity is architectural more than experienced, but a new integration now multiplies surfaces without fixing return.

## 3. Ranked decision view

1. Close one module-independent loop that consumes existing state and creates a next-session reason.
2. Ship a skill-based dice replacement, not merely its design.
3. Make active participation economically legible.
4. Give guild treasury, pets and family consequences—or retire/de-emphasize them.
5. Replace cases with visible deterministic collection/progression.
6. Unify identity across profile/pet/guild/family/mastery.
7. Give streamers a core-native session format.
8. Connect quick games to mastery/community progress.
9. Validate social mechanics with multi-viewer evidence; N=1 zeros are inconclusive.
10. Defer new worlds until the current experience earns second sessions.

This stops before feature specification. T2 contains candidate directions; this audit defines the product jobs they must solve.
