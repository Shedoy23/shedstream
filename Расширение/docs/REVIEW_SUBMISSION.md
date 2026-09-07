# ShedLink — Twitch Extension Review Notes

**Extension name:** ShedLink — interactive viewer engagement platform
**Version these notes describe:** `0.0.5` (SHA-256 `9200f6c2…`, MD5 `2e891a30…`)
**Type:** Video-overlay + mobile + config view
**Test/review channel:** https://twitch.tv/shedoy23
**Contact:** nasulskii6@gmail.com
**Privacy Policy:** https://shedoy23.ru/privacy.html
**Terms of Service:** https://shedoy23.ru/terms.html
**Last updated:** 2026-09-07 — сверено построчно с кодом архива `0.0.5`

This document is the reviewer walkthrough: what ShedLink does, how to test it, where
the backend lives, and a compliance tour with links to the exact code.

> **Правило поддержки (для нас, не для ревьюера).** Каждое утверждение здесь —
> проверяемое обещание про КОД, и ревьюер читает его буквально: расхождение хуже
> отсутствия. Перед подачей сверять по коду, а не по памяти. Сверка 07.09 нашла
> пять расхождений в версии от 05.07, включая описание механики, которой в
> архиве уже нет, и раздел changelog со словами «First submission» после того,
> как `0.0.1` был публично выпущен.

---

## 1. What ShedLink is

ShedLink turns viewers into participants in the streamer's game using an **in-Extension
virtual currency** ("crustics" / 💎, earned by watching, chatting, quests and Channel
Points). It is **multi-tenant** (one backend serves many channels) and game-agnostic —
games plug in as modules:

- **Bannerlord** — viewers shape their own hero in the streamer's Mount & Blade II: Bannerlord
  game (passive income, attributes, equipment, family/kingdom actions).
- **RimWorld** — viewers control a pawn in the streamer's RimWorld colony.
- **shedcolony** — viewers control a colonist in the streamer's MineColonies (Minecraft) colony
  (care, jobs, gear) and sponsor colony development (research, warehouse stock, building upgrades).

Plus channel-wide engagement features shipped in this archive: free fixed-reward cases
with published odds, skill minigames (Tic-Tac-Toe, Rock-Paper-Scissors, **Tug of War** —
all free to enter, ELO only), guilds, daily quests, cosmetic pets, a community game-vote,
and a paid **text-to-speech** message that the broadcaster must approve before it plays.

The virtual currency has **no monetary value**, cannot be purchased with money or Bits,
cannot be cashed out or exchanged, and cannot be transferred between users.

---

## 2. Reviewer walkthrough

**Streamer config** (`frontend/config.html`, Config view): the broadcaster authorizes the
extension; the config view lets them toggle overlay features. New streamers self-onboard via
`/streamer` (Twitch OAuth) — see `routes/streamer.py`.

**Viewer experience** (`frontend/extension.html` panel + `frontend/mobile.html`):
1. The viewer opens the panel; identity is requested via `Twitch.ext.actions.requestIdShare()`
   (declined → read-only view).
2. They earn crustics passively while watching, plus via chat, quests and Channel Points.
3. They spend crustics on game actions for the active module (the streamer picks the module in
   their dashboard). Every **purchase** has a fixed, server-enforced price and a deterministic
   outcome — nothing bought with currency rolls a random result.
4. If an action cannot be applied (the game is offline, the target is gone, a cooldown is
   active), the panel shows a plain-language reason and the price is refunded in full.
5. Free cases can be opened one by one or with "Open all". A case tier is the only random
   element anywhere in the extension, and its odds are published in the panel (see §4).

To test the game side, the review channel will be **live** with the relevant game running; we
provide pre-funded test viewer accounts on request (see §6).

---

## 3. Hosting & technical

- **Frontend** is the uploaded version `.zip` (served from Twitch CDN). 24 files, no build
  step, no minification, no source maps, no bundled binaries.
- **Backend** (the extension's API + game connectors) is self-hosted at **https://shedoy23.ru**.
  It is the only domain in the version's **URL Fetching / Image / Media** allowlists, and the
  only host the extension contacts besides Twitch's own.
- **§2.9 Twitch Helper is the first `<script>`** in all three views — `extension.html`,
  `mobile.html` and `config.html` load
  `https://extension-files.twitch.tv/helper/v1/twitch-ext.min.js` before any extension code.
- **§2.1/§2.2** No Flash, no iframes — vanilla HTML/JS only. JS is human-readable.

---

## 4. Compliance tour (§-by-§)

### §5 / §6 — Virtual currency, no gambling, no wagering

- Crustics are an **in-Extension loyalty currency** (earned watching / chat / quests /
  Channel Points). **No cash-out, no purchase for money or Bits, no user-to-user transfer,
  no exchange for anything of value outside the Extension.** A bilingual disclosure footer
  states this in both shells (`<details id="compliance-disclosure">`).
  - Verified in code: the direct transfer endpoint `/api/points/transfer` was removed
    2026-05-10 (`routes/misc.py`), duel stakes were removed the same day
    (`routes/duel.py` — ELO only), and the item-auction router, the last path that moved
    currency between viewers, was unwired 2026-07-29 (`main.py` — its four routes return 404).
  - Bits never produce currency. The `bits:read` scope and the `channel.cheer` subscription
    are used only to post a thank-you greeting (`eventsub.py::_on_channel_cheer`); no
    balance is changed anywhere in that path.

- **No casino / slots / mystery-box-for-currency.** Casino was removed
  (`migrations/m8_compliance_cleanup.py` drops the old tables). The Dice minigame was
  **frozen 2026-09-01** and replaced by Tug of War: `frontend/dice.js` is not in this
  archive at all, and the surviving backend route answers every call with a "frozen"
  message (`routes/dice.py`).

- **Cases** (`routes/cases.py`) are **always free** — granted by activity or by an event,
  never purchasable with currency or Bits. The reward inside a case is fixed by its tier
  (`config.CASE_TIER_REWARDS`) and is never rolled at opening; the animation is presentation
  only. Exactly two sources roll a random **tier**, and both publish their odds in the panel,
  in Russian and English:
  - drop during the stream — 70 / 25 / 4 / 1 % (`bot_core.DROP_CASE_TIERS`);
  - hourly case for active viewers — 68.9 / 25 / 6 / 0.1 % (`config.HOURLY_CASE_TIERS`).

  Cases from quests, streaks and watch-time milestones have a **fixed** tier, with no roll.
  A test (`tests/test_odds_disclosure.py`) fails the build if the published percentages ever
  drift from the weights in the code.

- **No wagering on outcomes.** Tic-Tac-Toe, Rock-Paper-Scissors, Tug of War and duels are
  **free to enter, ELO-only** — no stake, no currency transfer between players
  (`routes/tictactoe.py`, `routes/rps.py`, `routes/tugofwar.py`, `routes/duel.py`). The only
  prizes are platform-funded seasonal top-3 rewards paid from the platform, never from an
  opponent. The Bannerlord tournament is a **no-loss prediction**: entry is free, a correct
  guess pays a fixed bonus from a platform pool, a wrong guess costs nothing
  (`routes/bannerlord.py` — `tournament.predict` records `price=0, amount=0`).

- **Official contest rules are displayed inside the extension** (`<details id="contest-rules">`,
  both shells, RU + EN): sponsor, free entry, eligibility, how to enter, how winners are
  determined, prize nature, and explicit statements that **Twitch is not a sponsor** and
  **Apple is not a sponsor**. Prize amounts, dates and the rating threshold are served by the
  backend and shown in the minigames section. Gate: `tests/test_contest_rules_and_prize.py`.

- **Game-vote is a pledge, not a wager.** Viewers spend crustics as a contribution toward
  which game the community wants next; the highest-pool option wins. Contributions are
  deterministic spends — nothing is returned, paid out, or won by any user
  (`database.py — place_voting_bid / finalize_voting_event` contain no payout path).

### §7.2 — User-generated content and broadcaster moderation

The extension has one feature that puts viewer text in front of the audience: **"Speak my
message"** (TTS). A viewer spends 5 000 💎 to submit up to 200 characters, which are then
read aloud on the stream overlay.

- **The broadcaster must approve every message before it can play.** The approval gate is
  **on by default, including for a channel that has never touched the setting** — a channel
  with no settings row is treated as gated, not ungated
  (`routes/tts.py::tts_requires_approval`). The overlay's "next message" query filters on
  `approved_at IS NOT NULL` whenever the gate is on.
- The broadcaster can approve, hide, or block a viewer from the feature entirely, from their
  dashboard (`/api/streamer/tts/approve`, `/hide`, block list). A blocked viewer is refused
  **before** any charge.
- A message the broadcaster rejects is **refunded in full** and the viewer is told why, so
  moderation never costs the viewer anything. A request the broadcaster simply never acts on
  is refunded automatically after 30 minutes and can no longer be played, so a viewer is never
  charged for audio that did not air. While the gate is on, the purchase confirmation says the
  message is a request awaiting the broadcaster's decision, not a promise that it will play.
- Gates: `tests/test_tts_approval_gate.py`, `tests/test_tts_moderation.py`,
  `tests/test_tts_refund_on_reject.py`.

### Subscriptions — no pay-/sub-gating

- Subscription status does **not** affect prices or rewards. `SUB_BOOSTS` are all
  `(1.0, 1.0)` (`twitch_subs.py`); sub-only action gates were removed. The only role-based
  multipliers are **channel roles** (broadcaster/moderator), which is permitted. Sub badges
  are cosmetic only.
- **Third-party paid subscriptions have no effect either.** The Boosty subscriber list is a
  broadcaster-dashboard-only bookkeeping tool: it is not exposed to the extension frontend,
  and `bannerlord.buy_action` no longer reads it (`routes/bannerlord_boosty.py`, since
  2026-05-28). Verified 2026-09-07: the string `boosty` does not appear anywhere in the
  shipped frontend.

### §4.11 NFT / §4.4 ads / §4.6.3 external payments

- **None.** No tokenized assets, no advertising or sponsored content, no external payment
  links, no third-party storefronts, no links out to any paid platform.

### Data / privacy

- We store the viewer's Twitch **login** (username), their crustic balance, watch-time and a
  few gameplay fields. We do **not** collect or store email, IP, real name, or payment info
  (IP is used only transiently for rate-limiting). The streamer's OAuth scopes are
  `channel:read:redemptions channel:read:subscriptions moderator:read:followers user:read:chat
  user:bot channel:bot bits:read` (no `user:read:email`); `bits:read` powers the cheer
  thank-you only. Full detail: the Privacy Policy URL above.

---

## 5. Multi-tenant note for the reviewer

Every tenant query is scoped by `channel_id` (resolved from the Extension JWT / module token).
A viewer's data and currency are per-channel. The reviewer's test channel sees only its own data.

---

## 6. Test channel & access

**Channel:** https://twitch.tv/shedoy23

On a reviewer's request we will go live and provide:
- The relevant game running (Bannerlord / RimWorld / MineColonies) so game actions are visible.
- Pre-funded test viewer account(s) so paid actions can be exercised.
- **Availability window (UTC): `[ЗАПОЛНИТЬ ПЕРЕД ПОДАЧЕЙ]`** — реальное окно, которое владелец
  может выдержать, в UTC, и какая игра будет в нём запущена. Contact nasulskii6@gmail.com to
  schedule.

---

## 7. Changelog — what changed since the released version

`0.0.1` (released 2026-07-28) is what the public sees today. This archive replaces it.

- **New minigame: Tug of War** — free 1×1 matchmade duel with ELO and a season. It replaces
  the Dice minigame, which is frozen and no longer shipped.
- **Cases:** free hourly case for active viewers, an "Open all" button, and a rewritten odds
  disclosure that lists both random sources with their exact published percentages.
- **Official contest rules** are now displayed inside the extension in Russian and English,
  including the "Twitch is not a sponsor" statement.
- **Every price, limit, cooldown and refusal text now comes from the backend.** The frontend
  no longer carries its own copies, so what the viewer is charged is always what the panel
  showed. All 33 Bannerlord refusal codes now render a human-readable sentence instead of
  failing silently.
- **New viewer onboarding:** a first-step card for viewers without a character, and a
  permanent entry point for those who have one.
- **Four irreversible actions now ask for confirmation** before charging.
- **shedcolony (MineColonies) module:** the purchasable item catalogue is served by the
  backend and reconciled against the game build's own item registry, so items the streamer's
  modpack cannot deliver are removed from the panel instead of being sold and refunded.
- **Bannerlord:** the "Random item" purchase was removed along with the word "random" from the
  UI; tournament entry is locked free.
- **RimWorld:** heal and resurrect moved under the status line; dead-pawn state is handled.
- **Pets:** fixed a broken cosmetics-shop image; overlay pets no longer overlap.
- **Packaging:** the stream overlay page is no longer included in the extension archive.

No new external domains: the allowlists still contain only `https://shedoy23.ru/`.

---

## 8. Contact

nasulskii6@gmail.com
