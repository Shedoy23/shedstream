# Подписочная система — MVP Plan (final)

**Статус:** ⚠ **Partial impl shipped → NEUTRALIZED Sprint 5.33 (commit `9a0929c`)**

История:
- 2026-05-21: design draft (этот документ)
- Sprint 5.31 (#45): shipped Boosty manual list (`m42_boosty_subscribers.py`,
  `routes/bannerlord_boosty.py`) + Twitch native sub detection (`twitch_subs.py`,
  `SUB_BOOSTS` multipliers tier 1/2/3 → 0.85/0.70/0.50× price, 1.5/2.0/3.0× rewards).
- **Sprint 5.33 (2026-05-28, commit 9a0929c — feature/tos-compliance)**: gameplay
  multipliers за подписки REMOVED — Twitch Extension Developer Agreement
  prohibits subscription-gated gameplay rewards в Extensions. Spirit applies
  к third-party paid subs (Boosty/Patreon/Ko-fi) тоже.
  - `SUB_BOOSTS` всё → (1.0, 1.0)
  - Boosty router endpoints остались для **cosmetic UI only** (badge display)
  - `bannerlord.buy_action` больше не дёргает `get_boosty_tier`
  - `_ACTIONS_MIN_ROLE`: removed "subscriber" gates, оставлен только role-based
- Sprint 5.33 follow-up (commit `d46284d`): Boosty admin UI honest disclosure
  ("cosmetic only" warning, удалены misleading "T1 — ×0.85" labels).

**Применимость данного документа сегодня:**
- ✅ Раздел "Что РАЗРЕШЕНО" (cosmetic badges, emotes, frames) — still valid
- ✅ "❌ Что НЕ ДОБАВЛЯЕМ (pay-to-win banned)" — это и было нарушено в 5.31,
  fix'нуто в 5.33. **Following this rule strictly going forward.**
- ❌ Phase 2 implementation flow (admin grant, sub_status table) — частично shipped,
  но gameplay-effects neutralized

См. также: `BLT_AUDIT_2026-05-28.md` для актуального состояния.

**Created:** 2026-05-21 (initial)
**Revised:** 2026-05-21 (verification против Twitch ToS — упрощено после правильного чтения §5.2)
**Status update:** 2026-05-28 (Sprint 5.33 ToS compliance)

---

## TL;DR

3 тира подписки → viewer получает **cosmetic + convenience + community** perks. Подписка происходит **off-extension** (Twitch native, Boosty, Patreon), extension только **отображает** результат.

**MVP scope:** Tier 1 + Tier 2 backend wiring через Twitch native subs **И** Boosty manual grant. Tier 3 (custom artwork) отложен.

---

## ⚠️ Twitch Extension Guidelines — что точно НЕЛЬЗЯ

Цитаты из [Extensions Guidelines & Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/):

| Section | Запрет | Как соблюдаем |
|---|---|---|
| §5.2 | "Extensions may not allow items to be exchanged for money or other commerce instruments" | Нет purchase flow в extension. Payment происходит off-extension. Extension только **reads** membership state. |
| §4.6.3 | Off-site links на коммерческие сайты | Нет "Subscribe on Boosty!" CTA buttons в extension UI. Описание подписки — в Twitch panel description / Discord, **не** в extension. |
| §4.11 | NFTs | Не используем. |
| §5.3 | Loot boxes с monetary value | Sub-only items НЕ являются loot boxes — это predetermined unlocks. |
| §6.2.1 | Pay-to-play game access | Не блокируем mini-games / gameplay за подписку. Только cosmetic + convenience. |
| §6.2.3-6.2.6 | Gambling / sweepstakes | Не делаем. |

## ✅ Что РАЗРЕШЕНО (и industry standard)

| Что | Источник / прецедент |
|---|---|
| Extension показывает sub badge для Twitch native subs | [Subscription Status API](https://dev.twitch.tv/docs/extensions/reference/#configuration-service) — Twitch специально сделал |
| Cosmetic unlocks для viewer'ов с external membership (Patreon/Boosty) | StreamElements, Streamlabs, десятки existing extensions это делают |
| Sub badges / custom emotes / frames / colors | Mainstream practice |
| Pet items / character cosmetics → unlocked for subs | Cosmetic only — не competitive advantage |
| Out-of-band perks через Discord / YouTube / private streams | 100% safe |
| Bits для unlocking levels/avatars/features | [Bits Acceptable Use](https://legal.twitch.com/legal/bits-acceptable-use/) |

## ❌ Что НЕ ДОБАВЛЯЕМ (pay-to-win banned)

- ❌ Bonus crusticov ежемесячно (это competitive currency)
- ❌ Снижение cooldown'ов (`player.spawn`, powers, retinue)
- ❌ ELO boost / выигрыш в mini-games
- ❌ Skip queue в tournaments
- ❌ Эксклюзивные классы / powers в Bannerlord
- ❌ Доп retinue slots / Hero.Gold multipliers
- ❌ Higher loot rates / extra HP
- ❌ Free tournament entry

**Правило:** viewer без подписки и viewer с подпиской играют в mini-game → **те же шансы**. Подписан **выглядит круче**, не **выигрывает чаще**.

---

## Подписка — два канала

### 🅰️ Канал A: Twitch native subs (primary)

Через [Subscription Status API](https://dev.twitch.tv/docs/extensions/reference/#configuration-service):
```js
twitch.onAuthorized(auth => {
    // auth.token JWT содержит subscription_status claim
    // tier = 'not_subscribed' | '1000' | '2000' | '3000'
});
```

**Pros:** 100% legal, Twitch payment handles everything, automated, viewer'ы знают как пользоваться.

**Cons:** Russian viewers не могут платить (карты заблочены), Twitch fees 30-50%, цены fixed ($4.99 / $9.99 / $24.99).

### 🅱️ Канал B: Boosty manual grant (RU-friendly fallback)

**Flow:**
1. Viewer подписывается на Boosty **off-Twitch**
2. Viewer пишет streamer'у в Discord (screenshot Boosty profile)
3. Streamer через **admin panel** grant'ит perks: `POST /api/admin/sub/grant`
4. Extension отображает cosmetics — viewer видит badge/color/items

**Pros:** Покрывает Russian viewers, no Twitch fee, streamer ручной control verify.

**Cons:** Manual labor (~minutes/sub), latency от purchase до grant, no automation.

### 🅲 Канал C: Boosty automated polling (Phase 2 — future)

Backend polling Boosty API → auto-grant. Возможный compliance gray area если в extension UI прямо отображается "Boosty подписка → unlock". Митигация — описывать cosmetics generically ("Patron unlock") без mention Boosty.

**Для MVP пропускаем.**

---

## Tier breakdown (final)

### 🥉 Tier 1 — "Зритель"

**Условие:** Twitch Tier 1 sub ($4.99) OR Boosty ~200₽/мес OR manual admin grant

| Perk | Где видно |
|---|---|
| 🎨 Цветной ник в extension (выбор из 6 палитр) | Extension UI |
| 📛 Sub badge рядом с ником | Extension UI + overlay |
| 💬 Кастомная подпись (≤30 chars) | Extension hero card |
| 🎁 Random rare pet item раз в месяц | Pet inventory (sub-only items unlocked) |
| 💎 Sub-only Discord channel | Discord (off-Twitch) |

### 🥈 Tier 2 — "Постоянка"

**Условие:** Twitch Tier 2 ($9.99) OR Boosty ~500-700₽/мес OR manual admin grant

Всё из Tier 1, плюс:

| Perk | Где видно |
|---|---|
| 🌟 Animated pet auras (sub-only) | Pet inventory + overlay |
| 🖼 Custom card frame в overlay | OBS overlay (золотая рамка) |
| 🐾 Custom slime palette (4 sub-only) | Pet inventory |
| ⏰ Early access — beta toggle | URL flag, feature gates |
| 📞 Voice chat lobby за 30 мин до стрима | Discord (off-Twitch) |
| 🎤 Premium TTS voices | Extension TTS modal (всем доступен basic TTS) |
| 📣 "Гость недели" overlay | OBS overlay panel |

### 🥇 Tier 3 — "Меценат" (Phase 5, отложен)

**Условие:** Twitch Tier 3 ($24.99) OR Boosty ~1500-2000₽/мес OR manual grant

Всё из Tier 1+2, плюс:

| Perk | Где видно |
|---|---|
| 🎨 Custom pet species (sprite design) | Pet inventory — unique entry |
| 🏰 Custom Bannerlord clan banner | Game + extension |
| 👤 Custom hero portrait | Extension + overlay |
| 📜 Honor Wall mention | Overlay panel |
| 🎬 Personalized intro при призыве | OBS overlay |
| 🛠 Direct feature requests | Discord priority |
| 📊 Personal stats dashboard | Sub-only extension view |
| 💬 Кастомный chat command | Bot registration |

**Отложено потому что:** требует per-viewer custom artwork (Claude Design generation costs / artist work).

---

## Cross-game cosmetics — "Меценатская валюта" (опционально)

Единая sub-валюта поверх tiers:
```
Tier 1 = 100 очков / мес
Tier 2 = 300 очков / мес  
Tier 3 = 1000 очков / мес
```

Тратятся на эксклюзив cosmetics в **любой** игре:
- Bannerlord clan banner (50)
- Pet item премиум (30-100)
- RimWorld pawn skin (50)
- TTS voice slot (20)

Persistent across months — viewer чувствует value подписки независимо от того, в какую игру стример играет.

**Pro:** Долгосрочный engagement через collectibles.
**Contra:** Усложнение UI. Можно отложить до v2.

---

## Database schema (M37 migration)

```sql
-- M37: viewer_subscriptions — unified state (Twitch + Boosty + manual)
CREATE TABLE viewer_subscriptions (
    channel_id     INTEGER NOT NULL,
    username       TEXT NOT NULL,
    tier           TEXT NOT NULL,         -- 'tier1' | 'tier2' | 'tier3'
    source         TEXT NOT NULL,         -- 'twitch_native' | 'boosty_manual' | 'admin_grant' | 'patreon_manual'
    twitch_tier    TEXT,                  -- '1000' | '2000' | '3000' (если source='twitch_native')
    started_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at     TIMESTAMP NOT NULL,
    cosmetics_json TEXT,                  -- {name_color, badge_variant, custom_caption}
    granted_by     TEXT,                  -- admin username если manual grant
    granted_note   TEXT,                  -- "Boosty screenshot verified at 2026-05-21"
    PRIMARY KEY (channel_id, username)
);

CREATE INDEX idx_subscriptions_expires ON viewer_subscriptions(expires_at);
```

### M38: pet_catalog tier_gate column

```sql
ALTER TABLE pet_catalog ADD COLUMN tier_gate TEXT;
-- 'tier1' | 'tier2' | 'tier3' | NULL (open для всех)

CREATE INDEX idx_pet_catalog_tier_gate ON pet_catalog(tier_gate);
```

Эти ALTER'ы — обычные idempotent миграции.

---

## Backend endpoints

```python
# routes/subscriptions.py — новый файл

# Viewer-facing
GET  /api/sub/me                # current sub state + perks
GET  /api/sub/cosmetics         # available cosmetics для my tier
POST /api/sub/customize         # update cosmetics_json (color, caption)
POST /api/sub/sync              # Twitch native — sync tier from JWT

# Admin
POST /api/admin/sub/grant       # ручное добавление (Boosty / Patreon manual)
POST /api/admin/sub/expire      # отозвать
GET  /api/admin/sub/list        # все subs канала с фильтрами
```

---

## Twitch native sub integration (Phase 1)

### Frontend

```js
// viewer.js — на onAuthorized
twitch.onAuthorized(auth => {
    fetch('/api/sub/sync', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${auth.token}` }
    });
});
```

### Backend

```python
# routes/subscriptions.py
@router.post("/api/sub/sync")
async def sync_twitch_sub(claims):
    """JWT extension claims содержат subscription_status:
       'not_subscribed' / '1000' / '2000' / '3000'
       (если extension declared Subscription Status capability в manifest)
    """
    twitch_tier = claims.get('subscription_status')
    if twitch_tier in ('1000', '2000', '3000'):
        tier_map = {'1000': 'tier1', '2000': 'tier2', '3000': 'tier3'}
        await upsert_subscription(
            channel_id=claims['channel_id'],
            username=claims['user_id'],
            tier=tier_map[twitch_tier],
            source='twitch_native',
            twitch_tier=twitch_tier,
            expires_at=now + days(31)
        )
```

**Capability enable:** в Twitch Developer Console для extension → `Subscription Status` checkbox.

---

## Admin grant flow (Boosty / Patreon manual)

```python
# routes/admin.py
@router.post("/api/admin/sub/grant")
async def admin_grant_sub(claims=Depends(require_admin)):
    """Body: {username, tier, source, duration_days, note}"""
    data = await request.json()
    await upsert_subscription(
        channel_id=streamer_channel_id,
        username=data['username'],
        tier=data['tier'],
        source=data['source'],  # 'boosty_manual' | 'patreon_manual' | etc.
        expires_at=now + days(data['duration_days']),
        granted_by=claims['username'],
        granted_note=data['note']
    )
```

**Admin panel** (`/admin/subscriptions`):
- Username text input
- Tier select (tier1/2/3)
- Duration input (default 31 days)
- Source select (boosty/patreon/manual/etc.)
- Note textarea

---

## Frontend cosmetic gates

### 1. Hero card render

```js
function renderHeroCard(hero) {
    const sub = _bannerlordLastHero?.subscription;
    const nameColor = sub?.cosmetics?.name_color || '#efeff1';
    const badge = sub?.tier ? renderSubBadge(sub.tier) : '';
    
    return `<div class="hero-card">
        ${badge}
        <span style="color:${nameColor}">${hero.name}</span>
        ${sub?.cosmetics?.caption ? `<div class="sub-caption">${sub.cosmetics.caption}</div>` : ''}
    </div>`;
}
```

### 2. Pet items filter

```js
// pets.js — render catalog
const TIER_ORDER = { tier1: 1, tier2: 2, tier3: 3 };
const userTier = TIER_ORDER[currentSubTier] || 0;

const items = catalog.filter(item => {
    if (!item.tier_gate) return true;  // open для всех
    return userTier >= (TIER_ORDER[item.tier_gate] || 99);
});
```

### 3. Overlay frame

```js
// overlay.html — для tier2+ subs
participants.forEach(p => {
    const cardClass = p.sub_tier >= 2 ? 'sub-frame-gold' : '';
    // ...
});
```

### 4. TTS voices

```python
# routes/tts.py
DEFAULT_VOICES = ['default_male', 'default_female']
PREMIUM_VOICES = ['robot', 'baby', 'deep', 'asmr', 'announcer']

def allowed_voices(user_sub_tier):
    return DEFAULT_VOICES + (PREMIUM_VOICES if user_sub_tier >= 2 else [])
```

---

## Implementation phases

### Phase 1 — Twitch native subs (~4-5 часов)

- [ ] M37 migration: `viewer_subscriptions`
- [ ] Enable Subscription Status capability в Twitch Developer Console
- [ ] `routes/subscriptions.py`: `/api/sub/me`, `/api/sub/sync`, `/api/sub/customize`
- [ ] Frontend: sub state caching, `twitch.onAuthorized` → `/api/sub/sync`
- [ ] Tier 1 cosmetics: name color picker, custom caption, badge SVG render

### Phase 2 — Boosty / Patreon manual grant (~3-4 часа)

- [ ] Admin panel: `/admin/subscriptions` page (HTML form)
- [ ] `routes/admin.py`: `/api/admin/sub/grant`, `/api/admin/sub/expire`, `/api/admin/sub/list`
- [ ] Frontend: render manual-granted subs identically с Twitch native
- [ ] Docs: streamer flowchart для verify Boosty subscribers

### Phase 3 — Tier 2 cosmetics (~4-5 часов)

- [ ] M38 migration: `pet_catalog.tier_gate`
- [ ] Pet palettes: 4 sub-only entries (radioactive, glitch, gold-foil, holographic)
- [ ] Pet items: 5-10 sub-only entries marked tier_gate='tier2'
- [ ] Overlay: tier2+ frame styling
- [ ] TTS premium voices: backend param + frontend dropdown gating
- [ ] Animated pet auras (после pixel art batch'a от Claude Design)
- [ ] Early access feature flag (`?beta=true`)

### Phase 4 — Polish + monitoring (~2-3 часа)

- [ ] Daily cron: sub expiration → auto-demote
- [ ] Email / Discord ping owner на новой подписке
- [ ] Analytics dashboard: conversion / churn / breakdown by source
- [ ] Test 19 multi-tenant isolation для sub data

### Phase 5 — Tier 3 (отложен после launch)

- [ ] Custom artwork pipeline (Claude Design generation per-sub)
- [ ] Honor wall panel
- [ ] Personalized intro overlay
- [ ] Cross-game cosmetics — "Меценатская валюта" (опционально)

---

## Risk register

| Риск | Митигация | Severity |
|---|---|---|
| Twitch отозвать extension за §5.2 (payment flow concern) | Нет purchase CTA, нет payment forms в extension. Только reads external membership. | 🟢 Low (industry standard) |
| §4.6.3 off-site link на коммерческие сайты | Boosty/Patreon описания — в panel description / Discord, **не** в extension UI | 🟢 Low |
| Sub status JWT claim не работает | Fallback на Helix API call с extension client credentials | 🟢 Low |
| Russian viewers не могут платить ни Twitch ни Boosty | Allow manual admin grant с любым source | 🟢 Low |
| Viewer обманывает (fake Boosty screenshot) | Streamer manual verify — judgement call | 🟢 Low |
| Sub-only cosmetics не differentiate enough → отписки | Quarterly content drops с новыми items, exclusive seasonal events | 🟡 Mid |
| Manual grant burden если 50+ subs | Phase 2 polling Boosty API automation | 🟡 Mid |

---

## Open questions (отвечает streamer перед Phase 1)

1. **Tier цены RUB / USD** — финальные?
2. **Twitch native price tiers** ($4.99 / $9.99 / $24.99 fixed) — приемлемо?
3. **Honor wall** — public для всех viewers или sub-only view?
4. **Sub Discord channel** — кто модерирует?
5. **Premium TTS voices** — какие конкретно (robot/baby/deep/asmr/announcer)?
6. **Manual grant volume** — приемлемо отвечать на verify pings 1-3 раза в день?
7. **Cross-game cosmetics currency** — внедрять в MVP или Phase 5?

---

## Sources / verified citations

- [Twitch Extensions Guidelines & Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/) — §5.2 commerce, §4.6.3 off-site links, §4.11 NFTs, §5.3 loot boxes
- [Extension Monetization Documentation](https://dev.twitch.tv/docs/extensions/monetization/) — Subscription Status API
- [Twitch Developer Services Agreement](https://legal.twitch.com/legal/developer-agreement/)
- [Bits Acceptable Use Policy](https://legal.twitch.com/legal/bits-acceptable-use/) — §6.2.1 pay-to-play, §6.2.3-6.2.6 gambling
- [Monetized Streamer Agreement](https://legal.twitch.com/en/legal/monetized-streamer-agreement/) — May 2026 revisions
- [Monetization for All blog post (2026-05-13)](https://blog.twitch.tv/en/2026/05/13/monetization-for-all/)
- [Patreon perks for streamers](https://blog.patreon.com/rewards-for-streamers) — industry standard reference

---

**Дальнейшие шаги:**

- [ ] Streamer (shedoy23) одобряет финальный план
- [ ] Решить Open questions (7 вопросов выше)
- [ ] Phase 1 implementation — после pet pixel-art batch'а
- [ ] Soft-launch Twitch native subs → 2 недели метрик
- [ ] Phase 2 (Boosty manual) — параллельно или после Phase 1 stable
