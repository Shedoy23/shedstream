param([switch]$PreviewOnly, [switch]$Background)
$ErrorActionPreference = 'Stop'
$directorNode = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
if (-not (Test-Path -LiteralPath $directorNode)) { $directorNode = (Get-Command node -ErrorAction Stop).Source }
$directorGame = Join-Path $env:USERPROFILE 'Documents\Mount and Blade II Bannerlord'
$directorState = Join-Path $env:LOCALAPPDATA 'ShedLink\stream-director\state'
$directorConfig = Join-Path $env:APPDATA 'obs-studio\plugin_config\obs-websocket\config.json'
$directorArguments = @((Join-Path $PSScriptRoot 'server.mjs'), 'serve', '--game', $directorGame, '--state', $directorState)
if (Test-Path -LiteralPath $directorConfig) { $directorArguments += @('--obs-config', $directorConfig) }
if ($PreviewOnly) { $directorArguments += '--no-obs' }
if ($Background) {
    New-Item -ItemType Directory -Force -Path $directorState | Out-Null
    $directorCommandLine = ($directorArguments | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' }) -join ' '
    Start-Process -FilePath $directorNode -ArgumentList $directorCommandLine -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $directorState 'observer.stdout.log') -RedirectStandardError (Join-Path $directorState 'observer.stderr.log') | Out-Null
    exit 0
}
Write-Host 'Overlay: http://127.0.0.1:17863/overlay.html'
Write-Host 'Preview: http://127.0.0.1:17863/?demo=1'
Write-Host 'Highlights: http://127.0.0.1:17863/moments.html'
& $directorNode @directorArguments
exit $LASTEXITCODE
