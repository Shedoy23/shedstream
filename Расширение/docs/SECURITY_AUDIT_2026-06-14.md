# Audit 2026-06-14 — security / dead code / deps / debt

Метод: 4 субагента (sonnet) по областям + проверка ключевых находок основной моделью
(Opus). Где субагент переоценил severity — отмечено `[проверено: ...]`. Прошлый аудит —
`SECURITY_AUDIT_2026-04-30.md` (13 CRITICAL).

## Executive summary

- **~10 из 13 CRITICAL прошлого аудита закрыты** (казино вырезано, JWT добавлен на
  viewer/click/attendance/online/chat, brute-force защита логина работает). Остаток —
  организационный (ротация секретов в `.env`).
- **Касса прочная**: атомарное списание (`BEGIN IMMEDIATE` + `UPDATE … WHERE points>=?`),
  idempotency (client_action_id), per-user lock. Сегодня добавлен тест power.activate.
- **LGPL/BLT — чисто**: скопированных тел классов из BLT не найдено, только чистая
  реимплементация с пометками. Релиз не блокирует.
- Новый доминирующий класс находок — **multi-tenant leakage** (запросы без `channel_id`)
  в admin- и rimworld-роутах. Сейчас не течёт (один реальный канал), но обязателен к
  закрытию **до подключения 2-го стримера**.

---

## Tier 0 — СДЕЛАНО 2026-06-14 (deps hygiene)

Все — в `requirements.txt`; `python-multipart` обновлён и на проде (verified clean start).

| Пакет | Было | Стало | Почему |
|---|---|---|---|
| python-multipart | 0.0.6 | **0.0.32 (прод)** / `>=0.0.7` | CVE-2024-24762 ReDoS в парсере форм |
| python-jose | `==3.3.0` | **удалён** | фантом — нигде не импортится; реально работает PyJWT |
| PyJWT | не задекларирован | `>=2.8.0,<3.0` | используется в auth.py/pubsub.py/admin.py, работал «случайно» |
| gtts | отсутствовал | `>=2.3.2` | `routes/tts.py` импортит; на проде уже стоит (2.5.4) |
| twitchio | `==2.10.0` | `>=2.10.0,<3.0` | 3.x — ломающий rewrite, защита от случайного апгрейда |
| aiohttp | `==3.9.1` | `>=3.10,<4.0` | прод уже на 3.13.3; floor чтобы чистая переустановка не откатила |

> Побочно: `requirements.txt` в принципе отстал от прода (прод апгрейдили вручную мимо
> файла) — стоит как-нибудь пересобрать из `pip freeze` прода. Follow-up.

---

## Tier 1 — multi-tenant scoping (ДО публичного мультитенанта)

Запросы к tenant-таблицам **без `channel_id`**. С одним каналом не течёт; при 2-м стримере =
утечка между каналами. В коде уже помечено `TODO M4.4: per-channel admin UI`.

| Severity | Файл:строка | Проблема | [проверка] |
|---|---|---|---|
| HIGH | `routes/admin.py:190,196,210,244,258` | `SELECT/UPDATE viewers WHERE username=?` без `channel_id` — админ видит/правит пользователей всех каналов | [проверено: запросы реально без channel_id; но admin-панель = владелец, single-tenant TODO M4.4] |
| HIGH | `routes/viewer.py:371-383` | `/api/viewer/online-list` — `SELECT … WHERE is_afk=0` без `channel_id`, отдаёт активных всех каналов | [flagged субагентом; проверить наличие JWT перед фиксом] |
| HIGH | `rimworld.py:566-691` | `/api/rimworld/my-pawn/{username}` — публичный, без JWT/channel_id; пешка читается только по username | [flagged; RimWorld legacy — см. KNOWN ISSUE ниже] |
| HIGH | `rimworld.py:696+` | `sync-pawns` использует `resolve_channel_id_or_default()` вместо channel_id из мод-токена | [flagged; см. RimWorld known-issue] |
| MEDIUM | `routes/module_api.py:35-79` | `/v1/modules` + `/v1/module/{id}/info` публичны — раскрывают список модулей/каналов/actions (intelligence gathering) | [flagged] |
| MEDIUM | `auth.py:38-55` | DEV_MODE bypass проверяет `client.host` без X-Forwarded-For; за nginx все = 127.0.0.1 → если DEV_MODE утечёт в prod, все = broadcaster | [проверено: реальный риск ТОЛЬКО если RIMLINK_ENV≠prod в проде; убедиться что =prod] |

---

## Tier 2 — dead code / thin-front / debt

### Мёртвый код (безопасно удалить)
| Файл:строка | Что | confidence |
|---|---|---|
| `routes/bannerlord.py:~2177` | орфан-локал `_user_twitch_id` (присвоен, не читается) | HIGH |
| `config.py:640,642` | `ECONOMY_CONFIG['min_transfer'/'income_no_items']` — transfer вырезан | HIGH |
| `viewer.js:78-211` | 4 handler'а удалённых фич (market/transfer/withdraw) — ищут несуществующие DOM-элементы | HIGH |
| `viewer.js:310` | закомментированный `setupBetInputListener()` (casino вырезан) | HIGH |
| `viewer.js:989` `MARKET_MIN_PRICES` | маркет вырезан (m8), константа висит | HIGH |
| `overlay.html` jackpot/roulette tombstones | строки-надгробия вырезанных Phase 1.I | HIGH |
| `models.py:27`, `get_broadcaster_id.py` | пустой комментарий / одноразовый скрипт (M4 заменил) | MED |

### Thin-front дубли балансовых чисел (как power.activate, но мягче — бэк всё же enforce'ит)
| Число | Копии | Риск |
|---|---|---|
| GIVE_GOLD_PRESETS `{1k→5k,5k→25k,20k→100k}` | `viewer-bannerlord.js:2933` · `bannerlord.py` | **HIGH** — фронт хардкодит динар-суммы; бэк резолвит сам → после ребаланса экран врёт |
| ADD_SKILL_XP_PRESETS `{500→50,1k→100,5k→500}` | `viewer-bannerlord.js:2938` · `bannerlord.py` | **HIGH** — то же |
| FOCUS_TIER_COSTS / ATTRIBUTE_COST / SMITH_PRICE / HERO_GOLD_TIER_COSTS / RECRUIT_TIER | фронт + бэк + C#-мод (3-4 точки) | MEDIUM — сейчас совпадают, менять надо везде |
| KINGDOM/PARTY/VASSAL/CLAN_JOIN costs | только бэк+мод (фронт не участвует) | LOW |

### TODO/долг
| Приоритет | Где | Суть |
|---|---|---|
| ✅ DONE | `routes/module_api.py` | `refund #21` — ACK success=false теперь рефандит (роутит через `_on_action_failed`, idempotent). Backend закрыт + тест 40/40 + прод. **Остаётся мод-сторона** (см. ниже) |
| MED | дубль season/ELO логики в `duel.py`/`tictactoe.py`/`dice.py`/`rps.py` | фикс бага вносить в 4 места → вынести в общий модуль |
| MED | `auth.py:84` | subscriber detection не реализован (нужен Helix broadcaster scope) |
| — | миграции m1–m73 все зарегистрированы в `run_migrations()` | пропусков нет ✅ |

---

## RimWorld KNOWN ISSUE (отдельно, не часть аудита)

Мод RimLink не заливает данные на прод (POST'ы не доходят, только GET статуса). Детали —
`CONTEXT_RIMWORLD.md` §«KNOWN ISSUE 2026-06-14». STRICT token mode НЕ включать пока не
починено. Отложено по решению владельца (фокус — Bannerlord).

---

## Приоритет работ

1. **Tier 0** — ✅ сделано.
2. **Tier 2 dead code** — безопасная чистка, можно батчем сейчас.
3. **Tier 2 thin-front GIVE_GOLD/ADD_SKILL presets** — добить приёмом power.activate.
4. **Tier 1 multi-tenant scoping** — закрыть ДО онбординга 2-го стримера (проверять каждый
   запрос перед фиксом — у субагента бывали false positive).

## Сделано в этой сессии
- ✅ Tier 0 deps — прод.
- ✅ Tier 2 dead code — закоммичено (субагентовский «4 dead handlers» оказался живым
  диспетчером — снёс бы расширение; удалены только реальные орфаны).
- ✅ **refund #21 (backend)** — ACK success=false рефандит через idempotent `_on_action_failed`;
  тест 40/40; прод.

## refund — мод-сторона: разобрано (2026-06-14)
Проверка «~11 хендлеров без PostFailed» по-хендлерно показала: **угроза почти вся ложная.**
Большинство (clan/kingdom/gender/make_baby/recruit/set_combat_stance) — **free в крустиках**
(цена 0💎, платятся Hero.Gold динарами модом); их отказ теряет внутриигровое золото, НЕ
платёжную валюту → крустик-рефанд не нужен. «Критичный» `ModifyAttributeHandler`
(`player.modify_attribute`, 50💎) обслуживает **МЁРТВЫЙ action** — фронт его не зовёт (перешёл
на `hero.add_attribute`, а тот уже умеет `PostFailed`). Реальный крустик-гэп остался один:
- ✅ **GiveGoldHandler** (`player.give_item`, 500–5000💎) — ACK'ает success синхронно, выдаёт
  async; на отказе (hero null/dead/exception до выдачи) не звал `PostFailed`. **Исправлено**
  (`PostFailed` + флаг `applied` чтобы не рефандить уже выданное). Собирается (0 ошибок).
  **DLL НЕ задеплоен** — поедет со следующим `deploy.ps1 -Mod` (нужна закрытая игра).

### Побочные находки (не крустики)
- `player.modify_attribute` + `ModifyAttributeHandler` — **мёртвый action** (фронт не зовёт).
  Кандидат на удаление (dead code), не денежная дыра.
- `JoinKingdomHandler.cs` (~L91-109) — Hero.Gold (100K динаров) списывается на L98, и если
  `ApplyByJoinToKingdom` кидает исключение — золото сгорает без отката. Внутриигровая
  экономика (НЕ крустики), отдельный класс бага. Зафиксировано на будущее.
