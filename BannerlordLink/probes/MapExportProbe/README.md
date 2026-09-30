# Ручной Map Data Probe — фото отключено после native crash

## v4 (30.09, Claude): карта рисуется из данных, а не снимается

Решение: живую карту кампании больше не фотографировать (второй SceneView уронил
игру, причина внутри движка не найдена). Карта для зрителей рисуется из данных,
которые игра и так отдаёт: тип поверхности навмеша, высота рельефа, поселения,
цвета фракций. Никаких рендер-объектов — это держит `SafetyContract`.

- Сетка 96 столбцов × строки по пропорции карты (Кальрадия: 96×80 = 7680 точек),
  потолок 128 строк. До 64 точек за тик в бюджете 2 мс, общий таймаут 90 с,
  прогресс в JSON раз в секунду. Точка вне суши: пробуется морской навмеш (`sea:<тип>`).
- Плюс `settlements` (id, имя, вид, координаты, фракция, её цвет, клан, у деревни —
  город) и `factions` (королевства с цветами). Это управляемые объекты, без нативных вызовов.
- `python render-map.py <probe.json>` рисует PNG рядом с JSON. Проверка:
  `python tests/test_render_map.py` (переворот оси Y, цвета, отказ на неполной сетке).
- Установка: `bash /d/shedlink-build/pending-20260930-mapprobe-v4/apply.sh` при
  ЗАКРЫТОЙ игре (сам проверяет; старая падающая DLL уходит в `dll-rollback`).
  Затем включить модуль в лаунчере, загрузить сейв, на карте консоль:
  `shedmap_probe.data confirm-data-only`, закрыть консоль, подождать ~10 с,
  `shedmap_probe.status`. Команда `capture` по-прежнему только отказывает.
- Сайт `https://shedoy23.ru/map/<логин>` (`routes/campaign_map.py`, шаблон
  `templates/campaign_map.html`, тест `tests/test_campaign_map_page.py`):
  `python build-site.py <probe.json> <out>` → `terrain.png` + `map.json`; положить их на
  сервер в `/root/twitch-extension/backend/campaign_maps/<channel_id>/` (папка по номеру
  канала, не по логину; деплой её не трогает). Рестарт для новых файлов карты не нужен,
  нужен только при первом выкате маршрута. Карта — снимок на момент выгрузки: смена
  владельцев видна после новой выгрузки.
- Живой слой (30.09): `BannerlordLink/src/Behaviors/MapLiveBehavior.cs` раз в 15 с шлёт
  `map.live_snapshot` — отряды лордов/зрителей/стримера (позиция, бойцы, армия, осада, цель),
  у городов и замков гарнизон, ополчение, осада, владелец. Сервер (`campaign_map_store.py`)
  чистит и пишет `live.json` в папку карты канала, в базу не пишет. Страница опрашивает
  раз в 15 с; отряды в городе и участники армии показаны в карточке, а не отдельным значком.
  Пакет мода: `D:/shedlink-build/pending-20260930-link-maplive` (проверяет, что в игре
  стоит ожидаемая сборка `1561af9c`). В игре не проверено: размер снимка и время сборки
  (лог `[MapLive]` пишет, если дольше 20 мс).
- **Выкат 30.09 ~21:10 (во время стрима, решение владельца):** 6 файлов бэкенда
  (`main.py`, `campaign_map_store.py`, `routes/campaign_map.py`, `templates/campaign_map.html`,
  `modules/bannerlord/_adapter.py`, `manifest.yaml`) + карта канала 98319857 из v4.
  Бэкап и откат: `/root/twitch-extension/backups/map-20260930/rollback.sh`. Проверено:
  health 200 через 2 с, `/map/shedoy23` 200, первый живой снимок — 305 отрядов (17 зрителей),
  393 поселения, 120 с гарнизоном; снимок ~148 КБ.
- Первая настоящая выгрузка (v4, 20:57): 7680 точек за 1,04 с, без вылета; 2471 точка без
  навмеша — море и непроходимые горы, различаются высотой (`SEA_LEVEL` в render-map.py).
- v5: сетка 384×322 (~124 тыс. точек, ожидаемо ~20 с), пакет
  `D:/shedlink-build/pending-20260930-mapprobe-v5`; картинка ~1536 px, 4 px на точку.
- Не проверено в игре: скорость 7680 нативных запросов и то, как выглядит море
  (навмеш может не покрывать воду — тогда оно будет «нет данных», тёмным).

Ниже — описание v3 (Codex), механика та же, изменились размер и состав выгрузки.

Это локальный диагностический кандидат Bannerlord 1.4.8. Фото не исправлено:
прежний второй SceneView на живой campaign Scene вызвал native access violation.
Подробности, ограничения штатного tableau и свидетельство:
[NATIVE_CRASH_REVIEW](NATIVE_CRASH_REVIEW.md). Кандидат не установлен.

Старая команда `shedmap_probe.capture confirm-after-stream` теперь всегда
возвращает unsupported, не создаёт задания и не расходует data-попытку.
Рендерный код удалён из кандидата; предыдущие версии сохранены в Git history.
Это защита от повторения известного опасного пути, а не исправление фотографии.

Отдельная команда `shedmap_probe.data confirm-data-only` вручную ставит одно
задание за процесс: локальный JSON identity/bounds/landmarks и сетка рельефа
16×16. Автоматического запуска, загрузки отдельной сцены, картинки, сети,
публикации на сайт или динамического автоэкспорта нет.

- Один export за процесс, включая отказ/таймаут; лишние аргументы запрещены.
- Ready guard: тот же Campaign/MapScreen/map state, не Mission/меню,
  MapScreen.IsReady и IsLoadingFinished; повторная проверка перед каждым batch.
- Всего до 256 точек, до восьми за application tick; после запроса уступает
  следующему тику при превышении бюджета 2ms. Пятиминутного/долгого обхода нет:
  общий managed timeout пять секунд. Нативный вызов этим таймером не прервать.
- Сетка включает границы карты; row-major, X и Y возрастают в игровых координатах.
  Строка 0 у minY. Grid не переворачивает Y; это должен учитывать будущий viewer.
- Height/normal API и navmesh face/type используются только для чтения.
  Invalid face и отсутствующая высота сохраняются как null. Surface — тип
  land navmesh, а не текстура/точная береговая линия/маска воды.
- Основная камера, SceneView, lighting, visibility, entities и сейвы не меняются.
  Нет Camera/SceneView/Texture allocation, primary-view readiness calls,
  native clear/release/invalidation или GPU cleanup. Borrowed Scene только читается.
- Native queries по полной сетке ещё не проверены в игре. Data-only снижает
  конкретный риск дополнительного рендера, но не обещает отсутствие любых native crashes.

Выход: `%LOCALAPPDATA%\ShedLink\MapExportProbe\<UTC-GUID>\probe.json`.
Schema `shedlink.map-data-probe.v1`; revision `native-crash-photo-blocked.v3`.
JSON содержит mode=data-only/photoSupported=false, этап, очередной индекс batch,
количество завершённых точек, ошибки и raw coordinates. PNG не создаётся.
`runtimeValidated=false` сохраняется: успешное выполнение не доказывает географию.

## Только локальная сборка и offline checks

```powershell
pwsh -NoProfile -File .\build-probe.ps1 -ConfirmBuild
pwsh -NoProfile -File .\tests\run-contract.ps1 -ConfirmTests -ProbeDll .\bin\Win64_Shipping_Client\ShedLink.MapExportProbe.dll
```

Одна direct Roslyn compilation, net472/x64, `/parallel-`, без MSBuild/restore,
compiler server, hooks, install/autodeploy/postbuild. Outputs только рядом с probe.
Offline harness читает managed IL и вызывает лишь команды/чистый координатный helper:
не создаёт module instance, не выполняет application ticks и не запускает игру.
[Проверки и хеш кандидата](VALIDATION.md).

## Следующий шаг — пока не выполнять

Модуль оставлять отключённым. Нужен новый сигнал об установке при закрытой игре;
заменять только DLL/XML probe по манифесту, сохраняя обновлённый автопилот.
После обычной загрузки для отдельно разрешённой проверки на готовой, сохранённой,
поставленной на паузу global map: одна команда `shedmap_probe.data confirm-data-only`.
Закрыть console, ждать минимум шесть секунд. Проверить итог/256 samples/координаты
и landmarks в JSON. При отказе/таймауте остановиться; повторов/фото-команды нет.
`shedmap_probe.status` показывает состояние; `shedmap_probe.cancel` отменяет data.
Без нового разрешения нет установки, запуска, вмешательства или загрузки новой Scene.
