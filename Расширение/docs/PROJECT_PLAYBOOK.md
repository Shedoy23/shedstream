# Project Playbook

> **Версия:** 1.0
> **Дата:** 2026-05-10
> **Назначение:** Live-документ про продукт целиком. Дополняет специализированные:
>   - `COMPLIANCE_REWORK_PLAN.md` — правила Twitch + переделка под compliance
>   - `ARCHITECTURE.md` — архитектура, multi-tenant, Module API
>   - `MEMORY.md` (`memory/` папка) — личные заметки и философия
>
> Здесь — то, что не покрыто другими документами: подготовка к Twitch review submission, метрики/аналитика, B2B-монетизация, общий roadmap с приоритетами.
>
> **Live-документ.** Обновляется по мере работы. Изменения через PR с ревью.

---

## Table of contents

1. [Project at a glance](#1-project-at-a-glance)
2. [Review preparation playbook](#2-review-preparation-playbook)
3. [Metrics & Analytics](#3-metrics--analytics)
4. [B2B Monetization (черновик)](#4-b2b-monetization-черновик)
5. [Roadmap with priorities](#5-roadmap-with-priorities)
6. [Cross-reference](#6-cross-reference)

---

## 1. Project at a glance

### Что это
Twitch extension на платформенной архитектуре. Стримеры подключают канал → зрители видят оверлей с механиками вовлечения (квесты, кейсы, гильдии, дуэли, голосования за действия стримера). Под капотом: FastAPI + SQLite, multi-tenant per channel_id, Module API для подключения игр (RimWorld есть, Bannerlord scaffold).

### Валюта
**Крустики (💎).** Зарабатываются только за активность (просмотр / чат / квесты / streak / drops / sезоны). НЕ покупаются, НЕ передаются между юзерами, НЕ конвертируются во внешнюю валюту.

### Стек
- Backend: Python 3.12, FastAPI, aiosqlite, twitchio
- Frontend: vanilla JS, HTML/CSS (Twitch Extension iframe constraints)
- Deploy: VPS Timeweb, supervisor, nginx
- Storage: SQLite WAL + per-channel composite indexes
- Tests: 56 isolation tests, smoke-checks per миграция

### Текущий статус (2026-05-10)
- Phase 1 cleanup ВСЯ закрыта: вырезаны casino/crafting/market/donate/transfer/roulette/duel-wagers/family-financial. M8 миграция refundит всё ушедшее.
- Phase 2-6: добавление compliant-механик (кейсы, гильдии, голосование, дуэли v2, drops в кейсы)
- Прод: HEAD = `a426f6c` (Bug 4 fix, нон-compliant). Стримов нет, никто не лезет. При следующем deploy миграция M8 автоматически зачистит.

---

## 2. Review preparation playbook

### Зачем
Twitch reviewer'ы видят extension через **тестовый канал** под live-стримом. Если в момент ревью канал не в эфире, или фичи не показываются, или нет демо-данных — реджект. Подготовка занимает 2-3 дня перед submission, лучше делать заранее.

### 2.1 Test channel setup

**Что:** отдельный Twitch-канал (например `rimlink-demo`) с 24/7 стримом для ревьюеров.

**Как:**
- Зарегистрировать аккаунт через `/streamer` OAuth flow → попадает в `channels` таблицу как обычный
- Tier — `free` (чтобы reviewer проходил по самому массовому пути, не VIP)
- Канал стримит 24/7 либо real-content либо VOD-ы (пермит у Twitch есть на VOD-стримы для review-purposes — уточнить актуальность правил)
- На канале постоянно подключен extension (sтример активирует через Extension Manager)

**Backup-план:** если 24/7 стрим не получается — отметить в submission notes конкретные часы когда канал в эфире, попросить reviewer'а зайти в окно.

### 2.2 Demo-mode backend flag

**Что:** опциональный режим работы backend'a с ускоренными cooldown'ами для review-канала.

**Как (план):**
```python
# config.py
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
DEMO_CHANNEL_IDS = set(map(int, os.getenv("DEMO_CHANNEL_IDS", "").split(",")))

# В коде где cooldown:
def is_demo_channel(channel_id):
    return DEMO_MODE and channel_id in DEMO_CHANNEL_IDS

cooldown = 5 if is_demo_channel(cid) else 60  # 5 sec вместо минуты
```

**Где включается:**
- Quest progress: ускорить watch_30 → watch_3min
- Drops: 25% chance на ивент → 100% и каждые 30 сек
- Sезоны дуэлей: 7 дней → 30 минут
- Marriage proposal expiry: 24h → 5 min

**На обычных каналах флаг выключен.** Reviewer видит «как будет работать» без 4-часового просмотра.

### 2.3 Боты-имитаторы (multiplayer demo)

**Зачем:** дуэли / гильдии / голосования / sезонные лидерборды требуют 2+ юзеров. Один reviewer не сможет показать полноценный multiplayer.

**План:**
- 3-5 «fake»-юзеров с фиксированными user_id (создаются скриптом)
- Heartbeat-имитатор: каждые 30 сек посылает activity ping → они «онлайн» в overlay'e
- Чат-имитатор: раз в 1-2 минуты пишут разные сообщения через IRC bot account (отдельный твич-аккаунт)
- Дуэль-инициатор: раз в 5 минут один бот создаёт дуэль, через 30 сек другой принимает → reviewer видит бой
- Гильдия-демо: один бот основывает гильдию, остальные вступают → reviewer видит "Топ гильдий"
- Vote-bid имитатор: когда стартует голосование — боты вкидывают разные суммы по разным вариантам

**Где:** отдельный сервис `demo_bots.py` запускается через supervisor параллельно с основным backend'ом. Активен только когда `DEMO_MODE=true`.

### 2.4 Review-promo-code

**Что:** специальный promocode для reviewer'а — даёт стартовый набор чтобы он не сидел 2 часа копя крустики.

**Что выдаёт:**
- 100 000 крустиков (хватит на любые механики)
- 1 кейс легендарный + 3 эпик + 5 редких + 10 обычных (чтобы reviewer попробовал открытие)
- Авто-вступление в демо-гильдию (увидит UI участника)
- Бейдж «Reviewer» в overlay (косметический, для трассировки)

**Как:**
- Создается через дашборд стримера на демо-канале
- Код типа `TWITCH-REVIEWER-2026-05-10` (с датой для tracking)
- Лимит использований 5 (на случай если несколько ревьюеров)
- Срок действия 30 дней (review-window)
- Активация через `/api/promo/use` как обычный код, но обработка в коде проверяет `code.startswith("TWITCH-REVIEWER-")` → выдаёт расширенный пакет

### 2.5 Submission notes (template)

В Twitch Developer Console при подаче на ревью есть поле «Notes for reviewer». Template:

```
Hello reviewer!

Test channel: https://twitch.tv/rimlink-demo (24/7 live, EN+RU subtitles)
Promo code for full demo: TWITCH-REVIEWER-{DATE}
Demo bots are active in chat for multiplayer demonstration.

Quick tour (3 min):
1. Click extension icon → see action grid (quests, cases, guild, duels)
2. Click "Cases" → see your inventory of 19 cases (review-promo)
3. Open Epic case → animation + 100k💎 added
4. Click "Duels" → join queue → demo-bot accepts in ~30s → RPS match
5. "Guild" tab → see Top guilds + your auto-joined demo-guild
6. Wait for voting event (every 5 min in demo mode) → bid on stream action

Compliance:
- All gambling mechanics removed (casino, slots, jackpot, wagering, P2P trade)
- See section X.Y of attached docs for compliance checklist
- Currency (крустики) earned only via passive activity, never traded
- Loot boxes (cases) free, contents = fixed points (no monetary value items)

Demo video: https://...
Full feature description in store listing.

Issues / questions: [your contact]
Best regards, [studio name]
```

### 2.6 Pre-submission checklist (extension перед подачей)

Хард — без этого не подаём:
- [ ] 0 lexicon hits для casino/slot/jackpot/bet/spin/roulette/gamble в frontend
- [ ] 0 endpoints типа /api/casino/*, /api/craft/*, /api/market/*, /api/donate, /api/points/transfer
- [ ] Все механики проходят 3-вопрос compliance тест (`COMPLIANCE_REWORK_PLAN.md §1`)
- [ ] Loot boxes (кейсы) только за активность, не за валюту/Bits
- [ ] Description в store accurate описывает все фичи
- [ ] Twitch Extension Helper — first script в HTML
- [ ] No iframes / Flash / NFT
- [ ] Audio off by default + volume controls
- [ ] All fetched URLs declared в submission

Soft — для качества:
- [ ] Тестовый канал live во время review
- [ ] Demo bots работают
- [ ] Review-promo-code создан и протестирован
- [ ] Demo-mode подключён к review-каналу
- [ ] Демо-видео 3-5 мин записано
- [ ] Submission notes заполнены
- [ ] Backup contact info актуален

### 2.7 Что делаем после approval

- Постепенный rollout фич реальным стримерам через feature flags
- Demo-channel переходит в обычный режим (DEMO_MODE off)
- Боты-имитаторы выключены
- Review-promo-code просрочивается / удаляется
- В store listing — добавить «Twitch Approved» badge если есть

### 2.8 Что делаем при reject

- Изучить причины (Twitch присылает в письме)
- Если technical: исправить код, повторно submit
- Если policy: пересмотреть механику, переделать, повторно submit
- Между submission'ами — типично 1-2 недели cooldown
- Если 2-3 reject подряд — стоит запросить audit-call с Twitch dev relations team

---

## 3. Metrics & Analytics

### Зачем
Без метрик невозможно понять, работает ли продукт. «Тестерам зашло» ≠ «реально удерживает». Метрики — компас и для продуктовых решений, и для диагностики (почему фича пустует / экономика инфлирует / юзеры уходят).

### 3.1 Engagement metrics

**Активность:**
- **DAU / WAU / MAU per канал** — сколько уникальных юзеров открыли extension за день/неделю/месяц
- **Active viewers ratio** = (юзеры открывшие extension) / (юзеры в чате) — насколько extension разлекает
- **Heartbeat frequency** — как часто extension шлёт `track_activity` ping (норма: каждые 60 сек активного просмотра)
- **Avg session duration** — сколько минут extension активен у юзера за стрим

**Удержание:**
- **D1 / D7 / D30 / D90 retention** — % юзеров вернувшихся через N дней после первого взаимодействия
- **Cohort by registration week** — сравниваем cohorts разных недель (есть ли деградация после первого впечатления?)
- **Stickiness DAU/MAU** — % MAU которые активны в любой день

**Сегментация:**
- New vs returning split
- По tier канала (free / pro / premium / vip)
- По размеру канала (≤10 viewers / 10-100 / 100-1000 / 1000+)

### 3.2 Economy metrics

**Sources (откуда крустики приходят):**
| Источник | Доля от total income (норма) |
|---|---|
| Watch-time | 60-70% (основной) |
| Chat bonus | 10-15% |
| Quests | 10-15% |
| Streaks | 3-5% |
| Drops/cases | 3-5% |
| Sезонные награды дуэлей | 1-2% |
| Промокоды | <1% (epspiсодически) |

**Sinks (куда крустики уходят):**
| Сток | Доля от total spend (норма) |
|---|---|
| Создание гильдии | ~30% |
| Прокачка skills гильдии | ~50% |
| Bid на голосование | ~15% |
| Развод | ~5% |

**Баланс экономики:**
- **Sink/Source ratio** — норма ≈ 0.7-0.9 (источников чуть больше — стимулирует прогрессию, не вызывает деноминацию)
- Если ratio > 1.0 → дефляция (юзеры в минус, мотивация падает)
- Если ratio < 0.5 → инфляция (крустики обесцениваются, sинки слабые)

**Распределение богатства (PRE-FLIGHT REQUIRED — см. ниже):**
- **Avg balance per юзер** — общее
- **Median balance** — устойчивый юзер
- **p90 / p95 / p99 баланса** — percentile-перцентиль распределения
- **Max-юзеры vs median-юзеры comparison** — компаунд-эффекты
- **Top-1% / median ratio** — концентрация (норма ≤ 50, выше — pareto-перекос)
- **Gini index** — стандартная мера неравенства
- **Распределение дневного дохода** — кто сколько зарабатывает за сутки

**Pre-flight check для нового источника крустиков** (урок 13.7):
Прежде чем добавлять новый source — посчитать максимальный возможный доход сверх-активного юзера за день / неделю / месяц. Если максимум >> стоимость основных трат — экономика для топов сломается. Метрики distribution **обязаны быть реализованы ДО** появления механики, а не после жалоб.

Alerts при отрыве p99 от p95 (компаунд-перекос → возможный bot / abuse / mechanic-broken).

**Tracking sезонов:**
- Income/spend за сезон (3 мес)
- Aux: «спалили ли всё что заработали» — проверка sезонной завершённости

### 3.3 Feature health

**Quests:**
- Completion rate per quest type (watch_30 — 80%, watch_300 — 5%?)
- Skip rate (юзеры которые видели но не выполнили)
- Avg crustики/час по quest-path

**Achievements:**
- Unlock rate per achievement (streak_3 — 30%, streak_10 — 1%?)
- Lifetime unlock distribution

**Streaks:**
- Distribution: сколько % юзеров достигают 3 / 5 / 10 streak
- Avg max-streak per юзер
- Streak-loss rate (юзеры у кого был стрик и потеряли)

**Cases (Phase 2):**
- Open delay — сколько часов юзеры держат закрытый кейс перед открытием
- Tier distribution (norма 70/25/4/1 для drop'ов)
- Source breakdown (quest / streak / watch / drop / season)

**Дуэли:**
- Played per active user per stream
- Win rate distribution per ELO range
- Sезонная активность (старт vs конец)
- Queue wait time (Phase 5)

**Voting events (Phase 4):**
- Events per stream
- Participation rate (% активных юзеров проголосовавших)
- Avg variance в голосах (узкое разделение vs ландслайд)
- Stream-action delivery rate (стример выполнил выбранное?)

**Гильдии (Phase 3):**
- Guild creation rate
- Avg guild size
- Skills upgraded per guild per month
- Member churn (joins/leaves per week)

### 3.4 Compliance signal metrics (red flags)

Если метрики показывают, что какая-то механика стала dominant — это сигнал что баланс или mechanic-design съехал в gambling-like зону.

| Сигнал | Threshold | Что делать |
|---|---|---|
| Один источник дохода >30% от total | >30% | Sиквенс-shock; пересмотреть mechanics |
| Один юзер зарабатывает >50× медианы | за 7 дней | Bot detection / abuse |
| Drop легендарных кейсов >2% | от total drops | Balance issue (вес weight'а слишком высок) |
| Voting bid >50% от balance юзера regularly | >70% юзеров | Compulsion-loop, рассмотреть soft cap |
| Гильдийный buy-in >median 1-week earnings | >2× | Барьер слишком высокий, новые юзеры не доходят |

### 3.5 Где собирать

**Текущий стек:**
- Все таблицы БД с timestamps (`created_at`, `last_seen`, `awarded_at`, etc) — можно агрегировать SQL
- Logs supervisor (`/var/log/twitchbot.out.log`) — runtime errors, IRC events
- Backups daily SQLite snapshots (`backup_db.sh` cron) — для retroactive analysis

**Что нужно добавить (Phase 7+):**
- Daily snapshot table `metrics_daily(channel_id, date, metric_key, value)` — агрегация всего вышеуказанного раз в сутки
- Endpoint `/api/admin/metrics?channel_id=X&period=7d` для дашборда стримера
- Экспорт в CSV для аналитики offline
- Возможно: Grafana с Postgres-моста (когда мигрируем с SQLite)

### 3.6 Алерты (план Phase 7+)

- DAU drop >30% week-over-week → Telegram-уведомление dev-команде
- Sink/source ratio < 0.5 → инфляция alert
- Sink/source ratio > 1.0 → дефляция alert
- Один юзер заработал >50× медианы за 24h → bot/abuse flag
- Любой 5xx error в backend >1% → ops alert
- WAL size > 100MB → checkpoint stuck

### 3.7 Личный дашборд (для тебя как owner'a)

Раз в неделю смотреть:
1. Total channels, активных за неделю
2. Total active users, retention curve
3. Sink/source ratio per канал
4. Топ-5 каналов по DAU и средние их характеристики
5. Любые red-flag сигналы из §3.4

Один скрипт `weekly_report.py` (план), генерирует Markdown — отправляется в личный telegram.

---

## 4. B2B Monetization (черновик)

### Зачем
Twitch extension Free для viewer'а — это compliance-требование. Но стример может платить за расширенный функционал extension'а напрямую разработчику (вне Twitch payment system, через Stripe / другой billing). Это **B2B-канал монетизации**, основной для проекта.

> **Важно:** все tier'ы должны соответствовать compliance: tier'ы стримера НЕ могут давать игровых преимуществ юзерам канала (§7.3 COMPLIANCE_AND_ARCHITECTURE.md). Free path для юзера всегда работает полноценно.

### 4.1 Tiers (черновик)

| Tier | Цена | Кому | Что включено |
|---|---|---|---|
| **Free** | $0 | Affiliate, тестовые каналы | ~50% базового функционала: quests, achievements, streaks, drops, voting events, дуэли v1, marriage. **Достаточно для запуска**. |
| **Pro** | $9/мес | Постоянные стримеры (1000+ followers) | Free + кастомные emoji в чате, кастомизация overlay-цветов, расширенные промокоды (≥10 одновременно), кейсы legendary включены, гильдии разблокированы для канала, расширенный лидерборд |
| **Premium** | $29/мес | Партнёры с активным коммьюнити | Pro + brand customization (логотип в overlay, custom-фон), гильдийные турниры, custom achievement-set (стример создаёт свои достижения), экспорт аналитики CSV, priority support (24h ответ) |
| **VIP** | $149+/мес или custom | Топовые стримеры / IP-партнёры | Premium + dedicated dev (custom modules для их игры, например Bannerlord-specific фичи), white-label (extension под их брендом), custom integrations (Discord/Telegram bridge), 1-on-1 calls раз в месяц |

### 4.2 Принципы дизайна tier'ов

**Каждый tier = новый класс возможностей**, не просто «больше того же».
- Free → база работает
- Pro → косметика канала + больше «места» (промокоды, achievement set)
- Premium → продвинутая аналитика + турниры + custom achievement
- VIP → разработчик в команде стримера

**Equality для viewer'ов:**
- В одном канале все viewer'ы получают одинаковые крустики/мин
- Tier канала не влияет на скорость игры viewer'a
- Разница только в наличии / отсутствии фич у канала (например на free канале нет гильдий, а на pro — есть)

**Запрещено в tier'ах (§7.4 COMPLIANCE_AND_ARCHITECTURE.md):**
- ❌ Buy Bits to skip cooldown
- ❌ Бусты к скорости накопления крустиков юзерам
- ❌ Premium-функции дающие преимущество в шансе выиграть аукцион/дуэль
- ❌ Конвертация подписки → крустики

### 4.3 Платёжная инфраструктура (план Phase 8+)

**Stack:**
- Stripe Customer Portal (стандартный recurring billing)
- Webhook → `/api/billing/stripe-webhook` обновляет `channels.tier` + `channels.tier_until`
- Grace period: 7 дней при failed payment (extension не отваливается в момент стрима)
- Refund policy: pro-rata за неотделанные дни, инициируется через support

**Tier-gates в коде:**
```python
# dependencies.py
def require_tier(min_tier: str):
    """Декоратор: эндпоинт доступен только tier >= min_tier для данного канала."""
    ...

@require_tier("pro")
@router.post("/api/guild/create")  # Гильдии — Pro+
async def create_guild(...):
    ...
```

Tier-config в config.py:
```python
TIER_RANK = {"free": 0, "pro": 1, "premium": 2, "vip": 3}
TIER_FEATURES = {
    "free": {"max_promocodes": 3, "guilds": False, "tournaments": False},
    "pro":  {"max_promocodes": 10, "guilds": True, "tournaments": False},
    "premium": {"max_promocodes": 50, "guilds": True, "tournaments": True},
    "vip": {"max_promocodes": 9999, "guilds": True, "tournaments": True, "dedicated_dev": True},
}
```

### 4.4 Маркетинговый pitch (для будущей презентации)

**Free** — "Try it free, get core engagement features for your community."
**Pro** — "Make it yours. Custom emoji, branded overlay, full case system unlocked."
**Premium** — "Run tournaments. Build your community with guilds, get analytics that matter."
**VIP** — "Custom-built for top streamers. Your game, your brand, our dev team."

### 4.5 Что НЕ должно быть в B2B (тревожные звонки)

- Tier даёт юзерам канала больше крустиков → **бан §6.2.6 + наш самозапрет** §2.1 COMPLIANCE_AND_ARCHITECTURE.md
- Tier даёт «премиум кейсы» с другим content'ом → Twitch может read как pay-to-win extension
- Tier даёт право на gambling-механики → их нет в принципе, не возвращаем
- Tier auto-renew без warning → лучше иметь email-warning за 3 дня

### 4.6 Альтернативные модели (для размышления)

- **Patreon-style:** ежемесячная подписка на платформу → разблокирует ВСЕ премиум-фичи всем твоим каналам
- **One-time purchase:** $99 для unlimited Pro features lifetime (упрощает customer support)
- **Per-canal pricing:** $5/канал/мес (для multi-channel сетей)
- **Revenue share:** % от Bits-revenue extension'а (если интегрируем Bits — пока не интегрируем)

Решить позже, после первой волны платных стримеров.

---

## 5. Roadmap with priorities

### Принципы приоритизации

🔴 **HIGH** — блокирует следующие этапы или critical для compliance/quality
🟡 **MEDIUM** — важно но можно отложить на 1-2 sессии
🟢 **LOW** — wishlist, делается когда удобно

**Sсейчас → следующее → потом → отложено** — не больше 3 фаз в каждой колонке, иначе фокус размывается.

### 5.1 NOW (sессии 1-3, после Phase 1)

- 🔴 **Phase 2: Кейсы**
  - 4 тира (1k/10k/100k/500k💎), фиксированные награды
  - БД: `cases` table + миграция M9
  - Endpoints: `/api/viewer/cases`, `/case/open`, `/case/preview/{tier}`
  - Frontend: `cases.js` с простой анимацией раскрытия
  - Backend triggers: quest complete → common, streak 10 → rare, watch_100h → epic
  - Acceptance: открытие атомарно, idempotent, фиксированная награда

- 🔴 **Phase 6: Drops в кейсы** (зависит от Phase 2)
  - Изменить `_process_drop`: вместо `DROP_ITEMS` → `DROP_CASE_TIERS`
  - Tier weights: 70/25/4/1
  - Кейс выдаётся в `cases` table, не в `inventory`
  - Acceptance: distribution соответствует weights на 1000+ samples

### 5.2 NEXT (sессии 4-7)

- 🔴 **Phase 3: Гильдии база**
  - Создание (cost 100k💎), name + tagline + master
  - БД: `guilds`, `guild_members`, `guild_skills`, `guild_contributions` + миграция M10
  - Endpoints: create / join / leave / contribute / list / kick / upgrade-skill
  - Skills v1: 2 placeholder ветки (`extra_member_slots`, `cosmetic_banner_unlock`)
  - Frontend: `guild.js` — browse / my guild / master controls
  - Без бустов накопления (Variant 2a)
  - Acceptance: race conditions защищены, balance атомарно списывается

- 🟡 **Phase 5: Дуэли v2 (matchmaking)**
  - Убрать ставки (уже сделано Phase 1.F), теперь добавить queue
  - БД: ALTER pending_duels (`status`, `matched_with`, `room_id`) + миграция M12
  - Backend: `matchmaking_loop()` каждые 5 сек ищет пары по близкому ELO
  - Endpoints: `/queue`, `/queue/status`, `/room/{id}/move`, `/room/{id}/state`
  - Frontend: переписать UI «Найти противника» вместо «Создать дуэль»
  - Acceptance: ELO-spread соблюдается, нет deadlock'ов в очереди

- 🟡 **Phase 4: Голосование за действие стримера**
  - Полный rework `event_manager.py` под voting model
  - Копилка от пассивной активности (1 мин = 1 unit, 1 chat = 5 units)
  - Стример заранее настраивает варианты (что играть / какой стиль) через дашборд
  - БД: `voting_events`, `voting_options`, `voting_bids`, `streamer_voting_templates` + миграция M11
  - Победитель = max bid за вариант, без рефанда (collective vote, не commerce)
  - Acceptance: 0 хитов «рулетка» в lexicon, refund НЕ происходит, без шаблона событие не стартует

### 5.3 LATER (sессии 8-12)

- 🟡 **Косметика контента** (нужен art-resource)
  - Banner-эмблемы для гильдий (50+ вариантов)
  - Эмодзи для кейсов (рандомное содержимое)
  - Аватары для overlay
  - Маскоты канала

- 🔴 **Test infra для review prep** (см §2)
  - Demo-mode flag в backend
  - Боты-имитаторы (отдельный сервис `demo_bots.py`)
  - Review-promo-code logic в `routes/promo.py`
  - Submission notes draft + демо-видео

- 🔴 **Аналитика / metrics** (см §3)
  - Daily snapshot table `metrics_daily`
  - Endpoint `/api/admin/metrics`
  - Weekly report script (Telegram)
  - Compliance red-flag алерты

- 🟡 **Sезонные итоги дуэлей** (есть код, проверить корректность)
  - Auto-payout PRIZES при ends_at
  - Chat-уведомление топ-3
  - История прошлых сезонов

### 5.4 FUTURE (post-review, sессии 13+)

- 🟡 **Battle pass / sезоны (extension-wide)**
  - Прогрессия за активность с косметикой по дорожке
  - 2-3 месячный sезон
  - Free track + premium track (premium — за tier канала, не за деньги юзера)

- 🟡 **Турниры между гильдиями**
  - Расписание / бракет / награды (косметика + крустики)
  - Premium tier feature

- 🟡 **Гильдийские skills конкретные ветки**
  - Расписать после первых месяцев живой работы Phase 3 (увидим что просят юзеры)

- 🟡 **Channel Points integration**
  - EventSub `channel.channel_points_custom_reward_redemption.add` уже есть в scopes
  - Стример настраивает CP→кейсы, CP→бонус-крустики, CP→бан-сценарии

- 🟡 **Joint-streak для брака + лидерборд пар**
  - Раз убрали финансовое — добавим social-replacement
  - Счётчик «дней вместе на стриме» для женатых пар
  - Отдельный лидерборд

- 🟡 **B2B platform (Stripe, customer portal, tier-gates)**
  - см §4. После первого review approval, чтобы не тратить ревью на не-видную фичу

### 5.5 WISHLIST (когда захочется)

- 🟢 **Маскоты-аватары в overlay** (animal-crossing-style визуализация активных зрителей)
- 🟢 **Мини-игры внутри extension** (compliant — без ставок и monetary outcomes)
- 🟢 **Cross-channel turniры** (если разрешит Twitch — uncertain policy)
- 🟢 **Mobile-friendly redesign** (mobile.html уже есть, но это полный pwa)
- 🟢 **Discord/Telegram bridge** (VIP feature — уведомления о drop'ах в discord)
- 🟢 **AI-generated промокод-описания** (на базе Anthropic API)
- 🟢 **Maker-kit для community-разработчиков** (extract `modules/_base.py` в публичный репо)

### 5.6 АНТИ-СПИСОК (никогда, ни в какой обёртке)

🚫 Возврат любых gambling-форм (даже под новыми названиями)
🚫 P2P-перевод крустиков (даже с агрессивными лимитами)
🚫 Конвертация Bits/донатов → крустики
🚫 Премиум-tier дающий функциональные преимущества юзерам канала
🚫 NFT (запрещено §4.11 Twitch Extension Guidelines)
🚫 Off-platform value exchange / proxy-for-money схемы
🚫 «Купить дополнительный шанс» в любой механике
🚫 Roulette-style анимации даже без ставок

### 5.7 Текущий фокус — что сейчас делаем

| Фокус | Sессий до завершения | Cтатус |
|---|---|---|
| Phase 1 cleanup | 0 (закрыто 2026-05-10, 9 коммитов) | ✅ DONE |
| Phase 2 кейсы | 2-3 | NEXT |
| Phase 6 drops в кейсы | 0.5 | depends Phase 2 |
| Phase 3 гильдии база | 2-3 | потом |

**Не размываемся:** держим фокус на 1-2 фазах одновременно. Не открываем новые направления пока текущая не закрыта.

---

## 6. Cross-reference

| Документ | Где | Зачем читать |
|---|---|---|
| `Расширение/docs/COMPLIANCE_REWORK_PLAN.md` | репо | Правила Twitch + 6 фаз rework + verdict-таблица 16 механик |
| `Расширение/docs/ARCHITECTURE.md` | репо | Архитектура, multi-tenant, Module API, известные техдолги |
| `Расширение/docs/COMPLIANCE_RULES_v2.md` | (план Phase 7+) | Authoritative reference Twitch правил с цитатами |
| `Расширение/docs/MODULE_API.md` | репо | Game Bridge SDK для подключения новых игр |
| `memory/COMPLIANCE_AND_ARCHITECTURE.md` | personal | Личные заметки + философия проекта |
| `memory/MEMORY.md` | personal | Index всех memory-документов |

---

**Подпись:** этот playbook — live-документ. Обновляется по мере работы. История изменений в git log. Решения по структуре / приоритетам — через явное обсуждение перед изменением roadmap-секции (§5).
