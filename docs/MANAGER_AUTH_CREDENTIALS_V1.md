# Manager auth and credential lifecycle v1

Статус: design contract, реализация не начата  
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

### `POST /v1/manager/module-credentials/{id}/rotate`

Создаёт replacement с overlap до 10 минут. Manager атомарно обновляет config и
делает authenticated handshake. Только после успеха вызывает finalize; backend
отзывает старый credential. При неудаче старый остаётся рабочим.

### `DELETE /v1/manager/module-credentials/{id}`

Немедленный revoke. Повторный revoke идемпотентен. Module API отвечает одинаковым
`auth_failed` для missing/expired/revoked/wrong-module credentials.

### `POST /v1/manager/logout`

Отзывает manager session/refresh family. Module credentials не отзываются молча:
UI отдельно спрашивает, нужно ли отключить установленные integrations.

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

## Token formats

Opaque prefixes нужны только для безопасного routing/versioning:

```text
slmgr_v1.<session_id>.<secret>
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
5. Finalize rotation и удалить rollback copy.
6. Если шаг 3–4 неуспешен, вернуть старый config; старый credential ещё валиден.
7. Если Manager упал, transaction journal на следующем старте завершает либо
   откатывает config update до истечения overlap.

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
| Refresh token replay | Rotating family; reuse отзывает всю family |
| Legacy token после revoke | V1 revoke работает только для opaque token; legacy отключается отдельным migration gate |

До реализации обязательны automated tests: approve/deny/expire, duplicate
exchange, wrong device secret, cross-channel/module request, rotate success,
rotate rollback, revoke immediate, refresh replay, restart persistence и secret
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
