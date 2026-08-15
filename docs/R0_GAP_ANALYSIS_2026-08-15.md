# R0 gap analysis — current HEAD and production

Дата проверки: 2026-08-15  
Проверенный source baseline: `03b1fa944d0634007dcb9224f84f7f3597e1a149`

Follow-up fix: `f236ee4` (`M109.module_last_seen` ledger regression)

Production: `https://shedoy23.ru`, read-only проверка

## Итог

Критических P0 в проверенных денежных, tenant и delivery-путях не найдено.
Backend baseline достаточно устойчив, чтобы не переписывать runtime platform перед
Manager. Однако R0 release gate пока **не пройден**: первая Manager integration не
имеет полного live E2E доказательства. Installation/version contract отсутствует,
но его реализация относится к R1, а не к оставшемуся R0 gate.

Решение по первой Manager integration: **RimWorld — условный кандидат**. У неё
есть воспроизводимая .NET-сборка, готовый release archive, стандартный путь мода,
встроенный экран настройки и наиболее сильный restart/lost-ACK дизайн. Выбор
становится окончательным только после обязательного in-game smoke из
`Расширение/docs/RIMLINK_MOD_AUDIT_2026-08-04.md`.

## Что проверено

- Полный standalone backend suite: **44/44 теста зелёные**.
- Fresh-install migrations проходят в автоматическом suite.
- Денежные пути проверяются тестами atomic charge/refund, duplicate click,
  duplicate ACK, late failure, queued TTL и refund retry.
- Tenant isolation проверяется отдельными Bannerlord, RimWorld, ShedColony и
  общими multi-channel тестами.
- Lost response/requeue поверх cursor и dedup envelope per-module покрыты
  `test_module_delivery_gaps.py`.
- RimLink сохраняет terminal outcome до ACK в дисковый journal; restart повторяет
  ACK, а не игровой effect. Это подтверждено статически и backend-тестами, но ещё
  не подтверждено живой игрой.
- Специальные Bannerlord handlers используют общий enqueue contract. Автотест
  подтверждает сохранение `price`, `client_action_id`, доменных полей, точный
  refund и отсутствие прямых `INSERT` в обход общей функции.

## Production evidence

Проверка выполнялась без deploy, restart и изменения данных.

- `/`, `/health`, `/privacy.html`, `/terms.html`, `/streamer`: HTTP 200.
- `twitchbot`: RUNNING; `/health`: HTTP 200.
- Стрим на момент проверки offline, поэтому отсутствие свежего heartbeat мода —
  ожидаемое состояние, а не инцидент.
- SQLite `PRAGMA quick_check`: `ok`; 96 viewers; один approved channel.
- Балансы `< 0`: **0**.
- Повторяющиеся непустые `client_action_id` внутри channel/module: **0**.
- `module_actions`: 8088 `acked`, 1226 `failed`, незавершённых: **0**.
- Последние эфиры 11, 13 и 14 августа создают по одной реальной Twitch session
  на непрерывный эфир. Исправление duplicate `stream_sessions` live-подтверждено.
- Critical backend files и три runtime manifest совпадают с текущим source tree.
  `database.py` отличается только переводами строк: построчное содержимое равно.
- Самый свежий compressed backup `viewers.daily.2026-08-15.db.zst` восстановлен
  в изолированный временный файл: 86 130 688 bytes, `quick_check=ok`, 108 tables,
  143 migration markers, 96 viewers, 9314 module actions. Временный файл удалён;
  живая БД не открывалась на запись.

## Реально существующие integrations

| Integration | Runtime manifest | Game artefact / версия | Текущее доказательство | Статус для Manager |
|---|---|---|---|---|
| Bannerlord | `0.1.0-scaffold` — метка устарела | `SubModule.xml` `v0.1.0`; target игры 1.3.15 по документации | Рабочий C# connector и исторический prod E2E | Не выбран: сложнее packaging/dependencies, нет канонического install archive |
| RimWorld | `0.1.0` с устаревшей пометкой pre-migration | `RimLink-2026-08-04-hardening.zip`; About заявляет 1.5/1.6 | Build и backend regressions есть; in-game hardening smoke не завершён | Условный первый кандидат |
| ShedColony | `0.1.0` | `shedcolony-0.1.0.jar`, Minecraft 1.21.1 + NeoForge + MineColonies | Есть checksum и ручная инструкция; source connector находится вне repo | Не выбран: сборка не воспроизводится из этого repository |

Номера runtime manifest сейчас нельзя использовать как надёжный источник версии
для Manager. Installation Manifest должен отделить install artefact/version от
runtime API capability contract.

## Ручная установка и configuration matrix

| Integration | Установка сейчас | Config / credential | Update сейчас | Gap |
|---|---|---|---|---|
| Bannerlord | Ручное копирование module folder в `Modules/Shedoy23.BannerlordLink` | `config.json`: backend URL, module token, channel ID | Ручная замена файлов | Нет пользовательского install doc, signed/hash release и rollback |
| RimWorld | Ручная распаковка `RimLink` в game `Mods` | RimWorld Mod Settings: server URL и masked module token | Ручная замена folder | Нет install doc, artefact manifest/hash/signature и automated repair |
| ShedColony | JAR в `mods/`, один запуск, затем restart | `config/shedcolony.json`: backend URL, module token, channel ID, poll interval | Ручная замена JAR | Source/build не находятся в repo; нет rollback/repair |

Module token выдаётся channel-bound через authenticated streamer dashboard и
подписывается server-side `MODULE_TOKEN_SECRET`. Backend secrets остаются в
production `.env`; они не должны попадать в installation manifest или diagnostic
bundle. Manager должен получать токен после Twitch OAuth и хранить его через
Windows credential storage, а не в своём manifest.

## Release-gate matrix

| Инвариант | Доказательство | Результат |
|---|---|---|
| Не платить за инфраструктурный отказ | atomic/refund/TTL/503 regression tests; prod queue clean | PASS в backend scope |
| Duplicate request/ACK не даёт второй effect/reward | double-click, duplicate ACK, envelope dedup tests; RimLink outcome journal | PASS automated; live lost-ACK smoke pending |
| Cross-channel isolation | general + per-integration multi-tenant tests | PASS в покрытых путях |
| Restart не теряет оплаченное действие | backend requeue + RimLink durable outcome design | PARTIAL: нужен live restart/reconnect smoke |
| Moderируемый контент не играет автоматически | TTS approval/moderation tests | PASS |
| Fresh migrations и backup/restore | fresh-install test; restore свежего production `.zst`, `quick_check=ok` | PASS |

## Найденные gaps

### P1 — блокируют окончательное прохождение R0

1. Выполнить RimWorld in-game E2E: apply/refuse, lost ACK, restart с pending ACK,
   reconnect, save switch и burst. До этого RimWorld — кандидат, не утверждённая
   первая integration.

### P1 — следующий этап R1, не блокирует закрытие R0

1. Ввести Installation Manifest v1 и канонический version ledger. Текущие
   runtime manifest содержат устаревшие статусы/версии.

### P2 — исправить до внешней alpha либо явно вынести из M1

1. ~~`M109 module_last_seen` не пишет marker в `migrations_applied`.~~ Исправлено
   локально после аудита: migration ремонтирует существующую production-схему,
   сохраняет heartbeat и регистрируется ровно один раз. Production ещё не
   обновлён.
2. Добавить install/upgrade/rollback инструкции для Bannerlord и RimWorld.
3. Вернуть ShedColony source/build pipeline в канонический repository либо
   документировать отдельный versioned upstream.
4. Усилить special-action regression явной проверкой сохранения исходного
   `action_id` и terminal status, а не только косвенной проверкой через refund.
5. Обновить устаревший раздел testing strategy в `ARCHITECTURE.md`, где всё ещё
   написано, что автоматических тестов нет.

## Минимальная telemetry для Manager

До M1 достаточно следующей последовательности с anonymous installation ID,
channel ID, integration/version, Manager version, elapsed time, result/error code
и timestamp:

`manager_started → manager_authenticated → game_detected → install_started →
install_completed → configuration_completed → mod_heartbeat_received →
test_action_completed → technical_ready`.

События не должны содержать token, cookie, полный filesystem path или содержимое
пользовательского config. Backend уже имеет `stream_sessions`, `feature_usage` и
`module_last_seen`; Manager funnel пока отсутствует.

## Следующий исполнимый порядок

1. Выполнить и сохранить RimWorld live smoke evidence.
2. После этой gate-проверки окончательно утвердить RimWorld либо переключить
   M1 vertical slice на Bannerlord.
3. Начать R1 с Installation Manifest schema и одного RimWorld package.
