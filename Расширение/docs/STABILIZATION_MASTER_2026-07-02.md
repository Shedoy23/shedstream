# Мастер-список стабилизации ShedLink → релиз (2026-07-02)

Источник: независимый адверсарный аудит (40 агентов, 35 находок → 24 опровергнуто,
11 подтверждено) + completeness-critic. Каждый пункт закрывается с доказательством +
адверсарной перепроверкой. Статусы: ☐ open · ⚙ in progress · ✅ closed(verified).

## Кто может закрыть
- **[me]** — код, чиню + верифицирую сам.
- **[owner]** — только вживую (in-game клик, прод .env, стрим-нагрузка).

---

## WAVE A — security (код, [me]) — делаем первым

| # | Sev | Что | Файл | Статус |
|---|-----|-----|------|--------|
| A1 | HIGH→МЕД | `/dev` (dev_login.py). УТОЧНЕНО: роль JWT хардкод `viewer` (не broadcaster), логин через реальный OAuth = сам за себя (не импёрс). Fix: **whitelist логинов** (config `DEV_LOGIN_WHITELIST`, default `shedoy23`) — сессия выдаётся только своим, чужой cookie отвергается. | routes/dev_login.py, config.py | ✅ (verify: compile+import; whitelist грузится; owner проверит логин) |
| A2 | HIGH | `POST /api/overlay/tts/played` без auth. Fix: **overlay-token** (per-channel HMAC) обязателен на мутацию. Дашборд отдаёт полный OBS-URL с токеном (`/api/streamer/overlay-url` + карточка «🖥 URL оверлея»); overlay.html шлёт токен в /played; бэк verify. **⚠️ owner: обновить URL оверлея в OBS** (иначе TTS перестанет отмечаться проигранным). | routes/tts.py, streamer.py, overlay.html | ✅ (render-test+token-roundtrip+import; owner обновит OBS) |
| A3 | MED | IDOR-свип: `stats/{username}`, `quests/{username}`, `marriage/proposals/{username}` — брали username из пути без сверки с JWT. Fix: отдаём ТОЛЬКО данные JWT-юзера, path-параметр игнор (структурно не читается в теле → IDOR невозможен). | routes/viewer.py, routes/marriage.py | ✅ (verify: path-param unused в теле; compile+import) |
| A4 | MED | `_duels` — глобальный in-memory dict без channel_id: cross-channel листинг + приём чужой дуэли. Fix: channel_id в записи; `/list` по JWT+фильтр; `/accept` отвергает чужой канал; фронт duels.js шлёт JWT. | routes/duel.py, duels.js | ✅ (compile+import+node; prod-verify) |
| A5 | MED | `add-command` SOFT-auth = no-op. Fix: **дефолт RIMWORLD_REQUIRE_TOKEN → STRICT** — закрывает add-command-инъекцию + все 13 mod-ingest разом (модуль dormant, вьюверский таб не задет; реактивация → мод шлёт токен). | rimworld.py | ✅ (strict=True; prod-verify 401) |

## WAVE B — compliance + гигиена (код, [me])

| # | Sev | Что | Статус |
|---|-----|-----|--------|
| B1 | LOW | `donation_total`/`pool_pct_donations` — мёртвое поле с real-money-лексиконом в API+фронте. Fix: удалён целиком (event_manager donation-путь, event.py response, config-ключ, family.js render — HTML donation-бара не было, рендер был no-op). | ✅ (compile+import; 0 live refs) |
| B2 | LOW | `/api/duel/leaderboard` unauth→DEFAULT-fallback. Fix: require JWT-channel, пустой борд без JWT (duels.js шлёт JWT). `tts/pending` — accepted-low: оверлей всегда шлёт channel_id (после A2), read публичен by design. | ✅ (leaderboard); tts/pending accepted |
| B3 | MED | gTTS refund. **ПРОВЕРЕНО — уже безопасно, не был сломан:** debit (`remove_points`) идёт ПОСЛЕ успешной gTTS (tts.py:110-124); упал gTTS → return error БЕЗ списания. Критик пометил «не проверено» → verified. | ✅ (verify, без правок) |
| B4 | LOW | CONTEXT_BANNERLORD.md `tournament.bet`×3 → `tournament.predict`. | ✅ |

## WAVE C — RimWorld кластер (код, [me]) — «все косяки»

| # | Sev | Что | Статус |
|---|-----|-----|--------|
| C1 | MED | RimWorld write-дыры закрыты через **A5 (strict ingest-auth)** — лучше блокового kill-switch: закрывает add-command + 13 ingest, но НЕ ломает вьюверский read-таб (ревьюер видит рабочую вкладку). Остаток (colonists name-leak, my-pawn channel_id) — LOW/known-debt, `task_f2662300` при реактивации. | ✅ (write-часть; reads в task_f2662300) |

## WAVE D — хардening (код, [me], тяжелее)

| # | Что | Статус |
|---|-----|--------|
| D1 | Полный CSP `script-src` для дашборда/оверлея. **ОТЛОЖЕНО осознанно:** требует вынести ВСЕ inline `<script>` + убрать inline `onclick` (огромный рерайт дашборда) ради marginal-выгоды на **admin-only** странице, где XSS не найден (D2). Публичные вьюверские поверхности (extension/mobile.html) **уже имеют строгий CSP** (meta, добавлен в public-gate). | ⏸ deferred (обоснованно) |
| D2 | dashboard DOM-XSS. **ПРОВЕРЕНО — безопасно:** `bugEsc` (& < >) + `esc` ([&<>"']) экранируют весь ввод; user-данные только в тексте, не в атрибутах; `b.id` — int. Два неэкранир. innerHTML — серверный status / JS-ошибка, не ввод атакующего. | ✅ verified |
| D3 | pubsub cross-channel. **ПРОВЕРЕНО — безопасно:** очереди/seq/throttle ключ `(channel_id, topic)`; send-JWT bound к каналу; data — параметр вызывающего. Механизм не мешает каналы. | ✅ verified |
| D4 | eventsub replay. **ПРОВЕРЕНО — безопасно:** HMAC + 10-мин replay-окно + атомарный dedup (24ч TTL, channel_id-scoped) + UNIQUE(channel_id, redemption_id). Cross-channel replay невозможен. | ✅ verified |

## WAVE E — только владелец [owner] (я готовлю чек-листы)

| # | Что |
|---|-----|
| E1 | Прод .env: ADMIN_PASSWORD (сила/ротация), RIMWORLD_REQUIRE_TOKEN, EXPOSE_MODULE_DEBUG=unset. Я дам список что проверить. |
| E2 | In-game: 2 Bannerlord-DLL (md5 217B4F88 party/vassal/diplo/workshop/fief/caravan; E457EF74 combat powers) — не тестированы вживую. + тонкий фронт (цены выглядят как раньше). |
| E3 | ShedColony Phase-8 действия (colony.supply/festival/spy_boost/spawn_visitor/quest_unlock) — не проверены на ATM10. |
| E4 | Замер poll-нагрузки на живом стриме (SQLite один; ~2 req/с/зритель). |
| E5 | Twitch Dev Console: скриншот 1024×768, ZIP → Hosted Test → Submit; проверка config-страницы в реальном Twitch. |

## WAVE F — инфра-гигиена

| # | Что |
|---|-----|
| F1 | ~~Офсайт-бэкап прод-БД~~ — **СДЕЛАН** (забор на ПК владельца, задача `shedstream-db-backup-pull`, самопроверка `scripts/verify-backup.py`). Пометка 24.08: строка «единственный известный gap» устарела 11.06.2026 и после этого месяц пересказывалась владельцу как текущая. |
| F2 | Миграции m1–m87: upgrade-safety на реальной прод-БД (fresh-DB тест доказывает только wiring, не upgrade). |

---
**Порядок:** A (security) → B (compliance/гигиена) → C (RimWorld kill-switch) → D (хардening) → E/F параллельно/по готовности. Финальный зелёный гейт (Фаза 4 PUBLIC_GATE_PLAN) → подача.
