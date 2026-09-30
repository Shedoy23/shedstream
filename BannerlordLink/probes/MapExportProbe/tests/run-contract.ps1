[CmdletBinding()]
param([switch]$ConfirmTests, [Parameter(Mandatory=$true)][string]$ProbeDll, [string]$LogName='contract.log')
$ErrorActionPreference='Stop'
if(-not $ConfirmTests){throw 'Explicit local test invocation required.'}
if([IO.Path]::GetFileName($LogName) -ne $LogName){throw 'Log filename only.'}
# One direct offline Roslyn compile; no MSBuild imports, deploy or game output paths.
$probeRoot=Split-Path $PSScriptRoot -Parent
$testOutput=Join-Path $probeRoot 'build-evidence\contract'
New-Item -ItemType Directory -Path $testOutput -Force | Out-Null
$referenceRoot='C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework\v4.7.2'
$testExe=Join-Path $testOutput 'SafetyContract.exe'
$arguments=@('/noconfig','/nostdlib+','/target:exe','/platform:x64','/langversion:7.3','/parallel-','/warnaserror+',('/out:'+ $testExe))
$arguments+=@('mscorlib.dll','System.dll','System.Core.dll')|ForEach-Object { '/reference:'+(Join-Path $referenceRoot $_) }
$arguments+=Join-Path $PSScriptRoot 'SafetyContract.cs'
& 'C:\Program Files\dotnet\dotnet.exe' 'C:\Program Files\dotnet\sdk\9.0.310\Roslyn\bincore\csc.dll' @arguments
if($LASTEXITCODE -ne 0){throw 'Offline harness compile failed.'}
& $testExe (Resolve-Path -LiteralPath $ProbeDll).Path 2>&1 | Tee-Object -FilePath (Join-Path $testOutput $LogName)
exit $LASTEXITCODE
