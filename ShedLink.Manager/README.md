# ShedLink Manager

Windows desktop Manager для self-service установки игровых integrations.

Технологический выбор v1: .NET 8 + WPF. Причины: Manager поддерживает Windows,
не требует встроенного browser runtime, открывает Twitch pairing в системном
browser и использует штатный Windows Credential Manager.

Сейчас реализовано независимое от UI ядро:

- HTTPS-клиент Manager pairing/session/module-credential API;
- device secret только в памяти во время pairing;
- refresh и module credential в Windows Credential Manager;
- атомарный JSON только с несекретным installation state;
- восстановление Manager session после перезапуска с обязательной refresh rotation;
- явный logout с отдельным выбором revoke установленного module credential.
- crash-safe смена module credential с проверкой нового ключа и автоматическим
  продолжением после перезапуска.

WPF shell уже показывает account/game/integration stages, открывает pairing в
системном browser, восстанавливает сессию после перезапуска, ищет RimWorld во
всех Steam libraries и проверяет вручную выбранную папку.

Кнопка диагностического отчёта сначала показывает пользователю итоговый JSON и
только затем разрешает сохранить его. В отчёт входят версии, health probes,
heartbeat и последние сообщения; credentials, authorization, cookies и путь
профиля Windows автоматически удаляются. Версия RimWorld читается из игрового
`Version.txt`; отчёт отличает unmanaged installation от повреждённых файлов.
Unsupported/unknown game version блокирует install и `Technical Ready`.
Из встроенного каталога manifests Manager выбирает самый новый совместимый
RimLink release и использует его во всей install/config/repair операции.

Кнопка `Проверить отказы` выполняет два бесплатных production reliability
сценария через настоящую игровую очередь: ожидаемый отказ неизвестной no-op
команды и контролируемую потерю ACK. Во втором случае backend 120 секунд
отклоняет только помеченный диагностический ACK, затем удаляет команду по TTL;
поздний retry RimLink завершается идемпотентно. Состояние колонии и viewer points
не меняются.

Installation Core уже читает production manifest, проверяет размер/SHA-256,
безопасно распаковывает ZIP, отклоняет traversal/reparse points, выполняет
staging + atomic directory swap и восстанавливает прежнюю версию по crash
journal. Managed XML writer сохраняет неизвестные настройки, атомарно меняет
только объявленные поля и ограничивает ACL файла текущим Windows user.

Signed HTTPS delivery gate закрыт: RimLink `0.1.1` опубликован, проверен и имеет
встроенный trusted public key. Manager API и migrations M109–M112 развёрнуты.
Реальный production flow `login → detect → signed install → configure → game
heartbeat → diagnostic ACK → Technical Ready` подтверждён 2026-08-16.

HTTPS download и signature verification уже реализованы fail-closed: redirects,
HTTP downgrade, размер, SHA-256, неизвестный publisher key и RSA-PSS mismatch
отклоняются до распаковки. Production key/public half и immutable RimLink URL
созданы и независимо проверены.

Offline signer находится в `tools/ShedLink.Manager.SignArtifact`; он не создаёт
и не хранит private key, а принимает внешний PEM только на время запуска.
Бесплатный безопасный generator RSA 4096 находится в
`tools/ShedLink.Manager.GenerateReleaseKey`; production key создан вне repository
с user-only ACL. Внешняя резервная копия на отдельный носитель ещё требуется.
`tools/ShedLink.Manager.VerifyRelease` независимо проверяет подписанный manifest,
ZIP bytes, RSA fingerprint, безопасную распаковку и обязательные health probes.

Проверка:

```powershell
dotnet run --project ShedLink.Manager/tests/ShedLink.Manager.Core.SelfTest
dotnet run --project ShedLink.Manager/src/ShedLink.Manager.App
```

Self-test использует поддельный HTTP backend и временную запись в Windows
Credential Manager, которую удаляет даже при ошибке.
