# Что вставлять в форму подачи Twitch — версия 0.0.5

Собрано 2026-09-07 под конкретные поля формы. Полный разбор соответствия правилам
с ссылками на код — `REVIEW_SUBMISSION.md`; здесь только то, что копируется в кабинет.

**Проверено перед составлением:** панель НЕ запрашивает личность сама — она рисует
кнопку «🔑 Войти», и `requestIdShare` вызывается только по клику. Ревьюер, который
этого не знает, увидит экран входа и решит, что расширение не работает. Поэтому
первый пункт руководства — про эту кнопку. Интерфейс панели русский, поэтому в
руководстве даны английские значения всех нужных ярлыков.

---

## Поле «Название канала для проверки» (Extension Review Channel URL)

```
https://twitch.tv/shedoy23
```

**Требование Twitch:** поданная версия должна быть АКТИВИРОВАНА на этом канале всё
время проверки. `0.0.5` активирована — не переключай канал на другую версию, пока
идёт ревью.

---

## Поле «Пошаговое руководство и журнал изменений»

Вставить целиком:

```
SHEDLINK — REVIEWER WALKTHROUGH (version 0.0.5)

SCHEDULING — PLEASE READ FIRST
Our channel is not live 24/7, so the game-integration part of the extension cannot be
seen at an arbitrary time. Everything else can be reviewed at any moment while the
channel is offline (section A below). To see the game actions, please email
nasulskii6@gmail.com and we will go live at a time you choose, normally within 24
hours. Version 0.0.5 is activated on https://twitch.tv/shedoy23 and stays activated
for the whole review.

NOTE ON LANGUAGE
The panel UI is in Russian, because our audience is Russian-speaking. The two
compliance blocks at the bottom of the panel are bilingual (Russian + English), and
this walkthrough gives the English meaning of every button you need.

WHAT SHEDLINK IS
ShedLink lets viewers take part in the game the streamer is playing, using an
in-extension virtual currency ("crustics", the diamond icon) that viewers earn by
watching and chatting. One backend serves many channels; games plug in as modules —
currently Mount & Blade II: Bannerlord, RimWorld, and MineColonies (Minecraft).
The panel also has features that work regardless of the game: free cases, free skill
minigames with a seasonal ranking, guilds, daily quests, cosmetic pets, a community
vote on the next game, and a paid text-to-speech message that the broadcaster must
approve before it plays.

A. WHAT YOU CAN REVIEW RIGHT NOW, WITH THE CHANNEL OFFLINE

1. Open the panel on https://twitch.tv/shedoy23. You will first see a login card with
   a purple button labelled "🔑 Войти" ("Log in"). Click it — this is what calls
   Twitch.ext.actions.requestIdShare(). We deliberately do not call it on load, so the
   viewer decides. If you decline the Twitch prompt, the panel stays usable in a
   limited, read-only state.

2. Tell us your Twitch login by email and we will credit a test account with currency
   so you can exercise paid actions. A brand-new viewer starts at zero and is shown a
   first-step card labelled "Начать играть" ("Start playing").

3. At the bottom of the panel open the block labelled
   "ℹ️ О внутренней валюте и шансах · About virtual currency & drop rates".
   It states, in English as well as Russian, that the currency has no monetary value,
   cannot be purchased, cashed out, exchanged for Bits, or transferred between users,
   and it publishes the exact drop rates for the only random element in the extension.

4. Open the block labelled
   "📜 Официальные правила конкурсов · Official contest rules".
   Our seasonal minigame prizes are a contest, so the official rules are shown inside
   the extension: sponsor, free entry, eligibility, how to enter, how winners are
   determined, the nature of the prizes, and explicit statements that Twitch is not a
   sponsor and Apple is not a sponsor.

5. Play a minigame — Tic-Tac-Toe, Rock-Paper-Scissors, or Tug of War. Entry is free,
   there is no stake, and no currency moves between players; only the ELO rating
   changes. Seasonal prizes are paid by the platform, never by an opponent.

6. Free cases: cases are granted for activity and are never purchasable. Open one, or
   use the "Открыть все" ("Open all") button to open every case you hold at once.

7. With the game offline — which is the state you will see outside a stream — every
   game action is disabled and states the reason in plain language instead of failing
   silently. This is deliberate: a viewer must never be charged when the game cannot
   deliver.

8. The broadcaster configuration view is reachable from the extension's configuration
   page and lets the broadcaster toggle overlay features.

B. WITH THE STREAM LIVE (scheduled with you by email)

1. A normal paid action, for example training a skill for your RimWorld pawn: the
   price is enforced by the server, the outcome is deterministic, and the result is
   reported back into the panel.

2. A deliberately impossible action: the panel shows why it was refused and the full
   price is refunded. We will demonstrate both, and can show the corresponding server
   records.

COMPLIANCE SUMMARY

- Virtual currency. Earned only — by watching, chatting, quests, and Channel Points.
  It cannot be bought with money or Bits, cashed out, exchanged for anything of value,
  or transferred between users. There is no code path anywhere in the product that
  moves currency from one viewer to another.

- Randomness. Exactly one random element exists in the whole extension: which tier a
  free case is. The probabilities are published in the panel — 70 / 25 / 4 / 1 % for a
  case dropped during a stream, and 68.9 / 25 / 6 / 0.1 % for the hourly case given to
  active viewers. The reward inside a case is fixed by its tier and is never rolled;
  opening a case is presentation only. Cases granted for quests, streaks and watch-time
  milestones have a fixed tier with no roll at all. Cases can never be purchased.

- No wagering. Minigames and duels are free to enter and ELO-only. The Bannerlord
  tournament prediction is free to enter, and a wrong guess costs nothing.

- Subscriptions. Twitch subscription status does not affect any price or reward, and
  neither does any third-party paid subscription.

- No advertising, no sponsored content, no external payments, no third-party
  storefronts, no tokenized assets or NFTs.

- User-generated content. The only viewer-authored content shown to the audience is
  the text-to-speech message. The broadcaster must approve each message before it can
  be played, and this approval gate is ON BY DEFAULT — including on a channel whose
  broadcaster has never touched the setting. The broadcaster can approve, reject, or
  block a viewer from the feature entirely. A rejected message is refunded in full and
  the viewer is told why; a message the broadcaster never acts on is refunded
  automatically after 30 minutes and can no longer be played. A blocked viewer is
  refused before any charge is made.

- Data. We store the viewer's Twitch login, their currency balance, watch time, and a
  few gameplay fields. We do not store email, real name, or payment information; the
  IP address is used transiently for rate limiting and is not stored.
  Privacy Policy: https://shedoy23.ru/privacy.html
  Terms of Service: https://shedoy23.ru/terms.html

- Hosting. The backend is self-hosted at https://shedoy23.ru. It is the only external
  domain the extension contacts and the only entry in the URL Fetching, Image and Media
  allowlists. The Twitch helper is the first script in every view.

CHANGELOG — WHAT CHANGED SINCE THE RELEASED VERSION 0.0.1

- Our channel cannot stay live continuously. Please email nasulskii6@gmail.com to
  schedule a review window with the game running.
- New minigame "Tug of War": a free 1v1 matchmade duel with ELO and a season. It
  replaces the Dice minigame, which has been removed from the extension entirely.
- Cases: a free hourly case for active viewers, an "Open all" button, and a rewritten
  odds disclosure that lists both random sources with their exact percentages.
- Official contest rules are now displayed inside the extension, in English and Russian.
- Every price, limit, cooldown and refusal message is now served by the backend, so the
  price shown is always the price charged. Thirty-three refusal codes that previously
  failed silently now render a readable sentence.
- New viewer onboarding: a first-step card for viewers who do not have a character yet.
- Four irreversible actions now ask for confirmation before charging.
- MineColonies module: the purchasable item list is served by the backend and reconciled
  against the game build's own item registry, so an item the streamer's modpack cannot
  deliver is hidden from the panel instead of being sold and refunded.
- Bannerlord: the "Random item" purchase was removed, along with the word "random" in
  the interface. Tournament entry is free.
- RimWorld: heal and resurrect were moved under the status line; dead-pawn state is
  handled correctly.
- Pets: fixed a broken image in the cosmetics shop; overlay pets no longer overlap.
- Text-to-speech: a rejected message, or one the broadcaster never acts on, is now
  refunded automatically.
- The panel no longer shows a zero balance when the server cannot confirm who the
  viewer is: unknown values are shown as a dash, the panel re-identifies itself
  silently, and only then asks the viewer to log in again.
- The stream overlay page is no longer included in the extension package.

CONTACT
nasulskii6@gmail.com
```

---

## Что проверить в кабинете перед нажатием «Отправить на проверку»

1. Загружен АКТУАЛЬНЫЙ архив `0.0.5` от 08.09: MD5 `5e732eefd7d31eba71522728b5a84de6`,
   SHA-256 `26b1c777…`, 246 631 байт. Лежит в
   `.claude/worktrees/codex-public-release/dist/shedlink-0.0.5.zip`.
   Прежние архивы ОТМЕНЕНЫ: `2e891a30…` показывал нули вместо «не авторизован»,
   а `ec40d2b1…` ЛОМАЛ ВХОД В ПАНЕЛЬ — его грузить нельзя.
2. Streamer Allowlist ПУСТ — иначе после одобрения расширение не станет доступно всем.
3. Три allowlist-домена содержат `https://shedoy23.ru/`.
4. Версия `0.0.5` активирована на канале и остаётся активированной до вердикта.
5. После отправки — не менять фронт до вердикта (см. `TWITCH_UPDATE_RELEASE_PLAYBOOK.md`).

## Чего в этом тексте намеренно НЕТ

Обещания конкретного окна доступности. Twitch сам предлагает выход для каналов,
которые не могут быть в эфире постоянно: написать об этом в руководстве и журнале
изменений, и проверяющие свяжутся, чтобы назначить время. Выдуманное расписание
хуже: ревьюер придёт в названный час, игры не будет, и это готовый отказ.
