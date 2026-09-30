# Проверка кандидата 2026-09-30

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
