# Core standalone + compliant replacements — IDEAS (consolidated, in progress)

Owner ask (2026-08-26): make the CORE extension engaging independent of game
integrations; invent COMPLIANT mobile-13+ replacements for the cut gambling
mechanics (dice, cases, paid-entry tournament, paid-random). Some free is fine.
Owner wants imagination. IDEAS ONLY — no code.

Sources merged: god's round (chat) + doc-recon digest. **Jim's independent set to
be merged when it lands.**

Compliance filter (applied to every idea): NO chance-outcome-for-value, NO
paid-entry→prize, NO lootbox/rarity/random-reveal, NO wager. Allowed: skill,
free prediction-as-trivia (free guess → reward for correct is NOT a wager),
deterministic collections you can SEE, co-op/community goals, progression, social.
💎 crustики are EARNED in core only (never inside game modules).

---

## KEY REFRAME from the digest (this changes the request)

The core doesn't primarily need more mini-games — the docs say core state is
**"state without a consumer"** (DEFERRED 2026-08-23): pets bought but nothing
uses them; guild treasury fills but nothing to spend on; marriage has no effect.
Plus 💎 accrues for **passive presence** (25/min for an open panel), and the
frontend already sends `active_clicks`/`mouse_moves` that the backend drops.

Two structural fixes make core self-sufficient AND absorb the cut mechanics:
1. **A CONSUMER for accrued state** — the missing sink. (Owner's own recorded
   fix direction is a boss/RPG mechanic.)
2. **Engagement-driven earning** — reward active play, not passive presence.

Do NOT re-propose killed ideas: casino/slots/near-miss/double-or-nothing,
points-for-money/donate, sub gameplay bonuses, P2P market/trade, passive rent,
currency minting inside game modules. (digest §2)

---

## FLAGSHIP IDEA — "Осада" / co-op boss (the consumer) [core-standalone]
- **Pitch:** a channel-wide PvE boss/event that ALL dead state feeds into — your
  pet fights, your guild pools its treasury for a buff, your spouse gives a
  bonus, your level/title sets your contribution. Runs with NO game module
  connected — pure core.
- **Replaces:** tournament "compete for glory" (now free co-op) + gives the sink.
- **Compliant:** outcome driven by collective PARTICIPATION + skill checks, not
  chance; rewards are deterministic and visible; free entry.
- **Free/Paid:** FREE to join; 💎 optionally SPENT on deterministic, chosen
  buffs (never random). **Effort: L.** Caveat: spec + /twitch-compliance before code.
- Fixes: pets/guilds/family "state without a consumer" in one stroke.

## Replace DICE / "quick 1v1 thrill" (skill, free)
- **Реакция-дуэль** — 1v1 "жми когда загорится", fastest wins. Free, seasonal
  ELO ladder (cosmetic/title by rank, not per-match). **S–M.**
- **Блиц-викторина 1v1** — head-to-head quick questions, first correct wins. **S.**
- **RPS reframed** — keep as neutral "мини-матч", drop duel/prize framing. **S.**

## Replace CASES / "collect–surprise–rarity" (deterministic)
- **Альбомы/Коллекции** — earn sticker/card SETS by KNOWN tasks; whole album +
  unlock paths visible; complete → a cosmetic you also saw in advance. Collection
  dopamine, zero random reveal. **M.**
- **Витрина целей** — open catalog of cosmetics each with "earn by X" path,
  replaces the case. **S.**
- **Free сезонный пропуск** — transparent track of deterministic rewards unlocked
  by participation; replaces case cadence. **M.**

## Replace PAID-RANDOM / "spend-for-progress" (deterministic)
- **Прямые покупки** — 💎 buys only CHOSEN, deterministic outcomes (which
  cosmetic/title/known perk). Never "random reward for spend." **S.**
- **Донат-выражения** — 💎 on expression: TTS (exists), overlay emote, name
  highlight, pick next poll option. All deterministic, on-brand. **S–M.**

## Make CORE standalone (no game module)
- **Предсказания событий стрима (free)** — "что дальше?" free guess, points for
  correct = trivia not betting. Binds viewers to WATCHING with no game. **M.**
- **Событийная карточка** ("stream-bingo" reframed) — free checklist of stream
  events; complete a row → cosmetic. Engagement-only, no purchase. **S–M.**
- **Кооп-цели канала** — community bars: "chat together hits X → streamer does Y".
  Social, retentive, standalone. **S.**
- **Питомец-Тамагочи** — deepen pet into a free care/growth loop (feed via
  watch-time, mini-interactions, deterministic evolution). Daily hook + feeds the
  boss. **M.**
- **Голосование-штурвал** — deepen voting so chat truly steers the stream (already
  the brand: "реши что играет стример"). Core identity without any game. **S.**
- **Профиль/титулы/уровни + fixed daily bonus** — participation progression with
  visible titles; daily reward FIXED (not random), streak-based. **S.**
- **Активный зритель** — reward active participation (wire the already-sent
  `active_clicks`), not just passive presence — fixes the earning gap. **S–M.**

---

## JIM's independent top 8 (file: CORE_STANDALONE_IDEAS_JIM_2026-08-26.md)
1. **Shed Passport** — visible album of named stamps from disclosed milestones (FREE; fixed-price frames 💎). M.
2. **Signal Sprint** — 30–60s pattern-recall/reaction skill, personal bests + friend challenges (FREE). M.
3. **Channel Expedition** — ordinary core actions advance a shared route → visible mural/badge (FREE). M.
4. **Exact Workshop** — 💎 buys the EXACT previewed item; no tiers/mystery/resale/transfer (PAID). M.
5. **Quest Routes** — pick Social/Explorer/Helper paths, all tasks+rewards visible (FREE). M.
6. **Glory Circuit** — free-entry skill seasons, STATUS prizes (titles/Hall of Fame), NOT currency (FREE). M.
7. **Live Trivia Relay** — free questions, each correct advances a shared streak to a fixed milestone (FREE). M.
8. **Codebreaker Duels** — 1v1 race on the same Mastermind-like grid, server-authoritative timing (FREE). L.
- Jim's product loop: Quest Routes → skill play → Channel Expedition → Passport → Exact Workshop.

## CONVERGENCE (both agents, independently) — treat as high-confidence menu
- Deterministic collection album (Альбомы = Shed Passport)
- Quick 1v1 SKILL (Реакция-дуэль/викторина = Signal Sprint/Codebreaker)
- Co-op channel progress (Кооп-цели = Channel Expedition)
- Deterministic 💎 sink (Прямые покупки = Exact Workshop)
- Free status leagues (Свободные лиги = Glory Circuit)
- Free trivia/prediction (Предсказания = Live Trivia)

## DISAGREEMENT (the strategic fork for the owner)
- **god:** flagship = a boss/consumer that REVIVES pets+guilds+family (the docs'
  "state without a consumer"; the owner's own recorded fix direction). Highest
  leverage — converts 3 dead systems into value + gives 💎 a sink. Effort L.
- **Jim:** deliberately EXCLUDED expanding paused pet/guild/family systems; build
  fresh clean loops instead. Rationale: don't pour work into dead systems.
- Resolution = owner's product call: revive sunk investment (god) vs greenfield
  compliant loops (Jim). Not a compliance question — both are compliant.

## Jim's compliance refinements to FOLD IN regardless of the fork
- Status-only prizes (titles/pennants), NOT currency prizes — safest under Apple
  contest rules for any "league/tournament" surface.
- Skill duels: same deterministic puzzle/seed for all; server-authoritative timing;
  disconnect/accessibility rules — so skill (not chance/latency) decides.
- Every paid button states EXACT price → EXACT outcome; no mystery/rotation.

## Owner decisions this will need (later, not now)
- **The fork above:** boss/consumer (god) vs greenfield loops (Jim) vs both.
- Free-first vs some 💎 sinks (deterministic only — Exact Workshop).
- Spec + /twitch-compliance gate before ANY code (per project rules).
