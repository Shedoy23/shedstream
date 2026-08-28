param(
    [Parameter(Mandatory = $true)]
    [string] $OutputPath
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Deterministic ShedColony releases require PowerShell 7 (pwsh).'
}
Add-Type -AssemblyName System.IO.Compression
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'dist\releases'))
$output = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputPath))
$releasePrefix = $releaseRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) +
    [IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($releasePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'ShedColony release archive must be written under dist/releases.'
}
if (Test-Path -LiteralPath $output) { throw "Release archive already exists: $output" }

$source = Join-Path $repoRoot 'Расширение\frontend\downloads\minecraft\shedcolony-0.1.0.jar'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Required ShedColony JAR is missing: $source"
}
# 28.08: в релиз 19.08 уехал jar, собранный ДО того, как были дописаны 12
# действий. Их знал бэкенд и знал исходник мода, но не знал jar — двенадцать
# кнопок на 299 300 крустиков возвращали unknown_action. Версия у старого и
# нового jar одна и та же, поэтому подмену не видно ни глазом, ни по имени
# файла. Ворота стоят здесь, а не в pre-commit: ломает не коммит, а отгрузка.
$checker = Join-Path $PSScriptRoot 'check-shedcolony-jar.py'
& python $checker $source
if ($LASTEXITCODE -ne 0) {
    throw ("ShedColony JAR не проходит проверку покрытия платных действий " +
           "(код $LASTEXITCODE). Пересобери мод и положи свежий jar в " +
           "frontend/downloads/minecraft/, прежде чем паковать релиз.")
}
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$stream = [IO.File]::Open($output, [IO.FileMode]::CreateNew)
try {
    $archive = [IO.Compression.ZipArchive]::new(
        $stream, [IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        $entry = $archive.CreateEntry(
            'shedcolony-0.1.0.jar', [IO.Compression.CompressionLevel]::Optimal)
        $entry.LastWriteTime = [DateTimeOffset]::new(
            2020, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
        $input = [IO.File]::OpenRead($source)
        $entryStream = $entry.Open()
        try { $input.CopyTo($entryStream) }
        finally { $entryStream.Dispose(); $input.Dispose() }
    }
    finally { $archive.Dispose() }
}
finally { $stream.Dispose() }

$item = Get-Item -LiteralPath $output
$hash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "path=$output"
Write-Output "size_bytes=$($item.Length)"
Write-Output "sha256=$hash"
