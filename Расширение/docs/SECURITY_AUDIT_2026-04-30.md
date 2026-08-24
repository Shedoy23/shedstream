# Security Audit — 2026-04-30

**Скоп:** Backend FastAPI (`Расширение/backend/`) + frontend контракт + конфиг + secrets management.
**Mod RimLink/Source/ не проверялся** (мод-сторона менее критична — он работает в доверенной среде стримера).
**Метод:** ручной анализ кода + threat modeling. Один параллельный агент покрыл watch-time/EventSub. Остальные два упёрлись в лимит API — категории JWT/auth/CORS и race-conditions/SQL прошёл сам по исходникам.

---

## Executive summary

Текущий бэк **не готов к запуску с реальными деньгами в текущем виде.** Найдено **13 CRITICAL**, **9 HIGH**, **8 MEDIUM** и несколько LOW дыр. Главные классы проблем:

1. **Большинство action-эндпоинтов не требуют JWT** — `username` берётся из тела запроса. Это ломает экономику фундаментально: атакующий может играть в казино за чужой счёт, создавать дуэли за жертву и забирать её очки, фарминговать стрик-бонусы, кликать-фармить очки на любых ников.
2. **Слабые секреты в `.env`** — ADMIN_PASSWORD = 8 цифр (значение вырезано 2026-08-23), EVENTSUB_SECRET = 12 цифр (значение вырезано; с тех пор ротирован на 43 символа). Оба брутфорсятся за минуты. Failed-login-counter существует, но **не блокирует** попытки.
3. **EventSub webhook без timestamp-window** — старые валидные подписи можно переигрывать.
4. **RNG в казино — `random.random`** (Mersenne Twister), предсказуемый.
5. **Накрутка просмотра тривиальна** — `/api/viewer/activity` без авторизации, без cross-validation с Twitch viewer-list.

Одновременно есть и **хорошие куски**: JWT-верификация на тех эндпоинтах, где она применена, написана корректно. EventSub HMAC проверяется правильно. БД-операции на `points` атомарны (`UPDATE ... WHERE points >= ?`). `BEGIN IMMEDIATE` грамотно используется в market и free-spins. Это сводит риск race-conditions к минимуму **при условии**, что мы закроем authn-дыры. Без authn — атомарность нерелевантна, потому что атакующий действует как «легитимный» пользователь.

---

## CRITICAL (фиксить до любого продакшена с деньгами)

### C1. /api/viewer/activity — анонимная накрутка просмотра
**Файл:** [routes/viewer.py:119-186](../backend/routes/viewer.py)
**Что:** username берётся из body, JWT не проверяется. Любой POST с произвольным username + watch_time увеличивает `activity_stats` и рефрешит `last_seen`, что заставляет `bot.reward_points_loop()` начислять очки.
**Сценарий атаки:**
```bash
while true; do
  curl -X POST https://shedoy23.ru/api/viewer/activity \
    -H 'Content-Type: application/json' \
    -d '{"username":"ferma_acc1","watch_time":30}'
  sleep 25  # MIN_HEARTBEAT_SECONDS
done
```
Атакующий открывает 100 ботов с разными ников — фермит очки 24/7 даже если стрим офлайн (стрим-чек не блокирует, при ошибке `pass`).
**Фикс:**
```python
jwt_result = verify_twitch_jwt(request)
if jwt_result["status"] != "valid":
    return {"status": "unauthorized"}
username = sanitize_username(resolve_jwt_login(jwt_result))
# username из body игнорировать
```
Дополнительно — раз в 5 минут синхронизировать `viewers` с реальным Twitch viewer-list (Helix `/streams/{id}/chatters` или viewer-list endpoint), удалять очки начисленные «фантомам».

### C2-C5. Казино — все 4 эндпоинта без JWT
**Файлы:** [routes/casino.py:134-359](../backend/routes/casino.py)
- `/api/casino/bet`
- `/api/casino/slots`
- `/api/casino/slots/double`
- `/api/casino/slots/freespin`

**Что:** все берут `username` из тела, JWT не проверяется. Только `sanitize_username` + rate-limit по username.
**Сценарии:**
1. **Слив чужого баланса в казино:** атакующий шлёт `/api/casino/slots` с `username: victim, bet: <victim_balance>`. Спин может проиграть → очки жертвы пропадают.
2. **Угон pending-double:** жертва выиграла, у неё в `_pending_doubles[victim]` ждёт удвоение. Атакующий шлёт `/api/casino/slots/double?username=victim&choice=red` и забирает решение себе (оно переводит деньги жертве — но риск проиграть половина).
3. **Кража фриспинов:** атакующий тратит фриспины жертвы (5 в день).
**Фикс:** добавить JWT-проверку в начало каждого эндпоинта; брать username только из JWT-резолва. То же что C1.

### C6-C7. Дуэли — оба эндпоинта без JWT, тривиальный угон очков
**Файл:** [routes/duel.py:214-402](../backend/routes/duel.py)
**Что:** `create_duel` принимает `request.creator` из body, `accept_duel` — `req.username`. JWT не проверяется.
**Сценарий атаки (100% reliable):**
```bash
# Шаг 1: создать дуэль ОТ ИМЕНИ ЖЕРТВЫ с заранее известным ходом
curl -X POST .../api/duel/create -d '{"creator":"victim","amount":10000,"move":"rock"}'
# → возвращает duel_id

# Шаг 2: принять её СОБОЙ контр-ходом
curl -X POST .../api/duel/accept -d '{"duel_id":"...","username":"attacker","move":"paper"}'
# Paper бьёт rock → атакующий выигрывает, _transfer списывает 10К с victim, добавляет attacker
```
Атакующий может сливать сколько угодно сколько у жертвы есть. Бонусом ELO растёт у атакующего, и в конце сезона он берёт **1 000 000 очков приз** (PRIZES[1] = 1M).
**Фикс:** JWT для обоих эндпоинтов; `creator`/`username` строго из JWT.

### C8-C9. /api/event/contribute и /api/event/bid — анонимный слив очков жертвы в общую копилку
**Файл:** [routes/event.py:117-179](../backend/routes/event.py)
**Что:** оба берут `username` из body. Списывают очки с указанного аккаунта в копилку рулекциона.
**Сценарий:** атакующий шлёт `/api/event/contribute` с `{"username":"victim","amount":<victim_balance>}`. Очки жертвы пропадают в копилку — даже не атакующему. Чистый троллинг + DoS экономики.
**Фикс:** JWT, как везде.

### C10. /api/viewer/chat-message — фейковые сообщения, бонусные очки без чата
**Файл:** [routes/viewer.py:189-230](../backend/routes/viewer.py)
**Что:** ни JWT, ни проверки что сообщение реально пришло из IRC. Принимает body `{username, message_length, message_text}` и начисляет `min(length//10, 10)` очков.
**Сценарий:** скрипт шлёт `{"username":"acc","message_length":100}` 50 раз в секунду — 500 очков/сек до дневного лимита `max_daily_chat_bonus` (~500 очков сразу).
**Фикс:** удалить эндпоинт целиком — реальные сообщения уже отслеживаются IRC-ботом в `main.py:472-504` (`event_message`). Этот эндпоинт — дублирующая дыра.

### C11. /api/viewer/click — анонимный клик-фарм
**Файл:** [routes/viewer.py:233-245](../backend/routes/viewer.py)
**Что:** `bonus_per_click` за каждый POST. Rate-limit 10/мин по username (то есть 10/мин на каждый ник).
**Сценарий:** скрипт перебирает 1000 ников, на каждом 10 кликов в минуту — 10К кликов/мин на одном IP.
**Фикс:** JWT + rate-limit по `request.client.host`, не по username.

### C12. /api/viewer/attendance — фейковый стрик
**Файл:** [routes/viewer.py:281-291](../backend/routes/viewer.py)
**Что:** `username` из body, `minutes` из body. Триггерит `bot.record_viewer_attendance` → `db.record_attendance` → начисляет `1000 * streak` очков (database.py:1049).
**Сценарий:** атакующий 10 раз вызывает `/api/viewer/attendance` с разными `stream_id` — стрик выкручивается до 10, награда 10 000 очков.
Стоп — `record_attendance` не принимает stream_id из body. Надо проверить `bot.record_viewer_attendance`. Если внутри он берёт текущий `current_stream_id` из бота — атакующий может зачесть 1 стрим (15 минут просмотра, в реальности стримов идущих сейчас один). Но он зачтёт это **за чужой ник**, прибавляя жертве стрик. Что хуже — жертва сама не сможет потом зачесть (UNIQUE constraint на (username, stream_id) с claimed=1). **Ущерб:** саботаж зрителей, плюс начисление 1000-N очков на любые ники (минор-фарм, но реально).
**Фикс:** JWT.

### C13. /api/viewer/online — анонимная отметка «онлайн»
**Файл:** [routes/viewer.py:28-48](../backend/routes/viewer.py)
**Что:** обновляет `last_seen` для произвольного username. Само по себе очков не даёт, но `last_seen` — ключ для семейного дохода (`run_family_income` в main.py:265-289 даёт бонус если **оба** супруга онлайн). Атакующий может «удерживать» жертву онлайн → жертва получает family bonus за чужой счёт. Минорно.

Также этот эндпоинт смягчает antifarm-проверки в других местах, поэтому стоит закрыть.
**Фикс:** JWT.

---

## CRITICAL (секреты и инфра)

### C14. Слабый ADMIN_PASSWORD — 8 цифр
**Файл:** `.env` строка 9 (`ADMIN_PASSWORD=<вырезано 2026-08-23>`)
**Что:** 8-значный числовой пароль = 10⁸ комбинаций ≈ 27 бит энтропии. Брутфорс по сети с задержкой 100мс/попытка = ~3 года, но локально (украденный backup) — секунды. **Хуже:** failed-login-counter в `dependencies.py:142-177` инкрементирует, но **не блокирует** — нет кода который бы возвращал 429 после N попыток. То есть онлайн-брутфорс ничем не лимитирован кроме скорости HTTP.
**Сценарий:** атакующий запускает hydra/wfuzz по `/api/donate`, перебирает 10⁸ паролей (даже на 50 r/s это 23 дня). Найдя пароль, использует `/api/donate` чтобы выписывать произвольные очки любому юзеру.
**Фикс (срочно):**
1. Поменять `ADMIN_PASSWORD` на 16+ символов с буквами/цифрами/символами (`openssl rand -base64 24`).
2. В `require_admin` добавить блокировку IP после ≥10 неудач за 10 минут (counter уже есть, надо просто проверять и возвращать 429 если `count >= 10`).

### C15. Слабый EVENTSUB_SECRET — 12 цифр
**Файл:** `.env` строка 13 (`EVENTSUB_SECRET=<вырезано; ротирован>`)
**Что:** 12 цифр = 10¹² ≈ 40 бит энтропии. HMAC-SHA256 с таким секретом подбирается **офлайн** за часы на GPU. Атакующий получает легитимную подпись каждый раз, когда зритель redeem'ит channel points (webhook публичный).
**Сценарий:** атакующий собирает один валидный webhook (записал `Twitch-Eventsub-Message-Signature` + body + headers), запускает hashcat: `hashcat -m 1450 sig:body+id+ts wordlist.txt` или brute 12-digit space. Найдя секрет, форжит свои webhooks: `INSERT INTO channel_points_log` через эндпоинт, начисляет себе очки.
**Фикс:** заменить на криптографически сильный секрет (`openssl rand -hex 32`), пере-зарегистрировать EventSub-подписку с новым секретом.

### C16. Все секреты раскрыты мне в этой сессии
**Что:** в ходе аудита я прочитал `.env`. Содержимое теперь в context-window текущего разговора. Это **не утечка наружу** (контекст приватный), но любые секреты которые там были — потенциально скомпрометированы при условии что ты не доверяешь Anthropic-инфраструктуре или контекст-сохранение в файлы.
**Что в опасности:** TWITCH_OAUTH_TOKEN, TWITCH_CLIENT_SECRET, TWITCH_EXTENSION_SECRET, ADMIN_PASSWORD, EVENTSUB_SECRET, TWITCH_STREAMER_TOKEN.
**Фикс:** **ротировать все секреты** после завершения работы по аудиту. Можно сделать постепенно (после починки кода — иначе придётся править .env дважды).

---

## HIGH

### H1. EventSub webhook без timestamp-window
**Файл:** [main.py:649-666](../backend/main.py)
**Что:** HMAC-подпись проверяется корректно (`_hmac.compare_digest`), но `msg_timestamp` не валидируется на свежесть. Дедуп по `redemption_id` смягчает (line 695-700), но если БД когда-то очищалась (после переноса/миграции) — старые подписи могут пройти заново.
**Сценарий:** атакующий записал валидный webhook от Twitch (например через MITM на отправляющей стороне, или из логов), переигрывает после рестарта БД.
**Фикс:**
```python
import time as _t
try:
    msg_ts = _t.mktime(_t.strptime(msg_timestamp.split('.')[0], '%Y-%m-%dT%H:%M:%S'))
    if abs(_t.time() - msg_ts) > 600:  # 10 минут
        return JSONResponse({"error":"timestamp out of window"}, status_code=403)
except Exception:
    return JSONResponse({"error":"bad timestamp"}, status_code=403)
```

### H2. Failed login counter — тупик
**Файл:** [dependencies.py:142-177](../backend/dependencies.py)
**Что:** `_failed_login_attempts[ip]["count"]` накапливается, но `require_admin` нигде не проверяет это значение чтобы вернуть 429/403. Только лог `print(f"🚨 Failed login attempt #{count}")`. Брутфорс ничем не сдерживается.
**Фикс:** перед `secrets.compare_digest` в `require_admin` добавить:
```python
attempts = _failed_login_attempts.get(ip, {"count":0,"first":now})
if attempts["count"] >= 10 and now - attempts["first"] < 600:
    raise HTTPException(429, "Too many failed attempts, попробуй через 10 минут")
```

### H3. Casino RNG — Mersenne Twister, предсказуемый
**Файл:** [routes/casino.py:74-82, 254-274](../backend/routes/casino.py)
**Что:** `random.randint`, `random.choice` — стандартный Python MT19937. Состояние = 624 32-битных слова. После наблюдения ~624 outputs (с учётом скрытых символов — больше) можно реконструировать состояние и предсказать следующий спин/риск-игру.
**Сценарий:** атакующий делает 1000 спинов на копеечных ставках, скармливает символы reverse-engineering инструменту (`untwister` для Python), реконструирует состояние, дальше делает крупные ставки только когда предскажет тройку crown.
**Реальность угрозы:** теоретически возможно, но требует значительных вложений усилий. Для виртуальной экономики со ставками до 10К — **HIGH**, для реал-мани — **CRITICAL**.
**Фикс:** одно слово — `secrets`:
```python
import secrets
_rng = secrets.SystemRandom()
# Заменить random.randint(...) на _rng.randint(...)
# random.choice(...)  на _rng.choice(...)
```

### H4. Race на `_pending_doubles` в риск-игре
**Файл:** [routes/casino.py:253-286](../backend/routes/casino.py)
**Что:** между `pending = _pending_doubles.get(uname)` (line 260) и `_pending_doubles.pop(uname, None)` (line 272) есть `await get_bot().touch_viewer(uname)` — `await` отдаёт управление, второй конкурентный запрос проходит ту же проверку, оба попадают на pop+награду.
**Сценарий:** атакующий шлёт два `/api/casino/slots/double` через миллисекунду. Оба получают одинаковый `pending`, оба вызывают `random.choice` → независимые исходы. Если хоть один win — `add_points` сработает. Если оба win — двойная награда. Если оба lose — баланс уйдёт в большой минус (line 282-283 `to_remove = min(amount, bal)` спасает от <0).
**Фикс:** атомарный pop вместо get+pop:
```python
pending = _pending_doubles.pop(uname, None)
if not pending: ...
```

### H5. resolve_twitch_token — explicit_user_id из body превалирует над JWT
**Файл:** [routes/misc.py:197-204](../backend/routes/misc.py)
**Что:** если `explicit_user_id` в body — берётся он. JWT-decode только fallback. Кто угодно может resolve'ить любой Twitch ID → login (даже без JWT, line 230-231 — fallback на opaque_id).
**Сценарий:** атакующий перебирает Twitch user_ids, получает логины — для разведки целей.
**Фикс:** удалить `explicit_user_id` параметр; брать строго из JWT-decode (или из opaque_id если JWT нет). Кэширование в `_twitch_id_cache` оставить.

### H6. Donation_total в памяти + донат-эндпоинт без proof
**Файлы:** [routes/misc.py:142-152, routes/event.py:46-55](../backend/)
**Что:** admin шлёт `/api/donate` → `bot.event_manager.donation_total += amount_rub`. Это in-memory счётчик. После рестарта сбрасывается (хотя в БД лежит `event_pool` строка — если она используется при загрузке, OK; если нет — рассинхрон). `can_start_event` сравнивает с `EVENT_CONFIG['min_donations_for_event']`. Если admin-пароль скомпрометирован (см. C14), атакующий может бесконечно стартовать ивенты с призами.
**Фикс:** счётчик `donation_total` пересчитывать из БД при `event_manager.__init__` и после каждого ивента, не держать только в памяти.

### H7. JWT не проверяет `aud` / `iss`
**Файл:** [auth.py:43-48](../backend/auth.py)
**Что:** `jwt.decode` с `options={"verify_exp": True, "leeway": 60}` — но `verify_aud` не указан. Twitch Extension JWT содержит `channel_id` (broadcaster), но мы его не валидируем — токен от другого расширения (если у атакующего есть SECRET от другого Twitch Extension которое обслуживает наш сервер) пройдёт.
**Реальность:** низкая (нужен скомпрометированный secret), но добавление одной строки убирает класс атак.
**Фикс:**
```python
payload = jwt.decode(..., audience=TWITCH_EXTENSION_CLIENT_ID, options={"verify_exp":True, "verify_aud":True})
```
Только если у Twitch Extension JWT есть `aud` claim — нужно проверить.

### H8. DEV_MODE bypass
**Файл:** [auth.py:26-27](../backend/auth.py)
**Что:** если `DEV_MODE=True` в .env — JWT-верификация полностью отключена, любой запрос идёт от `DEV_USERNAME`. Сейчас в .env `DEV_MODE=False` ✓. Footgun: одна опечатка в .env — компрометация.
**Фикс:** в `verify_twitch_jwt` после check'а `DEV_MODE`:
```python
if DEV_MODE and os.getenv("ENVIRONMENT", "").lower() == "production":
    raise RuntimeError("DEV_MODE forbidden in production")
```

### H9. Race на `accept_duel` (двойной accept одной дуэли)
**Файл:** [routes/duel.py:256-402](../backend/duel.py)
**Что:** проверка `duel["status"] != "pending"` на line 280, дальше много `await`-ов до `duel["status"] = "completed"` на line 367. Между этим — два конкурентных accept могут пройти status-check. Денежный transfer защищён (`UPDATE WHERE points >= ?`), но ELO/streak обновятся **дважды**, и второй матч пишется в логи как валидный.
**Фикс:** заменить in-memory dict на атомарный INSERT в `pending_duels` (`UPDATE ... WHERE duel_id=? AND status='pending'` с rowcount-чеком), или гейтить по rowcount удаления `_db_remove_duel` в начале accept.

---

## MEDIUM

### M1. CORS-настройка содержит wildcard который не работает
**Файл:** [main.py:170-186](../backend/main.py)
**Что:** `"https://*.ext-twitch.tv"` в `allow_origins` — Starlette/FastAPI **не поддерживает** wildcards в `allow_origins` (только в `allow_origin_regex`). Эта строка молча игнорируется. Реальные ext-twitch субдомены, видимо, не в списке.
**Реальность:** функциональный баг, не security. Но для платформенного запуска критично — Twitch Extension хостится на `<extension-id>.ext-twitch.tv`.
**Фикс:** `allow_origin_regex=r"^https://[a-z0-9]+\.ext-twitch\.tv$"` рядом с явным списком.

### M2. CORS allow_origins содержит "null"
**Файл:** [main.py:179](../backend/main.py)
**Что:** "null" origin для OBS Browser Source. Любая локальная HTML на машине пользователя может звать API. Низкий риск, но если у пользователя малварь — она получит API-доступ через JS из локального файла.
**Фикс (опционально):** убрать "null" и использовать explicit OBS-friendly headers, или принять как design-decision.

### M3. /api/overlay/latest публичный, утечка данных
**Файл:** [routes/misc.py:182-185](../backend/routes/misc.py)
**Что:** возвращает последний джекпот/донат/дроп без авторизации. Логины + суммы.
**Реальность:** для overlay'я в OBS нужен публичный доступ. Скрыть нельзя без передачи токена в OBS source. Принять как trade-off, документировать.

### M4. /api/viewer/online-list публичный
**Файл:** [routes/viewer.py:315-327](../backend/routes/viewer.py)
**Что:** список логинов кто в данный момент в is_afk=0. Используется для дропдаунов в UI.
**Реальность:** утечка незначительная, но для DoS / phishing-таргетинга — даёт список «активных платящих». Можно ограничить до 50, что и так есть (`SELECT ... ORDER BY username`). Низкий приоритет.

### M5. Cache poisoning в /api/user/map-twitch-id
**Файл:** [routes/misc.py:302-324](../backend/routes/misc.py)
**Что:** если `jwt_login` пуст (cache miss), любой `(twitch_id, login)` маппинг разрешён (line 318: «Разрешаем если ... JWT ещё не закеширован»).
**Сценарий:** атакующий шлёт `{twitch_id: <victim_tid>, username: <attacker_login>}` пока его собственный JWT не закеширован. Запись `_twitch_id_cache[victim_tid] = attacker_login` отравляет последующие резолвы. Эксплоит — сложный (атакующий должен подменить **свой** JWT-резолв на жертвин — что не даёт ничего полезного), но хорошая гигиена.
**Фикс:** не разрешать маппинг если jwt_login пуст. Лучше — использовать БД таблицу `twitch_ids` (она уже есть, line 127 database.py) вместо in-memory кэша.

### M6. Bot-EM `donation_total` рассинхронизуется с БД
**Файл:** misc.py:149 vs main.py:765 (init).
**Что:** in-memory счётчик инкрементируется только в момент обработки `/api/donate`. После рестарта — 0. Если БД-таблица event_pool используется при `EventManager.__init__` — OK; иначе пересчитать вручную.
**Связано с H6.**

### M7. tooltip_cache.json генерируется в backend/ и не gitignored... ой, **уже** gitignored
Перепроверил `.gitignore`: `tooltip_cache.json` есть. INFO, не дыра.

### M8. Нет security headers
**Файл:** [main.py:170-186](../backend/main.py)
**Что:** CORSMiddleware есть, но `X-Content-Type-Options: nosniff`, `Strict-Transport-Security`, `X-Frame-Options` (или CSP `frame-ancestors`) — нет.
**Реальность:** не блокирует прямые атаки, но защита-в-глубину. Twitch Extension сам в iframe, поэтому `X-Frame-Options: DENY` не подходит — нужно CSP `frame-ancestors https://*.twitch.tv https://*.ext-twitch.tv`.
**Фикс:** middleware добавляющий headers ко всем responses.

---

## LOW

### L1. `print` логи вместо logging
По всему коду. Производственно лучше использовать `logger.info/warn` — они идут в structured log, можно фильтровать. INFO.

### L2. Donate-handler пишет в БД через `aiosqlite.connect`, не через пул
**Файл:** [routes/misc.py:144](../backend/routes/misc.py)
**Что:** инкосистентно с остальным кодом который использует `db._connect()`.
**Реальность:** работает, но обходит пул соединений. INFO.

### L3. cleanup_test_accounts в проде
**Файл:** [main.py:744-759](../backend/main.py)
**Что:** при каждом startup удаляет `'Ethanenak', 'Sosi', 'Pisun', 'Chlen', 'HACKED_PAWN', ...` — пент-тест-наследие. Не дыра, но нужно убрать в проде.

### L4. /get_broadcaster_id.py в backend/
**Файл:** [backend/get_broadcaster_id.py](../backend/get_broadcaster_id.py)
**Что:** скрипт, не route. Не торчит наружу. INFO.

### L5. Frontend trust
Я не дочитал `viewer.js` детально. Из того что видно по бэку — фронт шлёт `username` напрямую во многие эндпоинты. Это **отражение** проблемы C1-C13 (бэк не верифицирует). После починки бэка фронт надо обновить чтобы шёл через `verify_twitch_jwt` flow, а не отправлял голый username в body.

---

## Что работает корректно (не трогать)

- ✅ JWT-верификация, где применена: `algorithms=["HS256"]`, `verify_exp`, base64url-padding (auth.py:38-48). Корректна.
- ✅ `secrets.compare_digest` для admin-credentials (dependencies.py:159-160). Timing-safe.
- ✅ EventSub HMAC-проверка (main.py:661-666). Алгоритм правильный.
- ✅ Channel-points dedupe по redemption_id (main.py:695-700).
- ✅ `db.remove_points` атомарен — `UPDATE ... WHERE points >= ?` (database.py:469).
- ✅ Market `BEGIN IMMEDIATE` транзакции с rowcount-чеками (market.py:130-186, main.py:231-251). Хорошее использование.
- ✅ Streak rewards атомарны (database.py:993-995).
- ✅ Free spins `BEGIN IMMEDIATE` (casino.py:302).
- ✅ Duel `_transfer` атомарен (duel.py:319-322).
- ✅ Все SQL-запросы которые я просмотрел — параметризованы (`?` placeholder, нет f-string в SQL). **SQL injection не найдено.**
- ✅ /api/points/transfer корректно резолвит sender из JWT (misc.py:71). Не из body. Образцовый эндпоинт.
- ✅ /api/market/list, /buy, /cancel — все используют JWT (market.py:30-37, 110-117, 200-207). Образцовые.
- ✅ Stream-live check на multiple endpoints — ограничивает атаку только окном онлайна.

---

## Приоритет фиксов

### Tier 0 — сделать в первую же сессию (1-2 часа работы)
1. **C14 + C15 + C16:** ротировать все секреты. ADMIN_PASSWORD ≥ 16 случайных символов, EVENTSUB_SECRET = `openssl rand -hex 32`. Twitch Extension secret пере-сгенерировать в Twitch Developer Console (это сложнее — нужно обновить версию extension'а).
2. **H2:** добавить блокировку failed-login после 10 попыток.
3. **C13 / `/api/viewer/online`:** добавить JWT (одна функция-помощник используется уже в transfer/market — копи-паст).

### Tier 1 — критично, до запуска платных подписок (1 неделя работы)
4. **C1-C13 (кроме C13 уже в Tier 0):** добавить JWT во все action-эндпоинты. Это **системная** правка — стоит сделать одну общую `Depends(require_jwt)` зависимость:
```python
def require_jwt_user(request: Request) -> str:
    r = verify_twitch_jwt(request)
    if r["status"] != "valid":
        raise HTTPException(401, "Auth required")
    login = sanitize_username(resolve_jwt_login(r))
    if not login:
        raise HTTPException(401, "User not resolved — open extension and login")
    return login
```
И всюду где сейчас `request.username` — заменить на `username = Depends(require_jwt_user)`.
5. **H1:** EventSub timestamp window.
6. **H3:** заменить `random` на `secrets.SystemRandom` в casino.py.

### Tier 2 — до выхода в EN (2 недели)
7. **H4-H9:** race conditions, resolve-token, donation_total, JWT aud, DEV_MODE guard, accept_duel race.
8. **M1-M2:** CORS правка для ext-twitch.tv.
9. **M8:** security headers middleware.
10. **L5:** обновить frontend под JWT-only вызовы.

### Tier 3 — улучшения (по мере роста)
11. **C1 cross-validation:** реальная синхронизация с Twitch viewer-list (защита от ботов которые не в стриме).
12. Frontend `document.hidden` heartbeat-pause.
13. M3-M7 — мелкая гигиена.

---

## Оценка времени и риска

| Тир | Часы работы | Риск если не сделать |
|---|---|---|
| 0 | 1-2 ч | Полный admin-takeover, фейк-EventSub event'ы |
| 1 | ~30-40 ч | Атакующий выкручивает экономику до 0 за день |
| 2 | ~30 ч | Пробои меньше масштаба, RNG-эксплоиты |
| 3 | ~50 ч | Качество защиты для платформенного масштаба |

Tier 0 + Tier 1 — **минимум** перед тем как принимать первые ₽ от стримеров. До этого можно работать в режиме закрытой беты (ты + друзья тестировщики), при условии что они не пытаются хакать.

---

## Отдельный вопрос: можно ли это «починить за один присест»?

Можно сделать Tier 0 + основу Tier 1 (общий `require_jwt_user` dep + замена во всех routes) за **~6-8 часов** сосредоточенной работы. Это превращает бэк из «дырявого» в «допустимо защищённого для closed beta». Дальше — итеративно.

Ротацию Twitch Extension secret и переподписку EventSub сделай сам — мне не стоит трогать продакшн-конфиг Twitch.

---

## История

| Дата | Версия | Изменения |
|---|---|---|
| 2026-04-30 | 1.0 | Первый аудит. 13 CRITICAL, 9 HIGH, 8 MEDIUM, 5 LOW. |
