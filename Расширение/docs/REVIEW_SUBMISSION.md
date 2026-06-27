# ShedLink — Twitch Extension Review Notes

**Extension name:** ShedLink — interactive viewer engagement platform
**Type:** Video-overlay + mobile + config view
**Test/review channel:** https://twitch.tv/shedoy23
**Contact:** nasulskii6@gmail.com
**Privacy Policy:** https://shedoy23.ru/privacy.html
**Terms of Service:** https://shedoy23.ru/terms.html
**Last updated:** 2026-06-27

This document is the reviewer walkthrough: what ShedLink does, how to test it, where
the backend lives, and a compliance tour with links to the exact code.

---

## 1. What ShedLink is

ShedLink turns viewers into participants in the streamer's game using an **in-Extension
virtual currency** ("crustics" / 💎, earned by watching and chatting). It is **multi-tenant**
(one backend serves many channels) and **game-agnostic** — games plug in as modules:

- **Bannerlord** — viewers shape their own hero in the streamer's Mount & Blade II: Bannerlord
  game (passive income, attributes, equipment, family/kingdom actions).
- **RimWorld** — viewers control a pawn in the streamer's RimWorld colony.
- **shedcolony** — viewers control a colonist in the streamer's MineColonies (Minecraft) colony.

Plus channel-wide engagement features: fixed-reward cases, skill duels (ELO, no wager),
voting on streamer actions, guilds, and cosmetic pets.

The virtual currency has **no monetary value**, cannot be purchased, cannot be cashed out or
exchanged for money/Bits, and cannot be transferred between users.

---

## 2. Reviewer walkthrough

**Streamer config** (`frontend/config.html`, Config view): the broadcaster authorizes the
extension; the config view lets them toggle overlay features. New streamers self-onboard via
`/streamer` (Twitch OAuth) — see `routes/streamer.py`.

**Viewer experience** (`frontend/extension.html` panel + `frontend/mobile.html`):
1. The viewer opens the panel; identity is requested via `Twitch.ext.actions.requestIdShare()`
   (declined → read-only view).
2. They earn crustics passively while watching + via chat/quests.
3. They spend crustics on game actions for the active module (the streamer picks the module in
   their dashboard). Every action has a **fixed, deterministic** outcome and a server-enforced
   price — no random "open" / mystery purchases for currency.

To test the game side, the review channel will be **live** with the relevant game running; we
provide pre-funded test viewer accounts on request (see §6).

---

## 3. Hosting & technical

- **Frontend** is the uploaded version `.zip` (served from Twitch CDN).
- **Backend** (the extension's API + game connectors) is self-hosted at **https://shedoy23.ru**.
  Add this domain to the version's **URL Fetching Domains** allowlist (the panel fetches state
  and posts actions there). No other external domains are contacted.
- **§2.9 Twitch Helper is the first `<script>`** in both shells — `extension.html:8` and
  `mobile.html:8` load `https://extension-files.twitch.tv/helper/v1/twitch-ext.min.js` before any
  extension code.
- **§2.1/§2.2** No Flash, no iframes — vanilla HTML/JS only. JS is human-readable (not minified).

---

## 4. Compliance tour (§-by-§)

### §5 / §6 — Virtual currency, no gambling, no wagering
- Crustics are an **in-Extension loyalty currency** (earned watching/chat/channel-points). **No
  cash-out, no purchase, no user-to-user transfer, no exchange to Bits or anything of value
  outside the Extension.** A disclosure footer states this in both shells
  (`extension.html` + `mobile.html`, `<details id="compliance-disclosure">`).
- **No casino / slots / mystery-box-for-currency.** Casino was removed (`migrations/m8_compliance_cleanup.py`
  drops the old tables). A lexicon test (`tests/test_multi_tenant_isolation.py`) asserts the UI
  contains no `casino|jackpot|bet|wager|slot|spin|roulette` wording.
- **Cases** (`routes/cases.py`): granted only by activity/event (never bought for currency/Bits),
  4 fixed tiers with **fixed** rewards — the reveal is visual, the prize is deterministic at grant.
- **No wagering on outcomes.** Duels are ELO-only (no stake). The Bannerlord tournament feature is
  a **no-loss prediction**: a correct guess pays a fixed bonus from a platform pool, a wrong guess
  costs nothing (`routes/bannerlord.py` — `tournament.bet` enqueues with `price=0, amount=0`).

### Subscriptions — no pay-/sub-gating
- Subscription status (Twitch or third-party) does **not** affect prices or rewards. `SUB_BOOSTS`
  are all `(1.0, 1.0)` (`twitch_subs.py`); sub-only action gates were removed. The only role-based
  multipliers are **channel roles** (broadcaster/moderator), which is permitted. Sub badges are
  cosmetic only.

### §4.11 NFT / §4.4 ads / §4.6.3 external payments
- **None.** No tokenized assets, no advertising/sponsored content, no external payment links or
  third-party storefronts.

### Data / privacy
- We store the viewer's Twitch **login** (username), their crustic balance, watch-time and a few
  gameplay fields. We do **not** collect or store email, IP, real name, or payment info (IP is used
  only transiently for rate-limiting). The streamer's OAuth scopes are
  `channel:read:redemptions channel:read:subscriptions moderator:read:followers user:read:chat
  user:bot channel:bot` (no `user:read:email`). Full detail: the Privacy Policy URL above.

---

## 5. Multi-tenant note for the reviewer

Every tenant query is scoped by `channel_id` (resolved from the Extension JWT / module token).
A viewer's data and currency are per-channel. The reviewer's test channel sees only its own data.

---

## 6. Test channel & access

**Channel:** https://twitch.tv/shedoy23

On a reviewer's request we will go live and provide:
- The relevant game running (Bannerlord / RimWorld / MineColonies) so game actions are visible.
- Pre-funded test viewer account(s) so actions can be exercised.
- Availability window (please contact us at nasulskii6@gmail.com to schedule; we can be live
  09:00–17:00 PT on request).

---

## 7. Changelog (this version)

First submission. Multi-game viewer engagement (Bannerlord / RimWorld / shedcolony) on a
multi-tenant backend; in-Extension virtual currency with no cash-out/transfer/wager; cosmetic
pets; ELO duels; voting; fixed-reward cases.

---

## 8. Contact

nasulskii6@gmail.com · repo: https://github.com/Shedoy23/shedstream
