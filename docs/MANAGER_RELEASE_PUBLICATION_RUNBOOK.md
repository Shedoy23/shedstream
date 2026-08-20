# Manager release publication runbook

Дата: 2026-08-16  
Статус: RimLink `0.1.1` и BannerlordLink `0.1.0` опубликованы и независимо
проверены 2026-08-16

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

BannerlordLink `0.1.0` выпущен тем же контрактом: `218775` bytes, SHA-256
`2f5e431e…cf43416a`, HTTPS 200 без redirect, HTTP 404, listing/POST 403,
независимый verifier зелёный, `/health` 200. Evidence:
`docs/BANNERLORD_MANAGER_RELEASE_2026-08-16.md`.

## Выпуск 2026-08-19 — BannerlordLink 0.1.1 и ShedColony 0.1.0

Опубликованы тем же контрактом, по явному подтверждению владельца.

| Файл | Размер | SHA-256 |
|---|---|---|
| `BannerlordLink-0.1.1.zip` | 218885 | `58ce59857731273c64d4555c958876bef98fd77aeb3207f33a8080c926747c92` |
| `ShedColony-0.1.0.zip` | 49366 | `e1b270492c0bace8eefee8b871b9f49b9f39c95c2098df5cbdb5600b44cd9786` |

Порядок: загрузка под именами `.upload-*` → сверка size и SHA-256 НА СЕРВЕРЕ →
`chown root:root`, `chmod 0644` → `mv -n` в окончательное имя с явным отказом,
если имя занято. Ранее опубликованные `RimLink-0.1.1.zip` и
`BannerlordLink-0.1.0.zip` не тронуты (размеры и даты прежние).

Внешняя проверка после публикации:

```text
BannerlordLink-0.1.1.zip  https 200, redirects=0, Content-Length 218885, application/zip
ShedColony-0.1.0.zip      https 200, redirects=0, Content-Length 49366,  application/zip
скачанные SHA-256         совпали с локальными и с манифестами
independent verifier      VERIFIED × 2, exit 0 — против манифестов, взятых
                          ИЗ пакета Manager alpha.8, и артефактов, скачанных с прода
fingerprint               17e6043cca11dcb9f4230d5a91325e9d5d52ba9a29bb4cc4a6ffb51618001541
http://…                  404 (закрыт)
/releases/ listing        403
POST на файл              403
/health                   200
```

Backend обновлён отдельно (`deploy.ps1 -Backend`): гейт критических тестов
107/0, `Migrations complete`, `Modules discovered: ['bannerlord','rimworld',
'shedcolony']`, сервис RUNNING, публичные страницы 200, чат-бот переподключился,
после старта ноль traceback. Фронт расширения не деплоился — он заблокирован
флагом `$FrontendReviewOpen` на время ревью `0.0.2`.

Что этим НЕ доказано: живая установка обеих игр Manager'ом. См.
`docs/MANAGER_MULTIGAME_PREFLIGHT_2026-08-19.md` §10.

## Выпуск 2026-08-20 — ShedLink Manager alpha.10

Manager впервые опубликован по постоянному адресу — до этого он передавался из
рук в руки, и первая ступень воронки была недостижима в принципе.

```text
https://shedoy23.ru/releases/ShedLink.Manager-0.1.0-alpha.10-win-x64.zip
size    67853805
SHA-256 d4ea262c9800009bc7b18850948228861230d12a35b32d091226ebbe5613d3c3
```

Тем же контрактом: загрузка под `.upload-`, сверка размера и SHA-256 НА
СЕРВЕРЕ, `mv -n` с отказом при занятом имени. Внешняя проверка: HTTPS 200 без
редиректов, `Content-Length` точный, скачанный файл совпал по SHA-256, HTTP
404, листинг 403. Три мода рядом не тронуты.

**Ссылка версионная и не станет «последней».** Опубликованный файл неизменяем;
новая сборка — новое имя. Постоянной ссылки `latest` СОЗНАТЕЛЬНО нет: она
означала бы перезапись, а это ровно то, от чего защищает контракт. Ссылку на
свежую версию давать руками либо со страницы, когда фронт разморозят.

**Чего у файла нет:** подписи. Windows покажет SmartScreen при первом запуске —
это ожидаемо и записано в R3; для незнакомого человека это первая преграда, и
именно её теперь видно в воронке как разрыв «скачали, но не запустили».

### Подсчёт скачиваний

`scripts/ingest-download-events.py` разбирает журнал nginx и кладёт события
`manager_downloaded` в воронку. Запуск на сервере:

```bash
cd /root/twitch-extension && python3 scripts/ingest-download-events.py --db backend/viewers.db
```

Идемпотентен: прогресс лежит в `backend/viewers.db.download-ingest-state`,
обрабатываются только записи строго новее. Повторный прогон проверен — не
удваивает. IP-адреса не сохраняются.

**Первые две записи в воронке — мои проверочные скачивания 20.08 03:40 и
03:42.** Не вычищал: выкидывать неудобные данные хуже, чем объяснить их.

**Не автоматизировано:** скрипт никем не вызывается по расписанию. Пока
запускать руками перед тем, как смотреть воронку. Cron — решение владельца,
это постоянная настройка прода.

## Rollback

Если проверка не прошла, signed manifest не попадает в Manager. Временный ZIP
удаляется. Если nginx location уже был применён, восстанавливается backup
конфига, выполняются `nginx -t` и reload. Backend/DB при этом не изменяются.
