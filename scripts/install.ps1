# Installs Native Gyro Aim into Borderlands 4. Requires oak2-mod-manager (bl-sdk) already installed.
# Works from the release package (NativeGyro\ next to this script) or from the repo (after build.cmd).
# Run: powershell -ExecutionPolicy Bypass -File install.ps1 [-GameDir "<...>\Borderlands 4"]   (default: found via Steam)
param([string]$GameDir)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'steam-game-dir.ps1')
if (-not $GameDir) { $GameDir = Find-GameDir }
$packaged = Join-Path $PSScriptRoot 'NativeGyro'
if (Test-Path (Join-Path $packaged 'bl4gyro.dll')) {
    $init, $dll = (Join-Path $packaged '__init__.py'), (Join-Path $packaged 'bl4gyro.dll')
} else {
    $repo = Split-Path $PSScriptRoot -Parent
    $init, $dll = (Join-Path $repo 'mod\NativeGyro\__init__.py'), (Join-Path $repo 'build\release\bl4gyro.dll')
}

if (Get-Process Borderlands4 -ErrorAction SilentlyContinue) { throw 'Close Borderlands 4 first.' }
if (-not (Test-Path (Join-Path $GameDir 'OakGame\Binaries\Win64\Plugins\pyunrealsdk.dll'))) {
    throw "oak2-mod-manager not found in '$GameDir'. Install it first: https://github.com/bl-sdk/oak2-mod-manager/releases"
}
if (-not (Test-Path $dll)) { throw "Build first (build.cmd): $dll is missing." }

$target = Join-Path $GameDir 'sdk_mods\NativeGyro'
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item $init $target -Force
Copy-Item $dll $target -Force

# The Phase B probe binds keys that move the camera; it is a development tool only.
$probe = Join-Path $GameDir 'sdk_mods\NativeGyroProbe'
if (Test-Path $probe) { Remove-Item -Recurse -Force $probe; Write-Host 'Removed development probe (NativeGyroProbe).' }

Write-Host "Installed to $target"
Write-Host 'In game: open the console (F6 or your console key), type  mods , select Native Gyro Aim and enable it.'
