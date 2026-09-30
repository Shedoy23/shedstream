# Проверка кандидата 2026-09-30

## После native crash: фото заблокировано, локальный data-only кандидат

Первый enable-before-readiness кандидат был установлен позже и вызвал native AV.
Разбор фактов и пределов выводов: [NATIVE_CRASH_REVIEW](NATIVE_CRASH_REVIEW.md).
Точный native root cause не установлен; это НЕ исправление фотографического рендера.

Фото-команда отказывает без очереди/расхода попытки. Camera/SceneView/Texture,
primary-renderer calls и native cleanup исключены из этой версии. Отдельная
manual data-команда: 256 точек, максимум восемь за tick, бюджет 2ms между запросами,
managed timeout пять секунд, map/cancel guards. [Актуальная инструкция](README.md).

Offline contract закоммичен до исправления (`06ae30a0`): на прежней DLL `5526ABA0…`
**5 проверок / 5 FAIL, exit 1**. После исправления **14 проверок / 0 FAIL, exit 0**.
Проверены выполнение бывшей capture-команды, отсутствие постановки render work,
граница renderer API по скомпилированному IL, отдельное подтверждение data,
лишние аргументы/one-shot/cancel, endpoints/world-Y/nonfinite/index bounds.
Не выполнялись game ticks, module instance или native calls. Это не renderer test.
Первый harness-прогон выявил недостающий managed resolver для Native module DLL;
после добавления resolver красный прогон завершился ожидаемым ненулевым кодом.

Direct Roslyn compile net472/x64, один source, `/parallel-`, `/warnaserror+`:
**exit 0**, diagnostics нет. Local DLL SHA256:
`0B751D94AE5318E28965757575F61823F68B9C8743DDB834D7EB2C192B64D1B3`.
`SubModule.xml`: v0.0.2, название явно сообщает photo disabled, прежний Module Id.
System.Drawing reference исключена. Targets прочитаны; MSBuild/imports/restore/
autodeploy/game outputs отсутствуют. `git diff --check`: exit 0.

Новый кандидат не установлен. Installed DLL после работы остаётся `5526ABA0…`;
пользователь отключил модуль. Автопилот/игра/конфиги/сейвы не менялись.
Installed SceneTableau отдельно прочитан точечной декомпиляцией, без запуска сцены.
Data grid native queries ещё runtime-unverified. Следующий тест только по новому
сигналу после установки при закрытой игре; никаких photo capture/автоповторов.

Ниже — исторические проверки предыдущих кандидатов.

## Исправление после первого runtime timeout — только локально

Первый установленный кандидат дал JSON с bounds/landmarks и `phase_timeout`,
PNG отсутствует. Точный JSON и прежняя DLL сохранены локально, хеши и причинный
разбор: [TIMEOUT_DIAGNOSIS](TIMEOUT_DIAGNOSIS.md). Это исходное воспроизведение
ошибки до исправления; фиктивного offline теста нативного renderer нет.

Исправление: owned view включён с save=false до readiness checks; минимум пять
engine frames прогрева; ReadyToRender AND CheckSceneReadyToRender; окно сохранения
до продвижения engine frame. JSON содержит revision, этап сбоя, секунды/тики,
engine frame номера и последние результаты готовности. Scene/camera/targets,
one-shot и область cleanup сохранены.

`pwsh -NoProfile -File build-probe.ps1 -ConfirmBuild`: **exit 0**, net472/x64,
один source, `/parallel-`, `/warnaserror+`, installed 1.4.8; diagnostics нет.
Local corrected DLL SHA256:
`5526ABA0CDC810CB8D00D08064CA88CAD06A1D00914E007521E50C6E898E352B`.
Полная сборка/пакетные тесты не запускались. Windows PowerShell сначала отказал
из-за execution policy; запуск штатным доступным `pwsh` прошёл без смены политики.

`git diff --check`: exit 0. Installed probe DLL прочитана и остаётся с SHA256
`1A6572682EFCBD2A821743D5762D627E45B91DBA233C3768A4C7180E52E4A193`.
Корректированная DLL не устанавливалась; игру не трогали, capture не повторяли.
GPU completion, сохранение/содержимое PNG и cleanup новой версии ещё не проверены.
Установка/следующий запуск требуют нового отдельного сигнала и обычной загрузки
новой DLL при закрытой игре; горячей замены нет.

## Историческая проверка первоначального кандидата

База из свежего fetch `Shedoy23/shedstream/main`:
`7e382b1ca648a2719206f5ba2bec680ca557ca4f`.
Отдельный clone/ветка `prototype/bannerlord-map-export-probe`; dirty worktrees
не использовались. Изменения ограничены probe и ссылками передачи работы.

- Direct Roslyn compile `build-probe.ps1 -ConfirmBuild`: **exit 0**.
  Один source net472/x64, `/parallel-`, `/warnaserror+`, установленные DLL 1.4.8;
  compiler diagnostics отсутствуют. Полная сборка Link/MSBuild не запускалась.
- SHA256 локального `ShedLink.MapExportProbe.dll`:
  `1A6572682EFCBD2A821743D5762D627E45B91DBA233C3768A4C7180E52E4A193`.
  Локальные compiler log/response/hash: игнорируемая папка `build-evidence`.
- `SubModule.xml` прочитан XML parser; отдельный Id `Shedoy23.MapExportProbe`,
  `DefaultModule=false`. Entry point совпадает с C# классом.
- `git diff --check`: exit 0 до коммита.
- Статический просмотр: точная команда подтверждения и Interlocked one-shot;
  game API вызывается только из application tick/unload; readiness и five-second
  phase timeouts; absolute LocalAppData output; PNG signature/decode/dimensions;
  shared Scene borrowed, отдельные camera/view/targets; собственный view выключается
  на следующем тике; cleanup scope не включает shared scene или основную камеру.
- Lifecycle основан на точечной декомпиляции `NativeObject`, `Texture`, `View`,
  `SceneView`, `SceneLayer`, а не утверждении о всех native/render call sites.
  Нативное исполнение/GPU cleanup и успешность одного render opportunity не доказаны.

Game/console/renderer не запускались, runtime tests отсутствуют.
PNG/JSON игрового прогона ещё нет. Нет install, push, deploy, окна игры не трогались.
Следующие ручные шаги и критерии проверки описаны в [README](README.md).

Поиск существующей документации по SceneView/MapScene/export не нашёл готового
workflow в `docs`/`Расширение/docs`; прочитаны AGENTS/CLAUDE/LESSONS,
CONTEXT_BANNERLORD, BANNERLORD_DEV_ENV и TESTING_PLAYBOOK. Старый DEV_ENV местами
описывает 1.3.15 и сборку в игровой папке; для этой задачи это не применялось.
