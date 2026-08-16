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
$manifest = Join-Path $packageDirectory 'Release/rimworld-0.1.1.json'
foreach ($required in @($executable, $manifest)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Published package is missing required file: $required"
    }
}

$unexpected = Get-ChildItem -LiteralPath $packageDirectory -Recurse -File |
    Where-Object Extension -In @('.pdb', '.xml')
if ($unexpected) {
    throw "Published package contains debug/development files: $($unexpected.FullName -join ', ')"
}

$startHere = @'
ShedLink Manager — alpha

1. Полностью распакуйте ZIP в отдельную папку.
2. Закройте RimWorld перед установкой, обновлением или восстановлением RimLink.
3. Запустите ShedLink.Manager.App.exe.
4. Подключите Twitch. Если RimWorld не найдена автоматически — выберите её папку.
5. Нажмите установку RimLink, затем запустите игру и дождитесь свежего heartbeat.
6. Нажмите «Проверить готовность». Итог должен стать Technical Ready.

Если Windows предупредит о неизвестном издателе: проверьте SHA-256 архива по
файлу .sha256 рядом с ZIP. Alpha EXE пока не подписан платным Windows-сертификатом.

Если что-то не получилось, сохраните «Диагностический отчёт» и передайте JSON
разработчику. Manager автоматически удаляет из отчёта ключи и приватные пути.
'@
[IO.File]::WriteAllText(
    (Join-Path $packageDirectory 'START-HERE.txt'),
    $startHere,
    [Text.UTF8Encoding]::new($true))

$commit = (git -C $repositoryRoot rev-parse --short=12 HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commit)) {
    throw 'Cannot determine source commit.'
}
$metadata = [ordered]@{
    product = 'ShedLink Manager'
    version = $Version
    runtime = $Runtime
    source_commit = $commit
    built_at_utc = [DateTime]::UtcNow.ToString('O')
    executable_sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
    manifest_sha256 = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
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
