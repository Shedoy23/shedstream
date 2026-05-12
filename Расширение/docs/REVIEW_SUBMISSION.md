# Twitch Extension Review — Submission Notes

**Extension name:** RimLink — interactive viewer engagement platform
**Submission date:** 2026-05-12
**Repo:** https://github.com/Shedoy23/shedstream
**Live test channel:** https://twitch.tv/shedoy23

Этот документ — для reviewer'а. Короткий тур по compliance-критичным
точкам, с ссылками на конкретный код. Все номера секций — из текущих
Twitch Extension Developer Agreement / Extension Guidelines (см.
`Расширение/docs/COMPLIANCE_REWORK_PLAN.md §1` для выдержек).

---

## 1. TL;DR

RimLink — расширение для зрителей RimWorld (и будущих игр, см. §6
Game Bridge SDK). Зрители получают очки за активность, тратят их на
**non-wagering** механики: кейсы с фикс-наградой, дуэли (skill, no
wager), голосование за действие стримера, гильдии, цифровых питомцев.

**Что НЕ делаем:** casino / slots / wagering / mystery boxes за валюту /
P2P-передача / streamer-uploadable items / utility-бусты за деньги.

Все механики прошли 3-question test из COMPLIANCE_AND_ARCHITECTURE.md
§5.1 (**consideration / chance / prize** — никогда все три "yes"
одновременно).

---

## 2. Compliance hot spots (§-by-§)

### §4.11 NFT
**NONE.** Никаких токенизированных активов, blockchain, smart contracts.

### §2.1 No Flash, §2.2 No iframes
Только vanilla HTML/JS — см. `Расширение/frontend/extension.html`.

### §2.4 Audio off by default
Audio полностью отключён в текущей версии (no `<audio>` autoplay).
`SOUND_CONFIG['enabled']` в `config.py:399` — defaults true но не
используется в frontend audio-tag'ах.

### §2.9 Twitch Helper first
`extension.html:6` — `<script src="https://extension-files.twitch.tv/helper/v1/twitch-ext.min.js">`
загружается ДО любого extension-кода.

### §6.1.4 No casino-style mechanics
Casino полностью вырезан 2026-05-10 (Phase 1.A). Tombstone-комментарии
в коде помечены `casino_router удалён 2026-05-10 (Phase 1.A)`. См. также:
- `Расширение/backend/migrations/m8_compliance_cleanup.py` — DROP TABLE
  для casino_settings / free_spins_daily / craft_stats / market_listings
- Lexicon scrub: `tests/test_multi_tenant_isolation.py:1336` (Test 14)
  активно проверяет что dice.js не содержит forbidden words

### §6.2.4 No mystery boxes for currency
**Кейсы (`routes/cases.py`, `migrations/m9_cases.py`):**
- Кейсы выдаются ТОЛЬКО за активность (drops по таймеру) или ивент-награды
- НЕ продаются за крустики/Bits
- 4 фиксированных tier'а (common/rare/epic/legendary) с **фиксированными**
  наградами (1k/10k/100k/500k крустиков) — см. `config.py CASE_TIER_REWARDS`
- Reveal = visual flourish, prize детерминирован при grant — никакого RNG
  при открытии

**Pets cosmetics (`routes/pets.py`, `migrations/m13_pets.py`):**
- Каждая покупка = **specific `item_id`** с фиксированной ценой в Bits
- НЕТ кнопок «открыть случайный» / «mystery»
- Каталог dev-controlled (`PETS_CATALOG_SEED` в `m13_pets.py:34-41`),
  streamer НЕ загружает свои items (§6.2.8 защита)
- См. compliance-комментарии в `routes/pets.py:1-37` docstring

### §6.2.6 No wagering on game outcomes
- **Duels** (`routes/duel.py`): ELO-only, без ставок крустиков. См.
  `routes/duel.py:256` — «ставка крустиков убрана (§6.2.6)» комментарий
- **TicTacToe / Dice** (`routes/tictactoe.py`, `routes/dice.py`):
  matchmaking без entry fee, награда — ELO-rating only

### §6.2.8 Catalog/items not streamer-uploadable
- Pets catalog seed зашит в `migrations/m13_pets.py:34` — не имеет UI
  для streamer'а добавлять items
- Кейс-tiers зашиты в `config.py` — streamer контролит только включён
  ли drop, не содержимое

### §7.4 Broadcaster control
**Phase 7 pets:** broadcaster может выключить отображение pets-overlay
через `frontend/config.html` toggle → `POST /api/streamer/pets/overlay-toggle`
(`routes/pets.py:219`). Когда `overlay_enabled=0` — endpoint
`/api/overlay/pets` возвращает пустой viewers list (`routes/pets.py:209-211`).

### §7.5 Revenue attribution
Bits-покупки косметик записываются в `pet_purchases` с `channel_id`
канала где совершена покупка (`migrations/m13_pets.py:127-138`). Это
audit-trail для revenue split — НЕ scope-фильтр (см. §3.1 в
`docs/ARCHITECTURE.md` о cross-channel pattern).

### §5.2 Items за loyalty-points OR Bits
Кейсы — за loyalty-points (channel points / activity). Pets
косметика — за Bits в production (`PETS_BITS_REQUIRED=true`). Обе
формы compliant.

### §5.3 Косметика-only digital goods
Pets cosmetics dont confer game advantage:
- НЕТ utility (бусты накопления / преимуществ — см. compliance comment
  `migrations/m13_pets.py:18-19`)
- Только visual: head/accessory/background slots на pet-card

---

## 3. Tests — proof of compliance

**Isolation tests:** `Расширение/backend/tests/test_multi_tenant_isolation.py`

Запуск:
```bash
cd Расширение/backend
python tests/test_multi_tenant_isolation.py
```

Текущий результат: **1073/1073 passing.**

Compliance-релевантные тесты:
- **Test 14 (dice lexicon scrub, 1265+):** проверяет что dice.js не содержит
  `casino|jackpot|lucky|gamble|wager|slot|bet|spin|roulette`
- **Test 9 (cases, 558+):** атомарность grant + idempotency triggers
- **Test 17 (voting, 1714+):** voting за действие стримера НЕ wagering
  (см. comment `migrations/m12_voting.py:6`)
- **Test 18 (pets, 1714-2222):** PRAGMA-guard что cross-channel exception
  не drift'ит, hatch idempotency, audit-trail `pet_purchases.channel_id`

---

## 4. Repo / file map (для reviewer'а)

| Где смотреть | Что |
|---|---|
| `Расширение/docs/COMPLIANCE_REWORK_PLAN.md` | Полный план переработки (6 фаз, verdict-table 16 механик) |
| `Расширение/docs/ARCHITECTURE.md §3` | Multi-tenant invariants + cross-channel exception (§3.1) |
| `Расширение/backend/migrations/m8_compliance_cleanup.py` | DROP-таблиц вырезанных gambling-механик |
| `Расширение/backend/migrations/m9_cases.py` | Cases (fixed rewards, no purchase) |
| `Расширение/backend/migrations/m13_pets.py` | Pets cross-channel + Bits monetization |
| `Расширение/backend/routes/pets.py` | Pets endpoints с DEFERRED-секцией post-MVP scope |
| `Расширение/backend/tests/test_multi_tenant_isolation.py` | 1073 assertions включая compliance-guards |

---

## 5. Known DEFERRED (post-launch, документировано)

Эти scope-cuts intentional и не блокируют compliance:

- **[BITS-SIG]** Production-mode (`PETS_BITS_REQUIRED=true`) включит
  Twitch Bits transaction JWT signature verify. Сейчас MVP в mock-mode
  для test-канала, receipt-idempotency через UNIQUE-index уже работает.
  См. `routes/pets.py:33-42` DEFERRED docstring.

- **[BROADCASTER-JWT]** `/api/streamer/pets/overlay-toggle` сейчас под
  `require_admin` (HTTPBasic). Self-serve через Twitch Extensions
  broadcaster-JWT (role='broadcaster') — следующая итерация.

---

## 6. Test channel для review

**Канал:** https://twitch.tv/shedoy23

При запросе reviewer-а на стрим — стример выйдет в эфир и предоставит:
- Активные drops для демонстрации кейсов
- Pre-funded test viewer accounts для покупки pets cosmetics
- Pre-seeded guilds для демонстрации гильдий
- Все механики доступны через extension panel

---

## 7. Контакт

Issues / questions — через issues GitHub `Shedoy23/shedstream` или
напрямую через Twitch DM `@shedoy23`.
