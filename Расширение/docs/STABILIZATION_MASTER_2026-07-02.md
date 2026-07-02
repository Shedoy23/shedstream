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
| A2 | HIGH | `POST /api/overlay/tts/played` без auth — злоумышленник поллит `/tts/pending` (id+channel публичны) → POST played → платное TTS-сообщение (5000💎) удаляется до проигрыша. Нужен overlay-token на мутацию (streamer обновит OBS-URL). | routes/tts.py, overlay.js, streamer.py | ☐ (решено: делаем overlay-token) |
| A3 | MED | IDOR-свип: `stats/{username}`, `quests/{username}`, `marriage/proposals/{username}` — брали username из пути без сверки с JWT. Fix: отдаём ТОЛЬКО данные JWT-юзера, path-параметр игнор (структурно не читается в теле → IDOR невозможен). | routes/viewer.py, routes/marriage.py | ✅ (verify: path-param unused в теле; compile+import) |
| A4 | MED | `_duels` — глобальный in-memory dict без channel_id: cross-channel листинг + приём чужой дуэли (ELO-загрязнение между каналами). Скоупить по channel_id. | routes/duel.py | ☐ |
| A5 | MED | `add-command` SOFT-auth = no-op (мой Wave-1 «фикс» только логирует). Решить с A-RimWorld (kill-switch модуля). | rimworld.py | ☐ |

## WAVE B — compliance + гигиена (код, [me])

| # | Sev | Что | Статус |
|---|-----|-----|--------|
| B1 | LOW | `donation_total` — мёртвое поле с real-money-лексиконом, светится в API (routes/event.py:59) + рендерится (family.js:256). Убрать/переименовать. | ☐ |
| B2 | LOW | `/api/duel/leaderboard` + `/api/overlay/tts/pending` — unauth fallback на DEFAULT_CHANNEL_ID (публичные данные, но при 2-м стримере — тихий mis-route). Требовать явный channel_id / пусто без него. | ☐ |
| B3 | MED | gTTS без refund-on-failure: если Google TTS лёг — зритель теряет 5000💎 без возврата. Circuit-breaker/refund. | ☐ |
| B4 | LOW | Доки со старыми именами: CONTEXT_BANNERLORD.md `tournament.bet` (стр.493). Обновить. | ☐ |

## WAVE C — RimWorld кластер (код, [me]) — «все косяки»

| # | Sev | Что | Статус |
|---|-----|-----|--------|
| C1 | MED | Настоящий **kill-switch** RimWorld: раз модуль dormant — весь router 404 при выключенном флаге (закрывает разом: add-command A5, my-pawn channel_id, SOFT-ingest 13 эндпоинтов, colonists-leak). Реактивация RimWorld → фикс per-endpoint (task_f2662300) + флаг вкл. | ☐ |

## WAVE D — хардening (код, [me], тяжелее)

| # | Что | Статус |
|---|-----|--------|
| D1 | Полный CSP `script-src` — вынести inline-скрипты/стили дашборда (_dashboard_html) в /static, затем добавить директиву. | ☐ |
| D2 | Проверить dashboard-esc() на DOM-XSS в динамических путях (boosty/bug-report innerHTML). | ☐ |
| D3 | pubsub: сверить, что broadcast() не тянет cross-channel данные из stale-кэша (denylist полон для m38–m87). | ☐ |
| D4 | eventsub HMAC replay-window + cross-channel replay в dedup-таблице. | ☐ |

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
| F1 | Офсайт-бэкап прод-БД (единственный известный gap; сейчас только локальные копии на той же коробке). |
| F2 | Миграции m1–m87: upgrade-safety на реальной прод-БД (fresh-DB тест доказывает только wiring, не upgrade). |

---
**Порядок:** A (security) → B (compliance/гигиена) → C (RimWorld kill-switch) → D (хардening) → E/F параллельно/по готовности. Финальный зелёный гейт (Фаза 4 PUBLIC_GATE_PLAN) → подача.
