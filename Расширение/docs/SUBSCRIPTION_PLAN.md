# Подписочная система через Boosty — MVP Plan

**Статус:** Design draft, не реализовано
**Created:** 2026-05-21 (после ChatGPT-консультации с Claude про Twitch ToS)
**Контекст:** добавить **side revenue** для стримера через Boosty subscriptions, **строго cosmetic-only** чтобы не нарушать Twitch ToS

---

## TL;DR

3 тира Boosty-подписки → viewer получает **только cosmetic / convenience / community** perks. Никакого pay-to-win.

**MVP scope:** Tier 1 + Tier 2 + backend wiring. Tier 3 (custom artwork) откладываем — слишком дорого per-viewer.

---

## ⚠️ Compliance constraints (Twitch ToS)

### ✅ Разрешено
- Cosmetic visual changes (цветной ник, badge, custom skin)
- Community access (Discord sub-channel)
- Quality-of-life (early access к beta features, no ads если будут)
- Branded recognition (mention в overlay / honor wall)
- Cross-game cosmetics через единую "подписочную валюту"

### ❌ Запрещено
- Дополнительные **крустики** в месяц (валюта = gameplay impact)
- Снижение **cooldown'ов** (`player.spawn`, powers, retinue recruit)
- Boost ELO / выигрыш в mini-games (dice/duel/TTT)
- Free tournament entry / skip queue
- Эксклюзивные **классы / powers** в Bannerlord (pay-to-win combat)
- Доп. **retinue slots** / Hero.Gold income multiplier
- Higher loot rates / extra HP / reduced damage taken

### 🟡 Серая зона (избегаем)
- Priority в matchmaking queue (теоретически competitive advantage)
- Премиум кубики с большим числом сторон
- "Sub-only" prize pools в сезонах

**Правило:** если viewer без подписки играет с viewer'ом с подпиской в mini-game — у них **те же шансы**. Подписан **выглядит круче**, но не **выигрывает чаще**.

---

## Tier breakdown

### 🥉 Tier 1 — "Зритель" (~200₽/мес)

Easy commitment, цель = массовый conversion casual fan'ов.

| Perk | Реализация |
|---|---|
| 🎨 Цветной ник в extension | UI cosmetic — выбор из 6 палитр |
| 📛 Sub badge рядом с ником | SVG значок в hero card / chat |
| 💬 Кастомная подпись (≤30 chars) | Free-text поле "♂️ wifey", emoji, мини-bio |
| 🎁 Random rare pet item ежемесячно | Drop из sub-only pool в начале месяца |
| 💎 Sub Discord channel | Внешний linked invite |
| 🚫 Без рекламы | Если когда-то добавим promo cards — bypass |

### 🥈 Tier 2 — "Постоянка" (~500-700₽/мес)

Premium с visible cosmetics в overlay (другие viewers видят что ты sub).

Всё из Tier 1, плюс:

| Perk | Реализация |
|---|---|
| 🌟 Animated pet auras | Sub-only items в `pet_catalog` с tier_gate='tier2' |
| 🖼 Custom card frame | Золотая рамка вокруг summoned hero в `overlay.html` |
| 🐾 Custom slime palette (4 sub-only) | Sub-only entries в `PET_PALETTES` (radioactive/glitch/gold-foil/holographic) |
| ⏰ Early access — beta toggle | Feature flag в frontend на основе sub_tier |
| 📞 Voice chat lobby за 30 мин до стрима | Discord-side, не интегрируется в код |
| 🎤 Premium TTS voices | gTTS дополнительные lang/accent параметры (`/api/tts/submit` принимает voice_param) |
| 📣 "Гость недели" overlay | Раз/неделю выбор random sub'a → 1-мин показ в overlay |

### 🥇 Tier 3 — "Меценат" (~1500-2000₽/мес)

⚠️ **Отложено за MVP** — требует custom artwork работы per-viewer.

| Perk | Сложность |
|---|---|
| 🎨 Custom pet species (sprite design) | Custom SVG generation (Claude Design per-sub, ~$X в Anthropic credit) |
| 🏰 Custom Bannerlord clan banner | Custom SVG, persistent |
| 👤 Hero portrait вместо текста | Sprite generation, OBS overlay |
| 📜 Honor Wall | Отдельная страница / overlay panel |
| 🎬 Personalized intro при призыве | TTS + overlay panel customization |
| 🛠 Direct feature requests | Discord priority, off-product |
| 📊 Personal stats dashboard | Custom view с persistent data (survive save resets) |
| 💬 Кастомный chat command `!{phrase}` | Bot command registration через config UI |

---

## Cross-game cosmetics — "Меценатские очки"

**Идея:** единая sub-валюта поверх tiers, тратится на cosmetics в любой игре.

```
Tier 1 = 100 очков / мес
Tier 2 = 300 очков / мес
Tier 3 = 1000 очков / мес
```

Тратятся на:
- Bannerlord clan banner (50 очков)
- Pet item премиум (30-100 очков)
- RimWorld pawn skin (50 очков)
- TTS premium voice slot (20 очков на 100 messages)

**НЕ доступны** за крустики (regular currency). Persistent across months.

**Pro:** viewer'ы видят value подписки независимо от того, в какую игру стример играет.
**Contra:** усложнение UI. Возможно отложить до v2.

---

## Database schema (M37 migration)

```sql
-- M37: subscriptions table
CREATE TABLE viewer_subscriptions (
    channel_id    INTEGER NOT NULL,
    username      TEXT NOT NULL,
    tier          TEXT NOT NULL,         -- 'tier1' | 'tier2' | 'tier3'
    source        TEXT NOT NULL,         -- 'boosty' | 'manual' (admin)
    started_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at    TIMESTAMP NOT NULL,    -- расчёт + 31 день от Boosty webhook
    cosmetics_json TEXT,                 -- JSON {name_color, badge_id, custom_caption, palette_unlocks[]}
    boosty_user_id TEXT,                 -- для webhook match
    PRIMARY KEY (channel_id, username)
);

CREATE INDEX idx_subscriptions_expires ON viewer_subscriptions(expires_at);
CREATE INDEX idx_subscriptions_boosty ON viewer_subscriptions(boosty_user_id);
```

### Опционально (для Tier 1 cosmetics)

```sql
-- Subscriptions могут тратить очки на эксклюзив items
CREATE TABLE viewer_sub_currency (
    channel_id INTEGER NOT NULL,
    username   TEXT NOT NULL,
    balance    INTEGER NOT NULL DEFAULT 0,
    earned_total INTEGER NOT NULL DEFAULT 0,    -- lifetime
    spent_total  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (channel_id, username)
);

CREATE TABLE viewer_sub_unlocks (
    channel_id INTEGER NOT NULL,
    username   TEXT NOT NULL,
    item_id    TEXT NOT NULL,      -- 'pet:hat_rainbow' | 'bannerlord:banner_gold' | 'tts:voice_robot'
    unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_id, username, item_id)
);
```

---

## Boosty integration

### Webhook flow

Boosty не имеет официального webhook API (по состоянию на 2026-05-21). Варианты:

1. **Polling Boosty API** — `GET /api/v1/{user}/subscribers` каждые 5-15 мин, diff'им с БД
   - Pro: легко реализовать
   - Contra: задержка до 15 мин при новом sub'е, нужен Boosty access token
2. **Manual sub linking** — viewer вводит в extension свой Boosty username + код для верификации
   - Pro: zero Boosty API dependency
   - Contra: viewer-side friction
3. **Гибрид** — manual link при первой подписке, потом polling для renewals

**Для MVP:** вариант 3. Viewer 1 раз вводит свой Boosty username в extension, мы polling'ом обновляем `expires_at`.

### Backend (`routes/subscriptions.py` — новый)

```python
# Эндпоинты MVP
POST /api/sub/link          # {boosty_username, verify_code}
GET  /api/sub/me            # current sub state + perks
GET  /api/sub/cosmetics     # available cosmetics для my tier
POST /api/sub/customize     # update cosmetics_json (name_color, caption, etc)

# Admin only
POST /api/admin/sub/grant   # ручное добавление sub (для тестов / награждения)
POST /api/admin/sub/expire  # отозвать
```

### Polling task

`backend/sub_poller.py` — async task запускается на старте supervisor'а:
- Каждые 10 мин: для каждого linked Boosty user → check API → update tier/expires_at
- Если истёк → демоут до 'free' (cosmetics остаются visible но lock-on'ятся)

---

## Frontend touchpoints

### Где cosmetic gates

1. **extension.html / mobile.html** — секция "Профиль" с кастомизацией ника/подписи (только если sub)
2. **viewer.js hero card render** — добавить badge SVG + цветной ник
3. **overlay.html** — золотая рамка вокруг hero cards для tier2+ subs
4. **pet-stage.js** — sub-only palette options + sub-only items при render
5. **chat-area** — sub badge рядом с message author

### Sub badge SVG (placeholder, заменим pixel-art версией когда придёт)

```html
<svg viewBox="0 0 24 24" class="sub-badge sub-tier-{1|2|3}">
  <path d="..." fill="var(--tier-color)"/>
</svg>
```

Tier colors:
- Tier 1: серебро `#c0c0c0`
- Tier 2: золото `#f0c33a`
- Tier 3: радуга `linear-gradient(...)`

---

## Implementation phases

### Phase 1 — Backend wiring (~4-6 часов)

- [ ] M37 migration: `viewer_subscriptions`
- [ ] `routes/subscriptions.py`: link / me / cosmetics / customize endpoints
- [ ] `sub_poller.py` task: Boosty API polling
- [ ] Test 19 extension для sub data isolation

### Phase 2 — Tier 1 frontend (~3-4 часа)

- [ ] Sub link modal в extension UI ("введи свой Boosty username")
- [ ] Подпись + цветной ник + badge render в hero card
- [ ] Sub-only pet items unlock'нутся когда `tier >= 1`
- [ ] Monthly drop random item — backend cron, добавление в `pet_unlocked` table

### Phase 3 — Tier 2 cosmetics (~4-5 часов)

- [ ] Sub-only pet palettes (4 цвета) — добавить в `PET_PALETTES` с `tier_gate='tier2'`
- [ ] Animated pet auras — sub-only items в `pet_catalog` с `tier_gate`
- [ ] Custom card frame в `overlay.html` для tier2+ subs
- [ ] Premium TTS voices — `/api/tts/submit` принимает `voice` param, поддерживает 5-6 variants
- [ ] Early access feature flag — `?beta=true` в URL → frontend читает `_subscription.tier >= 2`

### Phase 4 — Polish + monitoring (~2-3 часа)

- [ ] Admin panel UI для grant/expire
- [ ] Analytics — sub conversion / retention metrics
- [ ] "Guest of the week" overlay panel
- [ ] Auto-expire workflow + email/Discord ping owner

### Phase 5 — Tier 3 (отложено, заявка по mvp data)

После Phase 1-4 + анализа conversion из Tier 1 → 2 → 3. Если есть spending demand — делаем custom artwork pipeline (Claude Design generation per-sub).

---

## Risk register

| Риск | Митигация |
|---|---|
| Twitch отозвает extension за pay-to-win претензию | Strict cosmetic-only enforcement в коде + audit перед каждым deploy |
| Boosty API меняется / закрывается | Manual fallback link, не критически зависим |
| Viewer обманывает (Boosty user fake) | Verify code: одноразовый key, viewer должен опубликовать на своём Boosty profile / отправить в стример Discord |
| Бренди bookkeeping (subs истекают) | Daily cron task auto-expire + email уведомление owner'у |
| Sub видит что perks тривиальные → отписывается | Quarterly content drops — новые sub-only items, чтобы оставался reason renew |

---

## Open questions

1. **Цены в RUB или USD?** Boosty — RUB native. Stripe / PayPal — USD/EUR. Возможно multi-platform позже.
2. **Цвет accent для tier 2 sub** — кастомизация или fixed gold?
3. **Honor wall** — публичный (видят все viewers) или sub-only?
4. **Sub-only Discord channel** — модерация чья? streamer'a или automated?
5. **Refund policy** — если viewer купил и пожаловался, что делать с unlocked cosmetics?

---

## Дальнейшие шаги

- [ ] Стример (shedoy23) одобряет tier prices + perk list
- [ ] Решить вопросы из Open questions (выше)
- [ ] Phase 1 implementation start — после deploy текущего pet pixel-art batch'a
- [ ] M37 migration + Boosty wiring → Phase 2-3 — параллельно
- [ ] Soft-launch Tier 1 → 2 недели метрик → решение про Tier 2 launch
- [ ] Tier 3 — постponed, не in scope MVP

---

**Источник:** ChatGPT-консультация со streamer'ом (2026-05-21), Twitch ToS analysis,
Boosty product research. Update'нуть при первом запуске + после feedback от subs.
