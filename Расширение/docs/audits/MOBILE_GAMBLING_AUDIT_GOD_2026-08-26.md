# Mobile View — gambling-orientation audit (independent pass by god/Michael)

Date: 2026-08-26 · Lens: how the MOBILE surface READS to a Twitch/Apple §4.7
reviewer applying a 13+ age rating — NOT our internal economics. Source of
truth for this pass: `Расширение/frontend/mobile.html` (static surface).
This is one of two independent passes; Jim audits in parallel. Consolidation +
cross-agent disagreements handled by god after Jim reports. READ-ONLY — no edits.

## Per-element verdict

| Element | Where | Signal | Verdict | Conf |
|---|---|---|---|---|
| **Кубики / Dice 🎲 "2d6 · бот/PvP"** | mobile.html:93-99 (tile) → dice.js | Dice imagery + "2d6" is the single most iconic gambling visual; a chance-based roll minigame. Reads as gambling regardless of stake. | **MUST-CUT from mobile** | high |
| **Кейсы / Cases 🎁** | mobile.html:142-148 → cases.js; odds in footer 411-465 | Case-opening with tiers Common/Rare/Epic/Legendary + disclosed drop odds (70/25/4/1) = textbook loot-box framing. Disclosing odds is what regulators demand *of loot boxes* → confirms the reader's loot-box frame. Random drop-tier is a real chance mechanic on the surface. | **MUST-CUT / heavy redesign for mobile** | high |
| **Дуэли / Duels ⚔️ (RPS)** | mobile.html:100-106 → duels.js | RPS outcome is luck, framed "дуэли" with ELO + seasonal prizes. Chance outcome + prize pool reads as competitive-gambling-adjacent. | **RISK (cut conservatively)** | med |
| **Крестики / Tic-tac-toe ❌⭕ "PvP · ELO"** | mobile.html:86-92 → tictactoe.js | Pure skill, no chance. Only residual: seasonal ELO prize attaches a prize to a game. | **KEEP** | high |
| Голосование 🗳️ | mobile.html:170-176 | Points-based channel vote — not gambling. | KEEP | high |
| 💎 Баланс / "Доход/мин +0" / TTS 5000💎 | mobile.html:45-55,184-190 | Idle-accrual currency framing around the games feeds the overall economy-of-chance impression, but currency itself is disclosed non-monetary/non-transferable (footer). | cosmetic / low | med |
| Стрик / Достижения / Квесты / Питомец / Семья / Гильдия | various | No chance, no wager. | KEEP | high |

## Bottom line (god)
1. **Primary trigger is almost certainly Кубики (🎲 dice) + Кейсы (loot-box framing).** Both are chance-visual/loot-box regardless of our no-wager truth.
2. **The mechanics are genuinely not "real" gambling** (no stake, seasonal ELO prizes, non-cashable currency) — but 3.5 judges the *reading*, so that defense does not save the dice/case imagery on mobile. Option B (conservative cut of dice + cases, likely duels; keep tic-tac-toe + non-competitive) is the correct move for mobile only; desktop untouched.
3. **Tiles are STATIC in mobile.html with no mobile-gating visible** — dice/cases/duels render on the phone surface as written. (Jim to confirm no JS removes them in the mobile helper context.)

## Where my read may diverge from our internal position (for the disagreement section)
- Rejection doc table claims cases have randomness "только в тире дропа" and frames it as minimal/disclosed → **fine**. My read: the disclosed random tier roll (70/25/4/1) shown in the mobile footer is *itself* the loot-box signal a reviewer keys on; disclosure confirms rather than defuses the frame. Same fact, opposite implication for 3.5.
- Rejection doc leans on "no wagering / seasonal prizes only" as the defense. My read: true but **irrelevant to 3.5**, which is about surface reading, not wagering. Risk = treating the no-wager argument as if it answers the mobile age-rating objection.
