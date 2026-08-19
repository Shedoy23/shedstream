# Предвыпускная проверка мульти-игрового Manager — 2026-08-19

Повторная независимая проверка перед публикацией BannerlordLink `0.1.1` и
ShedColony `0.1.0`. Публикация на прод на момент написания **не выполнена**:
ждёт явного «да, выкатывай» от владельца.

Проверял: сессия 19.08 (не та, что собирала артефакты). Всё судится по коду
возврата, а не по печати.

## 1. Исходное состояние

- рабочее дерево чистое, `main` == `afterlait/main`, HEAD `468494d`;
- чужих незакоммиченных правок нет — предыдущая сессия всё закоммитила.

## 2. Артефакты — совпадение с заявленным

| Файл | Размер | SHA-256 | Совпал с брифом |
|---|---|---|---|
| `dist/releases/BannerlordLink-0.1.1.zip` | 218885 | `58ce5985…26747c92` | да |
| `dist/releases/ShedColony-0.1.0.zip` | 49366 | `e1b27049…44cd9786` | да |
| `dist/releases/ShedLink.Manager-0.1.0-alpha.8-win-x64.zip` | 67851512 | `1e8cba10…21ce3180` | да |

## 3. Состав архивов — чисто

`BannerlordLink-0.1.1.zip` — ровно три файла: `SubModule.xml`,
`bin/Win64_Shipping_Client/BannerlordLink.dll`, `GUI/Prefabs/BLinkHeroNametag.xml`.
Ни `config.json`, ни PDB, ни исходников, ни ключа.

`ShedColony-0.1.0.zip` — один `shedcolony-0.1.0.jar` (22 записи внутри: только
классы `ru/shedoy/shedcolony/*`, `assets/shedcolony/lang/en_us.json`,
`META-INF/neoforge.mods.toml`). **Код MineColonies внутрь не попал** — только
ссылки на её API в дескрипторах классов, что и должно быть.

Отдельный скан обоих архивов (включая содержимое JAR) на `slmod_v1…`,
`oauth:…`, `-----BEGIN … PRIVATE KEY` — находок нет.

## 4. Подписи

```text
VERIFIED bannerlord 0.1.1   exit 0
VERIFIED shedcolony 0.1.0   exit 0
KEY_ID=shedlink-release-2026
PUBLIC_FINGERPRINT_SHA256=17e6043cca11dcb9f4230d5a91325e9d5d52ba9a29bb4cc4a6ffb51618001541
```

Проверено **дважды и по-разному**:

1. манифесты из репозитория (`manifests/installation/*.json`) против локальных ZIP;
2. **манифесты, физически лежащие внутри собранного Manager alpha.8**, против
   тех же ZIP — то есть ровно те байты, которыми будет пользоваться стример.
   Они отличаются от репозиторных только переводами строк, JSON идентичен,
   и обе копии проходят проверку.

Public key, встроенный в `ReleaseConfiguration.cs`, побайтово совпадает с
`%LOCALAPPDATA%\ShedLink\release-keys\shedlink-release-2026.public.pem`, его
отпечаток равен тому, что назвал верификатор. Цепочка «что доверяет Manager —
что подписало архивы» замкнута. Приватный ключ не открывался и не копировался.

## 5. Прогоны

| Проверка | Код возврата |
|---|---|
| `ShedLink.Manager.Core.SelfTest` (Release) | 0 |
| `dotnet build ShedLink.Manager.App -c Release` | 0, предупреждений 0 |
| `python scripts/run-backend-tests.py` — весь набор | 0, **51 из 51** |
| `python scripts/lint_consistency.py` | 0 |

**Ловушка машины, стоившая ложного красного:** запуск теста напрямую
(`python tests/test_manager_pairing_http.py`) падает с `UnicodeEncodeError` в
cp1251 ещё до начала проверок — это не регрессия. Запускать через
`scripts/run-backend-tests.py`, он ставит `PYTHONIOENCODING=utf-8`.

## 6. Новый тест: серверный сценарий готовности для трёх игр

`Расширение/backend/tests/test_manager_diagnostics_multigame.py` — 13 проверок,
exit 0. Раньше сценарий «Проверить готовность» был покрыт **только для
RimWorld**, хотя идёт тремя разными путями.

Что зафиксировано:

- **Bannerlord** — пока мод молчит, отказ `module_offline`; с живым модом
  команда `diagnostic_ping` ложится в общую очередь `module_actions` с
  префиксом `manager_`, коннектор забирает её обычным long-poll'ом,
  положительный ACK даёт «готово», отрицательный — «не готово» (без возврата:
  цена действия 0). Учебные режимы `refuse`/`lost_ack` честно отвечают
  `diagnostic_mode_not_supported`, а не притворяются выполненными.
- **ShedColony** — без heartbeat готовность НЕ подтверждается; с живым
  авторизованным heartbeat строка сразу `acked`, **и команда в очередь не
  кладётся вообще**.

Красным тест видели: возврат исторического дефекта (список поддерживаемых
модулей сузили обратно до `{"rimworld"}`) даёт exit 1 и называет симптом —
`получено: 409 diagnostic_not_supported`. После отката — exit 0, `git status`
по `routes/manager.py` чист.

## 7. Честно про ShedColony: что означает зелёная галочка

Опубликованный `shedcolony-0.1.0.jar` **не умеет** `diagnostic_ping`. Поэтому
для Minecraft «Проверить готовность» доказывает не «мод исполнил команду», а
«мод жив, авторизован и разговаривает с бэкендом». Это слабее, чем у Bannerlord
и RimWorld.

Компромисс сознательный и записан в коде (`routes/manager.py`) и в тесте. Как
только в JAR появится настоящий ping — тест обязан покраснеть на проверке «в
очередь не кладётся», и контракт надо будет переписать вместе с текстом,
который видит стример.

## 8. Целевые URL свободны

```text
https://shedoy23.ru/releases/RimLink-0.1.1.zip        200  Content-Length 63673
https://shedoy23.ru/releases/BannerlordLink-0.1.0.zip 200  Content-Length 218775
https://shedoy23.ru/releases/BannerlordLink-0.1.1.zip 404
https://shedoy23.ru/releases/ShedColony-0.1.0.zip     404
```

Публикация ничего не перезапишет. Уже выложенные версии остаются на месте.

## 9. Провенанс Manager alpha.8

`RELEASE.json` внутри пакета: `source_commit 468494d5a95b`, что равно HEAD на
момент проверки, `built_at_utc 2026-08-19T18:22:07Z`, sha256 исполняемого файла
записан. Пересборка ради провенанса не нужна: пакет собран из чистого коммита.
Коммиты этой сессии (тест + документация) кода Manager не трогают.

## 10. Что НЕ проверено — и без этого Minecraft нельзя объявлять готовым

- **Живая проверка Bannerlord** (Manager видит heartbeat, «Проверить
  готовность» проходит, в логе мода есть ping, бэкенд фиксирует ACK) — нужна
  запущенная игра, руки владельца.
- **Живая проверка Minecraft** с настоящим NeoForge 1.21.1 и MineColonies:
  установка только `shedcolony-0.1.0.jar`, соседние JAR байт-в-байт целы,
  `config/shedcolony.json` создан без утечки токена в отчёты, удаление
  ShedColony не трогает MineColonies, Technical Ready по реальному heartbeat.
- **Совместимость `shedcolony-0.1.0.jar` с актуальной MineColonies** — не
  подтверждена ничем, кроме компиляции. Если на живой проверке heartbeat не
  появится, релиз Minecraft останавливается, причина называется прямо.
- Матрица R3 целиком на чистой Windows.

## 11. Вывод

К публикации готово по всем машинным критериям. Публикация не выполнена: по
правилу проекта прод трогается только после явного «да, выкатывай». После
выкладки — внешняя проверка по
`docs/MANAGER_RELEASE_PUBLICATION_RUNBOOK.md` §«Внешняя проверка», затем живые
проверки из §10, и только потом Minecraft можно называть готовым.
