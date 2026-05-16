# Bannerlord Mod Build

**Target:** Bannerlord 1.3.15 (.NET Framework `net472`, x64)
**Game path:** `X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord`
**Stack:** existing `dotnet` SDK + `net472` targeting pack (уже стоят у юзера,
проверено через build AutoTraderRoute)

---

## Структура проекта

```
X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\
└── Modules\
    └── Shedoy23.BannerlordLink\
        ├── SubModule.xml          ← module declaration (loaded by Bannerlord)
        ├── src\
        │   ├── BannerlordLink.csproj
        │   ├── BannerlordLinkModule.cs   ← entry point
        │   └── *.cs (новые файлы как сделаем)
        └── bin\Win64_Shipping_Client\
            └── BannerlordLink.dll        ← output после build
```

Зеркало в git-репо: `BannerlordLink/` (для version control). Sync через
`cp` после правок.

---

## Build

```cmd
cd "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Shedoy23.BannerlordLink\src"
dotnet build
```

~2 сек. DLL автоматически попадает в `..\bin\Win64_Shipping_Client\` (через
`OutputPath` в csproj). После build — запускай Bannerlord launcher и
включай мод «BannerlordLink» в Mods list.

---

## Verify в game log

После Launch с включённым мод — в `<game>\bin\Win64_Shipping_Client\rgl_log_*.txt`:

```
[BannerlordLink] v0.1.0 loading...
[BannerlordLink] Harmony patched (id=ru.shedoy23.bannerlordlink)
```

---

## Editor

Любой текстовый редактор. VS Code с extension `ms-dotnettools.csharp`
даёт IntelliSense на TaleWorlds API через `dotnet restore` + OmniSharp
auto-config (читает .csproj).

---

## Iteration cycle

1. Edit `.cs` в редакторе
2. `dotnet build` (2 сек)
3. Restart Bannerlord (нет hot-reload, нужен полный exit)
4. Проверь rgl_log

---

## Sync репо ↔ Modules folder

Source-of-truth — папка в Modules/ (где dotnet build работает). Зеркало
в git-репо `BannerlordLink/` обновляется при коммитах:

```cmd
cd "C:\Users\Edward\Desktop\work\.claude\worktrees\tender-tharp-fc29e6"
cp "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Shedoy23.BannerlordLink\SubModule.xml" BannerlordLink\
cp "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Shedoy23.BannerlordLink\src\*.cs" BannerlordLink\src\
cp "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Shedoy23.BannerlordLink\src\*.csproj" BannerlordLink\src\
```

Sprint 2.2 follow-up: добавлю sync-script `tools/sync_bannerlord_link.cmd`.
