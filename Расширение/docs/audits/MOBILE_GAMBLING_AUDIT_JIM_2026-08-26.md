# Mobile gambling-orientation audit — Jim — 2026-08-26

## Scope and method

Independent, mobile-only review against the reviewer-read bar described in Twitch rule 3.5 / Apple §4.7: what a 13+ reviewer sees, not whether the economy is legally redeemable. I first audited `frontend/mobile.html` and every script it actually loads, then read `docs/TWITCH_REVIEW_0.0.2_REJECTION.md` only to prepare **DISAGREEMENTS**.

`mobile.html` loads the shared shell and game files directly (`mobile.html:497-525`), including `cases.js`, `tictactoe.js`, `dice.js`, `duels.js`, `viewer.js`, and all three integration renderers. Therefore the integration tab is part of the mobile surface whenever its module is active. `viewer.css` supplies generic cards/modals; it contains no surviving casino/jackpot/slot animation and explicitly records their removal (`viewer.css:1026`).

Verdicts mean: **KEEP** = no gambling-orientation signal on its own; **RISK** = could contribute to an adverse reviewer read; **MUST-CUT** = blocker-level mobile presentation under the stated conservative bar. Line numbers refer to the current worktree on 2026-08-26.

## Per-element verdicts

| Mobile surface element | Verdict | Severity | Evidence | Reviewer-visible signal | Confidence |
|---|---|---:|---|---|---:|
| Currency header: “Баланс”, passive “Доход/мин” | RISK | risk | `mobile.html:43-53` | A prominent accumulating balance resembles a spendable game currency before any disclaimer is opened. | High |
| Crystal-priced actions / shop framing | RISK | risk | `mobile.html:184-188`, `mobile.html:294-303`, `mobile.html:331-335` | Repeated prices and a Shop make 💎 read like purchasable premium currency even if it is not cashable. | High |
| Currency/odds disclosure | MUST-CUT | blocker | `mobile.html:411-457` | The collapsed footer itself advertises “virtual currency & drop rates”, Channel Points conversion, random case drops and 70/25/4/1 rarity odds. It confirms, rather than neutralizes, loot/random-reward orientation. | High |
| Tic-tac-toe card and play | KEEP | risk | `mobile.html:86-91`; `tictactoe.js:150-160` | Turn-based skill game, no dice/random imagery and no visible entry cost. Seasonal internal-currency prizes add adjacent risk (`tictactoe.js:94-115`; `duels.js:100-121`) but not gambling by themselves. | High |
| Dice card, bot roll, PvP roll/reroll | MUST-CUT | blocker | `mobile.html:93-99`; `dice.js:137-153`, `dice.js:192-254`, `dice.js:317-454` | Explicit 🎲/2d6, outcome decided by random rolls, roll animation, reroll choice, win/loss reveal, replay loop. This is the clearest prohibited mobile signal even without a per-match stake. | Very high |
| Dice seasonal leaderboard prizes/streak | MUST-CUT | blocker | `dice.js:87-109`; shared prize renderer `duels.js:100-121` | Chance-decided game is tied to ELO, win streak flames and top-three 💎 prizes. “Seasonal” does not break the visible causal path from random matches to valuable rewards. | Very high |
| RPS “Дуэли” gameplay | RISK | risk | `mobile.html:100-106`; `duels.js:53-70`, `duels.js:159-167` | No visible entry cost and simultaneous RPS has player agency, so it is not a pure chance game. However win/loss, matchmaking, streak and prizes make it read as prize competition. | Medium-high |
| RPS seasonal ELO prizes/streak | RISK | risk | `duels.js:100-131`, `duels.js:165` | Internal 💎 prizes are explicitly awarded to the season top three and the UI highlights win streaks. Not a wager, but reward-for-outcome framing is reviewer-sensitive. | High |
| Cases card / rarity ladder / closed inventory | MUST-CUT | blocker | `mobile.html:138-147`; `cases.js:7-46`, `cases.js:64-79`, `cases.js:116-147` | “Кейсы”, 🎁/💎/👑 rarity tiers, “closed/open”, “lucky drop”, and streak acquisition are textbook lootbox/case framing regardless of backend determinism. | Very high |
| Case open/reveal/reward loop | MUST-CUT | blocker | `cases.js:151-190`, `cases.js:193-249`, `cases.js:262-274` | Click-to-open, anticipation animation, reveal of +💎, success toast, and return for another daily case create a pull-to-win reward loop. Previewed fixed values reduce deception, not gambling orientation. | Very high |
| Random case-tier drops | MUST-CUT | blocker | `mobile.html:438-457`; `cases.js:38-46` | The surface expressly says cases randomly drop during streams with rarity odds. Free acquisition does not remove random-reward/lootbox presentation. | Very high |
| Quests | KEEP | cosmetic | `mobile.html:149-155`; `viewer.js:1126-1159`, `viewer.js:1169-1199` | Deterministic progress toward a disclosed fixed 💎 reward; no stake or random outcome in the quest UI. Association with the “Награды”/case ecosystem is contextual only. | High |
| Promo code | KEEP | cosmetic | `mobile.html:156-162`; `viewer.js:1201-1232` | Code redemption, no random outcome or stake displayed. | High |
| Pets, family, guilds | KEEP | cosmetic | `mobile.html:110-134` | Social/cosmetic navigation; no gambling signal in the cards. | High |
| Voting, bug report | KEEP | cosmetic | `mobile.html:166-182` | Deterministic channel interaction/support surfaces. | High |
| TTS purchase | KEEP | risk | `mobile.html:184-188` | Fixed-price, fixed-service purchase; not chance-based, though it reinforces 💎 as a spendable currency. | High |
| Stats / watch-time / passive earnings | KEEP | cosmetic | `mobile.html:340-399` | Deterministic activity statistics and earnings; no random outcome or stake. | High |
| RimWorld create/heal/resurrect/shop/events | KEEP | cosmetic | `mobile.html:286-327`; deterministic action rendering `viewer-rimworld.js:31-190` | Fixed-price game effects/catalogue; no random reward is presented in the audited renderer. | Medium-high |
| Bannerlord viewer tournament | MUST-CUT | blocker | `viewer-bannerlord.js:991-1016` | UI can charge 1000💎 to enter and promises winner/round prizes. This is the strongest actual stake/entry-cost + prize surface, omitted from the earlier mobile inventory. | Very high |
| Bannerlord random equipment box | MUST-CUT | blocker | `viewer-bannerlord.js:3721-3759` | It literally describes a “random box” and “🎁 Случайный товар”; user pays 500k/1m in-game dinars for an unknown high-tier weapon/armor/horse. | Very high |
| Crystal → dinar conversion feeding random equipment | MUST-CUT | blocker | `viewer-bannerlord.js:4017-4039`, `viewer-bannerlord.js:4050-4071` | The mobile UI sells in-game dinars for 💎, then accepts those dinars for random goods. The two-step currency path does not conceal the stake from a reviewer. | Very high |
| Paid random skill XP | MUST-CUT | blocker | `viewer-bannerlord.js:4025-4048`, `viewer-bannerlord.js:4057-4079` | Direct crystal cost for XP assigned to a random skill: stake/price + random reward. | Very high |
| Free daily reward | RISK | risk | `viewer-bannerlord.js:2695-2749` | Daily return loop with 🎁 framing; gold is fixed, while the XP option lands in a random skill. No entry cost, so this is not a wager, but it is a random reward/retention pull. | High |
| Paid random NPC marriage | MUST-CUT | blocker | `viewer-bannerlord.js:4480-4493` | Pays in-game gold and the engine selects a random NPC. It is a paid randomized outcome even though it is game-roleplay rather than a cash prize. | High |
| Free “🎲 Случайная культура” | RISK | cosmetic | `viewer-bannerlord.js:5078-5087` | Dice imagery and explicit random selection. No cost or prize, so low standalone severity, but avoidable visual association. | High |
| Bannerlord deterministic combat/hero/inventory/dynasty actions | KEEP | cosmetic | mobile containers `mobile.html:213-273`; representative deterministic actions `viewer-bannerlord.js:1099-1208`, `viewer-bannerlord.js:4278-4349` | Fixed selections/upgrades and ordinary RPG state do not themselves signal gambling. Excludes the separately listed tournament/random actions. | Medium-high |
| ShedColony actions | KEEP | cosmetic | mobile container `mobile.html:276-277`; action catalogue/rendering `viewer-shedcolony.js:95-126`, `viewer-shedcolony.js:480-579` | Fixed-cost, identified outcomes; no wager/random-reward presentation found. | Medium-high |

## Negative findings

No roulette, wheel, slot-machine, jackpot, cash-out, user-to-user transfer, or near-miss UI was found in the mobile-loaded frontend. There is no visible per-match entry cost for tic-tac-toe, dice, or RPS. Those facts help, but they do not cure the blocker combinations above.

## DISAGREEMENTS

### Where the earlier memo is correct

- I agree that the three shell mini-games show no per-match stake/entry cost; the mobile game flows expose matchmaking/play actions but no price.
- I agree that tic-tac-toe and RPS rewards are presented as seasonal ELO prizes, not an immediate fixed payout for one match (`duels.js:100-121`, `tictactoe.js:94-115`).
- I agree that the case-opening amount is fixed by already-known tier and the preview discloses tier values (`cases.js:262-274`), and that the footer says cases are free (`mobile.html:438-457`).
- I agree with the memo’s governing premise that reviewer perception, not internal economics, controls.

### Where my independent read diverges

1. **“No stakes” is too broad for the mobile view.** It is true only for the three shell mini-games. The mobile-loaded Bannerlord tournament charges an entry price and awards winner/round prizes (`viewer-bannerlord.js:991-1016`). Paid random equipment, random skill XP, and random NPC marriage also stake currencies on randomized outcomes (`viewer-bannerlord.js:3721-3759`, `4017-4079`, `4480-4493`).
2. **“The only payouts are seasonal leaderboard prizes” is false for the complete mobile surface.** The Bannerlord tournament promises immediate winner/round rewards (`viewer-bannerlord.js:1001-1005`); cases reveal 💎 rewards (`cases.js:225-249`); quests and daily rewards also pay currency/benefits (`viewer.js:1147-1159`, `viewer-bannerlord.js:2695-2749`). Even if the statement intended only mini-games, the letter and memo describe “our Extension” and “Mobile view” broadly.
3. **The memo’s inventory of what mobile offers is incomplete.** It lists tic-tac-toe, dice, RPS, cases and quests, but `mobile.html` also exposes an Integration tab and loads Bannerlord/RimWorld/ShedColony renderers (`mobile.html:213-327`, `497-525`). The omitted Bannerlord surfaces contain the clearest actual entry-cost and paid-random mechanics.
4. **Free, deterministic-at-open cases remain a blocker by presentation.** The memo treats free acquisition, fixed contents and disclosed odds as a defense. My reviewer-read verdict is the opposite: “Кейсы”, rarity tiers, closed inventory, streak/lucky-drop acquisition, click-to-open and reward reveal are still lootbox orientation (`cases.js:7-46`, `116-249`). Determinism at opening addresses fairness, not the prohibited mobile aesthetic.
5. **Seasonal rather than per-match settlement does not make dice safe.** Random dice outcomes feed ELO, streaks and a leaderboard that advertises 💎 prizes (`dice.js:87-109`, `137-153`; `duels.js:100-121`). The payout is delayed/aggregated, but the reviewer-visible chain remains random play → ranking → prize.
6. **The currency disclaimer does not eliminate currency risk.** It says Channel Points convert into crystals and foregrounds drop rates (`mobile.html:411-457`), while the UI shows balances, income, a shop and repeated prices (`mobile.html:43-53`, `184-188`, `294-335`). A reviewer can still read 💎 as premium/purchasable, and Bannerlord then converts it to dinars used for random goods (`viewer-bannerlord.js:4017-4071`).
7. **The memo’s conservative option B is not conservative enough.** Removing only dice, duels and cases would leave the Bannerlord paid-entry tournament and paid random rewards accessible on phones. Those must be accounted for independently of the shell cards.

## Bottom line

1. The mobile view contains blocker-level gambling orientation: dice + prizes, case/lootbox presentation, a paid-entry prize tournament, and paid randomized Bannerlord rewards.
2. “Free/noncashable/fixed at open” mitigations do not control how these surfaces read to a 13+ reviewer; the disclosure actually makes odds and currency conversion more conspicuous.
3. Tic-tac-toe, quests, social/channel tools, stats, and deterministic integration actions are independently keepable; RPS and free random selectors remain risk items.
