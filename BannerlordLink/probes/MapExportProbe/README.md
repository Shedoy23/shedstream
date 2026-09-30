# Ручной Map Export Probe — эксперимент для Bannerlord 1.4.8

Этот отдельный необязательный модуль проверяет доступ к текущей карте и одну
попытку ортографического снимка 256×256. Обычный BannerlordLink не меняется.
Основа: `Shedoy23/shedstream/main`, `7e382b1ca648a2719206f5ba2bec680ca557ca4f`.
В процессе подготовки модуль **не устанавливается и не запускается**.

## Ограничения

- Экспорт выключен до точной ручной команды с подтверждением. Одна принятая
  попытка на процесс, включая отказ/таймаут; загрузка сейва не сбрасывает лимит.
- Нет Harmony, сетевых запросов, автоматического campaign behaviour,
  горячих клавиш, автоэкспорта мира или связи с сайтом.
- Основная камера, entities, visibility и освещение общей сцены не меняются.
  Изображение может содержать игровые party meshes; они не скрываются.
- Отдельный SceneView получает собственные camera, color/depth targets.
  Он включается между двумя application ticks, а затем выключается.
  Это **одна возможность рендера**, не доказательство, что движок обработает её.
- Ready checks: campaign/map state, отсутствие Mission/меню, тот же MapScreen,
  IsReady, загрузка сцены, готовность штатного вида и собственного вида.
  Во время попытки смена карты/кампании отменяет работу.
- Каждый этап ожидания ограничен пятью реальными секундами между тиками.
  Этот watchdog не может прервать зависший нативный вызов или остановленный
  application loop. Managed catch не защищает от native crash.
- Cleanup выключает собственный вид и вызывает `AddClearTask(true)`
  (**только этот view**); спустя четыре application ticks отдаёт owned references
  через `ManualInvalidate`/`Texture.Release`. На unload ticks не гарантированы,
  поэтому references отдаются сразу после постановки clear task.
  Заимствованная Scene не очищается/не освобождается. Нет принудительного
  уничтожения camera, `ReleaseImmediately`, глобального GPU release или GC.
  `NativeObject.ManualInvalidate` статически проверен: снижает refcount один раз
  и исключает повторное снижение финализатором. Реальный native task/GPU lifecycle
  всё ещё требует наблюдения после стрима.

## Что сохраняется локально

Фиксированный корень `%LOCALAPPDATA%\ShedLink\MapExportProbe`, внутри новая
папка UTC+GUID для каждой попытки. Пользовательский output path не принимается.

`probe.json`: campaign id, тип wrapper, имя и module path сцены, active modules,
XML/navmesh CRC, campaign/scene bounds, камера, до пяти landmarks
(main party, первое town/village/hideout, центр bounds), высоты и валидные
land/sea navmesh types, итог/исключения/cleanup. Нет hardcoded городов.
`borderMaxMarkerZ` — Z маркера границы, не максимальная высота рельефа.

`snapshot.png`: только если движок сохранит файл. JSON подтверждает наличие PNG
лишь после проверки signature, стабильного размера и декодирования 256×256.
Назначение native filename/path API, полнота рельефа, географическое соответствие,
culling, отсутствие влияния второго вида на игровой кадр/производительность
**runtime не проверены**. При отказе получается JSON без выдуманного изображения.
Имена с двойным `.png` принимаются только в собственной уникальной папке.

Не использовать CRC как полный hash модового мира: он не доказывает неизменность
terrain/текстур. Этот probe не строит production `mapId` и не задаёт фильтрацию
зрителям. Физические material arrays не читает: campaign loader их инвалидирует.
Сцена не загружается вторым экземпляром; всего несколько контрольных запросов.

## Компиляция: отдельно от игры

```powershell
pwsh -NoProfile -File .\build-probe.ps1 -ConfirmBuild
```

Скрипт напрямую вызывает установленный Roslyn (`SDK 9.0.310`) с reference pack
net472 и DLL установленной игры. Один source, `/parallel-`, без compiler server,
MSBuild imports, restore, project references, pre/postbuild/deploy targets.
`bin/Win64_Shipping_Client` и `build-evidence` создаются только рядом со скриптом.
Нет команды установки. При другой машине сначала проверить/обновить пути входов.

## После стрима — пока НЕ выполнено

1. Дождаться окончания стрима; игру закрывает сам владелец. Не заменять
   установленный BannerlordLink общей сборкой ради этого эксперимента.
2. Проверить успешную компиляцию и hash DLL из `build-evidence`.
3. При закрытой игре вручную создать отдельный
   `<game>/Modules/Shedoy23.MapExportProbe`, скопировать **только** этот
   `SubModule.xml` и `bin/Win64_Shipping_Client/ShedLink.MapExportProbe.dll`.
   Не копировать game DLL dependencies. Этот документ ничего не устанавливает.
4. В launcher вручную выбрать диагностический модуль после Sandbox; проверить,
   что обычный набор модов не изменился. Запустить игру обычным способом.
5. Загрузить campaign на глобальной карте, закрыть игровые меню, дождаться полной
   загрузки. Открыть встроенную developer console обычным способом; если console
   недоступна, остановиться и отдельно согласовать её включение. Probe не меняет
   `engine_config.txt`, cheat mode или другие настройки.
6. Только после стрима ввести:
   `shedmap_probe.capture confirm-after-stream`, закрыть console и оставаться
   на карте не менее 15 секунд. `shedmap_probe.status` показывает очередь/итог,
   а **не** гарантированный снимок. `shedmap_probe.cancel` просит отмену.
7. Проверить JSON: ready/identity/bounds/landmarks, итог, cleanup errors.
   Если есть PNG, проверить вручную ориентацию/покрытие и совпадение нескольких
   landmark coordinates. Сравнить игровой кадр/камеру до и после; проверить
   отсутствие заметной задержки и ошибок. Валидный PNG может оказаться пустым.
8. При неуспехе сохранить JSON/лог; не запускать автоматически другую стратегию.
   Native сохранение/render lifecycle — гипотеза до этого прогона.
9. По окончании эксперимента при закрытой игре отключить диагностический модуль
   в launcher. Сейв не содержит добавленных behaviours/data.

## Статическое основание

Исследованы local DLL v1.4.8, Steam build 24573425/revision 119303:
`Campaign.MapSceneWrapper`, `MapScreen.Instance.MapScene`, Scene bounds/height/CRC,
Camera.SetViewVolume, SceneView и унаследованные View save/target методы.
Console attribute и `CollectCommandLineFunctions` public, ищут команды в загруженных
сборках с reference на TaleWorlds.Library. Фактическая регистрация в launcher
с выбранным отдельным модулем всё ещё требует runtime проверки.

Штатный `SceneLayer` по умолчанию делает `ClearAll(true,true)` при finalize;
его здесь намеренно нет. Прототип — собственный код, игровые assets/чужой
TOR Live Map код не скопированы. Статическая проверка не заменяет live evidence.
