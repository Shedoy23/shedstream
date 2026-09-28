[CmdletBinding()]
param(
    [string]$Version = '0.1.0-alpha.1',
    [string]$Runtime = 'win-x64'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest


$repositoryRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $repositoryRoot 'ShedLink.Manager/src/ShedLink.Manager.App/ShedLink.Manager.App.csproj'
$releaseRoot = Join-Path $repositoryRoot 'dist/releases'
$packageName = "ShedLink.Manager-$Version-$Runtime"
$packageDirectory = Join-Path $releaseRoot $packageName
$archivePath = Join-Path $releaseRoot "$packageName.zip"
$archiveHashPath = "$archivePath.sha256"

foreach ($candidate in @($packageDirectory, $archivePath, $archiveHashPath)) {
    if (Test-Path -LiteralPath $candidate) {
        throw "Release output already exists: $candidate"
    }
}

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null

dotnet publish $project `
    --configuration Release `
    --runtime $Runtime `
    --self-contained true `
    --output $packageDirectory `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    -p:Version=$Version
if ($LASTEXITCODE -ne 0) {
    throw "Manager publish failed with exit code $LASTEXITCODE."
}

$executable = Join-Path $packageDirectory 'ShedLink.Manager.App.exe'
$manifests = @(
    (Join-Path $packageDirectory 'Release/rimworld-0.1.1.json'),
    (Join-Path $packageDirectory 'Release/rimworld-0.1.2.json'),
    (Join-Path $packageDirectory 'Release/bannerlord-0.1.1.json'),
    (Join-Path $packageDirectory 'Release/bannerlord-0.1.2.json'),
    (Join-Path $packageDirectory 'Release/shedcolony-0.1.0.json'),
    # 0.1.0 остаётся рядом с 0.1.1 намеренно: по манифесту установленной
    # версии Manager находит путь старого jar, а без него кнопка «Удалить»
    # не знает, что убирать. Уберём, когда у владельца не останется
    # установленного 0.1.0.
    (Join-Path $packageDirectory 'Release/shedcolony-0.1.1.json'),
    # 06.09: этот список — не украшение. Манифесты попадают в сборку по маске из
    # csproj, но alpha.15 уехала БЕЗ shedcolony-0.1.2 просто потому, что была
    # собрана за несколько часов до появления того файла, и никто не заметил:
    # проверка требовала только перечисленные здесь версии. Дописывать сюда
    # каждую новую версию — и есть способ заметить пропажу.
    (Join-Path $packageDirectory 'Release/shedcolony-0.1.2.json'),
    (Join-Path $packageDirectory 'Release/shedcolony-0.1.4.json'),
    (Join-Path $packageDirectory 'Release/bannerlord-0.1.3.json'),
    (Join-Path $packageDirectory 'Release/rimworld-0.1.3.json')
)
foreach ($required in @($executable) + $manifests) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Published package is missing required file: $required"
    }
}

$unexpected = Get-ChildItem -LiteralPath $packageDirectory -Recurse -File |
    Where-Object Extension -In @('.pdb', '.xml')
if ($unexpected) {
    throw "Published package contains debug/development files: $($unexpected.FullName -join ', ')"
}

$startHere = @"
ShedLink Manager — alpha

КАК ЗАПУСТИТЬ

1. Распакуйте архив целиком в отдельную папку. Не запускайте программу прямо
   из окна архива: рядом с ней должна лежать папка Release.
2. Запустите ShedLink.Manager.App.exe.
3. Windows покажет синее окно «Система Windows защитила ваш компьютер».
   Так и должно быть: программа пока не подписана платным сертификатом.
   Нажмите «Подробнее», затем «Выполнить в любом случае».
4. Выберите игру, которую хотите подключить к стриму, и войдите через Twitch.
5. Если игра не нашлась сама — укажите её папку вручную.
6. Закройте игру и нажмите «Установить».
7. Manager сам скачает, проверит, установит и настроит нужный мод.
8. Запустите игру, дождитесь связи с модом и нажмите «Проверить готовность».
   Итог должен стать Technical Ready.

Игра должна быть закрыта при установке, обновлении и восстановлении мода.

ПРОВЕРКА АРХИВА — необязательно

Контрольную сумму разработчик присылает отдельным сообщением. Сравните её с
результатом команды в PowerShell, подставив свой путь к архиву:

    Get-FileHash "C:\путь\$packageName.zip" -Algorithm SHA256

ЕСЛИ ЧТО-ТО НЕ РАБОТАЕТ

Нажмите «Диагностический отчёт» и пришлите разработчику полученный JSON.
Ключи и личные пути программа вырезает из отчёта сама. Обязательно напишите,
на каком шаге вы остановились и что увидели на экране, — это важнее файла.
"@
$startHerePath = Join-Path $packageDirectory 'START-HERE.txt'
[IO.File]::WriteAllText($startHerePath, $startHere, [Text.UTF8Encoding]::new($true))

# A shell that reads this script as ANSI silently mangles the Russian text above.
# This canary is built from code points, so it survives any misreading of the
# file and stops matching as soon as the instructions themselves are mangled.
$canary = -join ([int[]](
    0x041F, 0x043E, 0x0434, 0x0440, 0x043E, 0x0431, 0x043D, 0x0435, 0x0435) |
    ForEach-Object { [char]$_ })
if (-not [IO.File]::ReadAllText($startHerePath).Contains($canary)) {
    throw "START-HERE.txt is corrupted by the shell encoding: $startHerePath"
}

$commit = (git -C $repositoryRoot rev-parse --short=12 HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commit)) {
    throw 'Cannot determine source commit.'
}
# Without this the metadata names a commit that does not contain what was built.
$dirty = git -C $repositoryRoot status --porcelain
if ($LASTEXITCODE -ne 0) {
    throw 'Cannot determine repository state.'
}
if ($dirty) {
    throw "Commit or stash changes before packaging; $commit would not describe this build."
}
$catalog = [ordered]@{}
foreach ($manifest in $manifests) {
    $catalog[(Split-Path $manifest -Leaf)] =
        (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
}
$metadata = [ordered]@{
    product = 'ShedLink Manager'
    version = $Version
    runtime = $Runtime
    source_commit = $commit
    built_at_utc = [DateTime]::UtcNow.ToString('O')
    executable_sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
    release_catalog_sha256 = $catalog
}
[IO.File]::WriteAllText(
    (Join-Path $packageDirectory 'RELEASE.json'),
    (($metadata | ConvertTo-Json) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false))

Compress-Archive -LiteralPath $packageDirectory -DestinationPath $archivePath -CompressionLevel Optimal
$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(
    $archiveHashPath,
    "$archiveHash  $packageName.zip$([Environment]::NewLine)",
    [Text.UTF8Encoding]::new($false))

Write-Output "PACKAGE=$archivePath"
Write-Output "SHA256=$archiveHash"
Write-Output "CONTENTS=$packageDirectory"
