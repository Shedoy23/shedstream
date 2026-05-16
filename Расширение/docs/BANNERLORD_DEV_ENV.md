# Bannerlord Mod Dev Environment Setup

**Target:** Bannerlord 1.3.15 (.NET Framework 4.8)
**Game path:** `X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord`
**Editor:** VS Code (стандарт для тех кто привык; VS 2022 — альтернатива)

---

## 1. Зависимости (~1.6 GB на диске суммарно)

### 1.1 .NET Framework 4.8 Developer Pack (~70 MB)

Скачать: https://dotnet.microsoft.com/download/dotnet-framework/net48

Содержит:
- Targeting pack (заголовки)
- Reference assemblies
- MSBuild props/targets для NET48

### 1.2 Visual Studio Build Tools 2022 (~1.5 GB)

Это **НЕ полный VS** — только msbuild + C# compiler без UI / debugger /
Solution Explorer / etc. Достаточно для `msbuild .csproj` из терминала.

Скачать: https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022

В установщике выбрать workload:
- ☑ **«.NET desktop build tools»** (включает MSBuild + Roslyn + .NET 4.8 targeting)

Не нужно (cuts ~3 GB):
- ☐ Web development
- ☐ Mobile development
- ☐ Game development with Unity
- ☐ Visual Studio IDE itself

После установки — `msbuild` появится в PATH:
```cmd
where msbuild
> C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\msbuild.exe
```

### 1.3 VS Code C# extensions

В VS Code:
1. `Ctrl+Shift+X` → marketplace
2. Установить:
   - **C# Dev Kit** (ms-dotnettools.csdevkit) — главный C# extension
   - **C#** (ms-dotnettools.csharp) — language server (auto-installed вместе с Dev Kit)

Перезапустить VS Code.

---

## 2. Environment variable

**КРИТИЧНО:** csproj ссылается на TaleWorlds DLL через
`$(BANNERLORD_GAME_DIR)`. Установить env var:

```cmd
setx BANNERLORD_GAME_DIR "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord"
```

Закрыть и перезапустить shell (включая VS Code — `setx` берётся только на старте процесса).

Verify:
```cmd
echo %BANNERLORD_GAME_DIR%
> X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord
```

---

## 3. Открыть проект в VS Code

```cmd
cd C:\Users\Edward\Desktop\work\.claude\worktrees\tender-tharp-fc29e6
code BannerlordLink
```

VS Code откроет папку. C# Dev Kit auto-detect .csproj в `src/`. Если нет
— right-click на `BannerlordLink.csproj` → «Open Folder as Solution» (или
вручную через Command Palette).

---

## 4. Первый билд

В терминале VS Code (`Ctrl+`` ` ``):

```cmd
cd src
msbuild BannerlordLink.csproj /p:Configuration=Debug
```

Что должно произойти:
1. msbuild читает .csproj
2. Резолвит `$(BANNERLORD_GAME_DIR)` → реальный путь
3. Компилирует BannerlordLinkModule.cs → BannerlordLink.dll
4. Кладёт в `<GAME>\Modules\BannerlordLink\bin\Win64_Shipping_Client\BannerlordLink.dll`

Verify:
```cmd
dir "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\BannerlordLink\bin\Win64_Shipping_Client\"
> BannerlordLink.dll
> BannerlordLink.pdb
```

Также скопировать SubModule.xml в game:
```cmd
mkdir "X:\SteamLibrary\...\Modules\BannerlordLink\_Module"
copy BannerlordLink\_Module\SubModule.xml ^
     "X:\SteamLibrary\...\Modules\BannerlordLink\_Module\SubModule.xml"
```

Sprint 2.1 follow-up: добавлю в .csproj `AfterBuild` target который автоматически копирует SubModule.xml после билда.

---

## 5. Запуск Bannerlord с модом

1. Steam → Bannerlord → Launch
2. В Launcher: на вкладке **«Mods»** включить:
   - ☑ Native (required)
   - ☑ SandBoxCore
   - ☑ Sandbox
   - ☑ Bannerlord.Harmony
   - ☑ **BannerlordLink** ← наш мод
3. Single Player → New Campaign → Verify в логе:
   ```
   [BannerlordLink] v0.1.0 loading...
   [BannerlordLink] Harmony patched (id=ru.shedoy23.bannerlordlink)
   ```

Логи Bannerlord:
- `<game>\bin\Win64_Shipping_Client\rgl_log_*.txt` (текущий лог)
- `<documents>\Mount and Blade II Bannerlord\Logs\` (отдельные ошибки)

---

## 6. Iteration cycle

1. Изменить `.cs` в VS Code
2. `msbuild BannerlordLink.csproj` → DLL обновляется в Modules/
3. Restart Bannerlord (нет hot-reload, нужен полный exit)
4. Проверить в rgl_log

Для **debugging:** прикрепить debugger к запущенному `Bannerlord.exe` процессу.
В VS Code требует **.NET Framework debugger** (он в C# Dev Kit). Sprint 2+ — настроим если будет нужно.

---

## 7. Troubleshooting

| Симптом | Причина | Fix |
|---|---|---|
| `error MSB3270: TargetFrameworkVersion v4.8 not installed` | Нет targeting pack | Install §1.1 |
| `error MSB4019: Microsoft.CSharp.targets not found` | Нет Build Tools | Install §1.2 |
| `error CS0234: TaleWorlds.MountAndBlade does not exist` | env var не подцепился | Restart shell, verify `echo %BANNERLORD_GAME_DIR%` |
| `LoadLibraryError BannerlordLink.dll` в игре | DLL not в правильной папке | Проверь output path в .csproj и Modules/BannerlordLink/bin/Win64_Shipping_Client/ |
| Мод не появляется в Launcher | SubModule.xml не там | Скопируй в Modules/BannerlordLink/_Module/SubModule.xml |
| `Method not found: TaleWorlds.Core.SomeClass.SomeMethod` | Версия игры ≠ 1.3.15 | Steam → Bannerlord → Properties → Betas → выбрать 1.3.15 |

---

## 8. Альтернатива: Visual Studio 2022 Community

Если VS Code путь окажется тяжёлым — VS 2022 Community даёт всё-в-одном:
- Download: https://visualstudio.microsoft.com/vs/community/ (free)
- В installer выбрать workload **«.NET desktop development»**
- Включает: IDE + msbuild + .NET 4.8 targeting + debugger + IntelliSense

Чуть тяжелее (~5-7 GB на диск), но zero-config для C#. Может стать
preferred если будем часто debug'ить через breakpoints.

---

## 9. Дальнейшие шаги (после успешного builds)

- **Sprint 2.2:** Backend HTTP client (`Net/BackendClient.cs`) — auth через JWT в config.json
- **Sprint 2.3:** Action poller (long-poll `/v1/module/bannerlord/actions`)
- **Sprint 2.4:** CampaignBehavior (CampaignEvents subscriptions)
- **Sprint 3:** Action handlers (summon hero, give item, modify skill)

Когда настройка готова — скажешь, я начну Sprint 2.2.
