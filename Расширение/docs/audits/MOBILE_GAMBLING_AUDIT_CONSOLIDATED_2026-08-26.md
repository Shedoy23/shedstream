# Mobile View — gambling-orientation audit, CONSOLIDATED (two independent passes)

Date: 2026-08-26 · Requested by owner (remote-control, conv-236704).
Two independent auditors, no shared conclusions before each formed its verdict:
- **god / Michael** — `MOBILE_GAMBLING_AUDIT_GOD_2026-08-26.md`
- **Jim** (jim-mtadc7c2) — `MOBILE_GAMBLING_AUDIT_JIM_2026-08-26.md`

Lens (both): how the MOBILE surface READS to a Twitch/Apple §4.7 reviewer at a
13+ age rating — not our internal economics. READ-ONLY audit; **no code changed**.

---

## ⚠️ CORRECTION (2026-08-26, verified in code by Jim + prod)
**The "paid-entry 1000💎 tournament" below was WRONG — the tournament is, and was,
FREE.** Backend enforces `TOURNAMENT_JOIN_PRICE = 0` (`routes/bannerlord.py:1089`,
forced to 0 at 2385-2386); a now-added regression test proves a hostile
`price=999999` is charged 0. The "1000💎" was a STALE code comment + a stale
frontend missing-config fallback (`viewer-bannerlord.js:925`), both since fixed
(commit 3728b18). god's earlier "verified in code" read the DISPLAY string and the
comment, not the enforced price — a real mistake.
**Consequences:** (a) the sent Twitch letter's "no entry cost, playing is free"
was TRUE — there was NO contradiction and NO concealment risk (§4 below is void).
(b) The tournament is at most a FREE competition with in-game-gold prizes, not a
paid-entry blocker; re-assess its mobile severity accordingly.
**Re-verified (Jim, enforced backend + registered mod execution, `BANNERLORD_BLOCKERS_REVERIFY_2026-08-26.md`):**
- Paid random skill XP — **REAL BLOCKER** (500/1000/5000💎 enforced; `AddSkillXpHandler.cs` picks skill via `Random`). Nuance: backend doesn't force blank skill_key, so a crafted API payload could pick a deterministic skill — but the mobile OFFER is paid/random.
- Random equipment box — **REAL BLOCKER** (Hero.Gold 500K/1M enforced; `EquipItemHandler.cs` selects via `MBRandom.RandomInt`).
- Paid random NPC marriage — **REAL BLOCKER** (50K Hero.Gold enforced; `MarryHandler.cs` picks NPC via `MBRandom.RandomInt`).
- Crystal→dinar — **NOT A BLOCKER** (deterministic: fixed preset in → fixed dinars out, no roll; keep). It can fund the random paths but itself rolls nothing.
**Net verified mobile blocker set:** dice + cases (core) + paid random XP + random equipment + random marriage (Bannerlord). Tournament (free) and crystal→dinar (deterministic) are OUT. RPS = separate reframe/hide call.

### FIX DIRECTION (owner 2026-08-26) — de-gamble by CHOICE, not hide [EXPLORE NEXT SESSION]
The 3 real Bannerlord blockers are gambling only because the OUTCOME is RANDOM.
Make the outcome viewer-CHOSEN → deterministic paid action → compliant → KEEP on
mobile (no hide needed). Same pattern for all three:
- **Marriage:** viewer picks the NPC (from an eligible list) instead of `MBRandom`
  choosing. Owner's explicit steer. Deterministic → not a gambling read.
- **Skill XP:** viewer picks the skill. NOTE: backend ALREADY accepts a concrete
  `skill_key` (Jim: it doesn't force blank); the UI just omits it → send a chosen
  skill and drop the "random" framing. Likely the smallest change of the three.
- **Equipment:** viewer picks the item/category instead of `MBRandom.RandomInt`
  from a pool (offer a visible catalog with fixed price → fixed item).
Result: pay 💎/dinars for a KNOWN outcome = an "Exact Workshop"-style deterministic
purchase (matches Jim's earlier compliant-sink pattern), no lootbox read. This is
preferable to hiding — it keeps the features on mobile. Scope/spec next session.
Parked with the rest pending Twitch reply.

## 1. Headline (what the independent audit changed)

The rejection-doc analysis and god's first pass both scoped the audit to the
**🎮 Игры / 🎁 Награды tiles only** (tic-tac-toe, dice, duels, cases) and treated
the **Integration (Bannerlord) tab as out of scope**. Jim traced what
`mobile.html:497-525` actually loads and found the **strongest blockers live in
the Integration tab** — verified by god in code:

- **Paid-entry prize tournament** — `viewer-bannerlord.js:995-1016`: button
  "⚔️ Вступить в турнир (**1000💎**)", backend charges 1000💎, winner gets
  gold+XP+prize, round winners get gold. **Entry fee → prize competition.**
- **Paid random skill XP** — `4041-4079`: crystals for "+XP (рандом)", empty
  `skill_key` → mod picks random. Pay-for-random-outcome.
- **Crystal→dinar conversion** — `4020-4024`: buy in-game gold with crystals
  (spendable-currency path feeding random goods).
- Jim also flags (not yet re-verified by god): random equipment box
  (`~3721-3759`), paid random NPC marriage (`~4480-4493`), free daily
  random-skill reward, free dice-icon random culture selector.

**Consequence:** Option B in the rejection doc ("cut dice/duels/cases from
mobile") is **insufficient** — paid-entry tournament + paid-random Bannerlord
actions remain on mobile and are arguably *worse* signals (an actual crystal
entry cost is the closest thing on the surface to a real stake).

---

## 2. Consolidated verdict (both passes merged)

**MUST-CUT from mobile (blockers):**
- Кубики 🎲 (dice 2d6) — iconic gambling visual + random outcome.
- Кейсы 🎁 — lootbox framing (tiers/rarities, open/reveal, random drop-tier).
- Currency/drop-rate disclosure block *as currently written* — Jim: foregrounds
  Channel-Points→crystals conversion + case odds, which confirms the loot-box
  read rather than defusing it.
- **Bannerlord paid-entry tournament (1000💎)** — strongest blocker.
- **Paid random Bannerlord rewards** — random skill XP, random equipment box,
  paid random NPC marriage; crystal→dinar two-step stake path.

**RISK (both flag; decide with reviewer's answer):**
- Дуэли ⚔️ (RPS) — no stake + player agency, but win/streak/ELO-prize framing.
- Balance / "Доход/мин" / crystal-priced shell + TTS — spendable-currency read.
- Free Bannerlord daily random-skill reward; free dice-icon random culture.

**KEEP (independently safe, both agree):**
- Крестики ❌⭕ (skill, no chance) — only residual is the seasonal ELO prize.
- Quests, promo, social (pets/family/guilds), voting, bug report, stats.
- Deterministic RimWorld / Bannerlord actions (fixed price, identified outcome).

---

## 3. Disagreements — BETWEEN THE TWO AGENTS

1. **SCOPE (the important one).** god's first pass = shell games only, said
   "desktop untouched". Jim = full loaded mobile surface, incl. Integration tab.
   Jim was right: mobile loads Bannerlord code; the tab's blockers dominate.
   god concurs after re-verifying `viewer-bannerlord.js` in code.
2. **Cases severity.** god: MUST-CUT/heavy-redesign, high confidence. Jim: same
   verdict, adds that the *odds disclosure itself* worsens the read. Aligned,
   Jim's point is sharper.
3. **Duels.** Both = RISK; no material disagreement.
4. No contradictions remain after god's re-verification; the passes are
   complementary, Jim's is broader.

## 4. Disagreements — vs the rejection doc AND the sent letter

The owner's letter (sent 24.08) states: *"none of the mini-games involve
wagering… there is no entry cost and no stake. Playing is free. No game pays out
for the result of an individual match."*

- **This is contradicted by the mobile Bannerlord tournament**, which charges a
  **1000💎 entry fee and pays prizes**. Even if "mini-games" was meant to scope
  only tic-tac-toe/dice/RPS, a reviewer inspecting the mobile view sees a
  paid-entry prize event. Risk: we look like we misrepresented the extension.
- Rejection doc "only payouts are seasonal ELO prizes" is **false surface-wide**:
  tournament winner/round prizes, case rewards, quest/daily rewards all visible.
- "No stakes" holds only for the three shell mini-games.

## 5. Agreements (both agents)
- No per-match stake in tic-tac-toe / dice / RPS.
- Tic-tac-toe & RPS prizes are seasonal, not per-match.
- Case reward is fixed by known tier; cases are stated free.
- Reviewer *perception* controls — free/non-cashable/fixed-at-open arguments do
  not overcome the mobile read; odds disclosure can worsen it.
- Tic-tac-toe, quests, social/channel tools, stats, deterministic integration
  actions are independently keepable.

---

## 6. Recommendation to owner (no action taken — awaiting decision)
1. **Before anything else:** the sent letter's "no entry cost / no stake" claim
   is contradicted by the mobile tournament. Decide whether to send a short
   correction to the reviewer, because if they find it first it reads as
   concealment.
2. A conservative mobile cut must cover **both** the shell games *and* the
   Bannerlord paid-entry/paid-random actions — Option B alone is not enough.
3. Desktop panel can keep these; the cut is mobile-surface only (subject to the
   reviewer's answer to question 3 in the letter).

---

## 7. HOW TO "PLAY IT" — gate a compliant mobile subset, don't delete (converged god+Jim)

Owner's steer: mobile is a copy, so gate/reframe rather than delete. Both agents
converged on this plan (READ-ONLY; nothing changed yet).

**Mechanism (CSP-safe):** `mobile.html` and `extension.html` are separate shells
kept in sync by choice → divergence is allowed. Mark the mobile shell with a
STATIC `<meta name="shedlink-surface" content="mobile">` (NOT an inline
`window.*=1` — mobile.html CSP is `script-src 'self'`, inline is blocked). A
shared `isMobileSurface()` helper reads it; ABSENCE = desktop (default), so
extension.html is untouched.

Two edit surfaces:
- (a) **Static tiles** already live in mobile.html — dice, cases, the tournament
  card (`mobile.html:251-260`), the case/odds disclosure block, and (if maximum
  conservatism) the RPS tile → simply ABSENT from mobile.html. Loaders no-op when
  their root is missing. Do NOT remove shared `<script>` tags.
- (b) **Shared-JS blockers** in `viewer-bannerlord.js` → under the mobile marker,
  do not EMIT (omit at render construction, not CSS `display:none`, so it's absent
  from DOM/accessibility): random-equipment HTML, paid random-XP rows, paid random
  marriage, daily random-XP option, random-culture button. Add a defensive early
  return in the matching click binders as a second layer.

**Per-element disposition (converged):**
- HIDE on mobile (mechanics — random outcome / paid-entry→prize, cannot reskin):
  dice; cases + odds disclosure (current form); paid-entry tournament; paid random
  skill XP; random equipment box; paid random marriage; daily random-XP option;
  random-culture selector.
- KEEP on mobile, REFRAMED (deterministic; presentation-only signal):
  - RPS duels → "Камень·Ножницы·Бумага"/"Матч", neutral icons, drop
    duel/bet/prize/streak/medal copy. (Salvageable — not system-random. If risk
    tolerance for the next review is ~0, hiding is safer — OWNER'S CALL.)
  - Crystal→dinar → label as fixed exchange of earned channel points to in-game
    gold, show both exact amounts, no gift/box imagery. Keep ONLY once random
    equipment is gone.
  - Balance/income/shop framing → rename 'Баланс'→'Очки канала',
    'Доход/мин'→'Начисление за просмотр', 'Магазин'→'Действия/Каталог', neutral
    points icon, show fixed outcome beside every fixed cost, keep concise
    noncashable/nontransferable text.
  - A fixed-tier reward COULD survive as a different surface ('Milestone rewards')
    with zero case/open/rarity/reveal/streak-pull language — optional, not required.

**Server-side:** NOT a viable security boundary — backend JWT (`backend/auth.py`)
has no signed Twitch placement claim; any surface header is client-controlled.
Treat mobile gating as presentation capability gating (frontend only). Keep
existing server price/action validation. Do NOT tell Twitch "backend refuses on
mobile" — it isn't true unless a signed placement claim is found.

**Regression guardrails that MUST stay green:**
- `test_frontend_module_lifecycle.py:82-119` — both shells must load the identical
  `viewer*.js` set + identical versions + ONE cache-bust. So keep all shared script
  tags; bump cache-bust in BOTH shells together on any shared-JS change.
- NEW test to ADD: assert forbidden mobile tiles/text/IDs are ABSENT in mobile.html
  yet PRESENT in extension.html — so future "sync the two shells" work can't copy
  the violations back. This is the essential safety net.
- NEW JS render test: desktop marker → emits tournament/random gear/XP/marriage/
  daily-XP/random-culture; mobile marker → emits none but keeps deterministic
  actions; NO marker → tests as desktop.
- Keep green: `test_game_registry.js`, `test_buy_action.js` + Bannerlord buy-action
  tests; run `pack-extension.py --check` and inspect the PACKAGED mobile.html.
- Top risks: inverted flag logic, accidentally gating a shared binder globally
  (kills desktop), cache-bust mismatch.

**Open decision for owner:** RPS — reframe-and-keep (better UX) vs hide (safer for
the imminent re-review). Everything else is agreed.
