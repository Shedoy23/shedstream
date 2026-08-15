# Manager release signature policy v1

Дата: 2026-08-16  
Статус: verifier реализован; production signing key и HTTPS publication ещё не созданы

## Правило допуска

- `source.kind=repository` разрешён только для разработки и может иметь
  `security.signature_status=unsigned`.
- `source.kind=https` всегда требует `signature_status=signed`, artifact
  signature и заранее известный Manager public key.
- HTTPS без подписи, неизвестный `key_id`, redirect, downgrade на HTTP,
  неверный `Content-Length`, превышение/усечение размера, SHA mismatch и
  signature mismatch завершаются до распаковки и не меняют игру.
- Manager не принимает пользовательский флаг «всё равно установить».

## Алгоритм

`rsa-pss-sha256`, RSA не короче 3072 bit для production key. Подписывается UTF-8
payload с обязательным финальным переводом строки:

```text
ShedLink-Artifact-v1
<integration_id>
<release_version>
<artifact_id>
<size_bytes>
<sha256>
```

Подпись кодируется standard Base64. Manifest хранит:

```json
{
  "signature": {
    "algorithm": "rsa-pss-sha256",
    "key_id": "shedlink-release-2026",
    "value": "base64-signature"
  }
}
```

SHA-256 проверяет скачанные bytes; publisher signature связывает digest с
integration/version/artifact identity. Подпись проверяется только ключом,
встроенным в конкретную сборку Manager.

## Ключи

- private key создаётся и хранится вне Git, production server и release ZIP;
- публичный ключ встраивается в Manager вместе с `key_id`;
- CI может использовать только временный тестовый ключ;
- утрата private key означает выпуск нового key pair и Manager update;
- компрометация требует удалить старый public key из новой Manager build и
  остановить публикацию manifest'ов со старым `key_id`.

## Порядок публикации

1. Собрать deterministic RimLink ZIP.
2. Зафиксировать точный size и SHA-256.
3. Подписать payload offline production key.
4. Загрузить ZIP по конечному HTTPS URL без redirect.
5. С внешней машины скачать URL и повторно проверить size/SHA/signature.
6. Обновить source/signature в Installation Manifest.
7. Выпустить Manager с trusted public key и только затем включить Install CTA.

Offline signer проверяет ZIP против текущих size/SHA, требует RSA 3072+, меняет
source/status/signature атомарно и сам перепроверяет результат перед заменой:

```powershell
dotnet run --project ShedLink.Manager/tools/ShedLink.Manager.SignArtifact -- `
  --manifest manifests/installation/rimworld-0.1.0.json `
  --artifact <path-to-release.zip> `
  --key <path-outside-repository/private.pem> `
  --key-id shedlink-release-2026 `
  --url https://<final-host>/releases/RimLink-0.1.0.zip
```

Publication и nginx/CDN change требуют отдельного подтверждения владельца и
обычного production runbook. Текущий repository manifest остаётся unsigned и
не выдаётся внешнему Manager как release source.
