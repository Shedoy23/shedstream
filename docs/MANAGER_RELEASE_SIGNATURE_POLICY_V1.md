# Manager release signature policy v1

Дата: 2026-08-16  
Статус: verifier, signer и безопасный key generator реализованы; production
signing key и HTTPS publication ещё не созданы

## Две разные подписи

- Подпись RimLink release artifact — собственная RSA-PSS подпись ShedLink.
  Она бесплатна и обязательна для Manager install flow.
- Authenticode-подпись Windows EXE — отдельный механизм доверия Windows.
  Она не требуется для проверки RimLink и может быть отложена до внешней beta;
  без доверенного сертификата Windows может показывать SmartScreen warning.

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

Production key pair создаётся бесплатным локальным generator только по явно
заданным абсолютным путям вне repository. Generator отказывается перезаписывать
существующие файлы, создаёт RSA 4096 и ограничивает ACL private PEM текущим
Windows user:

```powershell
dotnet run --project ShedLink.Manager/tools/ShedLink.Manager.GenerateReleaseKey -- `
  --private C:\<secure-external-location>\shedlink-release-2026.private.pem `
  --public C:\<secure-external-location>\shedlink-release-2026.public.pem `
  --key-id shedlink-release-2026
```

Перед настоящим запуском владелец выбирает external location и backup. Private
PEM не переносится в Git, production server или обычную cloud-sync папку.

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
  --manifest manifests/installation/rimworld-0.1.1.json `
  --artifact <path-to-release.zip> `
  --key <path-outside-repository/private.pem> `
  --key-id shedlink-release-2026 `
  --url https://<final-host>/releases/RimLink-0.1.0.zip
```

Publication и nginx/CDN change требуют отдельного подтверждения владельца и
обычного production runbook. Текущий repository manifest остаётся unsigned и
не выдаётся внешнему Manager как release source.

Независимая проверка локального либо заново скачанного ZIP проверяет manifest,
size, SHA-256, RSA-PSS signature, безопасную распаковку и обязательные health
probe paths:

```powershell
dotnet run --project ShedLink.Manager/tools/ShedLink.Manager.VerifyRelease -- `
  --manifest <signed-manifest.json> `
  --artifact <downloaded-release.zip> `
  --public-key C:\<secure-external-location>\shedlink-release-2026.public.pem
```

Локальный rehearsal 2026-08-16 прошёл полную цепочку на копии production
manifest и актуальном RimLink `0.1.1` ZIP: temporary RSA 4096 generation →
signer → independent verifier. Совпали size, SHA-256, key fingerprint и health
probes; временные private/public keys и подписанная копия manifest удалены.

После проверки подписи Manager не фиксирует пакет отдельно: package swap,
managed XML и side-effect-free module auth-check входят в одну recoverable
operation. До успешного auth-check сохраняются обе rollback-копии. Ошибка
возвращает прежние пакет и config; crash после verify завершается по локальному
несекретному journal при следующем запуске.
