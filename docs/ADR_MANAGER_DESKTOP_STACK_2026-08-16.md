# ADR: ShedLink Manager desktop stack

Дата: 2026-08-16  
Статус: принято для Windows MVP

## Решение

ShedLink Manager v1 строится на .NET 8. UI — WPF, логика установки и auth живёт
в отдельном `ShedLink.Manager.Core` без зависимости от UI.

## Почему

- поддерживаемая среда MVP уже ограничена Windows;
- Twitch pairing открывается в системном browser, встроенный web runtime не нужен;
- Windows Credential Manager доступен напрямую и не требует хранения refresh
  token в JSON, registry или собственном зашифрованном контейнере;
- .NET SDK уже используется в проекте, а C# знаком по игровым integrations;
- один self-contained publish сможет работать без установленного у пользователя
  SDK; конкретный формат installer/package выбирается перед внешней alpha.

Electron не выбран из-за отдельного Chromium runtime для небольшого native UI.
Tauri не выбран для MVP, потому что добавляет Rust/toolchain и webview-слой, не
давая необходимого преимущества для Windows-only установщика.

## Границы

- UI не обращается к backend и filesystem напрямую: только через Core;
- Manager access token живёт в памяти;
- refresh token и repair-копия module credential хранятся в Windows Credential
  Manager;
- `state.json` содержит только installation ID, channel/module IDs, credential
  ID и пути; bearer secrets в нём запрещены;
- OAuth выполняется только в системном browser по HTTPS;
- installation engine остаётся manifest-driven и не переносит RimWorld-specific
  lifecycle в UI.

## Уже проверено

Core self-test поднимает fake backend, проходит pending → approved pairing,
выдачу credential, restart с refresh rotation и logout/revoke. Отдельно делает
round-trip временного секрета через настоящий Windows Credential Manager и
удаляет его в `finally`. Тот же self-test является Windows CI gate.

## Следующий шаг

WPF shell состояния `login → detect → install → configure → verify`, затем
перенос conformance-tested installation transaction в Core.
