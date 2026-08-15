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

WPF shell уже показывает account/game/integration stages, открывает pairing в
системном browser, восстанавливает сессию после перезапуска, ищет RimWorld во
всех Steam libraries и проверяет вручную выбранную папку. Кнопка установки пока
честно отключена до готовности безопасной доставки release artifact.

Installation Core уже читает production manifest, проверяет размер/SHA-256,
безопасно распаковывает ZIP, отклоняет traversal/reparse points, выполняет
staging + atomic directory swap и восстанавливает прежнюю версию по crash
journal. Managed XML writer сохраняет неизвестные настройки, атомарно меняет
только объявленные поля и ограничивает ACL файла текущим Windows user.

Install CTA остаётся отключён не из-за transaction engine, а до появления
Manager-доступного HTTPS release artifact и принятой signature policy.

Проверка:

```powershell
dotnet run --project ShedLink.Manager/tests/ShedLink.Manager.Core.SelfTest
dotnet run --project ShedLink.Manager/src/ShedLink.Manager.App
```

Self-test использует поддельный HTTP backend и временную запись в Windows
Credential Manager, которую удаляет даже при ошибке.
