param(
    [Parameter(Mandatory = $true)]
    [string] $OutputPath
)

# Собирает архив мода Bannerlord для раздачи через Manager.
#
# ПОЧЕМУ СПИСКОМ, А НЕ ПАПКОЙ. Настройки RimWorld лежат вне мода, поэтому его
# упаковщик не может случайно захватить секрет. У Bannerlord конфиг лежит
# ВНУТРИ папки мода: `Modules/Shedoy23.BannerlordLink/config.json` содержит
# module_token и channel_id, и Manager пишет туда рабочий ключ. В рабочей папке
# игры рядом с ним живут ещё копия исходников и запасные DLL от прошлых
# откатов. Упаковка «взять папку целиком» отправила бы всё это каждому, кто
# скачает архив, и по самому архиву заметить это нельзя.
#
# Поэтому: перечисляем файлы поимённо, берём их из git-дерева и из вывода
# сборки, а не из папки игры, и падаем, если файла нет.

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Deterministic Bannerlord releases require PowerShell 7 (pwsh).'
}
Add-Type -AssemblyName System.IO.Compression
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'dist\releases'))
$output = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputPath))
$releasePrefix = $releaseRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) +
    [IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($releasePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Bannerlord release archive must be written under dist/releases.'
}
if (Test-Path -LiteralPath $output) {
    throw "Release archive already exists: $output"
}

$moduleId = 'Shedoy23.BannerlordLink'
$files = @(
    @{ Source = 'BannerlordLink\SubModule.xml'
       Entry  = "$moduleId/SubModule.xml" },
    @{ Source = 'BannerlordLink\bin\Win64_Shipping_Client\BannerlordLink.dll'
       Entry  = "$moduleId/bin/Win64_Shipping_Client/BannerlordLink.dll" },
    @{ Source = 'BannerlordLink\GUI\Prefabs\BLinkHeroNametag.xml'
       Entry  = "$moduleId/GUI/Prefabs/BLinkHeroNametag.xml" }
)

# Вторая линия защиты на случай, если список однажды правят наспех. Настоящая
# защита — сам список; это ловит опечатку в нём.
$forbidden = @('config.json', '.pdb', '.backup', '.rollback', '.crashy', '/src/')
foreach ($file in $files) {
    $entry = $file.Entry
    foreach ($pattern in $forbidden) {
        if ($entry.ToLowerInvariant().Contains($pattern.ToLowerInvariant())) {
            throw "Release archive must never contain '$pattern': $entry"
        }
    }
}

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$stream = [IO.File]::Open($output, [IO.FileMode]::CreateNew)
try {
    $archive = [IO.Compression.ZipArchive]::new(
        $stream, [IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        foreach ($file in $files) {
            $source = [IO.Path]::GetFullPath((Join-Path $repoRoot $file.Source))
            if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
                throw "Required release file is missing: $source"
            }
            $entry = $archive.CreateEntry(
                $file.Entry, [IO.Compression.CompressionLevel]::Optimal)
            $entry.LastWriteTime = [DateTimeOffset]::new(
                2020, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
            $input = [IO.File]::OpenRead($source)
            $entryStream = $entry.Open()
            try {
                $input.CopyTo($entryStream)
            }
            finally {
                $entryStream.Dispose()
                $input.Dispose()
            }
        }
    }
    finally {
        $archive.Dispose()
    }
}
finally {
    $stream.Dispose()
}

$item = Get-Item -LiteralPath $output
$hash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "path=$output"
Write-Output "size_bytes=$($item.Length)"
Write-Output "sha256=$hash"
