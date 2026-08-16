param(
    [Parameter(Mandatory = $true)]
    [string] $OutputPath
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'dist\releases'))
$output = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputPath))
$releasePrefix = $releaseRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) +
    [IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($releasePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'RimLink release archive must be written under dist/releases.'
}
if (Test-Path -LiteralPath $output) {
    throw "Release archive already exists: $output"
}

$files = @(
    @{ Source = 'RimLink\About\About.xml'; Entry = 'RimLink/About/About.xml' },
    @{ Source = 'RimLink\Assemblies\RimLink.dll'; Entry = 'RimLink/Assemblies/RimLink.dll' },
    @{ Source = 'RimLink\Defs\HediffDefs\RimLink_Hediffs.xml'; Entry = 'RimLink/Defs/HediffDefs/RimLink_Hediffs.xml' }
)

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
