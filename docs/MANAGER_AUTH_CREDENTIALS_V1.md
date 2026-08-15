# Manager auth and credential lifecycle v1

Статус: M110/M111 ledger, pairing, refresh/logout и opaque module credential
lifecycle реализованы локально; desktop storage/installer ещё впереди

Дата: 2026-08-15

## Решение

Manager не содержит Twitch client secret и никогда не получает Twitch
access/refresh token. Вход выполняется в системном browser через существующий
backend OAuth. Browser подтверждает одноразовую pairing session, после чего
Manager получает только собственную revocable session и узкий credential для
конкретной пары `channel_id + module_id`.

Текущий годовой HMAC module token остаётся legacy-механизмом на время перехода.
Он не подходит для self-service Manager: отдельный token невозможно отозвать,
не меняя общий server secret. V1 Manager использует opaque credentials с
server-side ledger и немедленным revoke.

## Границы секретов

| Credential | Где появляется | Где хранится | Чего не даёт |
|---|---|---|---|
| Twitch OAuth tokens | Только backend callback | Production DB, encrypted at rest | Не покидает backend |
| Manager refresh token | Один раз после pairing | Windows Credential Manager | Не вызывает Module API и не управляет чужим channel |
| Manager access token | Manager memory, короткий TTL | Не сохраняется в обычный файл | Не является Twitch token |
| Module credential | Manager и config выбранной integration | Game-readable config с user-only ACL; копия в Windows Credential Manager для repair | Только один channel и один module |
| Pairing device secret | Manager до завершения pairing | Только memory | Истекает через 10 минут |

RimWorld должен читать credential из своего XML config, поэтому абсолютной
секретности от процессов того же Windows user нет. Компенсация: credential узко
scoped, revocable, не даёт Twitch-доступа, автоматически redact'ится и не
попадает в Installation Manifest.

## Pairing flow

```text
Manager                         Backend                         Browser/Twitch
   | POST /manager/pairings        |                                  |
   | device_challenge,module_id -->|                                  |
   |<-- pairing_id,user_code,URL ---|                                  |
   | open system browser -------------------------------------------->|
   |                               |<-- Twitch OAuth + signed cookie --|
   |                               |<-- approve user_code/module_id ---|
   | poll(pairing_id,device_secret)|                                  |
   |------------------------------>|                                  |
   |<-- one-time manager session ---|                                  |
   | POST module-credentials        |                                  |
   |------------------------------>|                                  |
   |<-- credential shown once ------|                                  |
```

Правила:

- pairing TTL: 10 минут;
- user code короткий только для ручного сравнения, не является secret;
- `pairing_id` случайный и не даёт получить результат без `device_secret`;
- backend хранит только hash `device_secret`;
- approval требует валидную HttpOnly/Secure/SameSite cookie после Twitch OAuth;
- pairing привязывается к approved channel и заявленному `module_id`;
- polling interval и rate limit возвращаются при создании pairing;
- approve/deny и exchange одноразовые; повтор возвращает terminal status без
  повторной выдачи secret;
- browser callback не открывает custom URI с credential в query string.

## Предлагаемый API

### `POST /v1/manager/pairings`

Request:

```json
{
  "installation_id": "random local UUID",
  "module_id": "rimworld",
  "device_challenge": "base64url(sha256(device_secret))"
}
```

Response содержит `pairing_id`, `user_code`, `verification_uri`,
`expires_in=600`, `interval=3`. Никаких channel данных до browser approval.

### `GET /manager/pair?code=...`

Browser page требует streamer session cookie, показывает channel, integration и
installation label, затем отдельные Approve / Deny. State-changing submit имеет
CSRF token.

### `POST /v1/manager/pairings/{id}/exchange`

Принимает `device_secret`. До решения отвечает `authorization_pending`, после
deny/expiry — terminal error, после approve один раз выдаёт manager access token
и rotating refresh token.

### `POST /v1/manager/module-credentials`

Требует manager access token. Создаёт credential только для channel manager
session и разрешённого manifest module. Secret возвращается один раз.

Статус: реализовано локально. Ответ помечен `Cache-Control: no-store`; raw secret
не хранится в БД и повторно не показывается.

### `POST /v1/module/{module_id}/auth-check`

Проверяет module credential и его точный module scope без записи heartbeat или
изменения liveness. Manager вызывает endpoint после атомарной записи game config:
успех подтверждает доступность backend и валидность ключа, но не означает, что
игра запущена. `Technical Ready` по-прежнему требует отдельный реальный heartbeat
мода. Ответ помечен `Cache-Control: no-store`.

### `POST /v1/manager/session/refresh`

Принимает текущий refresh token и атомарно заменяет его новой Manager session в
той же family. Старые access/refresh немедленно перестают работать. Повторное
использование уже заменённого refresh token считается replay и отзывает всю
family, включая session, выигравшую конкурентную гонку. Абсолютный 30-дневный
срок family не продлевается.

### `POST /v1/manager/module-credentials/{id}/rotate`

Создаёт replacement с overlap ровно до 10 минут. Старый credential работает
только внутри этого окна и затем автоматически становится недействительным,
поэтому crash Manager не оставляет два бессрочных ключа. Manager должен атомарно
обновить config и проверить authenticated handshake до истечения окна.

### `DELETE /v1/manager/module-credentials/{id}`

Немедленный revoke. Повторный revoke идемпотентен. Module API отвечает одинаковым
`auth_failed` для missing/expired/revoked/wrong-module credentials.

### `POST /v1/manager/logout`

Отзывает manager session/refresh family. Module credentials не отзываются молча:
UI отдельно спрашивает, нужно ли отключить установленные integrations.

Статус: backend endpoint реализован локально; desktop UI ещё не реализован.

## Server-side ledger

Минимальные таблицы:

```text
manager_pairings
  id, device_secret_hash, user_code_hash, installation_id_hash, module_id,
  channel_id, status, created_at, expires_at, approved_at, exchanged_at

manager_sessions
  id, channel_id, installation_id_hash, refresh_hash, refresh_family_id,
  created_at, expires_at, last_used_at, revoked_at

module_credentials
  id, channel_id, module_id, secret_hash, label, created_at, expires_at,
  last_used_at, rotated_from_id, overlap_until, revoked_at
```

DB хранит hashes, не исходные bearer secrets. Для hash используется server-side
pepper, отдельный от Twitch OAuth encryption key и legacy HMAC signing key.
Индексы и uniqueness обеспечивают один exchange pairing и безопасную rotation
family. Все выборки credential обязательно scoped по `channel_id + module_id`.

Локальная migration `M110.manager_credentials` создаёт эти три таблицы,
ограничивает pairing status, добавляет scope/expiry indexes и регистрируется
идемпотентно. M111 добавляет обязательный для новых сессий `module_id`; старые
экспериментальные строки с `NULL` fail closed.

Локальный `manager_auth.py` реализует persistent approve/deny/expire,
одноразовый exchange по device secret, hash-only refresh storage и короткий
подписанный Manager access token. Negative tests проверяют wrong/weak secret,
pending/denied/expired/duplicate exchange, tampering, expiry, restart persistence
и fail-closed при отсутствии отдельного pepper.

Pairing HTTP/browser flow теперь экспонирован локально. Browser approval требует
approved streamer session, channel-bound CSRF и явное Approve/Deny. OAuth state
принимает только allowlisted local `return_to`, поэтому внешний open redirect
невозможен. JSON/form payload имеют жёсткий размер; verification URL строится из
канонического `MANAGER_PUBLIC_BASE_URL`, а не недоверенного Host header.

Opaque credential endpoints также экспонированы локально: issuance ограничен
scope Manager session, rotation создаёт hash-only replacement с десятиминутным
overlap, revoke идемпотентен. Общий Module API и RimWorld ingest распознают
`slmod_v1`; missing, tampered, expired, revoked и wrong-module token получают
одинаковый `401 auth_failed`. Legacy HMAC verification сохранена на переходный
период.

Refresh endpoint хранит только peppered hash текущего token. Каждая успешная
ротация создаёт новый session ID и отзывает предыдущий; replay старой строки
отзывает все строки с тем же `refresh_family_id`. Logout использует короткий
access token и отзывает family, но не меняет отдельно управляемые module
credentials.

Новые production settings:

- `MANAGER_CREDENTIAL_PEPPER` — отдельный secret минимум 32 символа; без него
  Manager endpoints fail closed, существующий backend продолжает работать;
- `MANAGER_PUBLIC_BASE_URL` — канонический HTTPS origin, default
  `https://shedoy23.ru`.

## Token formats

Opaque prefixes нужны только для безопасного routing/versioning:

```text
slmgr_v1.<session_id>.<expires_at>.<signature>
slmgrr_v1.<session_id>.<secret>
slmod_v1.<credential_id>.<secret>
```

Secret генерируется CSPRNG минимум 256 bit. В логах допустим только credential ID
и последние 4 символа fingerprint, но не bearer token. Сравнение hash —
constant-time.

## Local storage and config update

- Manager refresh token и repair-копия module credential — Windows Credential
  Manager, ключ включает installation ID и module ID.
- Access token живёт только в memory.
- Module credential записывается только в managed config field, указанное
  Installation Manifest.
- Config update: read → сохранить unmanaged fields → записать temp рядом →
  ограничить ACL текущим user → atomic replace → authenticated handshake.
- Diagnostic bundle и telemetry redact'ят manifest fields с `secret=true`,
  `Authorization`, cookies и token-like prefixes.
- Logout очищает Manager tokens из Credential Manager; удаление game credential
  выполняется только после явного выбора пользователя.

## Rotation, revoke and recovery

1. Получить replacement credential.
2. Сохранить предыдущий config как rollback copy.
3. Атомарно записать replacement.
4. Дождаться authenticated handshake нового credential.
5. Удалить rollback copy; старый credential автоматически истечёт по overlap.
6. Если шаг 3–4 неуспешен, вернуть старый config до истечения overlap.
7. Если Manager упал, transaction journal на следующем старте завершает либо
   откатывает config update, пока старый credential ещё валиден.

Server-side revoke действует сразу и переживает restart. Expired/revoked token не
может быть восстановлен локальным rollback.

## Threats and обязательные tests

| Риск | Контроль |
|---|---|
| Подмена browser callback | Одноразовый state + signed session + CSRF approval |
| Кража user code | Без device secret нельзя exchange |
| Pairing enumeration | Hash user code, rate limit, одинаковые ответы |
| Credential для чужого channel/module | Scope берётся из approved session и ledger, не из request body |
| Утечка БД | В ledger только peppered hashes |
| Утечка diagnostic bundle | Central redaction + negative fixtures |
| Потеря сети при rotation | Overlap + handshake-before-finalize + rollback |
| Refresh token replay | Реализованная rotating family; reuse отзывает всю family |
| Legacy token после revoke | V1 revoke работает только для opaque token; legacy отключается отдельным migration gate |

Automated tests уже покрывают approve/deny/expire, duplicate exchange, wrong
device secret, cross-module request, rotate success и ограничение overlap,
немедленный повторяемый revoke, tampering, hash-only storage, общий Module API,
RimWorld auth, restart persistence, refresh expiry/logout и конкурентный refresh
replay с family revoke. Ещё нужны desktop rotate-rollback и central diagnostic
redaction.

## Переход с legacy HMAC token

1. Module API принимает `slmod_v1` и старый HMAC token параллельно.
2. Manager выдаёт только `slmod_v1`.
3. Dashboard показывает legacy credentials как non-revocable и предлагает
   migration.
4. После подтверждённого обновления активных connectors legacy issuance
   отключается.
5. Legacy verification удаляется только после измеренного grace period; смена
   общего `MODULE_TOKEN_SECRET` остаётся аварийным глобальным revoke.

## Definition of Done для реализации

- Twitch tokens ни при каком пути не попадают в Manager;
- pairing и exchange одноразовы и переживают backend restart;
- отдельный module credential можно отозвать без влияния на другие channels;
- rotation не создаёт окно, где оба credential бессрочно активны;
- Manager logout/revoke/repair имеют понятное различие в UI;
- secrets отсутствуют в logs, telemetry, crash report и diagnostic bundle;
- все обязательные negative tests зелёные.
