# Подписочная система — MVP Plan (revised)

**Статус:** Design draft, не реализовано
**Created:** 2026-05-21 (initial)
**Revised:** 2026-05-21 (после verification против Twitch Extension Guidelines)

**КРИТИЧЕСКОЕ ОТКРЫТИЕ:** прямой Boosty-only flow **в extension** содержит compliance риски. Strategy переосмыслена: **двойной канал** — Twitch native subs как primary + Boosty как fallback для регионов без Twitch payment.

---

## TL;DR (revised)

Старый план — "Boosty подписки → unlock cosmetics в extension" — **на грани Section 5.2** ("Extensions may not allow items to be exchanged for money or other commerce instruments").

Новый план:
- **Primary channel:** Twitch native subscriptions через Subscription Status API ✅ **0% risk, Twitch-incentivized**
- **Secondary channel:** Boosty manual-grant (без direct in-extension purchase flow) ⚠️ **низкий риск, work-around для Russian viewers без Twitch payment**

**MVP scope:** Twitch native subs → cosmetic unlocks. Boosty integration — Phase 2.

---

## ⚠️ Verified Twitch Extension Guidelines compliance

Источники: [Extension Guidelines & Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/), [Monetization](https://dev.twitch.tv/docs/extensions/monetization/), [Developer Services Agreement](https://legal.twitch.com/legal/developer-agreement/), [Bits Acceptable Use](https://legal.twitch.com/legal/bits-acceptable-use/).

### ✅ ЯВНО РАЗРЕШЕНО

| Что | Источник |
|---|---|
| Bits для unlocking levels, lives, avatars, attributes, speeds, social features | Bits Acceptable Use |
| Twitch native subs — extension может видеть tier (1/2/3) viewer'a через Subscription Status API | Monetization docs |
| Streamer charging viewers (extension features for streamer) | §5.1 — "differentiated experiences or functionality" |
| Items exchangeable за loyalty points ИЛИ Bits | §5.2 |
| Off-platform perks через Discord / Patreon (вне extension) | Industry standard, не нарушает Twitch ToS |
| Cosmetic display в extension если sub status verified через Twitch API | По умолчанию |

### ❌ ЯВНО ЗАПРЕЩЕНО

| Что | Цитата |
|---|---|
| Items exchanged за money or commerce instruments | §5.2: "Extensions may not allow items to be exchanged for money or other commerce instruments" |
| Loot boxes с element of randomness и monetary value | §5.3 |
| Off-site links на коммерческие сайты (включая Boosty/Patreon purchase pages) | §4.6.3 |
| NFTs creation/listing/trading/redemption | §4.11 |
| Pay-to-play game access через Bits | §6.2.1 |
| Gambling/sweepstakes/wagering через Bits | §6.2.3-6.2.6 |
| Third-party advertising networks через extension | Twitch ToS — exclusive right to monetize |

### 🟡 СЕРАЯ ЗОНА (избегаем для safety)

| Что | Риск |
|---|---|
| Boosty subscription → unlock cosmetic в extension (direct link) | Может быть расценено как §5.2 violation (items exchanged for money) |
| In-extension UI "введи свой Boosty username" | Possibly OK, но **не должно содержать link/CTA на Boosty payment page** |
| "Premium TTS voices" gated за external sub | Серая зона — это extension feature gated за non-Bits/non-Twitch-sub payment |
| Кросс-game cosmetic currency через Boosty | Если описывается как "premium tier" — §5.2 риск |

### 🟢 БЕЗОПАСНЫЕ ПРИНЦИПЫ

1. **Twitch native sub** = primary signal для in-extension cosmetics. API легально, поддерживается, incentivized.
2. **Boosty / Patreon perks** — **только вне extension** (Discord, YouTube, etc.) — это standard practice
3. **Manual grant** через admin panel — minimal risk если не automated payment flow inside extension
4. **No purchase CTA** в extension UI на external platforms
5. **Cosmetic display** допустим если unlocks случились **вне extension** (не payment flow inside)

---

## Strategy — двойной канал

### Канал A: Twitch native subscriptions (primary)

Использует [Subscription Status API](https://dev.twitch.tv/docs/extensions/reference/#configuration-service):
```js
twitch.onAuthorized(auth => {
    twitch.viewer.subscriptionStatus  // tier 'not_subscribed' | '1000' | '2000' | '3000'
});
```

**Преимущества:**
- 100% Twitch-legal, специально для extensions
- Twitch pays creator 50-70% от sub
- Viewer уже умеет subscribe в Twitch
- Status auto-syncs, не нужен manual link

**Минусы:**
- Russian viewers не могут платить (PayPal/cards заблочены)
- Twitch fee = 30-50%
- Tier цены fixed: $4.99 / $9.99 / $24.99

### Канал B: Boosty manual (secondary, для RU)

**ВАЖНО:** ZERO direct integration с in-extension purchase flow. Только manual admin grant.

**Flow:**
1. Viewer subscribes на Boosty (off-Twitch)
2. Viewer пишет streamer'у в Discord/Twitter с подтверждением (screenshot Boosty profile)
3. Streamer через **admin panel** grant'ит perks вручную (`POST /api/admin/sub/grant`)
4. Extension отображает cosmetics для этого viewer'a (без знания почему)

**Преимущества:**
- Compliance-safe (нет purchase flow в extension)
- Покрывает Russian viewers
- Streamer ручной контроль (verify подлинности)

**Минусы:**
- Manual labor (не scaling если 50+ subs)
- Latency от purchase до grant (часы / дни)
- Verification механизм рудиментарный

### Канал C (отложен): Боссти автоматизация

Можно сделать polling Boosty API + auto-grant, **НО**:
- Если automation видна в extension UI ("Я подписан на Boosty → unlock cosmetic") → §5.2 risk
- Если automation **off-extension** (backend получает Boosty webhook → updates DB → extension показывает result) — **возможно** OK
- Решить **после** legal review or Twitch dev support consultation

**Для MVP пропускаем.**

---

## Tier breakdown (revised)

Все perks **строго cosmetic / convenience / community**, чтобы избежать pay-to-win претензий.

### 🥉 Tier 1 — "Зритель" (Twitch Tier 1 sub OR Boosty ~200₽/мес)

| Perk | Где видно | Безопасность |
|---|---|---|
| 🎨 Цветной ник в extension | extension UI | ✅ Cosmetic |
| 📛 Sub badge рядом с ником | extension UI + overlay | ✅ Cosmetic |
| 💬 Кастомная подпись (≤30 chars) | extension UI hero card | ✅ Cosmetic |
| 🎁 Random rare pet item ежемесячно | Pet inventory unlock | ✅ Cosmetic (не competitive) |
| 💎 Sub-only Discord channel | Discord (off-Twitch) | ✅ 100% out-of-band |
| 🚫 Without ads | Extension UI (если когда-то добавим promo) | ✅ Convenience |

### 🥈 Tier 2 — "Постоянка" (Twitch Tier 2 OR Boosty ~500-700₽/мес)

Всё из Tier 1 +

| Perk | Где видно | Безопасность |
|---|---|---|
| 🌟 Animated pet auras (sub-only items) | Pet inventory | ✅ Cosmetic |
| 🖼 Custom card frame в overlay | OBS overlay | ✅ Cosmetic |
| 🐾 Custom slime palette (4 sub-only) | Pet inventory | ✅ Cosmetic |
| ⏰ Early access — beta features | Extension UI feature flag | ✅ Convenience |
| 📞 Voice chat lobby за 30 мин | Discord (off-Twitch) | ✅ 100% out-of-band |
| 🎤 Premium TTS voices | Extension TTS modal | 🟡 См. ниже |
| 📣 "Гость недели" overlay | OBS overlay panel | ✅ Cosmetic |

**🟡 Премium TTS voices** — серая зона если viewer не получает то же качество TTS без подписки. Mitigation:
- **All viewers** имеют access к basic TTS (стандартные голоса)
- **Subs** имеют access к +5 voice variants (additional, не "лучше")
- TTS character cap одинаковый для всех
- Бот сам генерит audio в любом случае — sub только меняет voice param

Это similar to "custom emote" — premium content **в дополнение**, не **вместо**.

### 🥇 Tier 3 — "Меценат" (Twitch Tier 3 OR Boosty ~1500-2000₽/мес)

⚠️ **Отложено за MVP** — требует per-viewer custom artwork (Claude Design generation costs / Anthropic credits).

| Perk | Где видно | Безопасность |
|---|---|---|
| 🎨 Custom pet species (sprite design) | Pet inventory unique entry | ✅ Cosmetic |
| 🏰 Custom Bannerlord clan banner | Game / extension | ✅ Cosmetic |
| 👤 Hero portrait вместо текста | Extension UI + overlay | ✅ Cosmetic |
| 📜 Honor Wall mention | Overlay панель | ✅ Recognition |
| 🎬 Personalized intro при призыве | OBS overlay | ✅ Recognition |
| 🛠 Direct feature requests | Discord priority | ✅ Out-of-band |
| 📊 Personal stats dashboard | Extension UI sub-only view | ✅ Cosmetic data |
| 💬 Кастомный chat command `!{phrase}` | Twitch chat | 🟡 Bot-controlled, проверь chat ToS |

---

## ❌ ЧТО НЕ ДОБАВЛЯЕМ (банится по правилам)

### Pay-to-win (Section 5.2)

- ❌ Bonus crusticov в месяц
- ❌ Снижение cooldown'ов
- ❌ ELO boost в mini-games
- ❌ Skip queue в tournaments
- ❌ Эксклюзивные классы / powers в Bannerlord
- ❌ Доп retinue slots
- ❌ Higher loot rates / Hero.Gold income multipliers
- ❌ Free tournament entry

### Gambling / sweepstakes (Section 6.2.3-6.2.6)

- ❌ Loot box mechanic с monetary value
- ❌ Gachapon-style pet pulls с random rarity
- ❌ Chance to win Bits/money via subscription

### Off-site monetization (Section 4.6.3, 4.11)

- ❌ NFT integration
- ❌ Direct purchase link в extension UI
- ❌ Third-party ad networks через extension
- ❌ "Subscribe on Boosty" CTA button в extension

---

## Database schema (M37 migration)

```sql
-- M37: subscription state (unified Twitch + Boosty)
CREATE TABLE viewer_subscriptions (
    channel_id    INTEGER NOT NULL,
    username      TEXT NOT NULL,
    tier          TEXT NOT NULL,         -- 'tier1' | 'tier2' | 'tier3'
    source        TEXT NOT NULL,         -- 'twitch_native' | 'boosty_manual' | 'admin_grant'
    twitch_tier   TEXT,                  -- '1000' | '2000' | '3000' (если source=twitch_native)
    started_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at    TIMESTAMP NOT NULL,
    cosmetics_json TEXT,                 -- JSON {name_color, badge_variant, custom_caption}
    granted_by    TEXT,                  -- admin username если source='admin_grant'
    granted_note  TEXT,                  -- "Boosty subscription verified by screenshot at 2026-05-21"
    PRIMARY KEY (channel_id, username)
);

CREATE INDEX idx_subscriptions_expires ON viewer_subscriptions(expires_at);
```

**Note:** убрали `boosty_user_id` колонку — без auto-polling Boosty API она не нужна. Manual grant flow не требует Boosty ID storage.

---

## Twitch Subscription Status integration (Phase 1 priority)

### Frontend

```js
// extension.js / viewer.js на onAuthorized
twitch.onAuthorized(auth => {
    fetch('/api/sub/sync', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${auth.token}` }
    });
});

// Listen for subscription state changes
twitch.listen('broadcast', (target, contentType, message) => {
    if (message === 'subscription_changed') reloadHero();
});
```

### Backend

```python
# routes/subscriptions.py
@router.post("/api/sub/sync")
async def sync_twitch_subscription(claims):
    """Frontend sends Twitch JWT → backend extracts subscription tier
    from JWT claims OR через Helix API call.
    JWT contains: sub (user_id), subscription_status (опционально),
    pubsub_perms etc.
    """
    twitch_tier = claims.get('subscription_status')  # '1000' / '2000' / '3000' / null
    if twitch_tier:
        await upsert_subscription(
            channel_id=claims['channel_id'],
            username=claims['user_id'],
            tier=map_twitch_to_internal(twitch_tier),
            source='twitch_native',
            twitch_tier=twitch_tier,
            expires_at=now + 31 days
        )
```

**Twitch JWT contains** `subscription_status` claim если extension has Subscription Status capability enabled (declare в manifest). Free Twitch feature.

---

## Admin grant flow (Boosty manual)

```python
# routes/admin.py
@router.post("/api/admin/sub/grant")
async def admin_grant_subscription(request, claims=Depends(require_admin)):
    """Streamer вручную добавляет sub после off-Twitch verification.
    Body: {username, tier, source='boosty_manual', duration_days=31, note}
    """
    data = await request.json()
    await upsert_subscription(
        channel_id=streamer_channel_id,
        username=data['username'],
        tier=data['tier'],
        source='boosty_manual',
        expires_at=now + days(data['duration_days']),
        granted_by=claims['username'],
        granted_note=data['note']
    )
```

**Admin panel UI** (HTML form):
- Username dropdown
- Tier select
- Duration (default 31 days)
- Source select (boosty/youtube/manual/etc.)
- Note text area ("Boosty screenshot verified at...")

---

## Frontend cosmetic gates

Где cosmetics будут видны если viewer sub:

### 1. Hero card в extension.html

```js
function renderHeroCard(hero) {
    const sub = _bannerlordLastHero?.subscription;
    const nameColor = sub?.cosmetics?.name_color || '#efeff1';
    const badge = sub?.tier ? renderBadge(sub.tier) : '';

    return `<div class="hero-card">
        ${badge}
        <span style="color:${nameColor}">${hero.name}</span>
        ${sub?.cosmetics?.caption ? `<div class="sub-caption">${sub.cosmetics.caption}</div>` : ''}
    </div>`;
}
```

### 2. Pet items unlock

```js
// pets.js — render catalog
const items = catalog.filter(item => {
    if (!item.tier_gate) return true;
    return userSubTier >= item.tier_gate;
});
```

### 3. Overlay decorations (overlay.html)

```js
// Tier 2+ subs get golden frame around summoned hero
const frameClass = participant.sub_tier >= 2 ? 'sub-tier2-frame' : '';
```

### 4. TTS premium voices

```python
# routes/tts.py
ALL_VOICES = ['default']
PREMIUM_VOICES = ['robot', 'baby', 'deep', 'asmr', 'announcer']

def get_allowed_voices(user_tier):
    return ALL_VOICES + (PREMIUM_VOICES if user_tier >= 2 else [])
```

---

## Implementation phases

### Phase 1 — Twitch native subs (~4-5 часов) ⭐ PRIORITY

- [ ] M37 migration: `viewer_subscriptions` table
- [ ] Manifest update: enable Subscription Status capability in Twitch Developer Console
- [ ] Frontend: `twitch.onAuthorized` → `/api/sub/sync` call
- [ ] Backend `/api/sub/sync`: extract tier from JWT, upsert DB
- [ ] Tier 1 cosmetics: name color picker, custom caption, badge SVG render
- [ ] Pet catalog: add `tier_gate` column (M38), 5-10 sub-only items

### Phase 2 — Boosty manual flow (~3-4 часа)

- [ ] Admin panel: `/admin/subscriptions` page (HTML form)
- [ ] Backend: `POST /api/admin/sub/grant` endpoint (require_admin)
- [ ] Frontend: render Boosty-granted subs same way как Twitch native subs
- [ ] Docs: streamer instructions ("how to verify Boosty subscriber")

### Phase 3 — Tier 2 cosmetics (~4-5 часов)

- [ ] Pet palettes: 4 sub-only entries (radioactive, glitch, gold-foil, holographic)
- [ ] Overlay: tier2 frame styling
- [ ] TTS premium voices: backend voice param + frontend dropdown
- [ ] Animated pet auras (need pixel art batch from Claude Design)
- [ ] Early access feature flag (`?beta=true` URL toggle)

### Phase 4 — Polish + monitoring (~2-3 часа)

- [ ] Sub expiration cron task (daily check, auto-demote)
- [ ] Email/Discord ping streamer на новой подписке (Twitch native)
- [ ] Analytics dashboard: sub conversion / churn / breakdown by source
- [ ] Test 19 extension: sub data multi-tenant isolation

### Phase 5 — Tier 3 (отложен)

Только после Phase 1-4 + анализ Tier 1→2 conversion.

---

## Risk register (revised)

| Риск | Митигация | Severity |
|---|---|---|
| Twitch refused extension за §5.2 (Boosty as commerce instrument) | Strict separation: no purchase CTA в extension, manual admin grant only | 🟡 Mid |
| Sub status JWT claim не работает | Fallback на Helix API call с extension client credentials | 🟢 Low |
| Russian viewers не могут платить ни Twitch ни Boosty | Allow manual admin grant с любым source ('crypto', 'ko-fi', etc.) | 🟢 Low |
| Viewer обманывает (fake Boosty screenshot) | Streamer ручная verify — это его judgement call | 🟢 Low |
| Sub-only cosmetics виден как "premium tier locked to external pay" → §5.2 | Cosmetics unlocks через manual grant — нет automated payment connection в extension | 🟡 Mid |
| Currency conversion (USD ↔ RUB) | Multi-currency UI, prices in BOТH RUB и USD | 🟢 Low |
| Twitch меняет Subscription Status API | Subscription Status — stable Twitch product, доказано работает | 🟢 Low |

---

## Open questions (отвечает streamer перед Phase 1)

1. **Boosty integration срочность** — нужен ли в MVP (Phase 2) или отложить до запроса от viewer'ов?
2. **Tier цены RUB** — финальные? (200 / 500 / 1500 — это предположения)
3. **Honor wall** — public visible all viewers или sub-only?
4. **Sub-only Discord channel** — кто модерирует?
5. **Premium TTS voices** — какие конкретно? (robot/baby/deep — это плейсхолдеры)
6. **Manual grant frequency** — приемлемо ли для streamer'а отвечать на verify pings 1-2 раза в день?

---

## Sources / verified citations

- [Twitch Extensions Guidelines & Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/)
- [Extension Monetization Documentation](https://dev.twitch.tv/docs/extensions/monetization/)
- [Twitch Developer Services Agreement](https://legal.twitch.com/legal/developer-agreement/)
- [Bits Acceptable Use Policy](https://legal.twitch.com/legal/bits-acceptable-use/)
- [Twitch Monetized Streamer Agreement](https://legal.twitch.com/en/legal/monetized-streamer-agreement/)
- [Monetization for All blog post (May 2026)](https://blog.twitch.tv/en/2026/05/13/monetization-for-all/)

---

## TL;DR пересмотренного решения

**Раньше (initial draft):** "Boosty подписки → unlock cosmetics в extension" — ⚠️ §5.2 риск.

**Сейчас (revised):**
1. **Twitch native subscriptions** — primary channel (legal, Twitch-supported, automated)
2. **Boosty / Patreon / любой external** — manual admin grant only (streamer manually verifies, no in-extension purchase CTA)
3. **Cosmetic-only perks** (no pay-to-win, gambling, NFTs)
4. **Out-of-band community perks** (Discord, YouTube, voice lobby) — completely safe

**Phase 1 immediately actionable:** Twitch native sub integration через Subscription Status API. ~4-5 часов работы. Это **safe legal path** + Twitch payment infrastructure.

**Phase 2 (Boosty manual)** — для Russian viewers. Manual admin grant flow, no automated payment integration in extension UI.

---

**Дальнейшие шаги:**

- [ ] Streamer (shedoy23) одобряет revised plan
- [ ] Решить Open questions (6 вопросов выше)
- [ ] Phase 1 implementation — после deploy текущего pet pixel-art batch'а
- [ ] Soft-launch Twitch native subs (Phase 1+3) → 2 недели метрик
- [ ] Phase 2 (Boosty manual) — после feedback от Russian viewers
