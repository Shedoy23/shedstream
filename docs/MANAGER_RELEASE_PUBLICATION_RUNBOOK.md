# Manager release publication runbook

Дата: 2026-08-16  
Статус: RimLink `0.1.1` опубликован и независимо проверен 2026-08-16

## Подтверждённая исходная точка

- production nginx `/etc/nginx/sites-enabled/twitchbot` обслуживает reverse
  proxy и отдельный статический `/releases/`;
- канонический local artifact `RimLink-0.1.1.zip` имеет size `63673` и SHA-256
  `4e9656cb84b574691482938967928b0c50ad3cafd3cb7e41e79a12cb7ed42381`;
- эти значения совпадают с signed installation manifest;
- public key `shedlink-release-2026` встроен в Manager; private PEM хранится вне
  repository с user-only ACL;
- nginx backup: `/root/twitchbot.nginx.bak.20260816T123624Z`.

## Неизменяемый URL

Планируемый URL:

```text
https://shedoy23.ru/releases/RimLink-0.1.1.zip
```

Опубликованный versioned файл никогда не перезаписывается. Любое изменение
bytes требует нового release version, filename, manifest и подписи.

## Локальная подготовка

Сборка выполняется только PowerShell 7: алгоритм сжатия Windows PowerShell 5
даёт другие bytes.

```powershell
pwsh -File scripts/pack-rimlink-release.ps1 `
  -OutputPath dist/releases/RimLink-0.1.1.zip
```

Упаковщик отказывается перезаписывать существующий файл. Затем на копии
manifest выполняются generator/signer/verifier из
`docs/MANAGER_RELEASE_SIGNATURE_POLICY_V1.md`.

## Production-схема

- directory: `/srv/shedlink/releases/`;
- owner: `root:root`;
- directory mode: `0755`;
- immutable release files: `0644`;
- nginx location:

```nginx
location ^~ /releases/ {
    alias /srv/shedlink/releases/;
    autoindex off;
    limit_except GET HEAD { deny all; }
    add_header X-Content-Type-Options "nosniff" always;
    add_header Cache-Control "public, max-age=31536000, immutable" always;
}
```

Изменение применяется только через backup конфига, `nginx -t`, затем reload.
Backend и supervisor restart для статического location не требуются.

ZIP сначала загружается под временным именем, сверяется на сервере по size и
SHA-256 и только потом атомарно переименовывается в окончательный filename.

## Внешняя проверка

После публикации с отдельной машины проверяются:

1. HTTPS 200 без redirect;
2. точный `Content-Length`;
3. повторное скачивание ZIP;
4. независимый `ShedLink.Manager.VerifyRelease`;
5. совпадение public-key fingerprint;
6. отсутствие directory listing;
7. `/health` и публичные страницы backend остаются 200.

Только после этого signed manifest и public key встраиваются в Manager build и
становится доступен Install CTA.

Проверка 2026-08-16 завершена: HTTPS 200 без redirect, `Content-Length=63673`,
HTTP 404, listing 403, POST 403, server/local SHA-256 и RSA fingerprint совпали,
independent verifier зелёный, backend `/health` остался 200.

## Rollback

Если проверка не прошла, signed manifest не попадает в Manager. Временный ZIP
удаляется. Если nginx location уже был применён, восстанавливается backup
конфига, выполняются `nginx -t` и reload. Backend/DB при этом не изменяются.
