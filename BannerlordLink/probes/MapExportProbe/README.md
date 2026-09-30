# Ручной Map Data Probe — фото отключено после native crash

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
