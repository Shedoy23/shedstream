[CmdletBinding()]
param([switch]$ConfirmBuild)
$ErrorActionPreference = 'Stop'
if (-not $ConfirmBuild) { throw 'Manual build only: pass -ConfirmBuild. This script never installs or launches anything.' }

# Direct Roslyn compile: no MSBuild/project imports, restore, hooks, deploy or postbuild targets.
# One small source file, /parallel-, no compiler server. Only this probe folder receives output.
$probeRoot = $PSScriptRoot
$gameRoot = 'X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord'
$gameBin = Join-Path $gameRoot 'bin\Win64_Shipping_Client'
$sandboxBin = Join-Path $gameRoot 'Modules\SandBox\bin\Win64_Shipping_Client'
$referenceRoot = 'C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework\v4.7.2'
$dotnetPath = 'C:\Program Files\dotnet\dotnet.exe'
$compilerPath = 'C:\Program Files\dotnet\sdk\9.0.310\Roslyn\bincore\csc.dll'
$outputDir = Join-Path $probeRoot 'bin\Win64_Shipping_Client'
$evidenceDir = Join-Path $probeRoot 'build-evidence'
New-Item -ItemType Directory -Path $outputDir,$evidenceDir -Force | Out-Null
$outputDll = Join-Path $outputDir 'ShedLink.MapExportProbe.dll'
$references = @('mscorlib.dll','System.dll','System.Core.dll') | ForEach-Object { Join-Path $referenceRoot $_ }
$references += Join-Path $referenceRoot 'Facades\netstandard.dll'
$references += @('TaleWorlds.Core','TaleWorlds.Library','TaleWorlds.DotNet','TaleWorlds.Engine','TaleWorlds.MountAndBlade',
    'TaleWorlds.CampaignSystem','TaleWorlds.SaveSystem','TaleWorlds.Localization','TaleWorlds.ObjectSystem',
    'TaleWorlds.ModuleManager','TaleWorlds.ScreenSystem','Newtonsoft.Json') | ForEach-Object { Join-Path $gameBin ($_.ToString() + '.dll') }
$references += @('SandBox.dll','SandBox.View.dll') | ForEach-Object { Join-Path $sandboxBin $_ }
foreach ($path in @($dotnetPath,$compilerPath) + $references) { if (-not (Test-Path -LiteralPath $path)) { throw "Missing compile input: $path" } }
$response = @('/nostdlib+','/target:library','/platform:x64','/langversion:7.3','/parallel-',
    '/deterministic+','/optimize+','/warnaserror+','/utf8output',('/out:"' + $outputDll + '"'))
$response += $references | ForEach-Object { '/reference:"' + $_ + '"' }
$response += '"' + (Join-Path $probeRoot 'ProbeModule.cs') + '"'
$responsePath = Join-Path $evidenceDir 'compile.rsp'
Set-Content -LiteralPath $responsePath -Value $response -Encoding UTF8
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
& $dotnetPath $compilerPath /noconfig ('@' + $responsePath) 2>&1 | Tee-Object -FilePath (Join-Path $evidenceDir 'compile.log')
if ($LASTEXITCODE -ne 0) { throw "Probe compilation failed: exit $LASTEXITCODE" }
Get-FileHash -LiteralPath $outputDll -Algorithm SHA256 | Format-List | Out-String | Set-Content -LiteralPath (Join-Path $evidenceDir 'dll-sha256.txt')
Write-Output "COMPILED ONLY: $outputDll"
