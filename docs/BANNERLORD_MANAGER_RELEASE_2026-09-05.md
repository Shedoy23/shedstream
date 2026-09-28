# Bannerlord 0.1.2 / Manager alpha.15 — выпуск

Дата проверки: 2026-09-05. Статус: **опубликовано по версионным адресам, HTTPS-проверка пройдена**.

## Что подготовлено

BannerlordLink 0.1.2 содержит текущую DLL под установленную Bannerlord 1.4.8.
Старый релиз 0.1.1 и его контракт для 1.3 сохранены. Новый манифест допускает
семейство 1.4 согласно существующему major.minor контракту Manager; фактически
наблюдалась только 1.4.8, остальные patch-версии не проверены.

Manager получил номер alpha.15: alpha.14 уже существует локально и содержит
RimLink 0.1.2. Существующий ZIP alpha.14 не перезаписывался.

| Артефакт в `dist/releases/` | Байт | SHA-256 |
|---|---:|---|
| `BannerlordLink-0.1.2.zip` | 221549 | `4cfb8de99d657a2c1cf9a3b9e993dc31d53bbab79f8ad9b2bc2061852e771eda` |
| `ShedLink.Manager-0.1.0-alpha.15-win-x64.zip` | 67864877 | `ae4245fb7e95403ccc528c59d049352dcd85d604b66825fbe68e64ef22dc02da` |

Manager собран штатным `scripts/package-manager-alpha.ps1 -Version
0.1.0-alpha.15` из чистого коммита `b7afa0fe61ad` в ветке
`codex/bannerlord-0.1.2-release`, отдельная рабочая копия
`C:/Users/Edward/Desktop/work-manager-alpha15`. В основном рабочем дереве
сохранены изменения остальных задач; в релизный коммит они не включены.

## Доказательства

- `ShedLink.Manager.VerifyRelease`: размер, SHA-256, RSA-PSS, безопасная
  распаковка и обязательные health paths Bannerlord 0.1.2 прошли.
- Ключ `shedlink-release-2026`, публичный fingerprint:
  `17e6043cca11dcb9f4230d5a91325e9d5d52ba9a29bb4cc4a6ffb51618001541`.
  Использован публичный ключ; повторная подпись уже подписанного архива не нужна.
- ZIP содержит ровно SubModule.xml, BannerlordLink.dll и BLinkHeroNametag.xml.
  Каждый файл совпал с рабочим деревом; конфиг с токеном отсутствует.
- Повторная Release-сборка Bannerlord в отдельный output: 0 ошибок,
  0 предупреждений; DLL побайтно совпала с архивной. SHA-256 DLL:
  `c33c4bc523e15d2360d53de124b3c078c9bd692fb39727028c650d1e7b2bce40`.
- `CoreReliabilityHarness`: 133 assertions, exit 0.
- `ShedLink.Manager.Core.SelfTest`: exit 0, включая новые проверки реального
  каталога: игра 1.4.8 выбирает 0.1.2, 1.3.15 выбирает 0.1.1, 1.5.0 отклоняется.
- `scripts/test-installation-manifests.py`: exit 0. Новый манифест отдельно
  прошёл JSON Schema. Pre-commit consistency gate релизного коммита пройден.
- Готовый ZIP Manager проверен отдельно: шесть манифестов совпадают с source
  commit и `RELEASE.json`, hash EXE совпадает, debug-файлов и private PEM нет.
- В `dist/release-evidence/bannerlord-0.1.2-20260905/` сохранены
  `verification.json` и `bannerlord-working-tree.patch`: DLL собрана из
  незакоммиченных изменений Bannerlord относительно `654b84b`, а не из
  чистого Manager-коммита. Это явно различённые источники.

## Известные ограничения

Общий `scripts/validate-installation-manifests.py` **падает** на существующих
bannerlord-0.1.1 и shedcolony-0.1.0/0.1.1: JSON Schema отстала от каталога.
Новый bannerlord-0.1.2 валиден. Этот дефект не скрыт пропуском проверки:
он внесён в H4 hardening-плана; опубликованные старые контракты здесь не менялись.

Подпись защищает payload артефакта (идентичность, версия, размер, hash),
а не весь JSON манифеста. `supported_versions` не является подписанным полем.
Новый игровой прогон и чистая установка R3 в этой сессии не выполнялись.

## Публикация 05.09

Владелец подтвердил выпуск. Загружены Bannerlord 0.1.2, Manager alpha.15
и необходимый ему RimLink 0.1.2 (последнего ещё не было на сервере).
Артефакты сначала помещены в закрытую staging-папку, проверены на сервере
по размеру и SHA-256, затем опубликованы атомарным hard link с отказом
при занятом имени. Старые файлы не перезаписывались; staging удалён.

Дополнительный артефакт `RimLink-0.1.2.zip`: 64145 байт, SHA-256
`c474f0308ad4ddf2a31454618dac88eb721c6d578b59c38922915477bbb611cd`.

Все три ZIP повторно скачаны по HTTPS без редиректов: HTTP 200,
Content-Length и SHA-256 совпали. Скачанные Bannerlord и RimLink прошли
`VerifyRelease` с доверенным публичным ключом. У скачанного Manager проверены
EXE и шесть манифестов по `RELEASE.json`; source commit — `b7afa0fe61ad`.
`/health` и `/privacy.html` — 200, листинг `/releases/` — 403.
Машинный след: `dist/release-evidence/bannerlord-0.1.2-20260905/publication.json`.

Адреса:

- https://shedoy23.ru/releases/BannerlordLink-0.1.2.zip
- https://shedoy23.ru/releases/RimLink-0.1.2.zip
- https://shedoy23.ru/releases/ShedLink.Manager-0.1.0-alpha.15-win-x64.zip

## Что остаётся отдельно

Постоянная ссылка `/download/manager` проверена: пока отвечает 302 на
alpha.12. Публикация версионных ZIP не меняет её и канал автообновления.
Переключение ссылки требует отдельного изменения backend; в этом выпуске
backend не менялся и не перезапускался. До переключения alpha.15 доступна
по прямому адресу выше.

Чистая установка R3 и живой ACK остаются непроверенными этой сессией.
